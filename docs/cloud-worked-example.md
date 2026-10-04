# Cloud-only worked example: aggregation sensitivity

These scores illustrate a selection method, not a model ranking. All numbers were recomputed in 2026-10 from saved results and raw responses from 2026-09-21 and 2026-09-27; no new model runs were made. Questions, expected answers, hidden tests, hashes and run-directory names are not published. No adoption outcome is verified.

The three findings are that per-question errors can change an ordering, the aggregation function can change an ordering, and repeat runs of the same cloud model have a substantial noise floor. Re-run errored items before adjudicating, report pack and own scores separately, and show aggregation sensitivity beside the category gates.

## Conditions and corpus

Every arm used an OpenAI-compatible endpoint, thinking on (provider-default reasoning), a harness-uniform control recipe with requested temperature 0.5, top_p 0.95 and max_tokens 8000 including reasoning, `--tier public`, and `--parallel 4`. The public tier has no local-address restriction. The harness sent engine-specific chat_template_kwargs and a reasoning-effort value; the gateway drops the engine-specific field. Saved settings describe requests, not what providers applied. Whether providers honoured temperature, top_p and the output budget is not verified. These cloud arms did not use the later vendor-recipe gate.

On 2026-09-21 the review tier copied synthetic judgment (30 scenarios), agentic instruction following (30), tool use (15), and code fixes (12 hidden-test items) from a held-out bank. The first three are pack categories; code fixes are an own category. A pre-egress scan found one internal address in a hidden test, which was generalised.

The research tier used 81 pages from 38 already-published repositories. A local generator with thinking on produced questions, followed by deterministic lint and a privacy scan. KB QA, SRE-style, extraction and long-context each retained 30 items; the questions themselves are not published. This is open-book technical material from one author, and training-data contamination of the public pages is unknown.

Long-context sizes were three tiers of 10 items: 71-93 thousand, 212-230 thousand and 446-458 thousand characters. Provider-reported median prompt tokens per tier in the first run across five providers were 19.3-20.9 thousand, 56.6-61.0 thousand and 119.6-128.6 thousand. Earlier estimates of about 18K / 52K / 110K tokens were low.

One generation per research category on 2026-09-21 yielded the following lint counts, before the 30-item cap:

| category | candidates | rejected | passed | rejection detail |
|---|---|---|---|---|
| KB QA | 174 | 3 | 171 | all evidence not verbatim |
| SRE-style | 60 | 15 | 45 | deterministic lint failures |
| extraction | 60 | 17 | 43 | field evidence failure |

The final research-item privacy scan reported 9 hits across two categories, all one token that also names a public inference-server option. The scan aborted on any hit; manual review accepted them. The method lesson is to use an explicit allowlist with a recorded justification for each token. Such a scanner is not implemented in this update.

## One aggregation throughout

A category cell is the median of its runs, or the lowest run when spread exceeds 5 points (`*`). Pack mean is the mean of the three pack cells; own mean uses only own-category cells. Combined macros reproduce historical calculations only as an aggregation sensitivity check; they are not the method's selection score. The alternative is the median of per-run macros, with equal category weights.

The flat 5-point threshold remains in code. With 12 code items, one item is 8.3 points. The code category was flagged in 5 of 11 review arms below: four had spreads of 8.3-12.5 points (one to one and a half items), and the fifth had request timeouts. Read flags with item counts and differing-item counts.

## Round 1 review tier, 2026-09-21

Five cloud arms, 3 runs each, through a local OpenAI-compatible gateway to a public multi-provider model API. Gates are incumbent minus 5 for judgment and agentic IF, and minus 10 for tool use and code fixes. Conditions and requested sampling are as stated above.

| arm | judgment | agentic IF | tool use | code fixes | pack mean | own (code) | macro of 4 (sensitivity) | median of per-run macros (sensitivity) |
|---|---|---|---|---|---|---|---|---|
| qwen3.8-max (incumbent) | 80.0 | 81.7* | 50.0* | 79.2* | 70.6 | 79.2 | 72.7 | 76.5 |
| mimo-v2.6-pro | 80.0 | 86.7 | 50.0 | 87.5* | 72.2 | 87.5 | 76.0 | 78.1 |
| kimi-k2.6 | 93.3 | 85.0* | 60.0* | 87.5* | 79.4 | 87.5 | 81.5 | 86.5 |
| glm-5.3 | 90.0* | 88.3 | 76.7* | 95.8 | 85.0 | 95.8 | 87.7 | 91.0 |
| minimax-m3 | 96.7 | 83.3* | 86.7 | 95.8 | 88.9 | 95.8 | 90.6 | 91.9 |

