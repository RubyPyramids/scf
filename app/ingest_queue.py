
import os, asyncio, asyncpg, websockets, orjson
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")
WS_URL = os.getenv("RPC_PRIMARY")

RAYDIUM_AMM = os.getenv("RAYDIUM_AMM")
RAYDIUM_CLMM = os.getenv("RAYDIUM_CLMM")
ORCA_AMM = os.getenv("ORCA_AMM")

def sub_msg(pid, subid):
    return {
        "jsonrpc": "2.0",
        "id": subid,
        "method": "logsSubscribe",
        "params": [
            {"mentions": [pid]},
            {"commitment": "finalized"}
        ],
    }

async def main():
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=4)
    print("ingest_queue: subscribed; writing signatures into tx_queue")
    inserted = 0
    while True:
        try:
            async with websockets.connect(WS_URL, max_size=20_000_000) as ws:
                subid = 1
                for pid in [RAYDIUM_AMM, RAYDIUM_CLMM, ORCA_AMM]:
                    await ws.send(orjson.dumps(sub_msg(pid, subid)))
                    subid += 1

                async for raw in ws:
                    try:
                        msg = orjson.loads(raw)
                    except Exception:
                        continue
                    if msg.get("method") != "logsNotification":
                        continue

                    params = msg.get("params", {})
                    result = params.get("result", {})
                    value = result.get("value", {})
                    program_id = value.get("programId")
                    slot = result.get("context", {}).get("slot")

                    # Helius / Solana returns a *single* signature per logsNotification
                    sig = value.get("signature")
                    if not sig:
                        continue

                    async with pool.acquire() as conn:
                        try:
                            await conn.execute(
                                """INSERT INTO tx_queue(signature, program_id, slot, status)
                                       VALUES($1, $2, $3, 'queued')
                                       ON CONFLICT (signature) DO NOTHING""",
                                sig, program_id, slot
                            )
                            inserted += 1
                            if inserted % 10 == 0:
                                print(f"ingest_queue: queued {inserted} signatures so far...")
                        except Exception as e:
                            # harmless in dev; log and continue
                            print(f"ingest_queue: insert error for {sig}: {e}")
        except Exception as e:
            print(f"WS error: {e}; reconnecting in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
