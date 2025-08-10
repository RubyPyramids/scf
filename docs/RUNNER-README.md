# SCF Runner — Usage & Ops

`scf_runner.py` orchestrates the workers and emits a `[HEALTH]` line.

## Commands

```powershell
# Diagnostic
python app\scf_runner.py --diag

# Full pipeline (paper)
python app\scf_runner.py --full --mode paper

# Full pipeline (live stub)
python app\scf_runner.py --full --mode live
```
> Older docs may refer to `--exec {paper|live|none}`. Use `--mode` primarily; if your runner expects `--exec`, substitute it.

## Order under `--full`

1. `ingest_queue.py`  
2. `worker_resolve.py`  
3. `parser_swap.py`  
4. `parser_lp.py`  
5. `parser_authority.py`  
6. `feature_worker.py`  
7. `detector.py`  
8. Executor: paper or live

## Health heuristics

- `tx_queue/tx_raw` increasing → ingestion alive  
- `swap_event/lp_event` increasing and recent → parsers current  
- `features_latest` recent rows → features healthy  
- `detector_signal` intermittent rows → detector crossing  
- `position` changes → executor acting

## Troubleshooting

- **WS invalid URI** → fix `RPC_WS` (`wss://…`).  
- **DB down** → ensure container up; verify `DB_URL`.  
- **No fresh events** → compare `MAX(slot)` in `tx_raw` vs `swap_event/lp_event`.  
- **No signals** → thresholds too strict; tune `SCF_*`.  
- **No positions** → check mode and recent `detector_signal` rows.

## Clean stop

Press `Ctrl+C`. Runner asks children to terminate, then kills stragglers.

## Production notes

- Schedule for 24/7 (Task Scheduler/Service).
- Keep secrets out of VCS.
- Before live: routing/quotes/signing, kill-switches, budget caps, exits & PnL.
