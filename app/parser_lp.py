# parser_lp.py — writes lp_event rows from tx_raw for known AMM programs only.
# Advances by slot>last, skips unknown pools (does NOT write 'unknown') and stores sig.

import os, asyncio, asyncpg, time, json, sys
from datetime import datetime, timezone
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")
BATCH = int(os.getenv("PARSER_BATCH", "200"))

RAYDIUM_AMM  = os.getenv("RAYDIUM_AMM",  "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
RAYDIUM_CLMM = os.getenv("RAYDIUM_CLMM", "4hGdEStwqyqZkG2tZibsSDQ7SBy7xH2sVQ2QJVV5o4Ck")
ORCA_AMM     = os.getenv("ORCA_AMM",     "9WwG7VJp49r4bgx1mVQqZKkGKuX3sX5Y3F9F6w8vG8bS")
ORCA_WHIRL   = os.getenv("ORCA_WHIRL",   "whirLbMiicVq4SCVZxdrmB9otnE8u6VYzG9xH8Wc7so")

PROGRAM_SET = {RAYDIUM_AMM, RAYDIUM_CLMM, ORCA_AMM, ORCA_WHIRL}

SQL_LAST_SLOT = "SELECT COALESCE(MAX(slot), 0) AS s FROM lp_event;"

SQL_PICK_AFTER_SLOT = """
SELECT r.signature, r.slot,
       (r.j->'result'->>'blockTime')::bigint AS block_time,
       r.j AS raw
FROM tx_raw r
WHERE r.slot > $1
ORDER BY r.slot ASC
LIMIT $2;
"""

# NOTE: now inserting sig as the first column
SQL_INSERT_LP = """
INSERT INTO lp_event(sig, ts, slot, pool, x_reserve, y_reserve, fee_bps, kind)
VALUES($1, $2, $3, $4, NULL, NULL, NULL, 'update')
"""

SQL_UPSERT_PARSED = """
INSERT INTO parsed_sig(signature, has_lp) VALUES($1, TRUE)
ON CONFLICT (signature) DO UPDATE SET has_lp=TRUE
"""

def _collect_account_keys(raw: dict) -> set:
    found = set()
    try:
        keys = raw["result"]["transaction"]["message"]["accountKeys"]
        for k in keys:
            if isinstance(k, str):
                found.add(k)
            elif isinstance(k, dict) and isinstance(k.get("pubkey"), str):
                found.add(k["pubkey"])
    except Exception:
        pass
    try:
        ixs = raw["result"]["transaction"]["message"].get("instructions") or []
        for ix in ixs:
            pid = ix.get("programId")
            if isinstance(pid, str):
                found.add(pid)
    except Exception:
        pass
    return found

def detect_program_id(raw: dict) -> str | None:
    keys = _collect_account_keys(raw)
    for pid in PROGRAM_SET:
        if pid in keys:
            return pid
    return None

async def run():
    print("parser_lp: starting", flush=True)
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)

    last_slot = 0
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_LAST_SLOT)
        last_slot = int(row["s"]) if row and row["s"] is not None else 0

    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(SQL_PICK_AFTER_SLOT, last_slot, BATCH)

        if not rows:
            await asyncio.sleep(1.0)
            continue

        inserted = 0
        skipped  = 0
        max_slot_seen = last_slot

        async with pool.acquire() as conn:
            async with conn.transaction():
                for r in rows:
                    sig  = r["signature"]
                    slot = int(r["slot"])
                    if slot > max_slot_seen:
                        max_slot_seen = slot

                    bt   = int(r["block_time"]) if r["block_time"] is not None else int(time.time())
                    ts   = datetime.fromtimestamp(bt, tz=timezone.utc)

                    raw = r["raw"]
                    if isinstance(raw, str):
                        raw = json.loads(raw)

                    pool_id = detect_program_id(raw)
                    if not pool_id:
                        await conn.execute(SQL_UPSERT_PARSED, sig)
                        skipped += 1
                        continue

                    # Insert with sig captured
                    await conn.execute(SQL_INSERT_LP, sig, ts, slot, pool_id)
                    await conn.execute(SQL_UPSERT_PARSED, sig)
                    inserted += 1

        last_slot = max_slot_seen
        print(f"parser_lp: inserted {inserted}, skipped {skipped}, last_slot={last_slot}", flush=True)
        await asyncio.sleep(0.1)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("parser_lp: stopped", file=sys.stderr)
