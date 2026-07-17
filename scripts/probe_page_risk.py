"""连续请求 page=1..N，记录 BOSS 返回 code（排查深分页风控）。"""
from __future__ import annotations

import os
import sys
import time

from pathlib import Path

from pet_boss.api.client import AccountRiskError, BossClient
from pet_boss.auth.manager import AuthManager
from pet_boss.output import Logger


def main() -> int:
	query = sys.argv[1] if len(sys.argv) > 1 else "AI应用开发"
	city = sys.argv[2] if len(sys.argv) > 2 else "广州"
	max_page = int(sys.argv[3]) if len(sys.argv) > 3 else 6
	pause = float(os.environ.get("BOSS_PROBE_PAUSE", "2.0"))

	os.environ.setdefault("BOSS_HTTP_TRACE", "0")

	auth = AuthManager(Path.home() / ".boss-agent", logger=Logger(level="info"), platform="zhipin")
	auth.ensure_session(try_browser=True)
	client = BossClient(auth, delay=(0.5, 2.0))

	print(f"连续搜岗探测: query={query!r} city={city!r} page=1..{max_page} pause={pause}s\n", flush=True)

	try:
		for page in range(1, max_page + 1):
			try:
				raw = client.search_jobs(query, city=city, page=page)
				code = raw.get("code")
				msg = raw.get("message", "")
				jobs = len((raw.get("zpData") or {}).get("jobList") or [])
				has_more = (raw.get("zpData") or {}).get("hasMore")
				status = "OK" if code == 0 else f"FAIL code={code}"
				print(
					f"  page={page:2d}  {status}  jobs={jobs:2d}  hasMore={has_more}  message={msg!r}",
					flush=True,
				)
				if code != 0:
					print(f"\n>>> 第 {page} 页首次非 0 返回，停止探测", flush=True)
					return 1
			except AccountRiskError as exc:
				print(f"  page={page:2d}  RISK  message={exc!s}", flush=True)
				print(f"\n>>> 第 {page} 页触发 ACCOUNT_RISK，停止探测", flush=True)
				return 1
			if page < max_page:
				time.sleep(pause)
	finally:
		client.close_browser_session()
		client.close()

	print(f"\n>>> page=1..{max_page} 全部成功", flush=True)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
