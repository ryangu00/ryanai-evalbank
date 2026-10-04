#!/usr/bin/env python3
"""Compare saved runs without requests, question text, paths or hash values in the report."""
import argparse, json, os, statistics


def adjudicate(runs):
    """One definition for displayed cells, baseline gates and sensitivity scores."""
    if not runs or any(x is None for x in runs): return None
    return min(runs) if max(runs) - min(runs) > 5 else statistics.median(runs)


def mean_complete(values):
    return statistics.mean(values) if values and all(x is not None for x in values) else None


def read_arm(directory):
    with open(os.path.join(directory, "results.json")) as f: data = json.load(f)
    rows = {}
    for row in data["rows"]:
        row = dict(row); errors = []; excluded = []
        for k, score in enumerate(row["runs"], 1):
            path = os.path.join(directory, "raw", f"{row['cat']}-run{k}.jsonl")
            if not row["kind"].startswith("own") or not os.path.isfile(path):
                errors.append(None); excluded.append(None); continue
            with open(path) as f: raw = [json.loads(line) for line in f if line.strip()]
            if not raw:
                errors.append(None); excluded.append(None); continue
            errors.append(sum(bool(r.get("error")) for r in raw))
            completed = [r["score"] * 100 for r in raw if not r.get("error")]
            excluded.append(mean_complete(completed) if score is not None else None)
        row.update(item_errors=errors, runs_without_errors=excluded)
        rows[row["cat"]] = row
    return {"model": data["model"], "recipe_arm": data.get("recipe_arm", "not recorded"), "rows": rows}


def category_cell(row, baseline, margin, exclude_errors=False):
    key = "runs_without_errors" if exclude_errors and row["kind"].startswith("own") else "runs"
    base_key = "runs_without_errors" if exclude_errors and baseline and baseline["kind"].startswith("own") else "runs"
    score = adjudicate(row[key])
    base = adjudicate(baseline[base_key]) if baseline else None
    gate = base - margin if base is not None else None
    return {"score": score, "gate": gate, "pass": score >= gate if score is not None and gate is not None else None}


def group_mean(rows, kind, exclude_errors=False):
    return mean_complete([adjudicate(r["runs_without_errors"] if exclude_errors and kind == "own" else r["runs"])
                          for r in rows if r["kind"].startswith(kind)])


def macro_median(rows, exclude_errors=False):
    runs = [r["runs_without_errors"] if exclude_errors and r["kind"].startswith("own") else r["runs"] for r in rows]
    if not runs or len({len(r) for r in runs}) != 1: return None
    macros = [mean_complete(list(values)) for values in zip(*runs)]
    return statistics.median(macros) if macros and all(x is not None for x in macros) else None


def fmt(value):
    return "unknown" if value is None else f"{value:.1f}"


def render(arms, incumbent=0, critical=()):
    baseline = arms[incumbent]["rows"]
    kinds = {cat: row["kind"] for arm in arms for cat, row in arm["rows"].items()}
    cats = sorted(kinds)
    md = ["# Saved-run comparison", "", "Worked method output, not a ranking. Values are requested settings; applied settings are not verified.",
          "Cells and gates use the same adjudication: median, or lowest run when spread > 5 points. Pack and own means stay separate.",
          "Re-run errored items before adjudicating. Missing raw records leave error counts and exclusion sensitivity unknown. Pack infrastructure errors are unknown.", "",
          "| arm | category | adjudicated | gate | numerical gate |", "|---|---|---|---|---|"]
    for i, arm in enumerate(arms, 1):
        for cat in cats:
            row = arm["rows"].get(cat)
            cell = category_cell(row, baseline.get(cat), 5 if cat in critical else 10) if row else {"score": None, "gate": None, "pass": None}
            verdict = "unknown" if cell["pass"] is None else "pass" if cell["pass"] else "fail"
            md.append(f"| {i}: {arm['model']} | {cat} | {fmt(cell['score'])} | {fmt(cell['gate'])} | {verdict} |")
    md += ["", "| arm | sensitivity | pack mean | own mean | median of per-run macros (sensitivity only) |", "|---|---|---|---|---|"]
    for i, arm in enumerate(arms, 1):
        rows = [arm["rows"].get(cat, {"kind": kinds[cat], "runs": [None], "runs_without_errors": [None]}) for cat in cats]
        for excluded, label in ((False, "recorded scores"), (True, "errored own items excluded")):
            md.append(f"| {i}: {arm['model']} | {label} | {fmt(group_mean(rows, 'pack', excluded))} | {fmt(group_mean(rows, 'own', excluded))} | {fmt(macro_median(rows, excluded))} |")
    md += ["", "Per-question errors are listed separately from scores. Exclusion is a sensitivity check, not a replacement verdict.", "",
           "| arm | category | per-run item errors | per-run scores excluding errors | adjudicated excluding errors |", "|---|---|---|---|---|"]
    for i, arm in enumerate(arms, 1):
        for row in arm["rows"].values():
            errors = ", ".join("unknown" if x is None else str(x) for x in row["item_errors"])
            excluded = ", ".join(fmt(x) for x in row["runs_without_errors"])
            score = adjudicate(row["runs_without_errors"])
            md.append(f"| {i}: {arm['model']} | {row['cat']} | {errors} | {excluded} | {fmt(score)} |")
    md += ["", "Recipe arms: " + "; ".join(f"{i}: {arm['recipe_arm']}" for i, arm in enumerate(arms, 1)),
           "No deployment or adoption outcome is inferred. Combined macros above diagnose aggregation sensitivity only."]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directories", nargs="+")
    ap.add_argument("--incumbent", type=int, default=1, help="1-based input position (default: 1)")
    ap.add_argument("--critical", default="c8-judgment,c7-agentic-if", help="comma-separated categories with incumbent-minus-5 gates; others use minus 10")
    a = ap.parse_args()
    if not 1 <= a.incumbent <= len(a.directories): ap.error("--incumbent is outside the input list")
    print(render([read_arm(d) for d in a.directories], a.incumbent - 1, a.critical.split(",")))


if __name__ == "__main__":
    main()
