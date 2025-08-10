# SCF — Stealth Coil Framework  
**Full Technical Handover & Development Trajectory**  
_As of 10 Aug 2025 (post-runner integration)_

---

## 1. Project Overview

The **Stealth Coil Framework (SCF)** is an event-driven, fully automated memecoin trading bot for the **Solana** blockchain.

It runs continuously (24/7) in a local or hosted environment, ingesting raw blockchain transactions, parsing relevant events, computing market microstructure features, detecting SCF trade setups via strict rule-based primitives, and executing trades in **paper** or **live** mode.

SCF implements the **SCF5 primitives** for coil detection:

1. **Volatility Compression (VC)**  
2. **Order-Flow Stillness (OFS)**  
3. **Liquidity Thinness (LT)**  
4. **Wallet Convergence (WC)**  
5. **Retail Quiet (RQ)**  

Philosophy: **rule-based, data-driven, low-latency** — zero discretionary decision-making once deployed.

---

## 2. Current Environment

- **OS**: Windows 11  
- **Language**: Python 3.12 (venv `.venv`)  
- **Database**: PostgreSQL in Docker (`scf_db` container)  
- **Blockchain Feed**: Helius WebSocket RPC for real-time Solana tx  
- **Code layout**: `app/` contains workers (ingest, parse, feature, detect, execute)  
- **Configuration**: `.env` stores keys and connection strings  

**Example `.env` essentials:**
```ini
# RPCs (choose explicit URLs or use HELIUS_KEY)
RPC_PRIMARY=wss://...
RPC_HTTP_PRIMARY=https://...
# HELIUS_KEY=...

# Database
DB_URL=postgresql://scf:scf@localhost:5432/scf

# Detector thresholds (optional overrides)
SCF_VC_MAX=0.015
SCF_OFS_MAX=0.001
SCF_LT_MAX=5000
SCF_WC_MIN=0.6
SCF_RQ_MAX=0.5

# Executor polling
SCF_EXECUTOR_POLL_SEC=2
SCF_EXECUTOR_WINDOW_MIN=10
SCF_EXECUTOR_BATCH=200
```
Executor mode is chosen at runtime via CLI flag (`--mode {paper|live|none}`).

---

## 3. Database Schema & Pipeline Stages

**Raw ingestion & resolution**

- `tx_queue` — incoming tx signatures from WS
- `tx_raw` — decoded transactions (JSON) from Helius REST

**Parsed events**

- `swap_event` — swaps parsed from `tx_raw`
- `lp_event` — LP add/remove events (includes sig)
- `authority_event` — token authority changes

**Features & detection**

- `features_latest` — latest computed features per pool
- `detector_signal` — emitted trade signals from detection logic

**Execution & logging**

- `position` — open/closed positions
- `fill` — executed trades
- `error_log`, `latency_log` — diagnostics

---

## 4. Codebase Summary

| File | Purpose |
|---|---|
| `scf_runner.py` | Orchestrates workers, prints health, chooses executor via `--mode`. |
| `ingest_queue.py` | Subscribes to WS feed, inserts signatures into `tx_queue`. |
| `worker_resolve.py` | Reads `tx_queue`, fetches full tx JSON (REST), writes to `tx_raw`. |
| `parser_swap.py` | Extracts swaps → `swap_event`. Skips unknown pools; advances by slot. |
| `parser_lp.py` | Extracts LP add/remove → `lp_event` (with sig). |
| `parser_authority.py` | Extracts token authority changes → `authority_event`. |
| `feature_worker.py` | Joins latest events, computes features, upserts `features_latest`. |
| `detector.py` | Applies SCF5 threshold rules; emits into `detector_signal`; dedups. |
| `executor_paper.py` | Opens paper positions (size 0), inserts fills; off-chain. |
| `executor_live.py` | Live stub; records intent; routing/signing TBD. |
| `executor.py` | Legacy placeholder; not in runner path. |

---

## 5. How to Run (PowerShell)

