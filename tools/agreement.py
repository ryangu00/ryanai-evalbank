#!/usr/bin/env python3
"""Grader-vs-human agreement per category from a filled calibration jsonl (human_pass: true/false).
  agreement.py calibration/<ts>.jsonl [--min 0.95]
"""
import argparse, json, sys


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("path"); ap.add_argument("--min", type=float, default=0.95)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.path)]
    per = {}
    for r in rows:
        if r.get("human_pass") is None: continue
        g = bool(r["grader_score"] >= 0.5) if isinstance(r["grader_score"], (int, float)) else bool(r["grader_score"])
        per.setdefault(r["cat"], []).append(g == bool(r["human_pass"]))
    bad = 0
    for cat, v in sorted(per.items()):
        rate = sum(v) / len(v); flag = "" if rate >= a.min else "  <-- BELOW"
        print(f"{cat:16s} n={len(v):2d} agree={rate:.2f}{flag}"); bad += rate < a.min
    labelled = sum(1 for r in rows if r.get("human_pass") is not None)
    print(f"labelled {labelled}/{len(rows)}; categories below {a.min}: {bad}")
    sys.exit(1 if bad or labelled == 0 else 0)


if __name__ == "__main__":
    main()
