import os, asyncio, asyncpg
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))
DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")

# widen to 24h and also provide a backfill-all
PICK_POOLS_24H = '''
WITH recent AS (
  SELECT pool, max(ts) AS ts FROM (
    SELECT pool, ts FROM swap_event WHERE pool <> 'unknown' AND ts > now() - interval '24 hour'
    UNION ALL
    SELECT pool, ts FROM lp_event   WHERE pool <> 'unknown' AND ts > now() - interval '24 hour'
  ) u GROUP BY pool
)
SELECT pool, ts FROM recent;
'''

PICK_POOLS_ALL = '''
WITH allp AS (
  SELECT pool, max(ts) AS ts FROM (
    SELECT pool, ts FROM swap_event WHERE pool <> 'unknown'
    UNION ALL
    SELECT pool, ts FROM lp_event   WHERE pool <> 'unknown'
  ) u GROUP BY pool
)
SELECT pool, ts FROM allp;
'''

UPSERT = '''
INSERT INTO features_latest (pool, ts)
VALUES ($1, $2)
ON CONFLICT (pool) DO UPDATE SET ts = EXCLUDED.ts;
'''

async def backfill_all(conn):
    rows = await conn.fetch(PICK_POOLS_ALL)
    if not rows:
        return 0
    async with conn.transaction():
        for r in rows:
            await conn.execute(UPSERT, r["pool"], r["ts"])
    return len(rows)

async def loop_24h(conn):
    rows = await conn.fetch(PICK_POOLS_24H)
    if not rows:
        return 0
    async with conn.transaction():
        for r in rows:
            await conn.execute(UPSERT, r["pool"], r["ts"])
    return len(rows)

async def main():
    print("feature_worker: starting (24h + backfill)")
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)

    # one-time backfill so features_latest isn’t empty
    async with pool.acquire() as conn:
        n = await backfill_all(conn)
        print(f"feature_worker: backfilled {n} pools (all-time)")

    while True:
        async with pool.acquire() as conn:
            n = await loop_24h(conn)
            print(f"feature_worker: upserted {n} pools (last 24h) @ {datetime.now(timezone.utc).isoformat()}")
        await asyncio.sleep(10.0)

if __name__ == "__main__":
    asyncio.run(main())
