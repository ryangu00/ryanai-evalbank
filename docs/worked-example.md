# Worked example — what the method produced for us

These are our numbers, on our bank, at our settings. They are shown to demonstrate the method's output, not as a ranking for you. Your scores will differ from ours — different usage, different weights, different model strengths — and that is the point.

This page is a worked example of the method in [README.md](../README.md) and [method.md](method.md): five endpoints scored on the same held-out bank, two runs each, median plus spread, then adjudicated against gates derived from the incumbent. All columns were produced with the same bank hash and grader version, so they are comparable with each other; the absolute numbers are not transferable to your bank.

## Setup

Five endpoints, same bank, thinking off, temperature 0, two runs each, parallel 4. These runs predate the recipe gate: every endpoint ran under the harness-uniform recipe, which in our own terminology is a control arm, not a per-model vendor recipe. Hardware: two Dell Pro Max with GB10 nodes (head node + worker node, TP2 over RoCE). The incumbent is the production model. Scores are per-category medians of two runs; ⚠ marks spread > 5 (adjudication uses the lower run). Pack categories use tool-eval-bench scenario packs (0/1/2 points) and are never merged with the own (0/1) categories. The long-context 200K stack is N/A for models whose native context is below 200K, so the 20-item (32K/95K) subset is also reported.

## Per-category medians (two runs; ⚠ = spread > 5, adjudication uses the lower run)

| cat | DeepSeek V4 Flash Vision-Exp (two-node, incumbent) | Qwen3.8-27B (single node, reference) | Qwen3.8-Flash-Next (single node) | Qwen3.8-Flash-Next (two-node) | Muse Glimmer 30B (single node, thinking low) |
|---|---|---|---|---|---|
| c1-kbqa | 86.7 | 100.0 | 95.0 | 95.0 | 98.3 |
| c2-longctx | 90.0 ⚠(86.7/93.3) | 65.0 | 100.0 | 98.3 | 63.3 |
| c3-tool | 73.3 ⚠(70.0/76.7) | 66.7 | 86.7 ⚠(83.3/90.0) | 88.3 | 53.3 |
| c4-code | 87.5 | 95.8 | 91.7 ⚠(87.5/95.8) | 91.7 ⚠(87.5/95.8) | 95.8 |
| c5-extract | 92.1 | 89.3 | 91.1 | 90.6 | 88.2 |
| c6-vision | 81.2 | 80.0 | 87.5 | 87.5 | 90.0 |
| c7-zhif | 78.3 | 86.7 | 85.0 | 85.0 | 80.0 |
| c7-agentic-if | 95.0 | 80.0 | 87.5 | 85.0 ⚠(80.0/90.0) | 79.2 |
| c8-judgment | 76.7 ⚠(73.3/80.0) | 89.2 | 70.8 | 70.0 | 76.7 |
| c9-long-coding | 99.3 | 97.2 | 97.6 | 97.2 | 75.0 ⚠(66.7/83.3) |
| c10-sre-ops | 83.3 ⚠(80.0/86.7) | 90.0 | 88.3 | 90.0 | 93.3 |
| c2 (32K/95K 20 items, 200K tier N/A removed) | 92.5 [85.0, 100.0] | 97.5 [100.0, 95.0] | 100.0 [100.0, 100.0] | 97.5 [95.0, 100.0] | 95.0 [95.0, 95.0] |
| own mean (8 categories, original scope) | 87.3 | 88.0 | 92.0 | 91.9 | 85.5 |
| pack mean (3 categories) | 81.7 | 78.6 | 81.7 | 81.1 | 69.7 |
| errors / cat-runs | 1 / 22 | 20 / 22 | 0 / 22 | 0 / 22 | 23 / 22 |

## Throughput, KV cache and boot

