#!/usr/bin/env python3
"""Long-horizon coding category: a minimal, harness-independent agent loop (purpose-built harness).

Tools exposed to the model (OpenAI tools API): list_files, read_file, write_file, run_tests (VISIBLE tests only), done.
Hidden tests are never visible; score = hidden pass fraction. Records turns, tool calls, tokens, wall.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request

TOOLS = [
 {"type": "function", "function": {"name": "list_files", "description": "List all files in the repo (relative paths).", "parameters": {"type": "object", "properties": {}}}},
 {"type": "function", "function": {"name": "read_file", "description": "Read a file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
 {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a file with full content.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
 {"type": "function", "function": {"name": "run_tests", "description": "Run the repo's visible tests (pytest tests/). Returns summary + last lines.", "parameters": {"type": "object", "properties": {}}}},
 {"type": "function", "function": {"name": "done", "description": "Declare the task finished.", "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}}}},
]
SYSTEM = ("You are a coding agent working in a real repository. Use tools to read code, edit files, and run tests; "
          "call done when finished. Change only the files that are necessary; do not delete existing tests; "
          "do not invent file contents — read_file before write_file. Write your replies in English.")


def _safe(root, path):
    rr = os.path.realpath(root); p = os.path.realpath(os.path.join(rr, path))
    if not p.startswith(rr + os.sep) and p != rr: raise ValueError("path escapes repo")
    if os.path.relpath(p, rr).split(os.sep)[0].startswith("_hidden"): raise ValueError("reserved path")
    return p


def _passed(stdout):
    lines = [l for l in stdout.splitlines() if re.search(r"\b\d+ (passed|failed|error|errors|skipped)\b.* in [\d.]+s", l.strip())]
    if not lines: return 0
    m = re.search(r"(\d+) passed", lines[-1]); return int(m.group(1)) if m else 0


def run_pytest(root, target, budget=120):
    """cwd=root so the repo package imports; target may live OUTSIDE root (hidden tests). Returns passed, expected_total, tail."""
    files = [target] if os.path.isfile(target) else [os.path.join(dp, f) for dp, _, fn in os.walk(target) for f in fn if f.startswith("test_") and f.endswith(".py")]
    expected = sum(len(re.findall(r"^\s*def test_", open(f).read(), re.M)) for f in files)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}; env["PYTHONPATH"] = root
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider", "--rootdir", os.path.dirname(files[0]) if files else root, *files],
                       cwd=root, capture_output=True, text=True, timeout=max(5, min(120, budget)), env=env)
    return _passed(r.stdout), expected, (r.stdout + r.stderr)[-1500:]


def exec_tool(root, name, args, budget=120):
    if name == "list_files":
        out = []
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if not d.startswith((".", "__pycache__"))]
            for x in fn:
                if not x.endswith(".pyc"): out.append(os.path.relpath(os.path.join(dp, x), root))
        return "\n".join(sorted(out))
    if name == "read_file":
        try: return open(_safe(root, args["path"])).read()[:20000]
        except Exception as e: return f"ERROR: {e}"
    if name == "write_file":
        try:
            p = _safe(root, args["path"]); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(args.get("content", "")); return f"wrote {args['path']} ({len(args.get('content', ''))} chars)"
        except Exception as e: return f"ERROR: {e}"
    if name == "run_tests":
        if not os.path.isdir(os.path.join(root, "tests")): return "no visible tests/ dir"
        p, t, tail = run_pytest(root, os.path.join(root, "tests"), budget); return f"{p}/{t} passed\n{tail}"
    return "ERROR: unknown tool"


def run_task(task_dir, base, model, thinking, max_turns=30, timeout=600, log=None):
    """task_dir has: task.md, seed/ (repo), hidden/ (test_*.py). Returns dict(score, turns, tool_calls, ...)."""
    root = tempfile.mkdtemp(prefix="evalbank-c9-"); shutil.copytree(os.path.join(task_dir, "seed"), root, dirs_exist_ok=True)
    task = open(os.path.join(task_dir, "task.md")).read()
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}]
    t0 = time.time(); turns = 0; calls = 0; tok = 0; raws = []; finished = False; err = None
    try:
        while turns < max_turns and time.time() - t0 < timeout:
            body = {"model": model, "messages": msgs, "tools": TOOLS, "tool_choice": "auto", "max_tokens": int(os.environ.get("EVALBANK_MAX_TOKENS", "8000")),
                    "temperature": 0.5 if thinking else 0.0, "top_p": 0.95,
                    "chat_template_kwargs": {"thinking": thinking, **({"reasoning_effort": "high"} if thinking else {})}}
            req = urllib.request.Request(f"{base}/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=max(30, timeout - (time.time() - t0))) as r:
                raw = r.read().decode()
            raws.append(raw); d = json.loads(raw); turns += 1
            tok += (d.get("usage") or {}).get("completion_tokens", 0)
            m = d["choices"][0]["message"]; tcs = m.get("tool_calls") or []
            msgs.append({"role": "assistant", "content": m.get("content") or "", **({"tool_calls": tcs} if tcs else {})})
            if not tcs:
                msgs.append({"role": "user", "content": "Continue: use tools to modify and verify, then call done when finished."}); continue
            for tc in tcs:
                calls += 1; fn = tc["function"]["name"]
                try: args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception: args = {}
                remaining = timeout - (time.time() - t0)
                if remaining <= 0: err = "timeout"; break
                if fn == "done": finished = True; res = "ok"
                else: res = exec_tool(root, fn, args, budget=remaining)
                if log: log.write(f"[turn {turns}] {fn} {json.dumps(args, ensure_ascii=False)[:200]} -> {res[:160]!r}\n")
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", f"call_{calls}"), "content": res})
            if finished: break
    except Exception as e:
        err = str(e)[:200]
    # hidden grading: tests copied to a fresh dir OUTSIDE the repo (model cannot pre-seed it); rootdir there so repo conftest/ini are ignored
    hid = tempfile.mkdtemp(prefix="evalbank-hidden-"); shutil.copytree(os.path.join(task_dir, "hidden"), hid, dirs_exist_ok=True)
    try:
        p, t, tail = run_pytest(root, hid)
    except Exception as e:
        p, t, tail = 0, 1, str(e)
    shutil.rmtree(root, ignore_errors=True); shutil.rmtree(hid, ignore_errors=True)
    return {"score": (p / t) if t else 0.0, "hidden_passed": p, "hidden_total": t, "turns": turns, "tool_calls": calls, "finished": finished,
            "secs": round(time.time() - t0, 1), "usage": {"out": tok}, "error": err, "tail": tail[-400:], "raw_http_bodies": raws}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("task_dir"); ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", required=True); ap.add_argument("--thinking", default="off")
    a = ap.parse_args()
    r = run_task(a.task_dir, a.base_url, a.model, a.thinking == "on", log=sys.stderr)
    r.pop("raw_http_bodies"); print(json.dumps(r, ensure_ascii=False, indent=1))
