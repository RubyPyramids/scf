# parser_authority.py — scaffold parser for authority events
# Writes minimal authority_event rows keyed by mint or pool if detectable later.
# For now, we attach only timestamp and optional pool from tx_queue.

import os, asyncio, asyncpg, time
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")

BATCH = int(os.getenv("PARSER_BATCH", "100"))

SQL_PICK = """WITH c AS (
  SELECT r.signature, r.slot, (r.j->'result'->>'blockTime')::bigint AS block_time
  FROM tx_raw r
  LEFT JOIN parsed_sig p ON p.signature = r.signature
  WHERE (p.signature IS NULL OR p.has_auth = FALSE)
  ORDER BY r.slot ASC
  LIMIT $1
)
SELECT c.signature, c.slot, COALESCE(c.block_time, extract(epoch from now())::bigint) AS block_time,
       q.program_id
FROM c
LEFT JOIN tx_queue q ON q.signature = c.signature;
"""

SQL_INSERT_AUTH = """INSERT INTO authority_event(ts, mint, pool, fee_switch, tax_flag, mint_auth, freeze_auth)
VALUES($1, 'unknown', $2, NULL, NULL, NULL, NULL)
"""

SQL_UPSERT_PARSED = """INSERT INTO parsed_sig(signature, has_auth) VALUES($1, TRUE)
ON CONFLICT (signature) DO UPDATE SET has_auth=TRUE
"""

async def run():
  pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)
  print("parser_authority: starting")
  while True:
    async with pool.acquire() as conn:
      rows = await conn.fetch(SQL_PICK, BATCH)
    if not rows:
      await asyncio.sleep(1.0)
      continue

    ins = 0
    async with pool.acquire() as conn:
      async with conn.transaction():
        for r in rows:
          sig   = r["signature"]
          slot  = r["slot"]
          bt    = int(r["block_time"]) if r["block_time"] is not None else int(time.time())
          ts    = datetime.fromtimestamp(bt, tz=timezone.utc)
          pool_id = r["program_id"]
          await conn.execute(SQL_INSERT_AUTH, ts, pool_id)
          await conn.execute(SQL_UPSERT_PARSED, sig)
          ins += 1
    print(f"parser_authority: inserted {ins} rows")
    await asyncio.sleep(0.1)

if __name__ == "__main__":
  asyncio.run(run())
