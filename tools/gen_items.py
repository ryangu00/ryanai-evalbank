#!/usr/bin/env python3
"""Generate evalbank items from corpus pages with a LOCAL model .

  gen_items.py --cat c1-kbqa --pages 80 --per-page 3 --out private/c1-kbqa/gen-raw.jsonl

Writes raw candidates; lint.py filters them. Only local base_url allowed.
"""
import argparse, concurrent.futures as cf, ipaddress, json, os, random, re, socket, sys, time, urllib.request, hashlib

ROOT = os.environ.get("EVALBANK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_HOSTS = ("127.0.0.1", "localhost", *filter(None, os.environ.get("EVALBANK_ALLOW_HOSTS", "").split(",")))


def assert_local(base_url):
    """Same guard as the runner: the host must be allow-listed AND resolve only to loopback/private addresses."""
    host = re.sub(r"^https?://", "", base_url).split("/")[0].split(":")[0]
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"[egress] refusing non-local base_url host {host!r} (private tier)")
    for info in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(info[4][0])
        if not (ip.is_loopback or ip.is_private):
            raise SystemExit(f"[egress] {host} resolves to non-private {ip}")

# The question-writing templates below ask the generator to write questions in English; they can be
# localised if desired (the original bank was bilingual, with items in Chinese and English).
PROMPTS = {
    "c1-kbqa": """You are an evaluation item writer. Below is one page of an internal knowledge-base document (mixed Chinese and English). Write {n} question-answer items that are answered "given this page as context", to test whether a model answers faithfully from the document.
Requirements:
1. {n_neg} of them must be **counterfactual items**: ask about a specific fact related to the page's topic that sounds plausible but is **completely absent from this page** (e.g. a parameter value / date / tool name that never appears); the correct answer is that the document does not mention it.
2. The rest are factual items: the answer must be a phrase that appears **verbatim** in this page (at most 12 characters or at most 6 English words); prefer numbers, commands, version numbers, proper names, cause-and-effect conclusions.
3. The question must not contain the answer text verbatim; write questions in English, keeping technical terms as-is.
4. For each item give evidence: one **verbatim** sentence from this page (not a single character changed) that contains the answer.
5. difficulty: 1 = found directly in the page; 2 = requires combining two sentences; 3 = requires understanding causality/exceptions.
Output only a JSON array, no other text:
[{{"kind":"factual|counterfactual","prompt":"…","answers":["…"],"evidence":"…","difficulty":1,"negative_entity":"(counterfactual items only: the nonexistent entity being asked about)"}}]

<document slug="{slug}" title="{title}">
{text}
</document>""",
    "c10-sre-ops": """You are an SRE evaluation item writer. Below is one page of an internal operations document (incident reviews / pitfalls / runbooks). Write {n} **SRE/ops scenario items** to test the model's operational judgement; the model is not shown this page.
Pick any of these item shapes (at least two kinds): (1) give a symptom / log snippet, ask for the root cause; (2) give the root cause, ask for the correct next action / command; (3) give a number, ask capacity / threshold arithmetic (the answer is a value from the page); (4) give a set of operations, ask for the key step in the correct order.
Requirements:
1. The question must be self-contained: put the necessary symptoms, log lines, numbers, and environment into the question text (narrate in English, keep technical terms / commands / log lines exactly as-is), but **do not put the answer into the question**.
2. The answer must be a phrase that appears **verbatim** in this page (root-cause keyword / command / parameter / numeric value, at most 12 characters or at most 6 English words); give 1-3 equivalent phrasings.
3. evidence: one verbatim sentence from this page that contains the answer.
4. difficulty: 1 = direct match; 2 = requires eliminating distractors; 3 = requires combining two places.
Output only a JSON array:
[{{"kind":"rootcause|nextstep|capacity|ordering","prompt":"…","answers":["…"],"evidence":"…","difficulty":2}}]

<document slug="{slug}" title="{title}">
{text}
</document>""",
    "c5-extract": """You are an evaluation item writer. Below is one page of an internal document. Design 1 **structured extraction item**: give a JSON schema (3-6 fields whose values must be obtainable from this page verbatim or by normalisation: dates as YYYY-MM-DD, numbers as numeric values, lists as arrays of strings), plus the reference answer JSON and, for each field, the evidence sentence from the page.
Requirements: field names in English snake_case; at least one field must be **absent** from this page with its reference answer set to null (to test that the model does not fabricate); the question must instruct, in English, "extract from the document according to the schema, fill in null when missing".
Output only JSON: {{"prompt":"…","schema":{{…}},"answer":{{…}},"evidence":{{"field":"verbatim sentence",…}},"difficulty":2}}

<document slug="{slug}" title="{title}">
{text}
</document>""",
}


