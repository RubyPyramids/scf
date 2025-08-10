## Exit engine + parser/feature updates (drop-in)

- New `app/parser_swap.py`: real amounts/price from token balance deltas; skips uncertain txs (no zeros).
- `app/parser_lp.py`: no-op unless confident data (prevents junk rows).
- `app/feature_worker.py`: minimal ATR% + CVD slope (VC/OFS scaffolding). Writes `features_latest`.