All four candidates pass every gate. The ordering is unchanged under the two aggregations. The best candidate exceeds the incumbent by 17.9 points using unrounded adjudicated macros. This is a worked gate result, not evidence of adoption.

Per-question errors, separately from scores:

| scope | errored requests | exclusion sensitivity |
|---|---|---|
| code, each of the five arms | 0 | unchanged |
| code, total | 0 of 180 (12 items x 3 runs x 5 arms) | unchanged |
| pack categories | unknown | unavailable; saved statuses cannot separate infrastructure errors from failures |

Five own responses were truncated, all already scored 0. No saved pack scenario had zero turns, which does not establish the absence of infrastructure errors.

## Round 1 research tier, 2026-09-21

Five cloud arms, 2 runs each, through the same gateway. All four categories are own categories; extraction allows fractional credit. Gates are incumbent minus 5 for KB QA and long-context, and minus 10 for extraction and SRE-style. Conditions and requested sampling are as stated above.

| arm | KB QA | long-context | extraction | SRE-style | own mean | median of per-run macros (sensitivity) | gate result |
|---|---|---|---|---|---|---|---|
| mimo-v2.5-pro (incumbent) | 80.0* | 75.0 | 94.0 | 73.3* | 80.6 | 83.1 | baseline |
| glm-5.3 | 86.7* | 63.3* | 96.6 | 66.7* | 78.3 | 80.8 | fails long-context |
| deepseek-v4-pro | 85.0 | 70.0* | 96.6 | 91.7 | 85.8 | 87.5 | passes |
| mimo-v2.6-pro | 93.3* | 91.7 | 97.1 | 61.7 | 86.0 | 86.8 | fails SRE-style |
| kimi-k2.6 | 95.0 | 86.7* | 95.8 | 96.7 | 93.5 | 94.8 | passes |

Two of four candidates fail one gate each despite their means. The best candidate exceeds the incumbent by 12.9 points using unrounded adjudicated macros. The best and two worst arms retain their positions under the alternative aggregation; the two middle arms swap. Differences of a few tenths carry no information here.

Per-question errors, separately from scores:

| scope | errored requests | recorded run score | errored item excluded (sensitivity) |
|---|---|---|---|
| one kimi-k2.6 extraction run | 1 HTTP 500 | 94.5 | 97.8 |
| research tier, total | 1 of 1,200 | as above | no effect on any gate verdict |
| other research responses | 0 | unchanged | unchanged |

Four own responses were truncated, all already scored 0. The research build used a copy of the published runner patched to send authentication before these runs; that was observed on 2026-09-21.

## Round 2 review tier, 2026-09-27: cloud arms only

Six cloud arms, 3 runs each, the same four categories and bank content as round 1. Gateway arms were launched first; the four direct arms were then launched concurrently from one client to the public multi-provider API. Conditions and requested sampling are as stated above. Grader code differs from round 1. Recorded grader environment: pack tool 2.6.1 development build, 72 commits past the tag; pytest 9.1.1; Python 3.14. Round-1 grader environment was not recorded and is unknown.

| arm | judgment | agentic IF | tool use | code fixes | pack mean | own (code) | adjudicated macro (sensitivity) | per-run macros and median (sensitivity) |
|---|---|---|---|---|---|---|---|---|
| kimi-k2.6, direct | 90.0* | 91.7 | 76.7* | 66.7* | 86.1 | 66.7 | 81.2 | 90.2 / 89.4 / 82.9; median 89.4 |
| minimax-m3, direct | 76.7* | 83.3 | 76.7* | 95.8 | 78.9 | 95.8 | 83.1 | 82.3 / 89.4 / 87.3; median 87.3 |
| minimax-m3, gateway | 86.7* | 75.0* | 80.0* | 95.8 | 80.6 | 95.8 | 84.4 | 92.9 / 89.4 / 88.5; median 89.4 |
| glm-5.3, direct | 83.3* | 93.3 | 76.7* | 87.5 | 84.4 | 87.5 | 85.2 | 86.0 / 89.4 / 85.2; median 86.0 |
| deepseek-v4-pro, direct | 83.3 | 90.0 | 60.0* | 95.8 | 77.8 | 95.8 | 82.3 | 84.4 / 83.1 / 81.5; median 83.1 |
| deepseek-v4-pro, gateway | 83.3 | 91.7 | 66.7* | 87.5* | 80.6 | 87.5 | 82.3 | 84.2 / 81.9 / 86.5; median 84.2 |

