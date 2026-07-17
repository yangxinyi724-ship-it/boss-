"""Web 进程内 patchright 专用单线程执行器 — 避免 greenlet 跨线程切换。"""

from __future__ import annotations

import atexit
import concurrent.futures
import threading
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")

# patchright 同步 API 必须在固定线程内创建/使用/关闭；不可与 asyncio.to_thread 混用多线程。
_BROWSER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
	max_workers=1,
	thread_name_prefix="pet-boss-browser",
)
_BROWSER_THREAD_IDS: set[int] = set()


def is_browser_executor_thread() -> bool:
	"""当前线程是否为 patchright 专用浏览器线程。"""
	return threading.current_thread().ident in _BROWSER_THREAD_IDS


def run_browser_blocking(func: Callable[..., _T], /, *args, **kwargs) -> _T:
	"""在浏览器专用线程同步执行（供非 async 上下文使用）。"""
	if is_browser_executor_thread():
		return func(*args, **kwargs)
	future = submit_browser_task(func, *args, **kwargs)
	return future.result()


def submit_browser_task(func: Callable[..., _T], /, *args, **kwargs) -> concurrent.futures.Future[_T]:
	"""提交浏览器任务到专用线程（异步场景）。"""

	def _wrapper() -> _T:
		_BROWSER_THREAD_IDS.add(threading.current_thread().ident or 0)
		return func(*args, **kwargs)

	return _BROWSER_EXECUTOR.submit(_wrapper)


def shutdown_browser_executor() -> None:
	_BROWSER_EXECUTOR.shutdown(wait=False, cancel_futures=True)


atexit.register(shutdown_browser_executor)
