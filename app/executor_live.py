# executor_live.py — live executor skeleton
# Same polling/dedup loop as paper, but clearly marked TODOs where real trading should go.
# For now it records positions exactly like paper, but with meta.mode="live_stub".
# Replace the "price/qty/tx" section with your real trade integration (e.g., Jupiter, RPC send, signer).

import os, asyncio, json, logging, uuid
import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DB_URL    = os.getenv("DB_URL")
POLL_SEC  = float(os.getenv("SCF_EXECUTOR_POLL_SEC", "2"))
WINDOW    = os.getenv("SCF_EXECUTOR_WINDOW_MIN", "10")
BATCH     = int(os.getenv("SCF_EXECUTOR_BATCH", "200"))

if not DB_URL:
    raise SystemExit("DB_URL missing in .env")

SELECT_SIGNALS_SQL = """
SELECT id, pool, signal_type, reason
FROM detector_signal
WHERE created_at > NOW() - ($1::int || ' minutes')::interval
ORDER BY created_at ASC
LIMIT $2;
"""

EXISTS_SQL = "SELECT 1 FROM position WHERE (meta->>'signal_id') = $1 LIMIT 1;"

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
VALUES (NOW(), $1, 'entry', $2, $3, $4);
"""

async def process_batch(conn: asyncpg.Connection) -> int:
    signals = await conn.fetch(SELECT_SIGNALS_SQL, int(WINDOW), BATCH)
    opened = 0

    for s in signals:
        sig_id   = str(s["id"])
        pool     = s["pool"]
        sig_type = s["signal_type"]
        reason   = s["reason"]

        if await conn.fetchval(EXISTS_SQL, sig_id):
            continue

        # TODO: fetch market price and compute size/route; sign/send TX; wait for confirmation
        # For now, this is a no-risk stub that records the intent.
        token       = "SOL"
        size_sol    = 0.01           # example: small live allocation; change when you wire risk sizing
        entry_px    = 1.0            # TODO: replace with real fetched price
        slippage    = 50             # bps, example placeholder
        tx_sig      = None           # TODO: set to actual chain signature after send
        state       = "open"
        entry_price = entry_px
        meta        = {"signal_id": sig_id, "source": "detector_signal", "mode": "live_stub"}

        pos_id = uuid.uuid4()
        new_pos_id = await conn.fetchval(
            INSERT_POSITION_SQL,
            pos_id, pool, token, size_sol, entry_px, slippage, state,
            sig_type, reason, entry_price, json.dumps(meta),
        )

        await conn.execute(INSERT_FILL_SQL, new_pos_id, entry_px, size_sol, tx_sig)
        opened += 1
        logging.info("Opened LIVE-STUB position %s on pool %s (signal %s)", new_pos_id, pool, sig_id)

    return opened

async def main():
    logging.info("executor_live: starting (poll %.1fs, window %sm, batch %d)", POLL_SEC, WINDOW, BATCH)
    conn = await asyncpg.connect(DB_URL)
    try:
        while True:
            try:
                opened = await process_batch(conn)
                if opened:
                    logging.info("executor_live: opened %d positions in this tick", opened)
            except Exception as e:
                logging.exception("executor_live: tick error: %s", e)
                await asyncio.sleep(min(POLL_SEC * 2, 5.0))
            await asyncio.sleep(POLL_SEC)
    finally:
        await conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
