# app/detector.py
import os, asyncio, json, logging
from typing import Any, Dict
import asyncpg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

DB_URL = os.getenv("DB_URL")
if not DB_URL:
    raise SystemExit("DB_URL missing in .env")

# ---- Tunable thresholds (env overrides) ----
VC_MAX   = float(os.getenv("SCF_VC_MAX",   "0.015"))
OFS_MAX  = float(os.getenv("SCF_OFS_MAX",  "0.001"))
LT_MAX   = float(os.getenv("SCF_LT_MAX",   "5000"))
WC_MIN   = float(os.getenv("SCF_WC_MIN",   "0.6"))
RQ_MAX   = float(os.getenv("SCF_RQ_MAX",   "0.5"))
POLL_SEC = float(os.getenv("SCF_DETECTOR_POLL_SEC", "2"))
DEDUP_SEC = int(os.getenv("SCF_DETECTOR_DEDUP_SEC", "300"))

# Map feature columns in your schema
FEATURE_KEYS = {
    "vc":  ["atr15"],                 # volatility compression proxy
    "ofs": ["cvd_slope_1m"],           # order flow stillness proxy
    "lt":  ["depth_1p0"],              # liquidity thinness proxy
    "wc":  ["wc_quality_arrivals"],    # wallet convergence proxy
    "rq":  ["watchers_slope"],         # retail quiet proxy
}

def pick(row: Dict[str, Any], keys) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None

SIGNAL_TYPE = "long"  # SCF is long-only for memecoins initially

CREATE_SIGNAL_SQL = """
CREATE TABLE IF NOT EXISTS detector_signal (
    id             BIGSERIAL PRIMARY KEY,
    pool           TEXT NOT NULL,
    signal_type    TEXT NOT NULL,
    reason         TEXT,
    feature_snapshot JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_detector_signal_pool_time ON detector_signal(pool, created_at DESC);
"""

CREATE_CURSOR_SQL = """
CREATE TABLE IF NOT EXISTS detector_cursor (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_seen TIMESTAMPTZ
)"""
UPSERT_CURSOR_SQL = """
INSERT INTO detector_cursor (id, last_seen)
VALUES (1, NOW())
ON CONFLICT (id) DO UPDATE SET last_seen = EXCLUDED.last_seen;
"""

SELECT_FEATURES_SQL = """
SELECT *
FROM features_latest
ORDER BY ts DESC NULLS LAST
LIMIT 1000;
"""

INSERT_SIGNAL_SQL = f"""
WITH recent AS (
  SELECT 1 FROM detector_signal ds
  WHERE ds.pool = $1
    AND ds.signal_type = $2
    AND ds.created_at >= NOW() - INTERVAL '{DEDUP_SEC} seconds'
  LIMIT 1
)
INSERT INTO detector_signal (pool, signal_type, reason, feature_snapshot)
SELECT $1, $2, $3, $4::jsonb
WHERE NOT EXISTS (SELECT 1 FROM recent);
"""

def rule_pass(row: Dict[str, Any]) -> (bool, str):
    vc = pick(row, FEATURE_KEYS["vc"])
    ofs = pick(row, FEATURE_KEYS["ofs"])
    lt  = pick(row, FEATURE_KEYS["lt"])
    wc  = pick(row, FEATURE_KEYS["wc"])
    rq  = pick(row, FEATURE_KEYS["rq"])

    missing = [k for k, v in {"vc": vc, "ofs": ofs, "lt": lt, "wc": wc, "rq": rq}.items() if v is None]
    if missing:
        return False, f"missing:{','.join(missing)}"

    try:
        vc = float(vc); ofs = float(ofs); lt = float(lt); wc = float(wc); rq = float(rq)
    except Exception:
        return False, "type_cast_fail"

    conds = [
        ("VC",  vc <= VC_MAX),
        ("OFS", abs(ofs) <= OFS_MAX),
        ("LT",  lt <= LT_MAX),
        ("WC",  wc >= WC_MIN),
        ("RQ",  rq <= RQ_MAX),
    ]
    failed = [name for name, ok in conds if not ok]
    if failed:
        return False, "fail:" + ",".join(failed)

    return True, f"SCF5:vc<={VC_MAX},|ofs|<={OFS_MAX},lt<={LT_MAX},wc>={WC_MIN},rq<={RQ_MAX}"

async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(CREATE_SIGNAL_SQL)
        await conn.execute(CREATE_CURSOR_SQL)
        logging.info("Detector online. Poll %.1fs, dedup %ds.", POLL_SEC, DEDUP_SEC)

        while True:
            rows = await conn.fetch(SELECT_FEATURES_SQL)
            made = 0
            for r in rows:
                row = dict(r)
                pool = (row.get("pool") or "").strip()
                if not pool:
                    continue

                ok, reason = rule_pass(row)
                if not ok:
                    continue

                snapshot = json.dumps(row, default=str)
                await conn.execute(
                    INSERT_SIGNAL_SQL,
                    pool,
                    SIGNAL_TYPE,
                    reason,
                    snapshot,
                )
                made += 1

            if made:
                logging.info("Signals emitted: %d", made)

            await conn.execute(UPSERT_CURSOR_SQL)
            await asyncio.sleep(POLL_SEC)
    finally:
        await conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
