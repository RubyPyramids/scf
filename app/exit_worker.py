# app/exit_worker.py
# Monitors open positions and exits on configurable profit/loss thresholds.
# No time-based auto-close. Uses latest observed price per pool.
#
# ENV:
#   SCF_TP_MULT       (float)  default 2.0     e.g., 2.0 = +100% (2x)
#   SCF_SL_MULT       (float)  default 0.30    e.g., 0.30 = -70% (down to 30% of entry)
#   SCF_EXIT_POLL_SEC (int)    default 5       seconds between scans
#
# NOTES:
# - Price source = latest swap_event.price for the position's pool.
# - If price is 0/NULL (e.g., parser not decoding yet), skip that position this tick.
# - Records an exit row in exit_event and marks position.state='CLOSED'.
# - Adds a SELL fill at the exit price with qty=size_sol (paper/live reconciliation later).
# - Partial exits: scaffolding via SCF_TP_PARTIAL and SCF_SL_PARTIAL (disabled unless set).
#   Format: "level1:ratio1,level2:ratio2" where level is price multiple of entry, ratio∈(0,1].
#   Example: SCF_TP_PARTIAL="1.5:0.25,2.0:0.25" (sell 25% at 1.5x and 25% at 2.0x)

import os, asyncio, asyncpg
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL            = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")
TP_MULT           = float(os.getenv("SCF_TP_MULT", "2.0"))
SL_MULT           = float(os.getenv("SCF_SL_MULT", "0.30"))
POLL_SEC          = int(os.getenv("SCF_EXIT_POLL_SEC", "5"))
TP_PARTIAL_SPEC   = os.getenv("SCF_TP_PARTIAL", "").strip()
SL_PARTIAL_SPEC   = os.getenv("SCF_SL_PARTIAL", "").strip()

def _now_utc():
    return datetime.now(timezone.utc)

def _parse_partials(spec: str):
    # "1.5:0.25,2.0:0.25"  -> [(1.5, 0.25), (2.0, 0.25)] ordered by level asc
    out = []
    if not spec:
        return out
    for item in spec.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        lvl, rat = item.split(":", 1)
        try:
            lvl_f = float(lvl.strip())
            rat_f = float(rat.strip())
            if lvl_f > 0 and 0 < rat_f <= 1:
                out.append((lvl_f, rat_f))
        except ValueError:
            continue
    return sorted(out, key=lambda x: x[0])

TP_PARTIALS = _parse_partials(TP_PARTIAL_SPEC)
SL_PARTIALS = _parse_partials(SL_PARTIAL_SPEC)

SQL_OPEN_POSITIONS = """
SELECT id, opened, pool, token, size_sol, entry_px, state, COALESCE(meta, '{}'::jsonb) AS meta
FROM position
WHERE state='OPEN';
"""

SQL_LATEST_PRICE = """
SELECT price
FROM swap_event
WHERE pool=$1
ORDER BY ts DESC
LIMIT 1;
"""

SQL_INSERT_FILL = """
INSERT INTO fill(ts, pos_id, side, px, qty, tx)
VALUES($1, $2, $3, $4, $5, NULL);
"""

SQL_CLOSE_POSITION = """
UPDATE position
SET state='CLOSED'
WHERE id=$1;
"""

SQL_INSERT_EXIT = """
INSERT INTO exit_event(ts, pos_id, reason, meta)
VALUES($1, $2, $3, $4);
"""

async def _get_latest_price(conn: asyncpg.Connection, pool: str) -> float | None:
    px = await conn.fetchval(SQL_LATEST_PRICE, pool)
    try:
        if px is None:
            return None
        return float(px)
    except (InvalidOperation, ValueError, TypeError):
        return None

async def _apply_partial(conn: asyncpg.Connection, pos_id, pool, entry_px: float, cur_px: float,
                         partials: list[tuple[float, float]], side_label: str, reason: str, meta_tag: str):
    """
    Execute partial fills when price multiple is crossed. Uses 'meta' to track which
    levels have been filled already to avoid duplicate partials.
    """
    row = await conn.fetchrow("SELECT meta FROM position WHERE id=$1", pos_id)
    taken = set()
    if row and row["meta"]:
        m = row["meta"]
        if isinstance(m, dict):
            for k, v in m.items():
                if k.startswith("partial_") and v == True:
                    taken.add(k)
    mul = cur_px / max(entry_px, 1e-12)
    for level, ratio in partials:
        tag = f"partial_{meta_tag}_{level}"
        if mul >= level and tag not in taken:
            qty = await conn.fetchval("SELECT size_sol FROM position WHERE id=$1", pos_id)
            if qty is None:
                continue
            take_qty = float(qty) * float(ratio)
            now = _now_utc()
            await conn.execute(SQL_INSERT_FILL, now, pos_id, side_label, float(cur_px), take_qty)
            await conn.execute("UPDATE position SET size_sol = size_sol - $2 WHERE id=$1", pos_id, take_qty)
            await conn.execute("UPDATE position SET meta = COALESCE(meta,'{}'::jsonb) || $2::jsonb WHERE id=$1",
                               pos_id, {tag: True})
            await conn.execute(SQL_INSERT_EXIT, now, pos_id, f"{reason}_PARTIAL",
                               {"level": level, "ratio": ratio, "px": cur_px})

async def _close_full(conn: asyncpg.Connection, pos_id, side_label: str, cur_px: float, reason: str, meta=None):
    now = _now_utc()
    qty = await conn.fetchval("SELECT size_sol FROM position WHERE id=$1", pos_id)
    if qty is None:
        qty = 0.0
    await conn.execute(SQL_INSERT_FILL, now, pos_id, side_label, float(cur_px), float(qty))
    await conn.execute(SQL_CLOSE_POSITION, pos_id)
    await conn.execute(SQL_INSERT_EXIT, now, pos_id, reason, meta or {})

async def main():
    print("exit_worker: starting (TP/SL only; no time-stop)")
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)

    while True:
        try:
            async with pool.acquire() as conn:
                positions = await conn.fetch(SQL_OPEN_POSITIONS)
                for p in positions:
                    pos_id   = p["id"]
                    pool_id  = p["pool"]
                    entry_px = float(p["entry_px"])
                    cur_px = await _get_latest_price(conn, pool_id)
                    if not cur_px or cur_px <= 0.0:
                        continue

                    tp_px = entry_px * TP_MULT
                    sl_px = entry_px * SL_MULT

                    if TP_PARTIALS:
                        await _apply_partial(conn, pos_id, pool_id, entry_px, cur_px,
                                             TP_PARTIALS, "SELL", "TP", "TP")
                    if SL_PARTIALS:
                        await _apply_partial(conn, pos_id, pool_id, entry_px, cur_px,
                                             SL_PARTIALS, "SELL", "SL", "SL")

                    if cur_px >= tp_px:
                        await _close_full(conn, pos_id, "SELL", cur_px, "TP_HIT",
                                          {"entry_px": entry_px, "exit_px": cur_px, "tp_mult": TP_MULT})
                    elif cur_px <= sl_px:
                        await _close_full(conn, pos_id, "SELL", cur_px, "SL_HIT",
                                          {"entry_px": entry_px, "exit_px": cur_px, "sl_mult": SL_MULT})

        except Exception as e:
            print(f"exit_worker: error {e}")

        await asyncio.sleep(POLL_SEC)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("exit_worker: stopped")