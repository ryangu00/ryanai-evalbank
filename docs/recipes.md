# Model recipes

Since the 2026-10 update, `tools/run.py` resolves `recipes/<model>.json` before it creates a run directory. Only [the empty template](../recipes/template.json) is published. Copy it to the model's filename and replace the null placeholders with sourced values; the template deliberately cannot run. Model aliases containing a slash use a corresponding subdirectory under `recipes/`.

The three hard rules are: a vendor arm needs a recipe file; a `harness-uniform` control needs a non-empty `--reason`; and a recipe needs both `sampling.temperature` and `sampling.top_p`, plus an explicit `limitations` list (which may be empty). Per-field source labels qualify the resulting arm. This port does not implement hash-bound verification.

## Schema

| field | type | meaning |
|---|---|---|
| `sampling` | object | Required temperature and top_p, plus other request parameters such as top_k or penalties. Dedicated request fields such as model, messages, max_tokens and chat_template_kwargs cannot be placed here. |
| `chat_kwargs` | object | Values sent as `chat_template_kwargs`; defaults to an empty object in a vendor arm. |
| `max_tokens` | positive integer | Output budget including reasoning. If omitted, the harness default applies and its source must be treated as inferred. |
| `system` | string or null | Optional system text; the coding loop keeps its built-in instructions when null. |
| `preserve_reasoning` | boolean | Whether to echo non-empty reasoning_content across coding-loop turns. Omission means false and is inferred. |
| `limitations` | list | Required, even when empty. Record mismatches with vendor guidance, including pack-tool reasoning passthrough. |
| `sources` | list | First-hand evidence records: URL or file, quoted line, and the field or fields it supports. No researched model values or evidence documents are shipped here. |
| `field_sources` | object | Flat keys such as sampling.temperature, sampling.top_p, chat_kwargs.thinking, max_tokens and preserve_reasoning, each labelled official or inferred. Missing or unrecognised labels count as inferred. Every sampling key and every chat_kwargs key needs its own label. |

## Arm names and overrides

| source tier | recorded arm | interpretation |
|---|---|---|
| Every key field labelled official | `vendor` | A sourced recipe declaration; the runner has not independently verified the evidence. |
| At least one key field not official | `vendor-informed` | A recipe containing inferred or unsourced values. The fields appear in results.json and the report header. |
| No vendor recipe used | `harness-uniform` | A control arm, explicitly labelled with its required reason. |

`--sampling <json>` and `--chat-kwargs <json>` merge into their respective recipe objects. `--system <text>` and `--max-tokens N` replace those fields. Any supplied override, including an empty object or an unchanged value, adds the suffix `-overridden` to a vendor arm: `vendor-overridden` or `vendor-informed-overridden`. Overrides are recorded separately. A control remains `harness-uniform` and also records its overrides.

The resolved sampling, chat_template_kwargs, max_tokens, system, preserve_reasoning, recipe, recipe_arm, recipe_reason, recipe_non_official, recipe_overrides, limitations and timeout_scale are recorded in results.json. The report prints actual requested sampling. The runner exports the effective settings to the coding loop; selecting a control clears stale recipe sampling, chat kwargs, system and reasoning-preservation environment variables.

Harness defaults remain temperature 0.5 and top_p 0.95 with thinking on, temperature 0 with thinking off, and max_tokens 8000 (overridable through `EVALBANK_MAX_TOKENS`). These are reproducibility defaults, not vendor recommendations. Item budgets and pack wall-clock budgets scale by `max(1, max_tokens / 8000)`; a budget of 32768 has scale 4.096. The pack tool receives max_tokens only when a recipe or `--max-tokens` sets it explicitly; an unmodified control retains the pack tool's own output-budget default.

## First-hand sourcing

Copy each value from the vendor model card or generation configuration. Record the URL or file and the quoted line in `sources`, and label a field official only when that quote supports it. In recipe research in 2026-09, a substantial share of drafted values did not survive independent verification against vendor sources, including values that changed actual requests. Comparisons already run with unverified drafts had to be relabelled informed. A uniform recipe is a control, not a fair per-model recipe comparison.

Optional hardening would bind verification notes to hashes and check their model sections and field findings. That verification is not implemented here; source labels remain declarations.

## Reasoning and serving limits

Reasoning preservation handles only the `reasoning_content` field and only the long-horizon coding category. The pack tool decides what gets echoed in the three pack categories; document that limitation in recipes. Whether echoed reasoning reaches the model's rendered prompt depends on the serving engine and template. Other reasoning field names and an engine-side render check remain unverified and are outside this port.

## Offline checks

Run `python3 tools/test_run_gate.py`. The suite uses only unittest and other standard-library modules, fake HTTP responses and fake subprocesses. It exercises the recipe gate and source labels alongside authentication, truncation, concurrency, failure handling, grader-version recording, reasoning passthrough and saved-run comparison.