```powershell
# Diagnostic (DB + WS)
python app\scf_runner.py --diag

# Start everything in paper mode
python app\scf_runner.py --full --mode paper

# Start everything in live-stub mode
python app\scf_runner.py --full --mode live

# Start with no executor
python app\scf_runner.py --full --mode none
```

---

## 6. Progress by Phase

**Phase A — Ingestion & Resolution**  
✅ PostgreSQL container set up; schema loaded.  
✅ Helius WS subscription live.  
✅ `ingest_queue.py` + `worker_resolve.py` working — WS → `tx_queue` → REST → `tx_raw`.

**Phase B — Parsing**  
✅ Parsers produce clean events with valid pool IDs; skip unknowns.  
✅ Indexing + slot-based advancement avoids backpressure.

**Phase C — Feature Extraction**  
✅ `feature_worker.py` operational; features updating in real time.  
⚠ Placeholder math; SCF metrics need full implementation.

**Phase D — Detection**  
✅ `detector.py` runs; thresholds via `.env`.  
⚠ No confirmed prod-quality signals yet (strict thresholds + simple features).

**Phase E — Execution**  
✅ `executor_paper.py` functional.  
✅ `executor_live.py` stub integrated; routing/signing pending.  
⚠ No exit logic, PnL, or live trade integration.

---

## 7. Current Status

End-to-end loop runs: ingestion → parsers → features → detector → paper executor.  
Runner health shows DB advance and component activity.  
Signals rare with defaults — expected until metrics are real.

---

## 8. Immediate Next Steps

**Features**: compute true SCF metrics (ATR%, CVD slope, depth snapshots, watchers trend, wallet quality score).  
**Signals**: threshold tuning for occasional matches.  
**Exit Engine + PnL**: time stop, TP/SL, feature-based exit, risk halts.  
**Live Trading**: Jupiter quote/swap routing, key storage, slippage guards, confirmations.  
**Maintenance**: prune `tx_queue`, `tx_raw`, stale events for 24/7 stability.  
**Regime**: disable trading outside high-compressivity regimes.

---

## 9. Blind Spots & Risks

- Feature accuracy (placeholders).
- Threshold calibration (strict ⇒ no trades).
- Parser completeness (Solana complexity).
- Latency (Docker on Windows overhead).
- Uptime (no watchdog).
- Live trading safety.

---

## 10. Sanity Queries (PowerShell)

```powershell
docker exec -it scf_db psql -U scf -d scf -c "SELECT (SELECT MAX(slot) FROM tx_raw) tx_raw_max, (SELECT MAX(slot) FROM swap_event) swap_max, (SELECT MAX(slot) FROM lp_event) lp_max;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT (SELECT COUNT(*) FROM tx_raw WHERE to_timestamp((j->'result'->>'blockTime')::bigint)>now()-interval '10 min') tx_raw_10m, (SELECT COUNT(*) FROM swap_event WHERE ts>now()-interval '10 min') swaps_10m, (SELECT COUNT(*) FROM lp_event WHERE ts>now()-interval '10 min') lps_10m;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT pool, ts FROM features_latest ORDER BY ts DESC LIMIT 5;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM detector_signal WHERE created_at>now()-interval '1 hour';"
```

---

## 11. Target Production Flow

```
[ingest_queue]
      ↓
[worker_resolve]
      ↓
[parser_swap / parser_lp / parser_authority]
      ↓
[feature_worker]
      ↓
[detector]
      ↓
[executor_paper / executor_live]
      ↓
[positions / fills / logs]
```
Supervised by PM2/systemd/Task Scheduler. Configurable thresholds & modes. Auto-recovery, persistent logging, heartbeat.

---

## 12. Deployment Trajectory

1. Local full-loop test (paper).  
2. Historical backtest of detector logic.  
3. Go-live micro-size trades (`--mode live`).  
4. Iterate features/thresholds/risk.  
5. Deploy to VPS/cloud with monitoring.

---

## 13. Front-End & Modularity (post-core)

- Live dashboard (positions, signals, PnL, health).  
- Tuning UI for thresholds & regimes.  
- API layer for external tools.  
- Historical viewer/replay.

Reactive polling of DB/API; modular components.
