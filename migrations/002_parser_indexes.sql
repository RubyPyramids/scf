-- 002_parser_indexes.sql
-- Helper table to track which signatures each parser has processed + speed indexes.

CREATE TABLE IF NOT EXISTS parsed_sig (
  signature TEXT PRIMARY KEY,
  has_swap BOOL DEFAULT FALSE,
  has_lp   BOOL DEFAULT FALSE,
  has_auth BOOL DEFAULT FALSE,
  inserted TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_txraw_slot    ON tx_raw(slot);
CREATE INDEX IF NOT EXISTS idx_txqueue_prog  ON tx_queue(program_id);