| metric | DeepSeek V4 Flash Vision-Exp (two-node, incumbent) | Qwen3.8-27B (single node, reference) | Qwen3.8-Flash-Next (single node) | Qwen3.8-Flash-Next (two-node) | Muse Glimmer 30B (single node, thinking low) |
|---|---|---|---|---|---|
| decode tok/s | 31.8 | 20.0 | 36.6 | 52.9 | 27.1 |
| cold prefill tok/s | 2085 | 1957 | 2144 | 2989 | 2822 |
| 6-stream agg tok/s | 81.2 | 88.0 | 56.6 | 91.8 | 116.1 |
| KV tokens @ max_model_len | 1,301,037 @ 1,048,320 | — | 1,134,794 @ 262,144 | 3,042,386 @ 262,144 | 2,817,481 @ 131,072 |
| boot s (real request) | — | — | 300 | 300 | 520 |

## Per-category runner time (s; own categories: sum of per-item request seconds at parallel 4; pack categories: elapsed time of the pack run; median of two runs)

| cat | DeepSeek V4 Flash Vision-Exp (two-node, incumbent) | Qwen3.8-27B (single node, reference) | Qwen3.8-Flash-Next (single node) | Qwen3.8-Flash-Next (two-node) | Muse Glimmer 30B (single node, thinking low) |
|---|---|---|---|---|---|
| c1-kbqa | 19 | 36 | 41 | 28 | 60 |
| c2-longctx | 1288 | 752 | 1594 | 1177 | 563 |
| c3-tool | 39 | 66 | 68 | 118 | 137 |
| c4-code | 10 | 85 | 19 | 12 | 75 |
| c5-extract | 42 | 52 | 51 | 34 | 142 |
| c6-vision | 18 | 19 | 22 | 179 | 145 |
| c7-zhif | 24 | 16 | 23 | 14 | 92 |
| c7-agentic-if | 43 | 70 | 78 | 210 | 254 |
| c8-judgment | 69 | 63 | 107 | 72 | 268 |
| c9-long-coding | 839 | 131 | 180 | 178 | 1033 |
| c10-sre-ops | 32 | 60 | 54 | 34 | 94 |

## Adjudication under the first rule set: Qwen3.8-Flash-Next (single node) vs DeepSeek V4 Flash Vision-Exp (two-node, incumbent)

- 1. Stability: errors 0 (cat-runs 22) — boot 300s
- 2. Critical category c3-tool: 83.3 vs incumbent 70.0 (gate ≥65.0) ✓
- 2. Critical category c4-code: 87.5 vs incumbent 87.5 (gate ≥82.5) ✓
- 2. Critical category c8-judgment: 70.8 vs incumbent 73.3 (gate ≥68.3) ✓
- 2. Critical category c9-long-coding: 97.6 vs incumbent 99.3 (gate ≥94.3) ✓
- 3. Other category c1-kbqa: 95.0 vs incumbent 86.7 (gate ≥76.7) ✓
- 3. Other category c2-longctx: 100.0 vs incumbent 92.5 (gate ≥82.5) ✓
- 3. Other category c5-extract: 91.1 vs incumbent 92.1 (gate ≥82.1) ✓
- 3. Other category c6-vision: 87.5 vs incumbent 81.2 (gate ≥71.2) ✓
- 3. Other category c7-zhif: 85.0 vs incumbent 78.3 (gate ≥68.3) ✓
- 3. Other category c7-agentic-if: 87.5 vs incumbent 95.0 (gate ≥85.0) ✓
- 3. Other category c10-sre-ops: 88.3 vs incumbent 80.0 (gate ≥70.0) ✓
- 4. Performance decode: 36.6 (gate ≥30) ✓
- 4. Performance prefill: 2144 (gate ≥1000) ✓
- 4. Performance six-stream: 56.6 (gate ≥60) ✗
- 4. Performance KV: 1,134,794 (gate ≥1,000,000) ✓
- 5. Δ own (shared categories, c2 uses 20 items) = 91.5 − 87.2 = +4.3 → candidate wins
- **Verdict: negative result (keep the incumbent)** — the six-stream aggregate throughput gate failed.

## Adjudication under the first rule set: Qwen3.8-Flash-Next (two-node) vs DeepSeek V4 Flash Vision-Exp (two-node, incumbent)

