# Bank format — the item shape the runner reads

This page is derived only from the code in `tools/`. It documents exactly the keys the runner, the graders and the agent loop read, and the directory layout they expect. Bank items may be written in any language; the runner's own fixed strings (the agent-loop system prompt, the fallback answers, the lint negative answers) are English.

The bank is never published. Build your own from your own notes and synthetic generators; the runner scores whatever you put in `bank/<tier>/<category>/`.

## Directory layout

```
bank/
  private/                       # held-out tier; the runner refuses non-private endpoints for this tier
    c1-kbqa/items.jsonl
    c2-longctx/items.jsonl
    c4-code/
      items.jsonl
      <task_dir>/                # one directory per item (expected.type == "tests")
        hidden_test.py           # Python hidden tests; OR
        hidden_test.sh           # bash hidden tests (expected.lang selects which)
    c5-extract/items.jsonl
    c6-vision/items.jsonl
    c7-zhif/items.jsonl
    c9-long-coding/
      items.jsonl
      <task_dir>/                # one directory per item (expected.type == "agent")
        task.md                  # the task description shown to the model
        seed/                    # the repo the model works in (copied to a temp dir at run time)
        hidden/                  # hidden pytest tests (test_*.py); never visible to the model
    c10-sre-ops/items.jsonl
    c3-tool/...                  # tool-eval-bench scenario pack (see method.md)
    c7-agentic-if/...            # tool-eval-bench scenario pack
    c8-judgment/...              # tool-eval-bench scenario pack
  public/                        # same layout; for items you allow to be sent to any OpenAI-compatible endpoint
```

`--tier` selects the directory; both directories have the same shape and any category may live in either. We keep every category, including the three pack categories, under `private/` because our items derive from our own data; `public/` is for items you are willing to send to a remote endpoint.

Two categories use per-task directories instead of a single `items.jsonl` carrying everything:

- **`c4-code` (single-file code fixes, `expected.type == "tests"`)** — the item in `items.jsonl` points at a `task_dir`; the runner extracts the model's fenced code, writes it to a temp dir, copies `hidden_test.py` (Python) or `hidden_test.sh` (bash) from that task dir next to it, and runs the hidden tests. `expected.lang` selects `py` or `sh`.
- **`c9-long-coding` (long-horizon coding, `expected.type == "agent"`)** — the item points at a `task_dir` holding `task.md` (the task text given to the model), `seed/` (the repo the model is dropped into) and `hidden/` (hidden pytest tests). The agent loop runs `list_files`, `read_file`, `write_file`, `run_tests` (visible tests only) and `done`; the hidden tests are copied to a fresh directory outside the repo and run there, so a repo-side `conftest.py` cannot affect grading.

The three synthetic pack categories (`c3-tool`, `c7-agentic-if`, `c8-judgment`) are consumed by `tool-eval-bench --scenario-pack --pack-only`, not by the runner's own graders; their layout is the upstream pack layout.

## Item fields

Every item is one JSON object on a line of `items.jsonl`. Only the keys the code actually reads are listed below.

| key | read by | meaning |
|---|---|---|
| `id` | runner, calibration | unique across the whole bank (the calibration tool indexes results by `id` alone); `lint.py` assigns `<cat>-000` style ids |
| `prompt` | runner | the question text sent to the model |
| `expected` | runner, graders | the grader spec; see the per-type skeletons below |
| `judge` | runner | optional; if present, `judge.rubric` is sent to the cross-family judge when `expected.type == "judge"` |
| `image` | runner | optional; a URL or data URL the endpoint accepts (the runner passes the string through as `image_url.url` and does not load local files); if present, the prompt is sent as a multimodal message |
| `context` | runner | optional; if present (and no `image`), the prompt is wrapped with this document as context |
| `difficulty` | item metadata | integer, written by `lint.py` (1–3) |
| `kind` | item metadata | factual / counterfactual (c1), or the SRE sub-type (c10); written by `lint.py` |
| `evidence` | item metadata | the verbatim source quote the answer is drawn from; written by `lint.py` |
| `negative_check` | item metadata | for counterfactual items: the entity that must have zero hits in the page |
| `source` | generator | `{slug, hash, type}` of the source page; written by `gen_items.py` |
| `meta` | generator | `{gen, finish, secs}` provenance; written by `gen_items.py` |
| `cat` | runner, calibration | **required**; the category id (`c1-kbqa` … `c10-sre-ops`); the runner reads it from every item |
| `tier` | metadata | `private` or `public`; the runner selects the tier directory from `--tier`, not from this field |

