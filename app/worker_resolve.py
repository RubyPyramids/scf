
import os, asyncio, json, aiohttp, asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")
RPC_HTTP = os.getenv("RPC_HTTP_PRIMARY")

HEADERS = {"Content-Type": "application/json"}

async def get_tx(session, sig: str):
    payload = {
        "jsonrpc":"2.0",
        "id":1,
        "method":"getTransaction",
        "params":[sig, {"encoding":"json", "maxSupportedTransactionVersion":0}]
    }
    async with session.post(RPC_HTTP, headers=HEADERS, json=payload, timeout=30) as r:
        r.raise_for_status()
        return await r.json()

async def worker():
    print("worker_resolve: polling tx_queue and resolving to tx_raw")
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)
    async with aiohttp.ClientSession() as session:
        while True:
            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    WITH picked AS (
                        SELECT signature, program_id, slot
                        FROM tx_queue
                        WHERE status='queued'
                        ORDER BY enqueued ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE tx_queue q
                    SET status='resolving'
                    FROM picked p
                    WHERE q.signature = p.signature
                    RETURNING p.signature AS signature, p.program_id AS program_id, p.slot AS slot;
                """)
            if not row:
                await asyncio.sleep(1.0)
                continue

            sig = row["signature"]
            try:
                data = await get_tx(session, sig)
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(
                            """INSERT INTO tx_raw(signature, slot, j)
                               VALUES($1, $2, $3)
                               ON CONFLICT (signature) DO NOTHING""",
                            sig, row["slot"], json.dumps(data)
                        )
                        await conn.execute(
                            """UPDATE tx_queue SET status='resolved' WHERE signature=$1""",
                            sig
                        )
            except Exception as e:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE tx_queue
                           SET status = CASE WHEN retries >= 5 THEN 'error' ELSE 'queued' END,
                               retries = retries + 1,
                               last_error = left($2, 255)
                           WHERE signature=$1
                        """,
                        sig, str(e)
                    )
                await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(worker())