- 1. Stability: errors 0 (cat-runs 22) — boot 300s
- 2. Critical category c2-longctx: 97.5 vs incumbent 92.5 (gate ≥87.5) ✓
- 2. Critical category c3-tool: 88.3 vs incumbent 70.0 (gate ≥65.0) ✓
- 2. Critical category c6-vision: 87.5 vs incumbent 81.2 (gate ≥76.2) ✓
- 2. Critical category c8-judgment: 70.0 vs incumbent 73.3 (gate ≥68.3) ✓
- 2. Critical category c9-long-coding: 97.2 vs incumbent 99.3 (gate ≥94.3) ✓
- 3. Other category c1-kbqa: 95.0 vs incumbent 86.7 (gate ≥76.7) ✓
- 3. Other category c4-code: 87.5 vs incumbent 87.5 (gate ≥77.5) ✓
- 3. Other category c5-extract: 90.6 vs incumbent 92.1 (gate ≥82.1) ✓
- 3. Other category c7-zhif: 85.0 vs incumbent 78.3 (gate ≥68.3) ✓
- 3. Other category c7-agentic-if: 80.0 vs incumbent 95.0 (gate ≥85.0) ✗
- 3. Other category c10-sre-ops: 90.0 vs incumbent 80.0 (gate ≥70.0) ✓
- 4. Performance decode: 52.9 (gate ≥33) ✓
- 4. Performance prefill: 2989 (gate ≥2000) ✓
- 4. Performance six-stream: 91.8 (gate ≥75) ✓
- 4. Performance KV: 3,042,386 (gate ≥1,500,000) ✓
- 5. Δ own (shared categories, c2 uses 20 items) = 91.3 − 87.2 = +4.1 → candidate wins
- **Verdict: negative result (keep the incumbent)** — the c7-agentic-if gate failed.

## Adjudication under the first rule set: Muse Glimmer 30B (single node, thinking low) vs DeepSeek V4 Flash Vision-Exp (two-node, incumbent)

- 1. Stability: errors 23 (cat-runs 22) — the c2 200K tier exceeds the model's native context and is recorded as N/A, not an error; boot 520s
- 2. Critical category c3-tool: 53.3 vs incumbent 70.0 (gate ≥65.0) ✗
- 2. Critical category c4-code: 95.8 vs incumbent 87.5 (gate ≥82.5) ✓
- 2. Critical category c8-judgment: 76.7 vs incumbent 73.3 (gate ≥68.3) ✓
- 2. Critical category c9-long-coding: 66.7 vs incumbent 99.3 (gate ≥94.3) ✗
- 3. Other category c1-kbqa: 98.3 vs incumbent 86.7 (gate ≥76.7) ✓
- 3. Other category c2-longctx: 95.0 vs incumbent 92.5 (gate ≥82.5) ✓
- 3. Other category c5-extract: 88.2 vs incumbent 92.1 (gate ≥82.1) ✓
- 3. Other category c6-vision: 90.0 vs incumbent 81.2 (gate ≥71.2) ✓
- 3. Other category c7-zhif: 80.0 vs incumbent 78.3 (gate ≥68.3) ✓
- 3. Other category c7-agentic-if: 79.2 vs incumbent 95.0 (gate ≥85.0) ✗
- 3. Other category c10-sre-ops: 93.3 vs incumbent 80.0 (gate ≥70.0) ✓
- 4. Performance decode: 27.1 (gate ≥30) ✗
- 4. Performance prefill: 2822 (gate ≥1000) ✓
- 4. Performance six-stream: 116.1 (gate ≥60) ✓
- 4. Performance KV: 2,817,481 (gate ≥1,000,000) ✓
- 5. Δ own (shared categories, c2 uses 20 items) = 88.4 − 87.2 = +1.2 → dead heat (candidate only if decode ≥ incumbent × 1.2 and KV ≥ incumbent)
- 6. Runner-time ratio c3-tool: 137s vs 27B 66s ×2.1 (gate ≤3×) ✓
- 6. Runner-time ratio c7-zhif: 92s vs 27B 16s ×5.8 (gate ≤3×) ✗
- 6. Runner-time ratio c10-sre-ops: 94s vs 27B 60s ×1.6 (gate ≤3×) ✓
- **Verdict: negative result (keep the incumbent)** — five gates failed: c3-tool, c9-long-coding, c7-agentic-if, decode throughput, and the c7-zhif wall-clock ratio.

