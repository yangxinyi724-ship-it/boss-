import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_p0.py"


def _load_smoke_module():
	spec = importlib.util.spec_from_file_location("smoke_p0", SMOKE_SCRIPT)
	assert spec is not None and spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_smoke_script_exists():
	assert SMOKE_SCRIPT.exists()


def test_smoke_script_defines_required_step_names():
	module = _load_smoke_module()
	step_names = [step.name for step in module.DEFAULT_STEPS]
	assert step_names == ["doctor", "status"]


def test_smoke_script_step_metadata_is_complete():
	module = _load_smoke_module()
	for step in module.DEFAULT_STEPS:
		assert step.platform
		assert step.purpose
		assert step.preconditions
		assert step.failure_classification


def test_smoke_runner_skips_missing_env():
	module = _load_smoke_module()

	runner = module.SmokeRunner(
		steps=[
			module.SmokeStep(
				name="missing",
				platform="zhipin",
				purpose="skip",
				preconditions=["env:BOSS_AGENT_FAKE_TOKEN"],
				failure_classification="env_error",
				command=["echo", "skip"],
			),
		],
	)

	results = runner.run(run_command=lambda *a, **k: None)
	assert results[0]["status"] == "skipped"


def test_smoke_runner_marks_non_json_stdout_as_failed():
	module = _load_smoke_module()

	def fake_run(command, cwd, capture_output, text, timeout, check):
		return module.CommandResult(returncode=0, stdout="not json", stderr="")

	runner = module.SmokeRunner(
		steps=[
			module.SmokeStep(
				name="schema",
				platform="zhipin",
				purpose="contract",
				preconditions=["command:boss"],
				failure_classification="command_error",
				command=["boss", "schema"],
			),
		],
	)

	results = runner.run(run_command=fake_run)
	assert results[0]["status"] == "failed"
	assert "stdout was not a JSON envelope" in results[0]["reason"]


def test_smoke_runner_passes_valid_envelope():
	module = _load_smoke_module()

	def fake_run(command, cwd, capture_output, text, timeout, check):
		return module.CommandResult(
			returncode=0,
			stdout='{"ok": true, "schema_version": "1.0", "command": "doctor", "data": {}, "pagination": null, "error": null, "hints": null}',
			stderr="",
		)

	runner = module.SmokeRunner(
		steps=[
			module.SmokeStep(
				name="doctor",
				platform="zhipin",
				purpose="pass",
				preconditions=["command:boss"],
				failure_classification="env_error",
				command=["boss", "doctor"],
			),
		],
	)

	results = runner.run(run_command=fake_run)
	assert results[0]["status"] == "passed"
	assert results[0]["command"] == "doctor"
