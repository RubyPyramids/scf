# app/feature_worker.py
# Minimal feature computation: ATR% (VC component) + simple CVD slope (OFS component)
# Writes to features_latest. Skips if insufficient data. No zeros.

import os, asyncio, asyncpg, math, statistics as stats
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

DB_URL = os.getenv("DB_URL", "postgresql://scf:scf@localhost:5432/scf")

SQL_CREATE = """
CREATE TABLE IF NOT EXISTS features_latest (
  pool text PRIMARY KEY,
  ts timestamptz NOT NULL,
  atr_pct_15m numeric,
  atr_pct_24h numeric,
  vc_ratio numeric,
  cvd_slope_5m numeric,
  obs integer
);
"""

SQL_POOLS = """
SELECT DISTINCT pool FROM swap_event WHERE ts > NOW() - INTERVAL '36 hours';
"""

SQL_SERIES = """
SELECT ts, price, base_amt, quote_amt, side
FROM swap_event
WHERE pool=$1 AND ts > NOW() - INTERVAL '36 hours'
ORDER BY ts ASC;
"""

SQL_UPSERT = """
INSERT INTO features_latest(pool, ts, atr_pct_15m, atr_pct_24h, vc_ratio, cvd_slope_5m, obs)
VALUES($1,$2,$3,$4,$5,$6,$7)
ON CONFLICT(pool) DO UPDATE SET
  ts=EXCLUDED.ts,
  atr_pct_15m=EXCLUDED.atr_pct_15m,
  atr_pct_24h=EXCLUDED.atr_pct_24h,
  vc_ratio=EXCLUDED.vc_ratio,
  cvd_slope_5m=EXCLUDED.cvd_slope_5m,
  obs=EXCLUDED.obs;
"""

def true_range_series(prices):
    trs = []
    prev = None
    for p in prices:
        if prev is None:
            prev = p
            continue
        trs.append(abs(p - prev))
        prev = p
    return trs

def atr_pct(prices, window_secs):
    if len(prices) < 3:
        return None
    # sample prices in a sliding window; approximate via full series
    trs = true_range_series(prices)
    if not trs:
        return None
    atr = sum(trs) / len(trs)
    meanp = sum(prices)/len(prices)
    if meanp <= 0:
        return None
    return (atr / meanp) * 100.0

def cvd_slope(ts_prices, sides, base_amts):
    # simple cumulative volume delta based on side sign and base amount
    cvd = 0.0
    series = []
    for s, a in zip(sides, base_amts):
        sign = 1 if s and s > 0 else -1 if s and s < 0 else 0
        cvd += sign * (a or 0.0)
        series.append(cvd)
    if len(series) < 3:
        return None
    # slope over last ~5 minutes window
    return (series[-1] - series[max(0, len(series)-5)]) / 5.0

async def compute_for_pool(conn, pool_id):
    rows = await conn.fetch(SQL_SERIES, pool_id)
    if not rows or len(rows) < 5:
        return
    prices   = [float(r['price']) for r in rows if r['price'] and float(r['price']) > 0]
    if len(prices) < 5:
        return
    sides    = [r['side'] for r in rows]
    base_amt = [float(r['base_amt'] or 0) for r in rows]

    atr15  = atr_pct(prices, 15*60)
    atr24  = atr_pct(prices, 24*3600)
    ratio  = (atr15/atr24) if (atr15 and atr24 and atr24>0) else None
    cvd5   = cvd_slope([r['ts'] for r in rows], sides, base_amt)

    await conn.execute(SQL_UPSERT, pool_id, datetime.now(timezone.utc), atr15, atr24, ratio, cvd5, len(rows))

async def main():
    pool = await asyncpg.create_pool(dsn=DB_URL, min_size=1, max_size=3)
    async with pool.acquire() as conn:
        await conn.execute(SQL_CREATE)

    while True:
        async with pool.acquire() as conn:
            pools = await conn.fetch(SQL_POOLS)
            for r in pools:
                try:
                    await compute_for_pool(conn, r['pool'])
                except Exception:
                    pass
        await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("feature_worker: stop")
