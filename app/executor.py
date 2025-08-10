# app/executor.py
import os, asyncio, json, logging, uuid
import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DB_URL   = os.getenv("DB_URL")
POLL_SEC = float(os.getenv("SCF_EXECUTOR_POLL_SEC", "2"))
if not DB_URL:
    raise SystemExit("DB_URL missing in .env")

# Pull recent signals (time window prevents ancient backlog)
SELECT_SIGNALS_SQL = """
SELECT *
FROM detector_signal
WHERE created_at > NOW() - INTERVAL '10 minutes'
ORDER BY created_at ASC
LIMIT 200;
"""

# Strong dedup: skip if a position already references this signal_id in meta
EXISTS_SQL = "SELECT 1 FROM position WHERE (meta->>'signal_id') = $1 LIMIT 1;"

# Insert into your UUID+strict schema
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

async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        logging.info("Executor online. Poll %.1fs.", POLL_SEC)
        while True:
            signals = await conn.fetch(SELECT_SIGNALS_SQL)
            if signals:
                for s in signals:
                    sig_id   = s["id"]                # bigint (detector_signal.id)
                    pool     = s["pool"]
                    sig_type = s["signal_type"]
                    reason   = s.get("reason")

                    # Dedup: ensure we haven't already opened for this signal
                    if await conn.fetchval(EXISTS_SQL, str(sig_id)):
                        continue

                    # Paper placeholders (replace when price/size feed is wired)
                    pos_id      = uuid.uuid4()   # position.id is UUID
                    token       = "SOL"
                    size_sol    = 0              # paper size = 0 until sizing logic
                    entry_px    = 1.0            # stub price
                    slippage    = 0              # bps
                    state       = "open"
                    entry_price = entry_px
                    meta        = {"signal_id": str(sig_id), "source": "detector_signal"}

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
                    logging.info("Opened paper position %s on pool %s (signal %s)", new_pos_id, pool, sig_id)

            await asyncio.sleep(POLL_SEC)
    finally:
        await conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