def chat(base, model, content, thinking=True, effort="medium", timeout=900, max_tokens=16000):
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "temperature": 0.7, "top_p": 0.95,
            "chat_template_kwargs": {"thinking": thinking, **({"reasoning_effort": effort} if thinking else {})}}
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    return d["choices"][0]["message"].get("content") or "", d["choices"][0].get("finish_reason")


def extract_json(s):
    s = re.sub(r"<think>.*?</think>", "", s or "", flags=re.S)
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    # take the outermost JSON array/object span
    starts = [x for x in (s.find("["), s.find("{")) if x >= 0]
    if not starts:
        raise ValueError(f"no json start; head={s[:120]!r}")
    i = min(starts); j = max(s.rfind("]"), s.rfind("}"))
    return json.loads(s[i:j + 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", required=True, choices=list(PROMPTS))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--pages", type=int, default=80)
    ap.add_argument("--per-page", type=int, default=3)
    ap.add_argument("--types", default="decision,pitfall,runbook,infrastructure,guide,research,architecture,governance,audit,closeout")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260917)
    ap.add_argument("--out", required=True)
    ap.add_argument("--thinking", default="on", choices=["on", "off"]); ap.add_argument("--effort", default="medium")
    a = ap.parse_args()
    assert_local(a.base_url)

    rows = [json.loads(l) for l in open(f"{ROOT}/corpus/pages.jsonl")]
    types = set(a.types.split(","))
    pool = [r for r in rows if r["type"] in types and 1500 <= r["len"] <= 20000]
    random.Random(a.seed).shuffle(pool)
    pool = pool[: a.pages]
    print(f"[gen] cat={a.cat} pages={len(pool)} of pool types={sorted(types)}", flush=True)
    n_neg = 1 if a.per_page >= 3 else 0

    def one(r):
        p = PROMPTS[a.cat].format(n=a.per_page, n_neg=n_neg, slug=r["slug"], title=r["title"], text=r["text"])
        t0 = time.time()
        try:
            txt, fin = chat(a.base_url, a.model, p, thinking=(a.thinking == "on"), effort=a.effort)
            if fin == "length":
                raise ValueError(f"finish=length len={len(txt)}")
            items = extract_json(txt)
            if isinstance(items, dict):
                items = [items]
        except Exception as e:
            return {"slug": r["slug"], "error": str(e)[:200], "secs": round(time.time() - t0, 1)}
        out = []
        for it in items:
            it = dict(it)
            it["source"] = {"slug": r["slug"], "hash": hashlib.sha256(r["text"].encode()).hexdigest()[:16], "type": r["type"]}
            it["cat"] = a.cat
            it["meta"] = {"gen": f"{a.model}@{time.strftime('%Y-%m-%d')}", "finish": fin, "secs": round(time.time() - t0, 1)}
            out.append(it)
        return out

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    done = set()
    if os.path.exists(a.out):
        for l in open(a.out):
            try: done.add(json.loads(l)["source"]["slug"])
            except Exception: pass
    pool = [r for r in pool if r["slug"] not in done]
    print(f"[gen] resume: skipping {len(done)} done pages, {len(pool)} to go", flush=True)
    n_items = n_err = 0
    with open(a.out, "a") as f, cf.ThreadPoolExecutor(a.parallel) as ex:
        for res in ex.map(one, pool):
            if isinstance(res, dict):
                n_err += 1; print("[err]", res, flush=True); continue
            for it in res:
                f.write(json.dumps(it, ensure_ascii=False) + "\n"); n_items += 1
            f.flush()
            print(f"[ok] {res[0]['source']['slug'] if res else '?'} +{len(res)} ({res[0]['meta']['secs'] if res else 0}s) total={n_items}", flush=True)
    print(f"[done] items={n_items} errors={n_err} -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