`id`, `cat`, `prompt` and `expected` are required. `image` and `context` are mutually exclusive in practice (the runner checks `image` first, then `context`). The remaining keys are metadata or provenance and are not read by the graders.

## The `expected` block, by type

`expected.type` selects the grader. The sub-fields each type reads:

- **`contains`** — substring match after whitespace/case normalisation. Reads `values` (list), `all` (bool; default true), `max_chars` (default 600; answers over this length fail). Purely numeric values get digit boundaries so `"5"` never matches `"15"`.
- **`exact`** — normalised equality. Reads `value`.
- **`regex`** — `re.search` on the stripped answer. Reads `pattern`.
- **`numeric`** — reads the last number in the answer; passes if within tolerance. Reads `value`, `tol` (default 0).
- **`set`** — exact set of named entities: every expected value present AND no other member of the universe present. Reads `values` (expected set), `universe` (every name that could appear).
- **`json_schema`** — per-field credit on a parsed object; missing key ≠ null; a non-object is 0. Reads `answer` (the keyed comparison object). `schema` is lint metadata: the runner does not inject it, so the schema the model must follow has to be written into `prompt` itself.
- **`checks`** — IFEval-style format checks; all must pass. Reads `checks`, a list of `{kind, ...}` where `kind` ∈ `max_chars`/`min_chars`/`max_words`/`zh_ratio`/`no_words`/`must_words`/`regex`/`json_valid`/`json_path_len`/`line_count`/`starts_with`/`ends_with`/`exact_lines`.
- **`tests`** — `c4-code`: the runner extracts the model's fenced code and runs hidden tests. Reads `task_dir`, `lang` (`py` or `sh`). Keep one `def test_` per case and no parametrisation: the expected total is the count of `def test_` lines in the hidden file.
- **`agent`** — `c9-long-coding`: the agent loop runs over `task_dir`. Reads `task_dir`. An optional top-level `timeout` on the item overrides the default.
- **`judge`** — the answer is scored by a model from a different family than the one under test. Requires `item.judge.rubric` (the rubric text); the grader sends rubric + prompt + answer and expects `{"pass": bool, "critique": "..."}`.

## JSON skeleton per `expected` type

Placeholders only — replace each `<...>` with your own content. No example questions are given.

### contains
```json
{
  "id": "c1-kbqa-000",
  "cat": "c1-kbqa",
  "tier": "private",
  "prompt": "<your question>",
  "expected": {
    "type": "contains",
    "values": ["<verbatim phrase from your page>", "<equivalent phrasing>"],
    "all": false,
    "max_chars": 600
  },
  "context": "<the source page text, used as context>",
  "evidence": "<one verbatim sentence from the page that contains the answer>",
  "kind": "factual",
  "difficulty": 2,
  "negative_check": null,
  "source": {"slug": "<page slug>", "hash": "<page content hash>", "type": "<page type>"},
  "meta": {"gen": "<model>@<date>", "finish": "<finish_reason>", "secs": 0},
  "judge": null
}
```

A counterfactual item uses the same shape with `"kind": "counterfactual"`, `expected.values` set to the absent-field answers (for example the local "not mentioned" phrases), and `negative_check` set to the entity that must have zero hits in the page.

### exact
```json
{
  "id": "<cat>-000",
  "cat": "<cat>",
  "tier": "<tier>",
  "prompt": "<your question>",
  "expected": {"type": "exact", "value": "<the exact expected string>"}
}
```

