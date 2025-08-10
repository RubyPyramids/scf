# Changelog
Calendar versioning by date. Keep a Changelog style.

## [Unreleased]
### Added
- README (concise), Runner Ops, Handover, and Bootstrap docs split with clear scopes.
- `.env.example` augmented with detector thresholds and polling intervals.
- `.gitattributes` for sane line endings on Windows.
- `exit_worker.py` — price-based exit engine with configurable take-profit (TP) and stop-loss (SL) thresholds.
- Environment keys: `SCF_TP_MULT`, `SCF_SL_MULT`, `SCF_EXIT_POLL_SEC`, `SCF_TRADE_SIZE_SOL`, `SCF_SLIPPAGE_BPS` plus optional `SCF_TP_PARTIAL`, `SCF_SL_PARTIAL`.
- Runner spawns `exit_worker` alongside executor.
- README and env.example updated with exit engine and live risk sizing options.

### Changed
- Runner flag normalized: prefer `--mode {paper|live|none}`; `--exec` noted as alias.
- `executor_live.py` reads trade size and slippage from environment instead of hardcoded values.

### Fixed
- Naming: `SFC-Bootstrap.md` → `SCF-Bootstrap.md`.
- Date in Handover updated to 10 Aug 2025.

## [2025-08-10]
- Initial end-to-end skeleton validated on Windows 11:
  `ingest_queue → worker_resolve → parser_* → feature_worker → detector → executor(paper)`
- Docs restructured for clarity.