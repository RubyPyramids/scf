# app/scf_runner.py
# Unified runner: diagnostics + multi-worker orchestration + health checks.
# Windows-friendly. Requires: asyncpg, websockets, orjson, python-dotenv.

import asyncio, os, sys, time, signal, contextlib, argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import asyncpg
import websockets
import orjson
from dotenv import load_dotenv

###############################################################################
# Config loader
###############################################################################

def load_env() -> Dict[str, str]:
    ROOT = os.path.dirname(os.path.dirname(__file__))
    load_dotenv(os.path.join(ROOT, ".env"))

    cfg = {
        "db_url": os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf"),
        # try several names; fall back to HELIUS_KEY if present
        "rpc_ws": os.getenv("RPC_PRIMARY") or os.getenv("RPC_WS") or os.getenv("HELIUS_WS") or os.getenv("RPC_WS_URL"),
        # Program IDs (fallbacks are known defaults)
        "raydium_amm":  os.getenv("RAYDIUM_AMM",  "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"),
        "raydium_clmm": os.getenv("RAYDIUM_CLMM", "4hGdEStwqyqZkG2tZibsSDQ7SBy7xH2sVQ2QJVV5o4Ck"),
        "orca_amm":     os.getenv("ORCA_AMM",     "9WwG7VJp49r4bgx1mVQqZKkGKuX3sX5Y3F9F6w8vG8bS"),
        "orca_whirl":   os.getenv("ORCA_WHIRL",   "whirLbMiicVq4SCVZxdrmB9otnE8u6VYzG9xH8Wc7so"),
    }
    if not cfg["rpc_ws"]:
        key = os.getenv("HELIUS_KEY")
        if key:
            cfg["rpc_ws"] = f"wss://mainnet.helius-rpc.com/?api-key={key}"
    return cfg

###############################################################################
# Diagnostics
###############################################################################

LOG_LIMIT = 10

def _build_logs_sub_request(pid, subid):
    return {
        "jsonrpc":"2.0",
        "id": subid,
        "method":"logsSubscribe",
        "params":[
            {"mentions":[pid]},
            {"commitment":"finalized"}
        ]
    }

