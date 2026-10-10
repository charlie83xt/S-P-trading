"""Append-only record of EVERY strategy evaluation. The number of trials feeds the Deflated Sharpe
Ratio, so deleting entries to make results look better defeats the whole point."""
import datetime
import json
import os

REGISTRY = os.path.join(os.path.dirname(__file__), "registry.jsonl")


def record(entry):
    entry = dict(entry, recorded_at=datetime.datetime.now().isoformat(timespec="seconds"))
    with open(REGISTRY, "a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


def load():
    if not os.path.exists(REGISTRY):
        return []
    with open(REGISTRY) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def design_trials():
    """(count, variance of per-day Sharpe) over all design-stage trials so far."""
    srs = [e["design"]["sharpe_daily"] for e in load() if e.get("design")]
    if len(srs) < 2:
        return len(srs), 0.0
    m = sum(srs) / len(srs)
    return len(srs), sum((s - m) ** 2 for s in srs) / (len(srs) - 1)


def already_validated(name, params):
    return any(e.get("name") == name and e.get("params") == params and e.get("validation")
               for e in load())
