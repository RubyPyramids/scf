
-- 001b_fix_tx_queue.sql — normalize tx_queue / tx_raw schema

-- tx_queue: ensure required columns exist
ALTER TABLE IF EXISTS tx_queue
  ADD COLUMN IF NOT EXISTS signature TEXT,
  ADD COLUMN IF NOT EXISTS program_id TEXT,
  ADD COLUMN IF NOT EXISTS slot BIGINT,
  ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'queued',
  ADD COLUMN IF NOT EXISTS retries INT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS enqueued TIMESTAMPTZ DEFAULT now(),
  ADD COLUMN IF NOT EXISTS last_error TEXT;

-- primary key / unique constraint on signature
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tx_queue'::regclass
      AND contype IN ('p','u')
      AND conname = 'tx_queue_signature_pk'
  ) THEN
    -- drop any stray index using signature first
    DROP INDEX IF EXISTS idx_tx_queue_signature;
    -- add primary key
    ALTER TABLE tx_queue ADD CONSTRAINT tx_queue_signature_pk PRIMARY KEY (signature);
  END IF;
END $$;

-- tx_raw: create if it doesn't exist
CREATE TABLE IF NOT EXISTS tx_raw (
  signature TEXT PRIMARY KEY,
  slot BIGINT,
  j JSONB NOT NULL,
  inserted TIMESTAMPTZ DEFAULT now()
);

-- If exists, ensure columns are present
ALTER TABLE IF EXISTS tx_raw
  ADD COLUMN IF NOT EXISTS signature TEXT,
  ADD COLUMN IF NOT EXISTS slot BIGINT,
  ADD COLUMN IF NOT EXISTS j JSONB,
  ADD COLUMN IF NOT EXISTS inserted TIMESTAMPTZ DEFAULT now();

-- Ensure tx_raw has PK on signature
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tx_raw'::regclass
      AND contype IN ('p','u')
      AND conname = 'tx_raw_signature_pk'
  ) THEN
    ALTER TABLE tx_raw ADD CONSTRAINT tx_raw_signature_pk PRIMARY KEY (signature);
  END IF;
END $$;