async def diag_db_check(db_url: str) -> List[str]:
    conn = await asyncpg.connect(dsn=db_url)
    try:
        rows = await conn.fetch("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname='public'
            ORDER BY tablename
        """)
        return [r["tablename"] for r in rows]
    finally:
        await conn.close()

async def diag_ws_check(rpc_ws: str, pids: List[str]) -> int:
    printed = 0
    async with websockets.connect(rpc_ws, max_size=20_000_000) as ws:
        subid = 1
        for pid in pids:
            await ws.send(orjson.dumps(_build_logs_sub_request(pid, subid)))
            subid += 1

        while printed < LOG_LIMIT:
            raw = await ws.recv()
            try:
                msg = orjson.loads(raw)
            except Exception:
                continue
            if isinstance(msg, dict) and msg.get("method") == "logsNotification":
                v = msg.get("params",{}).get("result",{})
                pid = v.get("value",{}).get("programId","?")
                sigs = v.get("value",{}).get("signatures",[])
                logs = v.get("value",{}).get("logs",[])
                printed += 1
                print(f"[DIAG] LOG#{printed} program={pid} sigs={len(sigs)} lines={len(logs)}")
    return printed

###############################################################################
# Orchestrator
###############################################################################

@dataclass
class WorkerSpec:
    name: str
    cmd: List[str]
    cwd: Optional[str] = None
    restart_backoff: float = 2.0   # seconds, doubles up to max_backoff
    max_backoff: float = 60.0
    proc: Optional[asyncio.subprocess.Process] = field(default=None, init=False)
    last_start: float = field(default=0.0, init=False)
    exit_count: int = field(default=0, init=False)
    running: bool = field(default=False, init=False)
    last_log: str = field(default="", init=False)

class Orchestrator:
    def __init__(self, project_root: str):
        self.root = project_root
        self.workers: List[WorkerSpec] = []
        self._stop = asyncio.Event()

    def add_worker(self, name: str, module_path: str):
        py = sys.executable  # use current venv python
        cmd = [py, module_path]
        self.workers.append(WorkerSpec(name=name, cmd=cmd, cwd=self.root))

    async def start_all(self):
        for w in self.workers:
            await self._start_worker(w)

    async def _start_worker(self, w: WorkerSpec):
        w.last_start = time.time()
        w.proc = await asyncio.create_subprocess_exec(
            *w.cmd,
            cwd=w.cwd or self.root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        w.running = True
        asyncio.create_task(self._pump_logs(w))
        asyncio.create_task(self._watch_worker(w))

    async def _pump_logs(self, w: WorkerSpec):
        assert w.proc and w.proc.stdout
        try:
            while True:
                line = await w.proc.stdout.readline()
                if not line:
                    break
                txt = line.decode(errors="replace").rstrip()
                w.last_log = txt
                print(f"[{w.name}] {txt}")
        except Exception:
            pass

    async def _watch_worker(self, w: WorkerSpec):
        assert w.proc
        rc = await w.proc.wait()
        w.running = False
        w.exit_count += 1
        print(f"[{w.name}] exited rc={rc}")
        if not self._stop.is_set():
            delay = min(w.restart_backoff * (2 ** (w.exit_count - 1)), w.max_backoff)
            delay = max(2.0, delay)
            await asyncio.sleep(delay)
            await self._start_worker(w)

    async def stop_all(self):
        self._stop.set()
        for w in self.workers:
            if w.proc and w.running:
                with contextlib.suppress(ProcessLookupError):
                    w.proc.terminate()
        await asyncio.sleep(2.0)
        for w in self.workers:
            if w.proc and w.running:
                with contextlib.suppress(ProcessLookupError):
                    w.proc.kill()

###############################################################################
# Health monitor (DB-centric)
###############################################################################

class Health:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.snap: Dict[str, str] = {}

    async def tick(self):
        try:
            conn = await asyncpg.connect(self.db_url)
        except Exception as e:
            self.snap = {"db": f"DOWN: {e}"}
            return

        try:
            snap = {"db": "OK"}
            q_txq  = await conn.fetchval("SELECT COUNT(*) FROM tx_queue")
            q_txr  = await conn.fetchval("SELECT COUNT(*) FROM tx_raw")
            q_swap = await conn.fetchval("SELECT COUNT(*) FROM swap_event")
            q_lp   = await conn.fetchval("SELECT COUNT(*) FROM lp_event")
            q_auth = await conn.fetchval("SELECT COUNT(*) FROM authority_event")
            q_feat = await conn.fetchval("SELECT COUNT(*) FROM features_latest")
            q_sig  = await conn.fetchval("SELECT COUNT(*) FROM detector_signal")
            q_pos  = await conn.fetchval("SELECT COUNT(*) FROM position")

            max_swap = await conn.fetchval("SELECT MAX(ts) FROM swap_event")
            max_lp   = await conn.fetchval("SELECT MAX(ts) FROM lp_event")

            def ago(ts: Optional[datetime]) -> str:
                if not ts: return "n/a"
                delta = datetime.now(timezone.utc) - ts
                return f"{int(delta.total_seconds())}s ago"

            snap.update({
                "tx_queue": str(q_txq),
                "tx_raw":   str(q_txr),
                "swap_event": f"{q_swap} (max {ago(max_swap)})",
                "lp_event":   f"{q_lp} (max {ago(max_lp)})",
                "authority_event": str(q_auth),
                "features_latest": str(q_feat),
                "detector_signal": str(q_sig),
                "position":        str(q_pos),
            })
            self.snap = snap
        finally:
            await conn.close()

    def print(self):
        parts = [f"{k}={v}" for k, v in self.snap.items()]
        print("[HEALTH] " + " | ".join(parts))

###############################################################################
# Wiring
###############################################################################

def workers_layout(project_root: str, exec_mode: str) -> List["WorkerSpec"]:
    """
    exec_mode ∈ {'paper','live','none'}
    """
    orch = Orchestrator(project_root)
    # Order: ingest -> resolve -> parse -> features -> detector -> executor -> exit
    orch.add_worker("ingest_queue",     os.path.join(project_root, "app", "ingest_queue.py"))
    orch.add_worker("worker_resolve",   os.path.join(project_root, "app", "worker_resolve.py"))
    orch.add_worker("parser_swap",      os.path.join(project_root, "app", "parser_swap.py"))
    orch.add_worker("parser_lp",        os.path.join(project_root, "app", "parser_lp.py"))
    orch.add_worker("parser_authority", os.path.join(project_root, "app", "parser_authority.py"))
    orch.add_worker("feature_worker",   os.path.join(project_root, "app", "feature_worker.py"))
    orch.add_worker("detector",         os.path.join(project_root, "app", "detector.py"))

    if exec_mode == "paper":
        path = os.path.join(project_root, "app", "executor_paper.py")
        if not os.path.exists(path):
            raise SystemExit("exec_mode=paper requested but app/executor_paper.py not found.")
        orch.add_worker("executor_paper", path)
    elif exec_mode == "live":
        path = os.path.join(project_root, "app", "executor_live.py")
        if not os.path.exists(path):
            raise SystemExit("exec_mode=live requested but app/executor_live.py not found.")
        orch.add_worker("executor_live", path)
    elif exec_mode == "none":
        # no executor attached; useful for dry-runs or ingestion-only troubleshooting
        pass
    else:
        raise SystemExit(f"Unknown exec mode: {exec_mode} (expected paper|live|none)")

    # always include exit engine (TP/SL)
    orch.add_worker("exit_worker", os.path.join(project_root, "app", "exit_worker.py"))

    return orch.workers

###############################################################################
# Modes
###############################################################################

async def run_full(exec_mode: str):
    cfg = load_env()
    root = os.path.dirname(os.path.dirname(__file__))

    orch = Orchestrator(root)
    _ = workers_layout(root, exec_mode)
    orch.workers = _

    health = Health(cfg["db_url"])

    loop = asyncio.get_running_loop()
    stop_ev = asyncio.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(s, stop_ev.set)

    await orch.start_all()
    print(f"[RUNNER] started all workers (executor={exec_mode}).")

    try:
        while not stop_ev.is_set():
            await health.tick()
            health.print()
            await asyncio.sleep(5.0)
    finally:
        print("[RUNNER] stopping…")
        await orch.stop_all()
        print("[RUNNER] stopped.")

async def run_diag():
    cfg = load_env()
    pids = [cfg["raydium_amm"], cfg["raydium_clmm"], cfg["orca_amm"]]
    print("[DIAG] Checking DB…")
    tables = await diag_db_check(cfg["db_url"])
    print(f"[DIAG] DB OK. Tables: {tables}")
    print("[DIAG] Checking WebSocket feed…")
    n = await diag_ws_check(cfg["rpc_ws"], pids)
    print(f"[DIAG] WS OK. Received {n} logs.")

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SCF runner — diagnostics + multi-worker orchestration + health checks"
    )
    sub = p.add_subparsers(dest="cmd")

    # Default-less: if no subcmd, we route to --diag for safety
    p_diag = sub.add_parser("diag", help="One-shot sanity checks (DB + WS)")

    p_full = sub.add_parser("full", help="Start all workers with health monitor")
    p_full.add_argument(
        "--exec",
        dest="exec_mode",
        choices=["paper", "live", "none"],
        default="paper",
        help="Executor mode: paper (default), live, or none",
    )

    return p

def main():
    parser = build_argparser()
    args = parser.parse_args()

    # default to diag if no command provided
    if not args.cmd:
        return asyncio.run(run_diag())

    if args.cmd == "diag":
        return asyncio.run(run_diag())
    elif args.cmd == "full":
        return asyncio.run(run_full(args.exec_mode))
    else:
        parser.print_help()
        sys.exit(2)

if __name__ == "__main__":
    main()