import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SmokeStep:
	name: str
	platform: str
	purpose: str
	preconditions: list[str]
	failure_classification: str
	command: list[str]


@dataclass(frozen=True)
class CommandResult:
	returncode: int
	stdout: str
	stderr: str


def build_default_steps(
	platform: str = "zhipin",
	*,
	query: str = "golang",
	security_id: str = "demo-security-id",
) -> list[SmokeStep]:
	del query, security_id
	platform_args = ["--platform", platform] if platform != "zhipin" else []
	return [
		SmokeStep(
			name="doctor",
			platform=platform,
			purpose="验证本地环境、自检和网络前提",
			preconditions=["command:boss"],
			failure_classification="env_error",
			command=["boss", *platform_args, "doctor"],
		),
		SmokeStep(
			name="status",
			platform=platform,
			purpose="验证本地登录态是否存在且可读取",
			preconditions=["command:boss"],
			failure_classification="env_error",
			command=["boss", *platform_args, "status"],
		),
	]


DEFAULT_STEPS = build_default_steps()


def parse_envelope(stdout: str) -> tuple[dict | None, str | None]:
	try:
		payload = json.loads(stdout.strip())
	except json.JSONDecodeError:
		return None, "stdout was not a JSON envelope"
	required = {"ok", "schema_version", "command", "data", "pagination", "error", "hints"}
	if not isinstance(payload, dict) or set(payload) != required:
		return None, "stdout JSON did not match the envelope shape"
	if payload.get("schema_version") != "1.0":
		return None, "stdout envelope schema_version was not 1.0"
	return payload, None


def env_preconditions_met(preconditions: list[str]) -> tuple[bool, str | None]:
	for item in preconditions:
		if item.startswith("env:"):
			var = item.split(":", 1)[1]
			if not os.environ.get(var):
				return False, f"missing env {var}"
		elif item.startswith("command:"):
			cmd = item.split(":", 1)[1]
			if subprocess.run(
				["where" if os.name == "nt" else "which", cmd],
				capture_output=True,
				text=True,
			).returncode != 0:
				return False, f"missing command {cmd}"
	return True, None


@dataclass
class SmokeRunner:
	steps: list[SmokeStep]
	cwd: Path = ROOT
	timeout: int = 120

	def run(self, run_command=None) -> list[dict]:
		run_command = run_command or subprocess.run
		results: list[dict] = []
		for step in self.steps:
			ok, reason = env_preconditions_met(step.preconditions)
			if not ok:
				results.append({
					"name": step.name,
					"status": "skipped",
					"reason": reason,
				})
				continue
			proc = run_command(
				step.command,
				cwd=self.cwd,
				capture_output=True,
				text=True,
				timeout=self.timeout,
				check=False,
			)
			if isinstance(proc, CommandResult):
				result = proc
			else:
				result = CommandResult(proc.returncode, proc.stdout, proc.stderr)
			payload, parse_err = parse_envelope(result.stdout)
			if parse_err:
				results.append({
					"name": step.name,
					"status": "failed",
					"classification": step.failure_classification,
					"reason": parse_err,
					"returncode": result.returncode,
					"stderr": result.stderr,
				})
				continue
			if result.returncode != 0 or not payload.get("ok"):
				results.append({
					"name": step.name,
					"status": "failed",
					"classification": step.failure_classification,
					"reason": "command returned error envelope",
					"returncode": result.returncode,
					"error": payload.get("error"),
				})
				continue
			results.append({"name": step.name, "status": "passed", "command": payload.get("command")})
		return results


def main() -> int:
	runner = SmokeRunner(steps=DEFAULT_STEPS)
	results = runner.run()
	print(json.dumps(results, ensure_ascii=False, indent=2))
	return 0 if all(r.get("status") in {"passed", "skipped"} for r in results) else 1


if __name__ == "__main__":
	raise SystemExit(main())
