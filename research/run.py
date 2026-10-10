"""Evaluate one strategy with the research protocol.

    python -m research.run research/strategies/prev_day_fade.py \
        --design   analysis/glbx-mdp3-20241009-20251008.ohlcv-1m.csv.zst \
        --validate analysis/glbx-mdp3-20251009-20261008.ohlcv-1m.csv.zst

Stage 1 DESIGN: any number of tries, every try is recorded.
Stage 2 VALIDATION: only if design passes; a given name+params is validated once.
A strategy is a CANDIDATE only if validation passes too. (A future locked holdout year is stage 3.)
"""
import argparse
import importlib.util
import json
import os
import sys

from . import backtest, registry, stats
from .data import load_days

MIN_TRADES = 30
DSR_PASS = 0.95


def load_strategy(path):
    spec = importlib.util.spec_from_file_location("strategy_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Strategy()


def notify(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": f"Research: {text}"}, timeout=10)
    except Exception as exc:
        print(f"(telegram failed: {exc})")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--design", required=True)
    ap.add_argument("--validate", required=True)
    ap.add_argument("--trades-csv", help="optional: write design trades here for inspection")
    a = ap.parse_args(argv)

    strat = load_strategy(a.strategy)
    name, params = strat.name, getattr(strat, "params", {})

    design_days = load_days(a.design)
    t = backtest.run(strat, design_days)
    d = stats.summary(t, design_days)
    if a.trades_csv:
        t.to_csv(a.trades_csv, index=False)
    passed_design = d["trades"] >= MIN_TRADES and d["avg_usd"] > 0
    out = {"name": name, "params": params, "design_file": os.path.basename(a.design), "design": d,
           "design_pass": passed_design}

    if passed_design and registry.already_validated(name, params):
        out["validation_skipped"] = "this exact name+params was already validated once"
    elif passed_design:
        # count this design trial before deflating
        n, var = registry.design_trials()
        n += 1
        val_days = load_days(a.validate)
        tv = backtest.run(strat, val_days)
        v = stats.summary(tv, val_days)
        v["deflated_sharpe"] = round(stats.deflated_sharpe(
            v["sharpe_daily"], stats.daily_pnl(tv, val_days), n, var), 4)
        v["n_trials_counted"] = n
        out["validation_file"] = os.path.basename(a.validate)
        out["validation"] = v
        out["candidate"] = (v["trades"] >= MIN_TRADES and v["avg_usd"] > 0 and v["avg_ci90"][0] > 0
                            and v["deflated_sharpe"] >= DSR_PASS)
    registry.record(out)

    print(json.dumps(out, indent=2, default=str))
    verdict = ("CANDIDATE - passed design and validation" if out.get("candidate")
               else "rejected at validation" if "validation" in out
               else "rejected at design" if not passed_design else out.get("validation_skipped"))
    print(f"\n==> {name}: {verdict}")
    if out.get("candidate"):
        notify(f"{name} passed validation: {out['validation']['trades']} trades, "
               f"avg ${out['validation']['avg_usd']}/trade, DSR {out['validation']['deflated_sharpe']}")
    return 0 if out.get("candidate") else 1


if __name__ == "__main__":
    sys.exit(main())
