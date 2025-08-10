# SCF Bootstrap (Solana, Raydium+Orca) — Minimal Setup

## Files
- `docker-compose.yml` — spins up Postgres 15
- `init.sql` — schema auto-applied at first start (or run manually)
- `thresholds.json` — seed thresholds
- `.env.example` — RPCs and DB URL
- `feature_formulas.md` — exact math for VC/OFS/LT/WC/RQ
- `detector_pseudocode.txt` — state machine spec

## Quick Start
1) Install Docker Desktop (or Docker Engine + Compose).  
2) Put these files in a folder, open a terminal in that folder.  
3) `docker compose up -d` — brings up Postgres and runs `init.sql` automatically (if configured).  
4) Verify DB is live: connect to `postgresql://scf:scf@localhost:5432/scf`.  
5) Next: run the app skeleton (ingest + feature engine) — it will use `.env` and `thresholds.json`.

## Notes
- Helius RPC/WebSocket is primary; Solana public is backup.  
- Execution target: Jupiter public endpoints with slippage cap, TIF ~30s.  
- Pool age gate: ~30 minutes by default.
