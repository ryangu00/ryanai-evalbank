#!/usr/bin/env python3
"""evalbank runner — one command, several categories, N runs, median+spread, raw bodies kept.

  run.py --base-url <endpoint-base-url> --model <served> --label run1 [--tier private]
         [--cats c1-kbqa,c2-longctx,...] [--runs 2] [--thinking on|off] [--parallel 4] [--judge <model>]
         [--judge-base-url <judge-base-url>]

Private tier: base_url host must be on the allowlist AND resolve to loopback/RFC1918.
Outputs runs/<ts>-<label>/{results.json,report.md,raw/<cat>-run<k>.jsonl}. The tool-use categories shell
out to tool-eval-bench (--scenario-pack --pack-only); their 0/1/2 scores are reported in a separate column,
never merged with the own-bank 0/1 scores.
"""
import argparse, concurrent.futures as cf, hashlib, ipaddress, json, math, os, platform, re, socket, statistics, subprocess, sys, tempfile, time, urllib.request

ROOT = os.environ.get("EVALBANK_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ALLOW_HOSTS = set(filter(None, os.environ.get("EVALBANK_ALLOW_HOSTS", "").split(",")))  # private tier: explicitly configure allowed hosts
OWN_CATS = ["c1-kbqa", "c2-longctx", "c4-code", "c5-extract", "c6-vision", "c7-zhif", "c9-long-coding", "c10-sre-ops"]
PACK_CATS = ["c3-tool", "c7-agentic-if", "c8-judgment"]
ALL_CATS = ["c1-kbqa", "c2-longctx", "c3-tool", "c4-code", "c5-extract", "c6-vision", "c7-zhif", "c7-agentic-if", "c8-judgment", "c9-long-coding", "c10-sre-ops"]


# ---------- egress guard ----------
def assert_local(base_url):
    from urllib.parse import urlparse
    u = urlparse(base_url)
    if u.scheme not in ("http", "https") or "@" in (u.netloc or "") or u.username or u.password:
        raise SystemExit(f"[egress] refusing url with userinfo/odd scheme: {base_url!r}")
    host = (u.hostname or "").rstrip(".").lower()
    if host not in ALLOW_HOSTS:
        raise SystemExit(f"[egress] host {host!r} not on private allowlist {sorted(ALLOW_HOSTS)}")
    for fam, _, _, _, sa in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(sa[0])
        if not (ip.is_loopback or ip.is_private):
            raise SystemExit(f"[egress] {host} resolves to non-private {ip}")
    return host


# ---------- bank hash ----------
def bank_hash(tier, cats):
    h = hashlib.sha256()
    for cat in cats:
        d = f"{ROOT}/bank/{tier}/{cat}"
        if not os.path.isdir(d): continue
        for dp, dn, fn in os.walk(d):
            dn[:] = sorted(x for x in dn if x != "__pycache__")
            for name in sorted(fn):
                if name.startswith("gen-raw") or name.endswith(".pyc"): continue
                p = os.path.join(dp, name); h.update(os.path.relpath(p, f"{ROOT}/bank/{tier}").encode()); h.update(open(p, "rb").read())
    return h.hexdigest()[:16]


def load_items(tier, cat):
    p = f"{ROOT}/bank/{tier}/{cat}/items.jsonl"
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


# ---------- model call ----------
MAX_TOKENS = int(os.environ.get("EVALBANK_MAX_TOKENS", "8000"))  # the thinking-mode comparison in docs/worked-example.md used 16384
CONFIG = {}


def load_recipe(model):
    directory = os.path.realpath(f"{ROOT}/recipes")
    path = os.path.realpath(os.path.join(directory, model + ".json"))
    if not path.startswith(directory + os.sep): raise SystemExit("recipe path escapes recipes/")
    if not os.path.isfile(path): raise SystemExit(f"missing recipe: recipes/{model}.json; use --recipe-arm harness-uniform --reason '<why>' for a control")
    try:
        with open(path) as f: recipe = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read recipe: {e}")
    if not isinstance(recipe, dict): raise SystemExit("recipe must be an object")
    sampling = recipe.get("sampling")
    if not isinstance(sampling, dict) or any(k not in sampling for k in ("temperature", "top_p")):
        raise SystemExit("recipe sampling requires temperature and top_p")
    if not isinstance(recipe.get("limitations"), list): raise SystemExit("recipe requires an explicit limitations list")
    return recipe


def resolve_config(a):
    """Resolve before creating run artifacts; source labels are declarations, not verification."""
    uniform = a.recipe_arm == "harness-uniform"
    reason = (a.reason or "").strip()
    if uniform and not reason: raise SystemExit("harness-uniform requires a non-empty --reason")
    recipe = None if uniform else load_recipe(a.model)
    sampling = dict(recipe["sampling"]) if recipe is not None else {"temperature": 0.5 if a.thinking == "on" else 0.0, "top_p": 0.95}
    chat_kwargs = recipe.get("chat_kwargs", {}) if recipe is not None else {"thinking": a.thinking == "on", **({"reasoning_effort": "high"} if a.thinking == "on" else {})}
    if not isinstance(chat_kwargs, dict): raise SystemExit("recipe chat_kwargs must be an object")
    chat_kwargs = dict(chat_kwargs)
    max_tokens = recipe.get("max_tokens", MAX_TOKENS) if recipe is not None else MAX_TOKENS
    system = recipe.get("system") if recipe is not None else None
    preserve = recipe.get("preserve_reasoning", False) if recipe is not None else False
    if not isinstance(preserve, bool): raise SystemExit("preserve_reasoning must be boolean")
    non_official = []
    if recipe is not None:
        sources = recipe.get("field_sources", {})
        if not isinstance(sources, dict): raise SystemExit("field_sources must be an object")
        fields = [*(f"sampling.{k}" for k in sampling), *(f"chat_kwargs.{k}" for k in chat_kwargs), "max_tokens", "preserve_reasoning"]
        non_official = sorted(k for k in fields if sources.get(k) != "official" or (k in ("max_tokens", "preserve_reasoning") and k not in recipe))
    overrides = {}
    for field, target in (("sampling", sampling), ("chat_kwargs", chat_kwargs)):
        value = getattr(a, field)
        if value is None: continue
        try: value = json.loads(value)
        except ValueError: raise SystemExit(f"--{field.replace('_', '-')} requires a JSON object")
        if not isinstance(value, dict): raise SystemExit(f"--{field.replace('_', '-')} requires a JSON object")
        overrides[field] = value; target.update(value)
    if a.max_tokens is not None: max_tokens = overrides["max_tokens"] = a.max_tokens
    if a.system is not None: system = overrides["system"] = a.system
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise SystemExit("max_tokens must be a positive integer")
    if system is not None and not isinstance(system, str): raise SystemExit("system must be text or null")
    for key in ("temperature", "top_p"):
        value = sampling.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise SystemExit(f"sampling.{key} must be a finite number")
    if set(sampling) & {"model", "messages", "tools", "tool_choice", "max_tokens", "chat_template_kwargs", "system"}:
        raise SystemExit("sampling contains a reserved request field; use the dedicated recipe field")
    arm = "harness-uniform" if uniform else "vendor-informed" if non_official else "vendor"
    if overrides and not uniform: arm += "-overridden"
    config = {"sampling": sampling, "chat_template_kwargs": chat_kwargs, "max_tokens": max_tokens, "system": system,
              "preserve_reasoning": preserve, "recipe_arm": arm, "recipe_reason": reason, "recipe": recipe,
              "recipe_non_official": non_official, "recipe_overrides": overrides,
              "limitations": recipe["limitations"] if recipe is not None else [], "timeout_scale": max(1, max_tokens / 8000),
              "max_tokens_explicit": (recipe is not None and "max_tokens" in recipe) or a.max_tokens is not None}
    for name in ("EVALBANK_SAMPLING", "EVALBANK_CHAT_KWARGS", "EVALBANK_SYSTEM", "EVALBANK_PRESERVE_REASONING"):
        os.environ.pop(name, None)
    if recipe is not None or "sampling" in overrides: os.environ["EVALBANK_SAMPLING"] = json.dumps(sampling)
    if recipe is not None or "chat_kwargs" in overrides: os.environ["EVALBANK_CHAT_KWARGS"] = json.dumps(chat_kwargs)
    if system is not None: os.environ["EVALBANK_SYSTEM"] = system
    if preserve: os.environ["EVALBANK_PRESERVE_REASONING"] = "1"
    os.environ["EVALBANK_MAX_TOKENS"] = str(max_tokens)
    return config


def ctk(thinking):
    return CONFIG.get("chat_template_kwargs", {"thinking": thinking, **({"reasoning_effort": "high"} if thinking else {})})


def grader_env():
    versions = {"python": platform.python_version()}
    for key, cmd in (("tool_eval_bench", ["tool-eval-bench", "--version"]), ("pytest", [sys.executable, "-m", "pytest", "--version"])):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
            versions[key] = (p.stdout or p.stderr).strip()
        except Exception as e:
            versions[key] = f"?({type(e).__name__})"
    return versions


def chat(base, model, messages, thinking, max_tokens=None, temperature=None, timeout=600):
    sampling = dict(CONFIG.get("sampling", {"temperature": 0.5 if thinking else 0.0, "top_p": 0.95}))
    if temperature is not None: sampling["temperature"] = temperature
    if CONFIG.get("system") is not None: messages = [{"role": "system", "content": CONFIG["system"]}, *messages]
    body = {**sampling, "model": model, "messages": messages, "max_tokens": max_tokens or CONFIG.get("max_tokens", MAX_TOKENS),
            "chat_template_kwargs": ctk(thinking)}
    headers = {"Content-Type": "application/json"}
    if os.environ.get("EVALBANK_API_KEY"): headers["Authorization"] = f"Bearer {os.environ['EVALBANK_API_KEY']}"
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(body).encode(), headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout * CONFIG.get("timeout_scale", 1)) as r:
        raw = r.read().decode()
    d = json.loads(raw)
    return d["choices"][0]["message"].get("content") or "", raw, round(time.time() - t0, 2), d["choices"][0].get("finish_reason")


