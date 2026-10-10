# Research harness

Tests trading ideas on two years of MES 1-minute history **without fooling ourselves**.
Nothing here places orders or touches the live bot.

## Setup (once)
```
pip install -r research/requirements.txt
```
Data: the two Databento files on the `data/es-1m` branch, in `analysis/`. The first load of each
takes about a minute and writes a cache file next to it (`*.days.v1.pkl`; add `analysis/*.pkl`
to `.gitignore`).

## Run a strategy (always from the repo root)
```
python -m research.run research/strategies/<file>.py \
  --design   analysis/glbx-mdp3-20241009-20251008.ohlcv-1m.csv.zst \
  --validate analysis/glbx-mdp3-20251009-20261008.ohlcv-1m.csv.zst
```
Exit code 0 = candidate, 1 = rejected. Every run is appended to `research/registry.jsonl`
(commit it: it is the honest record of everything tried).

## The protocol (why results can be trusted)
| Stage | Data | Rule |
|---|---|---|
| 1 Design | Oct 2024 – Oct 2025 | Try as often as you like. Every try is recorded. Pass = at least 30 trades and average P&L above $0 after costs. |
| 2 Validation | Oct 2025 – Oct 2026 | Only if design passes, and **once** per name + params. Pass = at least 30 trades, average above $0, 90% bootstrap range above $0, **Deflated Sharpe ≥ 0.95**. |
| 3 Lockbox (later) | A year nobody has looked at (e.g. 2023–24) | Final check before any real money. |

- **Costs**: $1.24 commission + 1 tick slippage each side = **$3.74 per trade**.
- **No look-ahead**: `on_bar(i, bars)` only receives bars up to the bar that just closed.
- **Fills**: entry at that bar's close; inside a bar the stop is assumed hit before the target.
- **Deflated Sharpe** (Bailey & López de Prado, 2014): the more strategies are tried, the higher the
  bar. That is why the registry must never be edited or deleted.

## Files
| File | Purpose |
|---|---|
| `data.py` | Loads Databento files; front contract per day; previous-day levels from the same contract |
| `backtest.py` | Event-driven backtester with costs, stops, targets, breakeven, time exit |
| `stats.py` | Summary, bootstrap range, Deflated Sharpe |
| `registry.py` | Append-only trial log |
| `run.py` | The protocol above; optional Telegram alert for candidates (uses your `.env` variables) |
| `ml_baseline.py` | Gradient-boosting baseline: `python -m research.ml_baseline --design ... --validate ...` |
| `strategies/template.py` | Start here for a new idea |
| `strategies/prev_day_fade.py` | Previous-day level fade (rejected) |
| `strategies/mesrunner.py` | The live MESRunner with live-like exits (rejected) |

## Results so far
| Strategy | Stage reached | Trades | Avg / trade | Verdict |
|---|---|---|---|---|
| `mesrunner_live_like` | design | 161 | −$3.97 | rejected |
| `prev_day_fade` | design | 130 | −$3.40 | rejected |
| ML baseline (30-min direction) | validation | 2,896 | −$4.29 | AUC 0.87 in-sample → 0.50 unseen |

## Plugging in agents (next phase)
An agent (or you) writes one file in `strategies/` from the template, runs `research.run`, and reads
the JSON. The harness is the only judge. Agents bring ideas and coding speed, not statistical
power: every attempt they make counts as a trial and raises the bar for the next one.
