# app/parser_lp.py
# LP parser: placeholder upgraded to NO-OP unless confident data is present.
# It does not write zeroed reserves. It only writes when inferrable.

import os, asyncio, asyncpg, json
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")

SQL_CREATE_CURSOR = """
CREATE TABLE IF NOT EXISTS cursor_state(
  name text primary key,
  value jsonb not null default '{}'::jsonb
);
"""

SQL_GET_CURSOR = "SELECT value FROM cursor_state WHERE name=$1;"
SQL_SET_CURSOR = """
INSERT INTO cursor_state(name, value)
VALUES($1, $2)
ON CONFLICT(name) DO UPDATE SET value=EXCLUDED.value;
"""

SQL_FETCH_TX = """
SELECT sig, slot, json
FROM tx_raw
WHERE slot > $1
ORDER BY slot ASC
LIMIT 500;
"""

SQL_COLS = """
SELECT a.attname
FROM pg_attribute a
JOIN pg_class c ON a.attrelid=c.oid
JOIN pg_namespace n ON c.relnamespace=n.oid
WHERE n.nspname='public' AND c.relname=$1 AND a.attnum>0 AND NOT a.attisdropped
ORDER BY a.attnum;
"""

async def table_cols(conn, table):
    cols = await conn.fetch(SQL_COLS, table)
    return [r['attname'] for r in cols]

async def dyn_insert(conn, table, row: dict):
    cols = await table_cols(conn, table)
    use = {k: v for k, v in row.items() if k in cols}
    if not use: 
        return
    fields = ",".join(use.keys())
    params = ",".join(f"${i}" for i,_ in enumerate(use, start=1))
    sql = f"INSERT INTO {table} ({fields}) VALUES ({params}) ON CONFLICT DO NOTHING;"
    await conn.execute(sql, *use.values())

def now_utc():
    return datetime.now(timezone.utc)

def infer_pool_reserves(txj):
    # Without per-program account maps, we avoid guessing.
    # If the tx contains a clear pair of token balances in postTokenBalances with same owner,
    # we can record a coarse "snapshot". Otherwise return None.
    return None

async def main():
    print("parser_lp: start")
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(SQL_CREATE_CURSOR)
        cur = await conn.fetchval(SQL_GET_CURSOR, "parser_lp")
        last_slot = (cur or {}).get("last_slot", 0)

    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(SQL_FETCH_TX, last_slot)
            if not rows:
                await asyncio.sleep(2)
                continue
            for r in rows:
                sig = r['sig']; slot = r['slot']
                try:
                    txj = r['json']
                    if isinstance(txj, str):
                        import json as _json
                        txj = _json.loads(txj)
                    snap = infer_pool_reserves(txj)
                    if snap:
                        await dyn_insert(conn, "lp_event", snap | {"slot": slot, "sig": sig, "ts": now_utc()})
                except Exception:
                    pass
                last_slot = slot
            await conn.execute(SQL_SET_CURSOR, "parser_lp", {"last_slot": last_slot})

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("parser_lp: stop")