def usage_of(raw):
    try:
        u = json.loads(raw).get("usage") or {}
        return {"out": u.get("completion_tokens", 0), "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    except Exception:
        return {"out": 0, "reasoning": 0}


# ---------- graders (deterministic) ----------
def norm(s):
    return re.sub(r"\s+", "", (s or "")).lower()


def strip_think(s):
    return re.sub(r"<think>.*?</think>", "", s or "", flags=re.S).strip()


def _has(v, out):
    """substring match after whitespace/case normalisation; purely numeric values need digit boundaries ("5" must not match "15")."""
    nv = norm(v)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", nv):
        return re.search(r"(?<![\d.+-])" + re.escape(nv) + r"(?![\d.])", (out or "").replace(",", "").replace(" ", "")) is not None
    return nv in norm(out)


def grade_contains(exp, out):
    cap = exp.get("max_chars", 600)
    if len(out or "") > cap:   # echoing the document / listing every candidate is not an answer
        return False, {"err": f"answer too long ({len(out)} > {cap})"}
    hits = [_has(v, out) for v in exp["values"]]
    return (all(hits) if exp.get("all", True) else any(hits)), {"hits": hits}


def grade_exact(exp, out):
    return norm(out) == norm(exp["value"]), {}


def grade_regex(exp, out):
    return bool(re.search(exp["pattern"], out.strip(), re.S)), {}


def _json_from(out):
    s = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M).strip()
    i = min([x for x in (s.find("{"), s.find("[")) if x >= 0] or [0])
    return json.loads(s[i:])


