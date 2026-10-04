#!/usr/bin/env python3
"""Build the human calibration set (grader-vs-human agreement): stratified random sample (fixed
seed, >=4 per category) of items, paired with the model answer from a run's raw output and the
grader verdict. A reviewer fills `human_pass`.
  make_calibration.py --run runs/<dir> [--per-cat 4] [--seed 42]
Writes calibration/<ts>.jsonl (machine) + calibration/<ts>.md (form). agreement.py computes grader-vs-human.
"""
import argparse, glob, json, os, random, time
ROOT = os.environ.get("EVALBANK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--run", required=True); ap.add_argument("--per-cat", type=int, default=4); ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args(); rng = random.Random(a.seed)
    recs = {}
    for f in glob.glob(f"{a.run}/raw/*-run1.jsonl"):
        for l in open(f):
            r = json.loads(l); recs[r["id"]] = r
    items = {}
    for f in glob.glob(f"{ROOT}/bank/*/*/items.jsonl"):
        for l in open(f):
            it = json.loads(l); items[it["id"]] = it
    by_cat = {}
    for iid, r in recs.items():
        if iid in items: by_cat.setdefault(r["cat"], []).append(iid)
    sample = []
    for cat, ids in sorted(by_cat.items()):
        ids = sorted(ids); rng.shuffle(ids); sample += ids[: a.per_cat]
    ts = time.strftime("%Y%m%d-%H%M"); os.makedirs(f"{ROOT}/calibration", exist_ok=True)
    out_j = f"{ROOT}/calibration/{ts}.jsonl"; out_m = f"{ROOT}/calibration/{ts}.md"
    md = [f"# evalbank calibration set {ts} (seed={a.seed}, {a.per_cat} items per category, source run {os.path.basename(a.run)})", "",
          "For each item, review the question / reference answer / model answer / grader verdict, then fill in **Human verdict** with pass or fail; items where the grader and the human disagree are the ones to fix.", ""]
    with open(out_j, "w") as fj:
        for i, iid in enumerate(sample, 1):
            it, r = items[iid], recs[iid]
            exp = it["expected"]; exp_s = json.dumps({k: v for k, v in exp.items() if k not in ("schema",)}, ensure_ascii=False)[:400]
            ans = (r.get("answer") or json.dumps(r.get("detail"), ensure_ascii=False))[:800]
            fj.write(json.dumps({"n": i, "id": iid, "cat": r["cat"], "grader_score": r["score"], "human_pass": None, "note": ""}, ensure_ascii=False) + "\n")
            md += [f"## {i}. `{iid}` · Grader verdict {r['score']}", f"**Question**:{it['prompt'][:500]}", f"**Reference answer**:`{exp_s}`", f"**Model answer**:{ans}", "**Human verdict**:", ""]
    open(out_m, "w").write("\n".join(md))
    print("calibration", len(sample), "items ->", out_j, out_m)


if __name__ == "__main__":
    main()