## Adjudications under the revised rule set, 2026-09-19/20: non-thinking vs thinking settings

Under the revised rule set the gates are derived from the baseline: critical categories use the baseline value minus 5; other categories use the baseline value minus 10; wall-clock gates are 1.5× the baseline. Each category takes the median of its runs; when the spread exceeds 5 the lower run is used; c7-agentic-if takes the median of three or more runs. The baseline column and the candidate column are run and scored under the same adjudication scope. The `wall` rows are the runner's per-category time: for own categories the sum of per-item request seconds at parallel 4, for pack categories the elapsed time of the pack run — not the elapsed wall-clock of the whole run.

### Non-thinking settings (baseline DeepSeek V4 Flash Vision-Exp vs candidate Qwen3.8-Flash-Next)

| cat | incumbent | candidate | runs (candidate) | gate | ok |
|---|---|---|---|---|---|
| c1-kbqa | 83.3 | 90.0 | [90.0, 96.7] | ≥73.3 | ✓ |
| c2-longctx (crit) | 87.5 | 100.0 | [100.0, 100.0] | ≥82.5 | ✓ |
| c3-tool (crit) | 66.7 | 85.0 | [83.3, 86.7] | ≥61.7 | ✓ |
| c4-code | 87.5 | 95.8 | [95.8, 95.8] | ≥77.5 | ✓ |
| c5-extract | 92.2 | 91.1 | [92.3, 89.8] | ≥82.2 | ✓ |
| c6-vision (crit) | 82.5 | 85.0 | [85.0, 85.0] | ≥77.5 | ✓ |
| c7-zhif | 73.3 | 85.0 | [86.7, 83.3] | ≥63.3 | ✓ |
| c7-agentic-if (crit) | 95.0 | 81.7 | [85.0, 80.0, 81.7] | ≥90.0 | ✗ |
| c8-judgment (crit) | 78.3 | 75.0 | [73.3, 76.7] | ≥73.3 | ✓ |
| c9-long-coding (crit) | 100.0 | 98.3 | [100.0, 96.5] | ≥95.0 | ✓ |
| c10-sre-ops | 73.3 | 88.3 | [86.7, 90.0] | ≥63.3 | ✓ |
| wall c3-tool | 39s | 46s | | ≤1.5× (59s) | ✓ |
| wall c6-vision | 18s | 17s | | ≤1.5× (27s) | ✓ |
| wall c7-agentic-if | 42s | 52s | | ≤1.5× (63s) | ✓ |
| perf decode | 32.8 | 51.2 | | ≥33 | ✓ |
| perf prefill | 2129 | 3159 | | ≥2000 | ✓ |
| perf six | 82.8 | 87.6 | | ≥75 | ✓ |
| perf kv | 1,492,180 | 3,455,574 | | ≥1.5e+06 | ✓ |
| errors | 0 | 0 | | | |

Δ own (shared categories) = 91.7 − 85.0 = +6.7

**Verdict: negative result (keep the incumbent): only c7-agentic-if failed.**

### Thinking settings (both models thinking on, max_tokens 16384)

These runs used the sampling values we believed to be the vendors' thinking settings (temperature 1.0 and top_p 0.95 for both models, plus top_k 20 and related penalties for the Qwen model), supplied through a sampling override that the published runner at the time did not offer. The values were not independently verified when this table was produced. When we later verified recipes against vendor sources, top_p 0.95 applied to every category turned out not to match one of the two vendors' guidance, which distinguishes agent/tool scenarios from other scenarios. Treat this table as a control-arm comparison. The 2026-10 runner now supports explicit, recorded sampling overrides.