def grade_json_schema(exp, out):
    try:
        got = _json_from(out)
    except Exception as e:
        return False, {"err": f"json:{e}"[:80]}
    if not isinstance(got, dict): return 0.0, {"err": "not an object"}
    ans = exp["answer"]; per = {}
    for k, v in ans.items():
        if k not in got: per[k] = False; continue
        g = got[k]
        per[k] = (g is None and v is None) or (g is not None and v is not None and norm(json.dumps(g, ensure_ascii=False) if isinstance(g, (list, dict)) else str(g)) == norm(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)))
    frac = sum(per.values()) / max(1, len(per))
    return frac, {"fields": per}


CJK = re.compile(r"[\u4e00-\u9fff]")


def grade_checks(exp, out):
    o = out.strip(); res = {}
    for i, c in enumerate(exp["checks"]):
        k = c["kind"]
        if k == "max_chars": ok = len(o) <= c["n"]
        elif k == "min_chars": ok = len(o) >= c["n"]
        elif k == "max_words": ok = len(o.split()) <= c["n"]
        elif k == "zh_ratio":
            letters = len(re.findall(r"[A-Za-z]", o)); cjk = len(CJK.findall(o)); r = cjk / max(1, cjk + letters)
            ok = (r >= c.get("min", 0)) and (r <= c.get("max", 1))
        elif k == "no_words": ok = not any(w in o for w in c["words"])
        elif k == "must_words": ok = all(w in o for w in c["words"])
        elif k == "regex": ok = bool(re.search(c["pattern"], o, re.S))
        elif k == "json_valid":
            try: _json_from(o); ok = True
            except Exception: ok = False
        elif k == "json_path_len":
            try: ok = len(_json_from(o)) == c["n"]
            except Exception: ok = False
        elif k == "line_count": ok = len([l for l in o.splitlines() if l.strip()]) == c["n"]
        elif k == "starts_with": ok = o.startswith(c["s"])
        elif k == "ends_with": ok = o.rstrip("\u3002.!\uff01 ").endswith(c["s"])
        elif k == "exact_lines": ok = [l.strip() for l in o.splitlines() if l.strip()] == c["lines"]
        else: ok = False
        res[f"{k}#{i}"] = ok
    return all(res.values()), res


