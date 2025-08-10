# Changelog
Calendar versioning by date. Keep a Changelog style.

## [Unreleased]
### Added
- README (concise), Runner Ops, Handover, and Bootstrap docs split with clear scopes.
- `.env.example` augmented with detector thresholds and polling intervals.
- `.gitattributes` for sane line endings on Windows.
### Changed
- Runner flag normalized: prefer `--mode {paper|live|none}`; `--exec` noted as alias.
### Fixed
- Naming: `SFC-Bootstrap.md` → `SCF-Bootstrap.md`.
- Date in Handover updated to 10 Aug 2025.

## [2025-08-10]
- Initial end-to-end skeleton validated on Windows 11:
  `ingest_queue → worker_resolve → parser_* → feature_worker → detector → executor(paper)`
- Docs restructured for clarity.
