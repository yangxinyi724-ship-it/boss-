from pet_boss.web.browser_executor import (
	is_browser_executor_thread,
	run_browser_blocking,
	submit_browser_task,
)


def test_run_browser_blocking_on_browser_thread_runs_inline():
	seen: list[str] = []

	def outer() -> None:
		assert is_browser_executor_thread()

		def inner() -> None:
			assert is_browser_executor_thread()
			seen.append("ok")

		run_browser_blocking(inner)

	submit_browser_task(outer).result()
	assert seen == ["ok"]


def test_nested_run_browser_blocking_does_not_deadlock():
	counter = {"n": 0}

	def work() -> int:
		def nested() -> int:
			counter["n"] += 1
			return counter["n"]

		return run_browser_blocking(nested)

	assert submit_browser_task(work).result() == 1
	assert counter["n"] == 1
