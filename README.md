# SCF — Stealth Coil Framework

Event-driven Solana memecoin trading system. Ingests chain data, parses AMM events, derives features, detects SCF setups, and executes paper/live (live is stubbed).

**Status:** ingestion → parsing → features → detector → **paper** executor working (skeleton). **live** executor stubbed.

---

## Quick Start (Windows PowerShell)

```powershell
# 1) Python env
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r app\requirements.txt

# 2) DB (Docker) + schema
docker compose up -d     # ensure you have a Postgres service defined OR run your own container
# then apply schema if your container doesn't auto-run init.sql:
psql "postgresql://scf:scf@localhost:5432/scf" -f sql\init.sql

# 3) Configure env
copy .env.example .env   # put your keys in .env

# 4) Diagnostic
python app\scf_runner.py --diag

# 5) Full pipeline (paper)
python app\scf_runner.py --full --mode paper
```
> Note: Some earlier notes used `--exec {paper|live|none}`. Use `--mode` here. If your runner only supports `--exec`, substitute `--exec` for `--mode` — they are synonymous.

---

## Environment

- RPCs: `RPC_WS`, `RPC_PRIMARY`, `RPC_HTTP_PRIMARY` (Helius), backups.
- DB: `DB_URL`
- Mode: `SCF_MODE=paper|live` (CLI `--mode` overrides)
- Detector: `SCF_VC_MAX`, `SCF_OFS_MAX`, `SCF_LT_MAX`, `SCF_WC_MIN`, `SCF_RQ_MAX`
- Polling: `SCF_DETECTOR_POLL_SEC`, `SCF_EXECUTOR_POLL_SEC`
- Jupiter (later for live): `JUPITER_BASE`
- Programs: `RAYDIUM_*`, `ORCA_*`

Use `.env.example` as a safe template. **Never commit `.env`.**

---

## Ops Checks

```powershell
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM tx_queue;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM tx_raw;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM swap_event;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM lp_event;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT COUNT(*) FROM detector_signal;"
docker exec -it scf_db psql -U scf -d scf -c "SELECT status, COUNT(*) FROM position GROUP BY status;"
```

Runner’s `[HEALTH]` line: 
- `tx_queue/tx_raw` rising → ingestion OK
- `swap_event/lp_event` rising & recent → parsers OK
- `features_latest` recent → features OK
- `detector_signal` intermittent rows → detector OK
- `position` changing → executor OK

---

## Layout

```
app/
  ingest_queue.py
  worker_resolve.py
  parser_swap.py
  parser_lp.py
  parser_authority.py
  feature_worker.py
  detector.py
  executor_paper.py
  executor_live.py
  scf_runner.py
sql/
  init.sql
docs/
  RUNNER-README.md
  SCF-Handover.md
  SCF-Bootstrap.md
README.md
CHANGELOG.md
.env.example
.gitignore
.gitattributes
```

---

## Roadmap

- Replace placeholder feature math with production SCF metrics.
- Exits (TP/SL/time) + PnL.
- Regime filter & risk sizing.
- Control-plane UI.
- Live routing/signing/error paths.

---

## Security

- **Do not commit** `.env` or keypairs.
- Use a low-priv Solana keypair for live.
- Add kill-switches and budgets before live.
