# Method — how the bank is built, scored and kept honest

## Two tiers

| tier | what is in it | who can run it | what gets published |
|---|---|---|---|
| **private (held-out)** | questions generated from *your own* notes/runbooks/decisions (C1 KB-QA, C2 long-context, C5 extraction, C10 SRE/ops) | only local endpoints (the runner refuses anything that does not resolve to loopback/RFC1918) | scores + content hashes, never the questions |
| **synthetic** (any tier directory; ours live under `bank/private` too) | C3 tool use, C4 code fixes, C6 vision (rendered charts/diagrams/OCR), C7 instruction following, C7a agentic IF, C8 judgment, C9 long-horizon coding | any OpenAI-compatible endpoint | scores + content hashes (held out as well, so they cannot leak into training data) |

The private tier follows the `tool-eval-bench` "scenario pack" idea: two published numbers are comparable only if they carry the same content hash, and the questions are never burned by publishing them. The runner records a bank hash (every file under the category directories, including hidden tests and seeds) and a grader version (hash of the grader code) in every report. Scores and content hashes of your own bank are what make two runs comparable — two numbers are comparable only under the same hash. This page never prints a hash value.

## Generating private items from your own corpus

1. Export eligible pages (we used ~2,100 eligible pages with 800–40,000 chars each; anything you tag as sensitive — credentials, personal, restricted — is excluded up front; LAN IPs are masked).
2. A **local** model writes 3 candidate questions per page (`tools/gen_items.py`). Thinking on is 2–3× better at evidence discipline but ~4× slower; we ran the first third with thinking on and the rest off, and let the filter decide.
3. `tools/lint.py` keeps a candidate only if: the quoted evidence is verbatim in the page (ellipsis-joined fragments allowed), the answer is inside the evidence sentence, the answer does not appear in the question, no 3-gram-Jaccard ≥ 0.6 duplicate exists, and counterfactual items name an entity with zero hits in the page. Survival rates: KB-QA 85 % (thinking on) / 60 % (off), SRE/ops 17 %, extraction 30 %.
4. Equivalent answers are **any-of**; numeric answers get a digits-only alias; extraction items drop `null` fields whose key terms appear in the page (the generator otherwise invents "missing" fields that are actually present — we found this in calibration).

## Graders (deterministic first)

`contains` (whitespace/case-normalised; purely numeric values need digit boundaries so "5" never matches "15"; answers over 600 chars fail — echoing the document is not an answer), `exact`, `regex`, `numeric` (±tolerance, for reading values off an unlabeled chart), `set` (exact set of named entities — listing everything is a fail), `json_schema` (per-field credit; missing key ≠ null; non-object = 0), `checks` (IFEval-style format checks), `tests` (hidden pytest/bash, expected total read from the hidden file, only the final pytest summary line is trusted), `agent` (a minimal tool loop: `list_files/read_file/write_file/run_tests/done`, ≤30 turns, hidden tests copied to a directory the model cannot see or pre-seed; repo-side `conftest.py` cannot affect grading).

Tool-use and judgment categories run through `tool-eval-bench --scenario-pack --pack-only`. Its YAML evaluator matches tool calls **positionally** and checks `answer_contains` substrings only. Two consequences we hit: an exploratory `search_files` before the expected `read_file` scores 0, and injected tool errors (`--error-rate`) turn every retry into a 0. We therefore tell the model to read directly when the path is given, and we do not inject errors into YAML packs. Pack scores (0/1/2 per scenario) are reported in a separate column and never averaged with the 0/1 categories.

## Runs, spread, discrimination

The first worked example reports the **median of 2 runs** with the spread beside it; the cloud example explicitly uses 2 or 3 runs as specified for each table; spread > 5 flags the category as not comparable, and the adjudicated value then falls back to the lower run. The threshold is in points, not items: with n = 12 one item is 8.3 points, so a single disagreement between two runs already exceeds it. In our cloud-selection tables the 12-item code category was flagged in 5 of 11 arms; in four of them the spread was 8.3 to 12.5 points (one to one and a half items), and the fifth was an arm with request timeouts. Read a flag together with n and the number of differing items. The code still uses a flat 5-point threshold. The agentic-instruction-following category, whose spread was highest, takes the median of three or more runs. At n = 30 one item is 3.3 points; treat < 10 points between two models as noise. If the incumbent scores ≥ 95 or ≤ 5 on a category the bank is not measuring anything there and the category must be made harder before the next comparison (that happened to long-horizon coding and agentic IF on the first night).

`temperature 0` is not bitwise deterministic under batching + prefix cache: on KB-QA the same 30 questions moved 83.3 → 96.7 between two runs, and 3 of the 4 flips were answers that were semantically right but not verbatim (the same quantity written with a unit word in one language versus the other). That is a grader brittleness problem as much as a sampling one; the fix is aliasing, not more runs.

## Calibration without a human in the loop

Every grader verdict on a stratified sample (4 per category, fixed seed) is re-judged by a model from a **different family** than the one under test (self-preference bias), and an independent re-computation from the raw HTTP bodies must match the report cell by cell. On the first bank: 31/32 agreement, 11/11 categories recomputed identically; the single disagreement and both extraction defects were **item bugs**, which is the point of the exercise.

This is not human calibration. The standard practice is to calibrate graders against human labels; we replace it with a cross-family model re-judge plus recomputation from the raw HTTP bodies. The section is titled "without a human in the loop" because no human labels the verdicts. If you can label a sample by hand, prefer that — `tools/make_calibration.py` builds the form and `tools/agreement.py` computes grader-vs-human agreement.

## What this does not measure

Real-repo-scale coding (the 3–5 file repos here are a ceiling for a 284B MoE), user-simulated multi-turn dialogue, non-Python code, real screenshots (the vision items are rendered), rule adherence that cannot be checked by substring (a pack limitation).