TIER = "private"


def pytest_passed(stdout):
    """Count passed from pytest's FINAL summary line only (never from arbitrary stdout); skipped/xfail do not count."""
    lines = [l for l in stdout.splitlines() if re.search(r"\b\d+ (passed|failed|error|errors|skipped)\b.* in [\d.]+s", l.strip())]
    if not lines: return 0
    m = re.search(r"(\d+) passed", lines[-1]); return int(m.group(1)) if m else 0


def grade_tests(exp, out):
    """Code category: extract the fenced file, run HIDDEN tests in a temp dir. pytest → passed/expected_total; sh → 0/1."""
    import shutil
    d = f"{ROOT}/bank/{TIER}/c4-code/{exp['task_dir']}"; lang = exp["lang"]; ext = "py" if lang == "py" else "sh"
    m = re.findall(r"```(?:python|py|bash|sh)?\s*\n(.*?)```", out, re.S)
    if not m: return 0.0, {"err": "no fenced block"}
    code = m[-1]
    tmp = tempfile.mkdtemp(prefix="evalbank-c4-")
    try:
        open(f"{tmp}/seed.{ext}", "w").write(code)
        if lang == "py":
            shutil.copy(f"{d}/hidden_test.py", f"{tmp}/test_hidden.py")
            expected_total = len(re.findall(r"^\s*def test_", open(f"{d}/hidden_test.py").read(), re.M))
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider", "--rootdir", tmp, f"{tmp}/test_hidden.py"], capture_output=True, text=True, timeout=120, cwd=tmp)
            p = pytest_passed(r.stdout)
            return min(1.0, p / max(1, expected_total)), {"passed": p, "total": expected_total, "rc": r.returncode}
        shutil.copy(f"{d}/hidden_test.sh", f"{tmp}/hidden_test.sh")
        r = subprocess.run(["bash", "hidden_test.sh"], cwd=tmp, capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0 and "PASS" in r.stdout
        return float(ok), {"out": (r.stdout + r.stderr)[-200:]}
    except Exception as e:
        return 0.0, {"err": str(e)[:120]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def grade_numeric(exp, out):
    m = re.findall(r"-?\d+(?:\.\d+)?", out)
    if not m: return False, {"err": "no number"}
    v = float(m[-1]); return abs(v - exp["value"]) <= exp.get("tol", 0), {"got": v}


def grade_set(exp, out):
    """exact set of named entities: every expected name present AND no other name from the universe present."""
    o = (out or "").lower(); present = {n for n in exp["universe"] if n.lower() in o}
    return present == set(exp["values"]), {"present": sorted(present)}


GRADERS = {"set": grade_set, "numeric": grade_numeric, "contains": grade_contains, "exact": grade_exact, "regex": grade_regex, "json_schema": grade_json_schema, "checks": grade_checks, "tests": grade_tests}


# ---------- judge (anti-family, pass/fail + critique) ----------
def judge(item, out, judge_model, gw=None):
    gw = gw or os.environ.get("EVALBANK_JUDGE_BASE_URL")
    if not gw: raise ValueError("judge endpoint is required")
    key = os.environ.get("EVALBANK_JUDGE_API_KEY") or ""
    rubric = item["judge"]["rubric"]
    prompt = ("You are grading a model answer. Rubric:\n" + rubric + "\n\nQuestion:\n" + item["prompt"][:4000] +
              "\n\nModel answer:\n" + out[:6000] + "\n\nReply ONLY with JSON {\"pass\": true|false, \"critique\": \"<one sentence>\"}.")
    body = {"model": judge_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 300,
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(f"{gw}/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    j = _json_from(d["choices"][0]["message"]["content"])
    if not isinstance(j.get("pass"), bool): raise ValueError("judge pass not boolean")
    return j["pass"], j.get("critique", "")


# ---------- one item ----------
def run_item(item, base, model, thinking, judge_model, judge_base=None):
    if item["expected"]["type"] == "agent":
        sys.path.insert(0, f"{ROOT}/tools"); import agent_loop
        r = agent_loop.run_task(f"{ROOT}/bank/{TIER}/c9-long-coding/{item['expected']['task_dir']}", base, model, thinking, timeout=item.get("timeout", 900) * CONFIG.get("timeout_scale", 1))
        raws = r.pop("raw_http_bodies"); detail = {k: r[k] for k in ("hidden_passed", "hidden_total", "turns", "tool_calls", "finished", "tail")}
        return {"id": item["id"], "cat": item["cat"], "score": r["score"], "secs": r["secs"], "usage": r["usage"], "error": r["error"], "detail": detail, "raw_http_body": json.dumps(raws)}
    msgs = []
    if item.get("image"):
        msgs.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": item["image"]}}, {"type": "text", "text": item["prompt"]}]})
    elif item.get("context"):
        msgs.append({"role": "user", "content": f"Answer using only the reference document below; if the document does not mention it, reply \"not mentioned in the document\".\n\n<document>\n{item['context']}\n</document>\n\nQuestion: {item['prompt']}"})
    else:
        msgs.append({"role": "user", "content": item["prompt"]})
    rec = {"id": item["id"], "cat": item["cat"]}
    try:
        out, raw, secs, fin = chat(base, model, msgs, thinking, timeout=item.get("timeout", 600))
    except Exception as e:
        rec.update({"score": 0.0, "error": str(e)[:200]}); return rec
    ans = strip_think(out)
    exp = item["expected"]; t = exp["type"]
    if t in GRADERS:
        ok, detail = GRADERS[t](exp, ans); score = float(ok) if isinstance(ok, bool) else float(ok)
    elif t == "judge" and judge_model:
        try:
            ok, crit = judge(item, ans, judge_model, gw=judge_base); score, detail = float(ok), {"critique": crit}
        except Exception as e:
            score, detail = 0.0, {"judge_err": str(e)[:120]}
    else:
        score, detail = 0.0, {"err": f"no grader for {t}"}
    if fin == "length" and score > 0:
        detail = {"truncated_credit_revoked": score, "grader_detail": detail}; score = 0.0
    rec.update({"score": score, "secs": secs, "finish": fin, "usage": usage_of(raw), "detail": detail, "answer": ans[:2000], "raw_http_body": raw})
    return rec


def run_cat(cat, items, base, model, thinking, judge_model, parallel, rawdir, k, judge_base=None):
    recs = []
    with cf.ThreadPoolExecutor(parallel) as ex:
        for r in ex.map(lambda it: run_item(it, base, model, thinking, judge_model, judge_base), items):
            recs.append(r)
    with open(f"{rawdir}/{cat}-run{k}.jsonl", "w") as f:
        for r in recs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tok = sum(r.get("usage", {}).get("out", 0) for r in recs); secs = sum(r.get("secs", 0) or 0 for r in recs)
    return 100.0 * sum(r["score"] for r in recs) / max(1, len(recs)), len(recs), (f"tok={tok} wall={round(secs)}s" if not any(r.get("error") for r in recs) else f"errors={sum(1 for r in recs if r.get('error'))} tok={tok}")


def run_pack(cat, base, model, thinking, rawdir, k, tier, parallel=4):
    packdir = f"{ROOT}/bank/{tier}/{cat}"
    out = f"{rawdir}/{cat}-run{k}.json"
    kw = {**CONFIG.get("sampling", {"temperature": 0.5 if thinking else 0.0, "top_p": 0.95}), "chat_template_kwargs": ctk(thinking)}
    if CONFIG.get("max_tokens_explicit"): kw["max_tokens"] = CONFIG["max_tokens"]
    if CONFIG.get("system") is not None: kw["system"] = CONFIG["system"]
    scale = CONFIG.get("timeout_scale", 1)
    cmd = ["tool-eval-bench", "--base-url", base.rsplit("/v1", 1)[0], "--model", model, "--scenario-pack", packdir, "--pack-only",
           "--seed", "42", "--trials", "1", "--parallel", str(parallel), "--timeout", str(math.ceil(360 * scale)), "--max-turns", "16", "--no-live", "--no-warmup",
           "--json-file", out, "--backend-kwargs", json.dumps(kw)]
    if os.environ.get("EVALBANK_API_KEY"): cmd += ["--api-key", os.environ["EVALBANK_API_KEY"]]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600 * scale)
    except subprocess.TimeoutExpired:
        return None, 0, f"pack timeout after {3600 * scale:g}s"
    except OSError as e:
        return None, 0, f"pack failed: {type(e).__name__}"
    if p.returncode: return None, 0, f"rc={p.returncode}: {p.stderr[-400:]}"
    try:
        d = json.load(open(out))
    except Exception:
        return None, 0, p.stderr[-400:]
    # points: PASS=2 PARTIAL=1 FAIL=0 → normalize to 0..100 using tool-eval-bench's own totals
    sc = d.get("scores") or {}
    tot, mx = sc.get("total_points"), sc.get("max_points")
    sr = sc.get("scenario_results") or []
    n = len(sr) if isinstance(sr, (list, dict)) else d.get("total_scenarios", 0)
    if not mx: return None, n, "no max_points"
    return 100.0 * tot / mx, n, f"teb_final={d.get('final_score')} safety={len(d.get('safety_warnings') or [])}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True); ap.add_argument("--model", required=True); ap.add_argument("--label", required=True)
    ap.add_argument("--tier", default="private", choices=["private", "public"]); ap.add_argument("--cats", default=",".join(ALL_CATS))
    ap.add_argument("--runs", type=int, default=2, help="2 or more; a single run has no spread and is not comparable"); ap.add_argument("--thinking", default="on", choices=["on", "off"])
    ap.add_argument("--parallel", type=int, default=4); ap.add_argument("--judge", default="")
    ap.add_argument("--judge-base-url", default=None, help="OpenAI-compatible endpoint for the cross-family judge (default: EVALBANK_JUDGE_BASE_URL env, else --base-url)")
    ap.add_argument("--recipe-arm", choices=["vendor", "harness-uniform"], default="vendor"); ap.add_argument("--reason", default="")
    ap.add_argument("--max-tokens", type=int); ap.add_argument("--sampling"); ap.add_argument("--chat-kwargs"); ap.add_argument("--system")
    a = ap.parse_args()
    global CONFIG; CONFIG = resolve_config(a)
    if a.runs < 1 or a.parallel < 1: ap.error("--runs and --parallel must be positive")
    global TIER; TIER = a.tier
    if a.tier == "private": assert_local(a.base_url)
    judge_base = a.judge_base_url or os.environ.get("EVALBANK_JUDGE_BASE_URL") or a.base_url
    if a.judge and a.tier == "private": assert_local(judge_base)
    cats = [c for c in a.cats.split(",") if c]
    if a.runs < 2: print("[warn] --runs 1: no spread is measured; the report is not comparable with another model", file=sys.stderr)
    thinking = a.thinking == "on"
    bh = bank_hash(a.tier, cats)
    gv = hashlib.sha256(open(__file__, "rb").read() + open(f"{ROOT}/tools/agent_loop.py", "rb").read()).hexdigest()[:12]
    ts = time.strftime("%Y%m%d-%H%M%S"); outdir = f"{ROOT}/runs/{ts}-{a.label}"; rawdir = f"{outdir}/raw"; os.makedirs(rawdir)
    table = {}
    for k in range(1, a.runs + 1):
        assert bank_hash(a.tier, cats) == bh, "bank changed between runs"
        for cat in cats:
            t0 = time.time()
            if cat in PACK_CATS:
                score, n, err = run_pack(cat, a.base_url, a.model, thinking, rawdir, k, a.tier, parallel=a.parallel)
            else:
                items = load_items(a.tier, cat)
                if not items: score, n, err = None, 0, "no items"
                else: score, n, err = run_cat(cat, items, a.base_url, a.model, thinking, a.judge, a.parallel, rawdir, k, judge_base)
            table.setdefault(cat, []).append(score)
            print(f"[run{k}] {cat:12s} n={n:3d} score={score if score is None else round(score,1)} {err or ''} ({round(time.time()-t0)}s)", flush=True)
    rows = []
    for cat in cats:
        s = [x for x in table[cat] if x is not None]
        complete = len(s) == len(table[cat])
        med = round(statistics.median(s), 1) if (s and complete) else None
        raw_spread = (max(s) - min(s)) if len(s) > 1 else 0.0
        rows.append({"cat": cat, "kind": "pack(0/1/2)" if cat in PACK_CATS else "own(0/1)", "runs": table[cat], "median": med, "spread": round(raw_spread, 1),
                     "flag": ("✗run-failed" if not complete else ("⚠" if raw_spread > 5 else ""))})
    own = [r["median"] for r in rows if r["kind"].startswith("own") and r["median"] is not None]
    pack = [r["median"] for r in rows if r["kind"].startswith("pack") and r["median"] is not None]
    res = {"label": a.label, "model": a.model, "base_url": a.base_url, "tier": a.tier, "thinking": thinking, "runs": a.runs,
           "bank_hash": bh, "grader_version": gv, "grader_env": grader_env(), **CONFIG, "cats": cats, "ts": ts, "rows": rows,
           "own_mean": round(statistics.mean(own), 1) if own else None, "pack_mean": round(statistics.mean(pack), 1) if pack else None}
    json.dump(res, open(f"{outdir}/results.json", "w"), ensure_ascii=False, indent=1)
    md = [f"# evalbank {a.label} · {a.model} · thinking={'on' if thinking else 'off'} · bank_hash={bh} · grader={gv} · runs={a.runs}", "",
          f"Recipe arm: **{CONFIG['recipe_arm']}**" + (" (control arm)" if CONFIG['recipe_arm'] == "harness-uniform" else " (source labels are not independently verified)"),
          f"Reason: {CONFIG['recipe_reason']}", f"Non-official fields: {json.dumps(CONFIG['recipe_non_official'])}",
          f"Overrides: {json.dumps(CONFIG['recipe_overrides'])}", f"Limitations: {json.dumps(CONFIG['limitations'])}", "",
          "| cat | kind | runs | median | spread | |", "|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['cat']} | {r['kind']} | {r['runs']} | {r['median']} | {r['spread']} | {r['flag']} |")
    md += ["", f"own(0/1) mean: **{res['own_mean']}** · pack(0/1/2) mean: **{res['pack_mean']}** (pack scores are reported separately, never merged with own-bank scores; ⚠ = spread > 5, runs not comparable)",
           "", "Significance: for a category with n=30 items, one item is 3.3 points; a within-category gap below 10 points between two models should be treated as noise. Discriminative range: any category scoring >=95 or <=5 needs harder or replacement items.",
           f"Recipe arm: {CONFIG['recipe_arm']}; requested sampling: {json.dumps(CONFIG['sampling'])}; chat_template_kwargs: {json.dumps(ctk(thinking))}; max_tokens: {CONFIG['max_tokens']}; system: {json.dumps(CONFIG['system'])}; preserve_reasoning: {CONFIG['preserve_reasoning']}; timeout_scale: {CONFIG['timeout_scale']}. Pack max_tokens: {'explicit' if CONFIG['max_tokens_explicit'] else 'tool default'}. Pack scoring is strict positional matching (a single extra exploratory tool call scores 0), so tool errors are never injected."]
    open(f"{outdir}/report.md", "w").write("\n".join(md)); print("\n".join(md)); print("saved", outdir)
    if any("run-failed" in r["flag"] for r in rows): raise SystemExit(1)


if __name__ == "__main__":
    main()
