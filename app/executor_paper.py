# executor_paper.py — long-running paper executor
# - Watches detector_signal for fresh rows
# - Dedups using position.meta->>'signal_id'
# - Opens paper positions (size=0, stub price) + inserts an entry fill
# - Never exits; logs activity periodically

import os, asyncio, json, logging, uuid
from typing import Optional
import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DB_URL    = os.getenv("DB_URL")
POLL_SEC  = float(os.getenv("SCF_EXECUTOR_POLL_SEC", "2"))
WINDOW    = os.getenv("SCF_EXECUTOR_WINDOW_MIN", "10")  # minutes of signals to consider
BATCH     = int(os.getenv("SCF_EXECUTOR_BATCH", "200"))

if not DB_URL:
    raise SystemExit("DB_URL missing in .env")

# Pull recent signals from the last N minutes, oldest first
SELECT_SIGNALS_SQL = """
SELECT id, pool, signal_type, reason
FROM detector_signal
WHERE created_at > NOW() - ($1::int || ' minutes')::interval
ORDER BY created_at ASC
LIMIT $2;
"""

# Strong dedup: skip if a position already references this signal_id in meta
EXISTS_SQL = "SELECT 1 FROM position WHERE (meta->>'signal_id') = $1 LIMIT 1;"

# Minimal insert for your UUID schema
INSERT_POSITION_SQL = """
INSERT INTO position (
  id, opened, pool, token, size_sol, entry_px, slippage_bps, state, status,
  signal_type, reason, entry_price, opened_at, meta
) VALUES (
  $1, NOW(), $2, $3, $4, $5, $6, $7, 'open',
  $8, $9, $10, NOW(), $11::jsonb
) RETURNING id;
"""

INSERT_FILL_SQL = """
INSERT INTO fill (ts, pos_id, side, px, qty, tx)
VALUES (NOW(), $1, 'entry', $2, $3, NULL);
"""

async def process_batch(conn: asyncpg.Connection) -> int:
    signals = await conn.fetch(SELECT_SIGNALS_SQL, int(WINDOW), BATCH)
    opened = 0

    for s in signals:
        sig_id   = str(s["id"])
        pool     = s["pool"]
        sig_type = s["signal_type"]
        reason   = s["reason"]

        # Dedup
        if await conn.fetchval(EXISTS_SQL, sig_id):
            continue

        # Paper placeholders (safe no-trade stubs)
        pos_id      = uuid.uuid4()
        token       = "SOL"
        size_sol    = 0            # paper size = 0 until sizing logic added
        entry_px    = 1.0          # stub price
        slippage    = 0            # bps
        state       = "open"
        entry_price = entry_px
        meta        = {"signal_id": sig_id, "source": "detector_signal", "mode": "paper"}

        new_pos_id = await conn.fetchval(
            INSERT_POSITION_SQL,
            pos_id,           # $1 id (uuid)
            pool,             # $2 pool
            token,            # $3 token
            size_sol,         # $4 size_sol
            entry_px,         # $5 entry_px
            slippage,         # $6 slippage_bps
            state,            # $7 state
            sig_type,         # $8 signal_type
            reason,           # $9 reason
            entry_price,      # $10 entry_price
            json.dumps(meta), # $11 meta jsonb
        )

        await conn.execute(INSERT_FILL_SQL, new_pos_id, entry_px, 0)
        opened += 1
        logging.info("Opened PAPER position %s on pool %s (signal %s)", new_pos_id, pool, sig_id)

    return opened

async def main():
    logging.info("executor_paper: starting (poll %.1fs, window %sm, batch %d)", POLL_SEC, WINDOW, BATCH)
    conn = await asyncpg.connect(DB_URL)
    try:
        while True:
            try:
                opened = await process_batch(conn)
                if opened:
                    logging.info("executor_paper: opened %d positions in this tick", opened)
            except Exception as e:
                logging.exception("executor_paper: tick error: %s", e)
                # brief backoff on error so we don't spam logs
                await asyncio.sleep(min(POLL_SEC * 2, 5.0))
            await asyncio.sleep(POLL_SEC)
    finally:
        await conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
