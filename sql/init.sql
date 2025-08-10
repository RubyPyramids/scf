-- SCF bootstrap schema (lossless, minimal). Run automatically at first container start via docker-entrypoint.
-- core events
CREATE TABLE IF NOT EXISTS swap_event(
  ts TIMESTAMPTZ NOT NULL,
  sig TEXT NOT NULL,
  slot BIGINT NOT NULL,
  pool TEXT NOT NULL,
  token TEXT NOT NULL,
  side CHAR(1) NOT NULL, -- 'B' or 'S' from taker perspective
  price NUMERIC NOT NULL,
  base_amt NUMERIC NOT NULL,
  quote_amt NUMERIC NOT NULL,
  taker TEXT,
  maker TEXT,
  router TEXT
);
CREATE INDEX IF NOT EXISTS idx_swap_event_pool_ts ON swap_event(pool, ts);
CREATE INDEX IF NOT EXISTS idx_swap_event_sig ON swap_event(sig);

CREATE TABLE IF NOT EXISTS lp_event(
  ts TIMESTAMPTZ NOT NULL,
  slot BIGINT NOT NULL,
  pool TEXT NOT NULL,
  x_reserve NUMERIC,
  y_reserve NUMERIC,
  fee_bps INT,
  kind TEXT -- add/remove/update
);
CREATE INDEX IF NOT EXISTS idx_lp_event_pool_ts ON lp_event(pool, ts);

CREATE TABLE IF NOT EXISTS authority_event(
  ts TIMESTAMPTZ NOT NULL,
  mint TEXT NOT NULL,
  pool TEXT,
  fee_switch BOOL,
  tax_flag BOOL,
  mint_auth BOOL,
  freeze_auth BOOL
);
CREATE INDEX IF NOT EXISTS idx_auth_event_mint_ts ON authority_event(mint, ts);

-- features (latest row per pool)
CREATE TABLE IF NOT EXISTS features_latest(
  pool TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL,
  atr15 NUMERIC,
  atr24 NUMERIC,
  sigma15 NUMERIC,
  intertrade_ms NUMERIC,
  cvd NUMERIC,
  cvd_slope_1m NUMERIC,
  cvd_slope_1h NUMERIC,
  swap_cv_15m NUMERIC,
  alternation_idx NUMERIC,
  depth_0p5 NUMERIC,
  depth_1p0 NUMERIC,
  depth_cont NUMERIC,
  lp_top10 NUMERIC,
  spread_bps NUMERIC,
  spread_persist NUMERIC,
  wc_quality_arrivals NUMERIC,
  wc_gini_dir NUMERIC,
  wc_cohort_jaccard NUMERIC,
  watchers NUMERIC,
  watchers_slope NUMERIC,
  social_min NUMERIC,
  regime_cr NUMERIC,
  regime_td NUMERIC,
  regime_cp NUMERIC
);

-- detector + trading
CREATE TABLE IF NOT EXISTS detector_signal(
  ts TIMESTAMPTZ NOT NULL,
  pool TEXT NOT NULL,
  token TEXT NOT NULL,
  score NUMERIC NOT NULL,
  reasons JSONB NOT NULL,
  state TEXT NOT NULL  -- QUIET/COIL/ARMED/ENTER
);
CREATE INDEX IF NOT EXISTS idx_detector_signal_pool_ts ON detector_signal(pool, ts);

CREATE TABLE IF NOT EXISTS position(
  id UUID PRIMARY KEY,
  opened TIMESTAMPTZ NOT NULL,
  pool TEXT NOT NULL,
  token TEXT NOT NULL,
  size_sol NUMERIC NOT NULL,
  entry_px NUMERIC NOT NULL,
  slippage_bps INT NOT NULL,
  state TEXT NOT NULL, -- OPEN/CLOSED/SCRATCH
  meta JSONB
);

CREATE TABLE IF NOT EXISTS fill(
  ts TIMESTAMPTZ NOT NULL,
  pos_id UUID NOT NULL,
  side TEXT NOT NULL,
  px NUMERIC NOT NULL,
  qty NUMERIC NOT NULL,
  tx TEXT,
  FOREIGN KEY (pos_id) REFERENCES position(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exit_event(
  ts TIMESTAMPTZ NOT NULL,
  pos_id UUID NOT NULL,
  reason TEXT NOT NULL,
  meta JSONB,
  FOREIGN KEY (pos_id) REFERENCES position(id) ON DELETE CASCADE
);

-- ops
CREATE TABLE IF NOT EXISTS error_log(
  ts TIMESTAMPTZ NOT NULL,
  where_mod TEXT NOT NULL,
  msg TEXT NOT NULL,
  ctx JSONB
);
CREATE TABLE IF NOT EXISTS latency_log(
  ts TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL,
  ms NUMERIC NOT NULL
);