### regex
```json
{
  "id": "<cat>-000",
  "cat": "<cat>",
  "tier": "<tier>",
  "prompt": "<your question>",
  "expected": {"type": "regex", "pattern": "<a python regex, dot matches newline>"}
}
```

### numeric
```json
{
  "id": "<cat>-000",
  "cat": "<cat>",
  "tier": "<tier>",
  "prompt": "<your question>",
  "expected": {"type": "numeric", "value": 0, "tol": 0}
}
```

### set
```json
{
  "id": "<cat>-000",
  "cat": "<cat>",
  "tier": "<tier>",
  "prompt": "<your question>",
  "expected": {
    "type": "set",
    "values": ["<expected named entity 1>", "<expected named entity 2>"],
    "universe": ["<every name that could appear>"]
  }
}
```

### json_schema
```json
{
  "id": "c5-extract-000",
  "cat": "c5-extract",
  "tier": "private",
  "prompt": "<your extraction instruction, including the JSON schema the model must follow>",
  "expected": {
    "type": "json_schema",
    "schema": {"<field_key>": "<type description>"},
    "answer": {"<field_key>": "<value or null>"}
  },
  "context": "<the source page text>",
  "evidence": {"<field_key>": "<verbatim sentence from the page for that field>"},
  "difficulty": 2,
  "source": {"slug": "<page slug>", "hash": "<page content hash>", "type": "<page type>"},
  "meta": {"gen": "<model>@<date>", "finish": "<finish_reason>", "secs": 0},
  "judge": null
}
```

### checks
```json
{
  "id": "c7-zhif-000",
  "cat": "c7-zhif",
  "tier": "private",
  "prompt": "<your instruction-following instruction>",
  "expected": {
    "type": "checks",
    "checks": [
      {"kind": "max_chars", "n": 0},
      {"kind": "zh_ratio", "min": 0.0, "max": 1.0},
      {"kind": "no_words", "words": ["<forbidden word>"]},
      {"kind": "must_words", "words": ["<required word>"]},
      {"kind": "line_count", "n": 0},
      {"kind": "starts_with", "s": "<prefix>"},
      {"kind": "ends_with", "s": "<suffix>"},
      {"kind": "exact_lines", "lines": ["<line 1>", "<line 2>"]}
    ]
  },
  "judge": null
}
```

### tests (c4-code)
```json
{
  "id": "c4-code-000",
  "cat": "c4-code",
  "tier": "private",
  "prompt": "<your code-fix task; the model returns one fenced code block>",
  "expected": {"type": "tests", "task_dir": "<c4 task directory name>", "lang": "py"},
  "difficulty": 2,
  "judge": null
}
```
The named `task_dir` under `bank/private/c4-code/` must contain `hidden_test.py` (when `lang == "py"`) or `hidden_test.sh` (when `lang == "sh"`).

### agent (c9-long-coding)
```json
{
  "id": "c9-long-coding-000",
  "cat": "c9-long-coding",
  "tier": "private",
  "prompt": "<not used; the task text comes from task_dir/task.md>",
  "expected": {"type": "agent", "task_dir": "<c9 task directory name>"},
  "timeout": 900,
  "judge": null
}
```
The named `task_dir` under `bank/private/c9-long-coding/` must contain `task.md`, `seed/` (the repo) and `hidden/` (hidden pytest tests).

### judge
```json
{
  "id": "<cat>-000",
  "cat": "<cat>",
  "tier": "<tier>",
  "prompt": "<your question>",
  "expected": {"type": "judge"},
  "judge": {"rubric": "<the rubric the cross-family judge grades against>"}
}
```

## Notes

- `id`, `cat`, `tier` are written by `lint.py`; `source` and `meta` are written by `gen_items.py`. When you author items by hand, keep the same key names.
- The runner hashes every file under `bank/<tier>/<category>/` (excluding `gen-raw*` and `.pyc`) into a short bank hash, and hashes the grader code into a grader version, recording both in every report. Two reports are comparable only if they share the same bank hash and grader version.
- See [method.md](method.md) for how items are generated, linted and scored, and [../README.md](../README.md) for the command sequence.
