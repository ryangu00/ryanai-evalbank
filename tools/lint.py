#!/usr/bin/env python3
"""Deterministic filters turning gen-raw candidates into bank items.

  lint.py --cat c1-kbqa --in private/c1-kbqa/gen-raw.jsonl --out private/c1-kbqa/items.jsonl [--max 30]
Prints a rejection table. Exit 1 if fewer than --min items survive.
"""
import argparse, json, os, re, sys

ROOT = os.environ.get("EVALBANK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NEG_ANSWERS = ["not mentioned", "does not mention", "no information", "not provided", "absent from the document", "not stated"]


def norm(s):
    return re.sub(r"\s+", "", (s or "")).lower()


def ev_ok(e, text_n, min_len=10):
    """evidence must be verbatim; an ellipsis-joined quote ("A ... B") is accepted iff every fragment (at least 6 chars) is verbatim."""
    if not e: return False
    frags = [f for f in re.split(r"\.\.\.|\[\.\.\.\]", e) if norm(f)]
    if len(norm(e).replace("...", "")) < min_len: return False
    return all(len(norm(f)) >= 6 and norm(f) in text_n for f in frags)


def grams(s, n=3):
    s = norm(s); return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jacc(a, b):
    A, B = grams(a), grams(b); return len(A & B) / max(1, len(A | B))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", required=True); ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--max", type=int, default=30); ap.add_argument("--min", type=int, default=30)
    ap.add_argument("--neg-ratio", type=float, default=0.25)
    a = ap.parse_args()
    pages = {json.loads(l)["slug"]: json.loads(l) for l in open(f"{ROOT}/corpus/pages.jsonl")}
    cands = [json.loads(l) for l in open(a.inp)]
    rej = {}; keep = []

    def reject(why):
        rej[why] = rej.get(why, 0) + 1

    for c in cands:
        pg = pages.get(c.get("source", {}).get("slug"))
        if not pg: reject("no_source"); continue
        text_n = norm(pg["text"])
        prompt = c.get("prompt", "")
        if len(prompt) < 8: reject("short_prompt"); continue
        if a.cat in ("c1-kbqa", "c10-sre-ops"):
            kind = c.get("kind", "factual") if a.cat == "c1-kbqa" else "factual"
            ev = c.get("evidence", "")
            if not ev_ok(ev, text_n): reject("evidence_not_verbatim"); continue
            if kind == "counterfactual":
                ent = c.get("negative_entity") or ""
                if not ent or norm(ent) in text_n: reject("neg_entity_present_or_missing"); continue
                item = {"expected": {"type": "contains", "values": NEG_ANSWERS, "all": False}, "negative_check": ent}
            else:
                ans = [x for x in c.get("answers", []) if x and (len(norm(x)) >= 2 or norm(x).isdigit())]
                if not ans: reject("no_answers"); continue
                if any(norm(x) not in text_n for x in ans): reject("answer_not_in_page"); continue
                if any(norm(x) not in norm(ev) for x in ans): reject("answer_not_in_evidence"); continue
                if any(norm(x) in norm(prompt) for x in ans): reject("answer_leaks_in_prompt"); continue
                if any(len(norm(x)) > 40 for x in ans): reject("answer_too_long"); continue
                alias = []
                for x in ans:
                    m = re.match(r"^\s*([~]?[\d][\d,\.]*\+?%?)\s*[A-Za-z]{1,8}\s*$", x)
                    if m and len(m.group(1)) >= 2: alias.append(m.group(1))
                item = {"expected": {"type": "contains", "values": ans + [a for a in alias if a not in ans], "all": False}}
            item.update({"kind": c.get("kind", kind) if a.cat == "c10-sre-ops" else kind, "evidence": ev})
        elif a.cat == "c5-extract":
            sch, ans, ev = c.get("schema"), c.get("answer"), c.get("evidence") or {}
            if not isinstance(sch, dict) or not isinstance(ans, dict): reject("bad_schema_or_answer"); continue
            bad = None
            def _in_page(v):
                if isinstance(v, bool): return True
                if isinstance(v, (int, float)): return norm(str(v)) in text_n or norm(f"{v:,}") in text_n
                if isinstance(v, str): return norm(v) in text_n or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))
                if isinstance(v, list): return all(_in_page(x) for x in v)
                if isinstance(v, dict): return all(_in_page(x) for x in v.values())
                return False
            for k, v in ans.items():
                if v is None: continue
                e = ev.get(k, "")
                if not ev_ok(e, text_n, 6): bad = f"evidence:{k}"; break
                if not _in_page(v): bad = f"value:{k}"; break
            if bad: reject("field_evidence_fail"); continue
            STOP = {"date","count","name","status","id","type","path","paths","list","total","number","value","flag","is","has","of","the","time","text","str"}
            for k in [k for k, v in ans.items() if v is None]:
                terms = [t for t in re.split(r"[_\-]", k.lower()) if len(t) >= 4 and t not in STOP]
                low = pg["text"].lower()
                if any((t[:5] in low) if len(t) >= 6 else (t in low) for t in terms):
                    ans.pop(k); sch.pop(k, None)   # page mentions the concept, so the null was forced rather than a real absence
            if len(ans) < 3: reject("too_few_fields_after_prune"); continue
            item = {"expected": {"type": "json_schema", "schema": sch, "answer": ans}, "evidence": ev}
            prompt = (prompt.strip() + "\n\nSchema (field names and types must follow this exactly):\n```json\n" + json.dumps(sch, ensure_ascii=False, indent=1)
                      + "\n```\nOutput only a single JSON object, no explanations; fill in null for fields absent from the document; write dates as YYYY-MM-DD.")
        else:
            reject("unknown_cat"); continue
        if any(jacc(prompt, k["prompt"]) >= 0.6 for k in keep): reject("duplicate"); continue
        keep.append({"cat": a.cat, "tier": "private", "difficulty": int(c.get("difficulty", 2) or 2), "source": c["source"],
                     "context": pg["text"], "prompt": prompt, **item, "judge": None, "meta": c.get("meta", {})})
    # balance counterfactual share
    if a.cat == "c1-kbqa":
        neg = [k for k in keep if k["kind"] == "counterfactual"]; pos = [k for k in keep if k["kind"] != "counterfactual"]
        n_neg = min(len(neg), int(a.max * a.neg_ratio)); keep = pos[: a.max - n_neg] + neg[:n_neg]
    keep = keep[: a.max]
    for i, k in enumerate(keep): k["id"] = f"{a.cat}-{i:03d}"
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        for k in keep: f.write(json.dumps(k, ensure_ascii=False) + "\n")
    print(f"[lint] {a.cat}: candidates={len(cands)} kept={len(keep)} rejected={rej}")
    if len(keep) < a.min: print(f"[lint] FAIL need {a.min}", file=sys.stderr); sys.exit(1)


if __name__ == "__main__":
    main()