Per-question errors, separately from scores:

| scope | errored requests | recorded code run score | errored items excluded (sensitivity) |
|---|---|---|---|
| kimi-k2.6 direct, code run 3 | 4 client-side timeouts of 12 | 66.7 | 100.0 over the 8 completed items |
| round-2 own responses, total | 4 of 216 | affected run as above | re-run errors before adjudicating |
| all other round-2 own responses | 0 | unchanged | unchanged |
| pack categories | unknown | not separable | unavailable |

The affected arm's other two code runs both scored 95.8. Excluding the four timed-out items changes its adjudicated macro from 81.2 (lowest of six arms) to 88.5 (highest of six arms); its median of per-run macros changes from 89.4 to 90.2. This sensitivity row diagnoses infrastructure effects, not a replacement verdict:

| kimi-k2.6 direct sensitivity | adjudicated macro | median of per-run macros |
|---|---|---|
| timeouts counted as 0 | 81.2 | 89.4 |
| four timed-out items excluded | 88.5 | 90.2 |

## Three method lessons

1. **Separate errors from model scores.** Four unanswered requests were enough to reverse an apparent ordering in round 2. List per-question errors separately, show exclusion sensitivity, and re-run errored items before adjudicating. A failed whole category is not the same as an errored item.
2. **Keep one aggregation and expose sensitivity.** Earlier tables mixed mean of adjudicated values, mean of category medians and median of per-run macros. The tables here consistently use adjudicated category values, with pack and own means separate. Round 1 largely preserves the ordering under the alternative aggregation; round 2 changes substantially.
3. **Measure repeat-run noise.** Across 9 runs in three arms, minimax-m3 judgment ranged from 76.7 to 100.0. Its adjudicated macro was 90.6 on 2026-09-21 and 84.4 / 83.1 on 2026-09-27. Date, route, concurrency and grader version all differ, so no single cause can be assigned. One run on a 30-scenario category is insufficient to establish a stable result.

`tools/compare_select.py` reads result directories and raw own-item files offline. Use `python3 tools/compare_select.py <baseline-directory> <candidate-directory>` for review gates, or add `--critical c1-kbqa,c2-longctx` for research gates. It reports pack and own means separately, median-of-per-run-macro sensitivity, numerical category gates, per-question error counts and scores with errored own items excluded. It does not print question text or hash values. Pack-error sensitivity remains unavailable.

## Open and not verified

- Continued use of the selected models and practical effects of selection are not verified; no adoption outcome is claimed.
- Response aliases matched requested aliases in all responses with a body: 180 of 180 review responses in round 1, 1,199 of 1,200 research responses, and 212 of 216 round-2 responses. This does not identify the upstream provider, quantisation or applied reasoning effort. Pack logs carry only the requested name.
- Non-zero reasoning tokens were observed in 174 of 180 round-1 review responses, 1,172 of 1,200 research responses and 192 of 216 round-2 responses, consistent with provider-default reasoning. Applied settings remain unknown.
- Across the three tables, 12 of 1,596 own-category responses ended with finish_reason=length; all already scored 0 because their answer fields were empty. The truncation fix would not change those recorded numbers.
- Provider compliance with requested temperature, top_p and the 8,000-token budget is not verified. Both rounds are harness-uniform controls, not vendor-recipe comparisons.
- Public-document training contamination is unknown. Infrastructure errors inside pack categories cannot be separated from real failures in saved files.
- Reasoning passthrough supports only reasoning_content in long-horizon coding; other fields and engine-side rendering are not covered.
- The small-sample spread limitation is documented; the code still uses a flat 5-point threshold.
- Prices recorded on 2026-09-21 and in notes on 2026-09-27 were not re-verified; no price comparison is made here.
- Differences between direct and gateway routes in round 2 cannot be attributed to route, time, concurrency or grader version.
