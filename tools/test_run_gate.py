#!/usr/bin/env python3
"""Offline regression checks. Run: python3 tools/test_run_gate.py"""
import argparse, contextlib, copy, io, json, os, pathlib, subprocess, sys, tempfile, unittest, warnings
from unittest.mock import patch

import agent_loop
import compare_select
import gen_items
import run

BASE = "https:///v1"  # Deliberately no host; all transports are mocked.
REPO = pathlib.Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, content="42", finish="stop", **extra):
        self.body = json.dumps({"choices": [{"message": {"content": content, **extra}, "finish_reason": finish}], "usage": {"completion_tokens": 3}}).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *args): return False


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(warnings.catch_warnings()); warnings.simplefilter("ignore", ResourceWarning)
        self.root = pathlib.Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix=".test-", dir=REPO)))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(tempfile, "tempdir", str(self.root)))
        self.stack.enter_context(patch.object(run, "ROOT", str(self.root)))
        self.stack.enter_context(patch.object(run, "CONFIG", {}))
        self.stack.enter_context(patch.object(run, "MAX_TOKENS", 8000))
        self.stack.enter_context(patch.object(run, "TIER", "public"))
        self.stack.enter_context(patch.object(sys, "path", list(sys.path)))
        self.network = self.stack.enter_context(patch.object(run.urllib.request, "urlopen", side_effect=AssertionError("unexpected request")))
        self.process = self.stack.enter_context(patch.object(run.subprocess, "run", side_effect=AssertionError("unexpected subprocess")))
        self.raw = self.root / "raw"; self.raw.mkdir()

    def config(self, **overrides):
        args = dict(model="model", recipe_arm="vendor", reason="", thinking="on", sampling=None, chat_kwargs=None, max_tokens=None, system=None)
        args.update(overrides)
        run.CONFIG = run.resolve_config(argparse.Namespace(**args))
        return run.CONFIG

    def recipe(self):
        recipe = {"sampling": {"temperature": 0.7, "top_p": 0.8, "top_k": 7}, "chat_kwargs": {"thinking": True},
                  "max_tokens": 12000, "system": "fixture", "preserve_reasoning": True, "limitations": ["pack passthrough unverified"], "sources": []}
        recipe["field_sources"] = {k: "official" for k in [*(f"sampling.{k}" for k in recipe["sampling"]), "chat_kwargs.thinking", "max_tokens", "preserve_reasoning"]}
        self.write_recipe(recipe)
        return recipe

    def write_recipe(self, recipe):
        directory = self.root / "recipes"; directory.mkdir(exist_ok=True)
        (directory / "model.json").write_text(json.dumps(recipe))

    def fake_pack(self, rc=0, timeout=False):
        def fake(cmd, **kwargs):
            if timeout: raise subprocess.TimeoutExpired(cmd, 1)
            pathlib.Path(cmd[cmd.index("--json-file") + 1]).write_text(json.dumps({"scores": {"total_points": 20, "max_points": 30, "scenario_results": [{}] * 15}}))
            return subprocess.CompletedProcess(cmd, rc, "", "fixture failure")
        self.process.side_effect = fake

    def pack(self, **kwargs):
        return run.run_pack("c3-tool", BASE, "model", True, str(self.raw), 1, "public", **kwargs)

    def command_value(self, key):
        cmd = self.process.call_args.args[0]
        return cmd[cmd.index(key) + 1]

    def main(self, *extra):
        (self.root / "tools").mkdir(exist_ok=True)
        (self.root / "tools" / "agent_loop.py").write_text((REPO / "tools" / "agent_loop.py").read_text())
        argv = ["run.py", "--base-url", BASE, "--model", "model", "--label", "fixture", "--tier", "public", "--cats", "c3-tool", "--runs", "2", *extra]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            run.main()

    def result(self):
        path = next((self.root / "runs").glob("*/results.json"))
        return json.loads(path.read_text()), path.with_name("report.md").read_text()

    def agent(self, reasoning="R"):
        task = self.root / "task"; task.mkdir(exist_ok=True)
        (task / "seed").mkdir(exist_ok=True); (task / "hidden").mkdir(exist_ok=True)
        (task / "task.md").write_text("fixture")
        bodies = []; requests = []
        def fake(req, timeout):
            requests.append(req); bodies.append(json.loads(req.data))
            name = "list_files" if len(bodies) == 1 else "done"
            return Response("", "tool_calls", tool_calls=[{"id": "call", "type": "function", "function": {"name": name, "arguments": "{}"}}], reasoning_content=reasoning if len(bodies) == 1 else "")
        self.network.side_effect = fake
        with patch.object(agent_loop, "run_pytest", return_value=(1, 1, "fixture")):
            result = agent_loop.run_task(str(task), BASE, "model", True)
        self.assertIsNone(result["error"]); self.assertEqual(len(bodies), 2)
        return bodies, requests

    def test_a1_chat_auth_optional(self):
        self.network.side_effect = lambda *a, **k: Response()
        for key in ("k-test", ""):
            if key: os.environ["EVALBANK_API_KEY"] = key
            else: os.environ.pop("EVALBANK_API_KEY", None)
            run.chat(BASE, "model", [], True)
            headers = {k.lower(): v for k, v in self.network.call_args.args[0].header_items()}
            self.assertEqual(headers.get("authorization"), "Bearer k-test" if key else None)

    def test_a2_agent_auth_every_turn(self):
        os.environ["EVALBANK_API_KEY"] = "k-test"
        _, requests = self.agent()
        self.assertTrue(all(r.get_header("Authorization") == "Bearer k-test" for r in requests))
        del os.environ["EVALBANK_API_KEY"]
        _, requests = self.agent()
        self.assertTrue(all(r.get_header("Authorization") is None for r in requests))

    def test_a3_pack_auth_optional(self):
        self.fake_pack(); os.environ["EVALBANK_API_KEY"] = "k-test"
        self.pack(); self.assertEqual(self.command_value("--api-key"), "k-test")
        del os.environ["EVALBANK_API_KEY"]
        self.pack(); self.assertNotIn("--api-key", self.process.call_args.args[0])

    def test_b_truncated_credit_revoked(self):
        item = {"id": "fixture", "cat": "c1-kbqa", "prompt": "fixture", "expected": {"type": "contains", "values": ["42"]}}
        for finish, score in (("length", 0.0), ("stop", 1.0)):
            with patch.object(run, "chat", return_value=("42", "{}", 1.0, finish)):
                result = run.run_item(item, BASE, "model", True, "")
            self.assertEqual(result["score"], score)
            if finish == "length":
                self.assertEqual(result["detail"]["truncated_credit_revoked"], 1.0)
                self.assertIn("grader_detail", result["detail"])

    def test_c1_pack_parallel(self):
        self.fake_pack()
        self.pack(parallel=2); self.assertEqual(self.command_value("--parallel"), "2")
        self.pack(); self.assertEqual(self.command_value("--parallel"), "4")

    def test_c2_pack_nonzero_rejects_valid_json(self):
        self.fake_pack(rc=2)
        score, n, message = self.pack()
        self.assertIsNone(score); self.assertEqual(n, 0); self.assertIn("rc=2", message); self.assertIn("fixture failure", message)

    def test_c3_pack_timeout_is_failure(self):
        self.fake_pack(timeout=True)
        score, n, message = self.pack()
        self.assertIsNone(score); self.assertEqual(n, 0); self.assertIn("timeout", message)

    def test_c4_main_parallel_failure_writes_artifacts(self):
        with patch.object(run, "run_pack", return_value=(None, 0, "fixture")) as pack, patch.object(run, "grader_env", return_value={}):
            with self.assertRaises(SystemExit) as caught:
                self.main("--parallel", "2", "--recipe-arm", "harness-uniform", "--reason", "fixture")
            self.assertNotEqual(caught.exception.code, 0)
            self.assertTrue(all(c.kwargs["parallel"] == 2 for c in pack.call_args_list))
        result, report = self.result()
        self.assertIn("run-failed", result["rows"][0]["flag"]); self.assertIn("run-failed", report)

    def test_d_grader_environment(self):
        def fake(cmd, **kwargs):
            if cmd[0] == "tool-eval-bench": raise FileNotFoundError()
            return subprocess.CompletedProcess(cmd, 0, "pytest 9.9\n", "")
        self.process.side_effect = fake
        versions = run.grader_env()
        self.assertEqual(set(versions), {"tool_eval_bench", "pytest", "python"})
        self.assertEqual(versions["tool_eval_bench"], "?(FileNotFoundError)")
        self.assertEqual(versions["pytest"], "pytest 9.9")
        with patch.object(run, "run_pack", return_value=(80, 15, "")):
            self.main("--recipe-arm", "harness-uniform", "--reason", "fixture")
        self.assertEqual(self.result()[0]["grader_env"], versions)

    def test_e1_missing_recipe_before_run_directory(self):
        with self.assertRaisesRegex(SystemExit, "recipe"): self.main()
        self.assertFalse((self.root / "runs").exists())

    def test_e2_uniform_requires_reason(self):
        for reason in ("", "  "):
            with self.assertRaisesRegex(SystemExit, "reason"): self.config(recipe_arm="harness-uniform", reason=reason)

    def test_e3_recipe_requires_sampling_and_limitations(self):
        recipe = self.recipe()
        for field in ("temperature", "top_p", "limitations"):
            value = copy.deepcopy(recipe)
            del (value if field == "limitations" else value["sampling"])[field]
            self.write_recipe(value)
            with self.assertRaises(SystemExit): self.config()
        recipe["limitations"] = "not a list"; self.write_recipe(recipe)
        with self.assertRaises(SystemExit): self.config()

    def test_e4_recipe_changes_chat_and_agent_body(self):
        self.recipe(); self.config()
        self.network.side_effect = lambda *a, **k: Response()
        run.chat(BASE, "model", [], True)
        chat_body = json.loads(self.network.call_args.args[0].data)
        bodies, _ = self.agent()
        for body in (chat_body, *bodies):
            self.assertEqual(body["top_k"], 7); self.assertEqual(body["max_tokens"], 12000)
            self.assertEqual(body["temperature"], 0.7); self.assertEqual(body["top_p"], 0.8)
            self.assertEqual(body["chat_template_kwargs"], {"thinking": True})
            self.assertEqual(body["messages"][0], {"role": "system", "content": "fixture"})

    def test_e5_overrides_label_and_record(self):
        self.recipe()
        for field, value in (("sampling", '{"temperature": 0.2}'), ("chat_kwargs", '{}'), ("system", ""), ("max_tokens", 9000)):
            config = self.config(**{field: value})
            self.assertEqual(config["recipe_arm"], "vendor-overridden")
            self.assertIn(field, config["recipe_overrides"])

    def test_e6_nonofficial_fields_and_combined_arm(self):
        recipe = self.recipe(); recipe["field_sources"].pop("sampling.top_k"); self.write_recipe(recipe)
        config = self.config()
        self.assertEqual(config["recipe_arm"], "vendor-informed")
        self.assertEqual(config["recipe_non_official"], ["sampling.top_k"])
        self.assertEqual(self.config(max_tokens=16000)["recipe_arm"], "vendor-informed-overridden")
        with patch.object(run, "run_pack", return_value=(80, 15, "")), patch.object(run, "grader_env", return_value={}):
            self.main()
        result, report = self.result()
        self.assertEqual(result["recipe_non_official"], ["sampling.top_k"])
        self.assertIn('Non-official fields: ["sampling.top_k"]', report)

    def test_recipe_omitted_fields_are_inferred(self):
        recipe = self.recipe()
        del recipe["max_tokens"]; del recipe["preserve_reasoning"]
        self.write_recipe(recipe)
        config = self.config()
        self.assertEqual(config["recipe_arm"], "vendor-informed")
        self.assertEqual(config["recipe_non_official"], ["max_tokens", "preserve_reasoning"])

    def test_e7_uniform_clears_stale_recipe_environment(self):
        self.recipe(); self.config()
        config = self.config(recipe_arm="harness-uniform", reason="fixture")
        for key in ("EVALBANK_SAMPLING", "EVALBANK_CHAT_KWARGS", "EVALBANK_SYSTEM", "EVALBANK_PRESERVE_REASONING"):
            self.assertNotIn(key, os.environ)
        self.assertIsNone(config["recipe"])
        bodies, _ = self.agent()
        self.assertEqual(bodies[0]["temperature"], 0.5); self.assertNotIn("top_k", bodies[0])

    def test_e8_timeout_scaling_and_explicit_pack_budget(self):
        self.config(recipe_arm="harness-uniform", reason="fixture", max_tokens=32768)
        self.network.side_effect = lambda *a, **k: Response()
        run.chat(BASE, "model", [], True, timeout=100)
        self.assertAlmostEqual(self.network.call_args.kwargs["timeout"], 409.6)
        self.fake_pack(); self.pack()
        self.assertEqual(json.loads(self.command_value("--backend-kwargs"))["max_tokens"], 32768)
        self.assertAlmostEqual(self.process.call_args.kwargs["timeout"], 3600 * 4.096)
        self.config(recipe_arm="harness-uniform", reason="fixture"); self.pack()
        self.assertNotIn("max_tokens", json.loads(self.command_value("--backend-kwargs")))
        self.recipe(); self.config(); self.pack()
        kwargs = json.loads(self.command_value("--backend-kwargs"))
        self.assertEqual(kwargs["max_tokens"], 12000); self.assertEqual(kwargs["top_k"], 7)

    def test_e8_agent_timeout_scales_once(self):
        self.config(recipe_arm="harness-uniform", reason="fixture", max_tokens=32768)
        result = dict(score=0, hidden_passed=0, hidden_total=1, turns=0, tool_calls=0, finished=False, tail="", secs=0, usage={}, error=None, raw_http_bodies=[])
        with patch.object(agent_loop, "run_task", return_value=result) as task:
            run.run_item({"id": "fixture", "cat": "c9-long-coding", "timeout": 100, "expected": {"type": "agent", "task_dir": "fixture"}}, BASE, "model", True, "")
        self.assertAlmostEqual(task.call_args.kwargs["timeout"], 409.6)

    def test_e9_results_and_report_config(self):
        self.recipe()
        with patch.object(run, "run_pack", return_value=(80, 15, "")), patch.object(run, "grader_env", return_value={}):
            self.main("--max-tokens", "16000", "--reason", "fixture")
        result, report = self.result()
        for key in ("recipe_arm", "recipe_reason", "recipe", "recipe_overrides", "limitations", "sampling", "chat_template_kwargs", "system", "preserve_reasoning", "timeout_scale"):
            self.assertIn(key, result)
        self.assertEqual(result["recipe_arm"], "vendor-overridden"); self.assertEqual(result["recipe_overrides"], {"max_tokens": 16000})
        self.assertIn('"temperature": 0.7', report); self.assertNotIn("on t=0.5", report)

    def test_e9_control_report_label(self):
        with patch.object(run, "run_pack", return_value=(80, 15, "")), patch.object(run, "grader_env", return_value={}):
            self.main("--recipe-arm", "harness-uniform", "--reason", "fixture")
        result, report = self.result()
        self.assertEqual(result["recipe_reason"], "fixture"); self.assertIn("(control arm)", report)

    def test_f_reasoning_passthrough(self):
        for flag, reasoning in (("1", "R"), ("", "R"), ("1", "")):
            os.environ["EVALBANK_PRESERVE_REASONING"] = flag
            bodies, _ = self.agent(reasoning)
            previous = next(m for m in bodies[1]["messages"] if m["role"] == "assistant")
            if flag and reasoning: self.assertEqual(previous["reasoning_content"], "R")
            else: self.assertNotIn("reasoning_content", previous)

    def test_recipe_template_is_not_runnable(self):
        self.write_recipe(json.loads((REPO / "recipes" / "template.json").read_text()))
        with self.assertRaises(SystemExit): self.config()

    def fake_arm(self, name, error=False):
        path = self.root / name; (path / "raw").mkdir(parents=True)
        rows = [{"cat": "c3-tool", "kind": "pack(0/1/2)", "runs": [80, 80]}, {"cat": "c4-code", "kind": "own(0/1)", "runs": [50 if error else 100, 100]}]
        (path / "results.json").write_text(json.dumps({"model": name, "rows": rows}))
        for k in (1, 2):
            records = [{"score": 1}, {"score": 0, "error": "timeout"} if error and k == 1 else {"score": 1}]
            (path / "raw" / f"c4-code-run{k}.jsonl").write_text("\n".join(json.dumps(r) for r in records))
        return compare_select.read_arm(path)

    def test_t1_separate_pack_and_own_means(self):
        arms = [self.fake_arm("baseline"), self.fake_arm("candidate")]
        report = compare_select.render(arms)
        self.assertIn("| pack mean | own mean |", report)
        self.assertIn("recorded scores | 80.0 | 100.0 |", report)

    def test_t2_per_item_errors_and_exclusion_sensitivity(self):
        arm = self.fake_arm("candidate", error=True)
        row = arm["rows"]["c4-code"]
        self.assertEqual(row["item_errors"], [1, 0]); self.assertEqual(row["runs_without_errors"], [100, 100])
        report = compare_select.render([arm])
        self.assertIn("recorded scores | 80.0 | 50.0 |", report)
        self.assertIn("errored own items excluded | 80.0 | 100.0 |", report)
        self.assertIn("| c4-code | 1, 0 | 100.0, 100.0 | 100.0 |", report)
        self.assertIn("Re-run errored items", report)

    def test_t3_cell_and_gate_share_adjudication(self):
        baseline = {"kind": "own", "runs": [100, 100]}
        row = {"kind": "own", "runs": [80, 100]}
        self.assertFalse(compare_select.category_cell(row, baseline, 10)["pass"])
        with patch.object(compare_select, "adjudicate", side_effect=lambda values: max(values)):
            cell = compare_select.category_cell(row, baseline, 10)
            self.assertEqual(cell["score"], 100); self.assertEqual(cell["gate"], 90); self.assertTrue(cell["pass"])

    def test_comparison_incomplete_run_is_unknown(self):
        self.assertIsNone(compare_select.adjudicate([100, None]))
        self.assertIsNone(compare_select.macro_median([{"kind": "own", "runs": [100, None]}]))

    def test_comparison_missing_raw_and_all_errors_are_unknown(self):
        self.fake_arm("candidate")
        path = self.root / "candidate"
        (path / "raw" / "c4-code-run1.jsonl").unlink()
        (path / "raw" / "c4-code-run2.jsonl").write_text(json.dumps({"score": 0, "error": "timeout"}))
        row = compare_select.read_arm(path)["rows"]["c4-code"]
        self.assertEqual(row["item_errors"], [None, 1])
        self.assertEqual(row["runs_without_errors"], [None, None])

    def test_comparison_cli_omits_private_record_fields(self):
        self.fake_arm("baseline"); self.fake_arm("candidate", error=True)
        out = io.StringIO()
        with patch.object(sys, "argv", ["compare_select.py", str(self.root / "baseline"), str(self.root / "candidate")]), contextlib.redirect_stdout(out):
            compare_select.main()
        self.assertIn("| pack mean | own mean |", out.getvalue())
        self.assertNotIn(str(self.root), out.getvalue())

    def test_private_guards_require_explicit_host_allowlist(self):
        for module, name in ((run, "ALLOW_HOSTS"), (gen_items, "LOCAL_HOSTS")):
            with patch.object(module, name, set()), patch.object(module.socket, "getaddrinfo", side_effect=AssertionError("unexpected lookup")):
                with self.assertRaises(SystemExit): module.assert_local(BASE)


if __name__ == "__main__":
    unittest.main()