| cat | incumbent | candidate | runs (candidate) | gate | ok |
|---|---|---|---|---|---|
| c1-kbqa | 91.7 | 88.3 | [90.0, 86.7] | ≥81.7 | ✓ |
| c2-longctx (crit) | 82.5 | 87.5 | [86.7, 93.3] | ≥77.5 | ✓ |
| c3-tool (crit) | 56.7 | 76.7 | [76.7, 76.7] | ≥51.7 | ✓ |
| c4-code | 79.2 | 95.8 | [95.8, 95.8] | ≥69.2 | ✓ |
| c5-extract | 89.4 | 84.2 | [84.6, 83.9] | ≥79.4 | ✓ |
| c6-vision (crit) | 86.2 | 87.5 | [87.5, 87.5] | ≥81.2 | ✓ |
| c7-zhif | 85.0 | 90.0 | [96.7, 90.0] | ≥75.0 | ✓ |
| c7-agentic-if (crit) | 90.0 | 91.7 | [90.0, 93.3, 88.3, 91.7, 91.7] | ≥85.0 | ✓ |
| c8-judgment (crit) | 81.7 | 98.3 | [100.0, 96.7] | ≥76.7 | ✓ |
| c9-long-coding (crit) | 82.3 | 100.0 | [100.0, 100.0] | ≥77.3 | ✓ |
| c10-sre-ops | 76.7 | 70.0 | [76.7, 70.0] | ≥66.7 | ✓ |
| wall c3-tool | 94s | 96s | | ≤1.5× (141s) | ✓ |
| wall c6-vision | 305s | 266s | | ≤1.5× (458s) | ✓ |
| wall c7-agentic-if | 107s | 88s | | ≤1.5× (160s) | ✓ |
| perf decode | 32.8 | 51.2 | | ≥33 | ✓ |
| perf prefill | 2129 | 3159 | | ≥2000 | ✓ |
| perf six | 82.8 | 87.6 | | ≥75 | ✓ |
| perf kv | 1,492,180 | 3,455,574 | | ≥1.5e+06 | ✓ |
| errors | 34 | 2 | | | |

Δ own (shared categories) = 87.9 − 84.1 = +3.8

**Verdict: candidate wins: 11/11, wall 3/3, perf 4/4, own-mean +3.8.**

Changing the adjudication baseline moves both sides' scores and gates together, so cross-baseline comparison is invalid. The verdict under non-thinking settings (keep the incumbent, because c7-agentic-if failed) and the verdict under thinking settings (candidate wins) are not contradictory — they are two different decisions, and the method is to run at the settings you would deploy with.

## Known inconsistencies in this run of the method

Left as they were adjudicated, and recorded here rather than rewritten:

1. The incumbent's 20-item C2 subset had spread 15 (85.0 / 100.0): by the rule above it should carry ⚠ and the lower run (85.0) should derive the gate; the first-rule-set adjudications used the median 92.5. With 85.0 the C2 gates become ≥75.0 (other) / ≥80.0 (critical) and every candidate still passes C2; the incumbent own-mean drops by about 0.9, which widens every candidate's margin without changing any verdict.
2. In the thinking-settings table the C2 runs column [86.7, 93.3] does not reproduce the adjudicated 87.5 (the lower run would be 86.7). The gate ≥77.5 passes with either value and the candidate own-mean moves by 0.1 (87.9 → 87.8); the verdict is unchanged.

## What the method caught

- Qwen3.8-Flash-Next (single node) won the score comparison (+4.3 own-mean) but failed the six-stream aggregate throughput gate (56.6 vs ≥60); the verdict was to keep the incumbent. Score alone would have switched models.
- Qwen3.8-Flash-Next (two-node) won the score comparison (+4.1) but failed the c7-agentic-if gate (80.0 vs ≥85.0); the verdict was to keep the incumbent.
- Muse Glimmer 30B failed five gates: c3-tool (53.3 vs ≥65.0), c9-long-coding (66.7 vs ≥94.3), c7-agentic-if (79.2 vs ≥85.0), decode throughput (27.1 vs ≥30), and the c7-zhif wall-clock ratio (92s vs the reference 16s, ×5.8 vs ≤3×). Its own-mean was only +1.2, a dead heat.
- The verdict flipped between settings: under non-thinking settings the candidate failed only c7-agentic-if and the incumbent was kept; under thinking settings the candidate passed every gate and won. The largest swing came from the setting (thinking on/off), not from the model — which is why the method runs at the settings you would deploy with.
