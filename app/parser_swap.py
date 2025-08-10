# app/parser_swap.py
# Swap parser: derive per-tx swap amounts and price from pre/post token balances.
# No zeros inserted: if we can't infer, we skip.
# Writes into swap_event using dynamic column introspection.

import os, asyncio, asyncpg, json
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")
WSOL  = os.getenv("WSOL_MINT", "So11111111111111111111111111111111111111112")

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

def _balances_by_mint(tb):
    # tb: list of {accountIndex, mint, uiTokenAmount:{uiAmount}}, may contain None uiAmount for 0
    out = {}
    for b in tb or []:
        mint = b.get('mint')
        amt  = (((b.get('uiTokenAmount') or {}).get('uiAmount')) or 0) or 0
        try:
            amt = float(amt)
        except Exception:
            amt = 0.0
        out[mint] = out.get(mint, 0.0) + amt
    return out

def _two_largest_opposite(m):
    # m: dict mint -> delta
    # pick two with largest |delta| and opposite sign
    items = sorted(((k, v) for k, v in m.items() if v != 0.0), key=lambda kv: abs(kv[1]), reverse=True)
    for i in range(len(items)):
        for j in range(i+1, len(items)):
            if items[i][1] * items[j][1] < 0:
                return items[i], items[j]
    return None

def infer_swap(txj):
    meta = txj.get('meta') or {}
    pre  = _balances_by_mint(meta.get('preTokenBalances'))
    post = _balances_by_mint(meta.get('postTokenBalances'))
    if not pre and not post:
        return None
    # deltas = post - pre
    all_mints = set(pre) | set(post)
    deltas = {m: post.get(m,0.0) - pre.get(m,0.0) for m in all_mints}
    pick = _two_largest_opposite(deltas)
    if not pick:
        return None
    (m1, d1), (m2, d2) = pick
    # Orient so base is the asset with positive delta (received), quote is negative (spent)
    if d1 > 0 and d2 < 0:
        base_mint, base_amt = m1, d1
        quote_mint, quote_amt = m2, -d2
    elif d2 > 0 and d1 < 0:
        base_mint, base_amt = m2, d2
        quote_mint, quote_amt = m1, -d1
    else:
        return None
    # Price definition: quote per base
    if base_amt <= 0 or quote_amt <= 0:
        return None
    price = quote_amt / base_amt
    # Side: if base mint is WSOL, treat as SELL (received SOL), else BUY (spent SOL, received token)
    side = 1 if base_mint != WSOL and quote_mint == WSOL else (-1 if base_mint == WSOL else 0)
    return {
        "base_mint": base_mint, "quote_mint": quote_mint,
        "base_amt": base_amt, "quote_amt": quote_amt,
        "price": price, "side": side
    }

async def main():
    print("parser_swap: start")
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)
    async with pool.acquire() as conn:
        await conn.execute(SQL_CREATE_CURSOR)
        cur = await conn.fetchval(SQL_GET_CURSOR, "parser_swap")
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
                        txj = json.loads(txj)
                    got = infer_swap(txj)
                    if got:
                        # choose a pool id if present in log messages; fallback to "<base>-<quote>"
                        pool_id = f"{got['base_mint']}-{got['quote_mint']}"
                        await dyn_insert(conn, "swap_event", {
                            "ts": datetime.fromtimestamp((txj.get('blockTime') or 0), tz=timezone.utc) if txj.get('blockTime') else datetime.now(timezone.utc),
                            "pool": pool_id,
                            "token": got["base_mint"],
                            "side": got["side"],
                            "price": got["price"],
                            "base_amt": got["base_amt"],
                            "quote_amt": got["quote_amt"],
                            "slot": slot,
                            "sig": sig
                        })
                except Exception as e:
                    # best-effort; skip bad tx
                    pass
                last_slot = slot
            await conn.execute(SQL_SET_CURSOR, "parser_swap", {"last_slot": last_slot})

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("parser_swap: stop")
