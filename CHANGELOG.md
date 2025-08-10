## [0.3.1] - 2025-08-10
### Added
- parser_swap: derive base/quote amounts and price from token balance deltas; no zero inserts.
- feature_worker: ATR% (15m/24h) and simple CVD slope; upserts features_latest.

### Changed
- parser_lp: skips writing unless reserves can be inferred (prevents noise).
