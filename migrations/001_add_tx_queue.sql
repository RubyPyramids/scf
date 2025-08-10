-- tx_queue: signatures to resolve
CREATE TABLE IF NOT EXISTS tx_queue (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  signature TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued', -- queued/resolved/error
  attempts INT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_queue_sig ON tx_queue(signature);
CREATE INDEX IF NOT EXISTS idx_tx_queue_status ON tx_queue(status);

-- tx_raw: resolved transaction json
CREATE TABLE IF NOT EXISTS tx_raw (
  sig TEXT PRIMARY KEY,
  ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  raw JSONB NOT NULL
);
