import hashlib
import json
import sqlite3
import time
from pathlib import Path
from types import TracebackType
from typing import Any, cast

_SEARCH_TTL = 86400  # 24 hours
_MAX_SEARCH_CACHE = 100


class CacheStore:
	def __init__(self, db_path: Path, *, search_ttl_seconds: int = _SEARCH_TTL) -> None:
		self._db_path = db_path
		self._search_ttl = search_ttl_seconds
		db_path.parent.mkdir(parents=True, exist_ok=True)
		self._conn = sqlite3.connect(str(db_path))
		self._conn.execute("PRAGMA journal_mode=WAL")
		self._init_tables()

	def _init_tables(self) -> None:
		self._conn.executescript("""
			CREATE TABLE IF NOT EXISTS greet_records (
				security_id TEXT PRIMARY KEY,
				job_id TEXT NOT NULL,
				greeted_at REAL NOT NULL
			);
			CREATE TABLE IF NOT EXISTS search_cache (
				cache_key TEXT PRIMARY KEY,
				response TEXT NOT NULL,
				created_at REAL NOT NULL
			);
			CREATE TABLE IF NOT EXISTS saved_searches (
				name TEXT PRIMARY KEY,
				params TEXT NOT NULL,
				created_at REAL NOT NULL,
				updated_at REAL NOT NULL
			);
			CREATE TABLE IF NOT EXISTS watch_hits (
				search_name TEXT NOT NULL,
				job_key TEXT NOT NULL,
				payload TEXT NOT NULL,
				first_seen_at REAL NOT NULL,
				last_seen_at REAL NOT NULL,
				PRIMARY KEY (search_name, job_key)
			);
			CREATE TABLE IF NOT EXISTS scout_transmitted (
				channel TEXT NOT NULL,
				job_key TEXT NOT NULL,
				payload TEXT NOT NULL,
				scout_score INTEGER DEFAULT 0,
				transmitted_at REAL NOT NULL,
				PRIMARY KEY (channel, job_key)
			);
			CREATE TABLE IF NOT EXISTS apply_records (
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				applied_at REAL NOT NULL,
				PRIMARY KEY (security_id, job_id)
			);
			CREATE TABLE IF NOT EXISTS shortlist_records (
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				title TEXT NOT NULL,
				company TEXT NOT NULL,
				city TEXT NOT NULL,
				salary TEXT NOT NULL,
				source TEXT NOT NULL,
				created_at REAL NOT NULL,
				PRIMARY KEY (security_id, job_id)
			);
			CREATE TABLE IF NOT EXISTS resume_job_links (
				resume_name TEXT NOT NULL,
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				job_title TEXT NOT NULL,
				company TEXT NOT NULL,
				status TEXT NOT NULL DEFAULT 'prepared',
				notes TEXT DEFAULT '',
				linked_at REAL NOT NULL,
				updated_at REAL NOT NULL,
				PRIMARY KEY (resume_name, security_id, job_id)
			);
			CREATE TABLE IF NOT EXISTS analysis_records (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				status TEXT NOT NULL,
				title TEXT NOT NULL,
				company TEXT NOT NULL,
				city TEXT NOT NULL DEFAULT '',
				salary TEXT NOT NULL DEFAULT '',
				analysis_score INTEGER DEFAULT 0,
				search_query TEXT NOT NULL DEFAULT '',
				search_city TEXT NOT NULL DEFAULT '',
				channel TEXT NOT NULL DEFAULT '',
				payload TEXT NOT NULL,
				analyzed_at REAL NOT NULL
			);
			CREATE INDEX IF NOT EXISTS idx_analysis_records_analyzed_at
				ON analysis_records(analyzed_at);
			CREATE INDEX IF NOT EXISTS idx_analysis_records_status
				ON analysis_records(status);
			CREATE TABLE IF NOT EXISTS scout_history (
				job_key TEXT PRIMARY KEY,
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				title TEXT DEFAULT '',
				company TEXT DEFAULT '',
				outcome TEXT NOT NULL DEFAULT 'seen',
				channel TEXT DEFAULT '',
				analysis_score INTEGER DEFAULT 0,
				payload TEXT NOT NULL DEFAULT '{}',
				first_scouted_at REAL NOT NULL,
				last_scouted_at REAL NOT NULL,
				scout_count INTEGER DEFAULT 1
			);
			CREATE INDEX IF NOT EXISTS idx_scout_history_outcome
				ON scout_history(outcome);
			CREATE INDEX IF NOT EXISTS idx_scout_history_job_id
				ON scout_history(job_id);
			CREATE TABLE IF NOT EXISTS scout_query_exhausted (
				scope_key TEXT PRIMARY KEY,
				query TEXT NOT NULL,
				city TEXT DEFAULT '',
				last_page INTEGER DEFAULT 0,
				exhausted_at REAL NOT NULL
			);
			CREATE INDEX IF NOT EXISTS idx_scout_query_exhausted_at
				ON scout_query_exhausted(exhausted_at);
		""")
		self._bootstrap_scout_history()

	@staticmethod
	def _make_search_key(params: dict[str, Any]) -> str:
		raw = json.dumps(params, sort_keys=True, ensure_ascii=False)
		return hashlib.sha256(raw.encode()).hexdigest()

	def is_greeted(self, security_id: str) -> bool:
		row = self._conn.execute(
			"SELECT 1 FROM greet_records WHERE security_id = ?",
			(security_id,),
		).fetchone()
		return row is not None

	def get_job_id(self, security_id: str) -> str | None:
		row = self._conn.execute(
			"SELECT job_id FROM greet_records WHERE security_id = ?",
			(security_id,),
		).fetchone()
		return row[0] if row else None

	def record_greet(self, security_id: str, job_id: str) -> None:
		self._conn.execute(
			"INSERT OR REPLACE INTO greet_records (security_id, job_id, greeted_at) VALUES (?, ?, ?)",
			(security_id, job_id, time.time()),
		)
		self._conn.commit()

	def get_search(self, params: dict[str, Any]) -> str | None:
		key = self._make_search_key(params)
		row = self._conn.execute(
			"SELECT response, created_at FROM search_cache WHERE cache_key = ?",
			(key,),
		).fetchone()
		if row is None:
			return None
		if time.time() - row[1] > self._search_ttl:
			self._conn.execute("DELETE FROM search_cache WHERE cache_key = ?", (key,))
			self._conn.commit()
			return None
		return cast("str", row[0])

	def put_search(self, params: dict[str, Any], response: str) -> None:
		key = self._make_search_key(params)
		self._conn.execute(
			"INSERT OR REPLACE INTO search_cache (cache_key, response, created_at) VALUES (?, ?, ?)",
			(key, response, time.time()),
		)
		self._conn.commit()
		self._evict_old_search_cache()

	def _evict_old_search_cache(self) -> None:
		count = self._conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
		if count > _MAX_SEARCH_CACHE:
			excess = count - _MAX_SEARCH_CACHE
			self._conn.execute(
				"DELETE FROM search_cache WHERE cache_key IN "
				"(SELECT cache_key FROM search_cache ORDER BY created_at ASC LIMIT ?)",
				(excess,),
			)
			self._conn.commit()

	def save_saved_search(self, name: str, params: dict[str, Any]) -> None:
		now = time.time()
		existing = self._conn.execute(
			"SELECT created_at FROM saved_searches WHERE name = ?",
			(name,),
		).fetchone()
		created_at = existing[0] if existing else now
		self._conn.execute(
			"INSERT OR REPLACE INTO saved_searches (name, params, created_at, updated_at) VALUES (?, ?, ?, ?)",
			(name, json.dumps(params, ensure_ascii=False, sort_keys=True), created_at, now),
		)
		self._conn.commit()

	def get_saved_search(self, name: str) -> dict[str, Any] | None:
		row = self._conn.execute(
			"SELECT name, params, created_at, updated_at FROM saved_searches WHERE name = ?",
			(name,),
		).fetchone()
		if row is None:
			return None
		return {
			"name": row[0],
			"params": json.loads(row[1]),
			"created_at": row[2],
			"updated_at": row[3],
		}

	def list_saved_searches(self) -> list[dict[str, Any]]:
		rows = self._conn.execute(
			"SELECT name, params, created_at, updated_at FROM saved_searches ORDER BY updated_at DESC"
		).fetchall()
		return [
			{
				"name": row[0],
				"params": json.loads(row[1]),
				"created_at": row[2],
				"updated_at": row[3],
			}
			for row in rows
		]

	def delete_saved_search(self, name: str) -> bool:
		cursor = self._conn.execute(
			"DELETE FROM saved_searches WHERE name = ?",
			(name,),
		)
		self._conn.execute(
			"DELETE FROM watch_hits WHERE search_name = ?",
			(name,),
		)
		self._conn.commit()
		return cursor.rowcount > 0

	@staticmethod
	def _make_watch_job_key(item: dict[str, Any]) -> str:
		security_id = item.get("security_id") or item.get("securityId") or ""
		job_id = item.get("job_id") or item.get("encryptJobId") or ""
		if security_id or job_id:
			return f"{security_id}:{job_id}"
		raw = json.dumps(item, sort_keys=True, ensure_ascii=False)
		return hashlib.sha256(raw.encode()).hexdigest()

	def is_scout_transmitted(self, channel: str, job_key: str) -> bool:
		row = self._conn.execute(
			"SELECT 1 FROM scout_transmitted WHERE channel = ? AND job_key = ?",
			(channel, job_key),
		).fetchone()
		return row is not None

	def has_analysis_record(self, security_id: str, job_id: str) -> bool:
		if not security_id or not job_id:
			return False
		row = self._conn.execute(
			"SELECT 1 FROM analysis_records WHERE security_id = ? AND job_id = ? LIMIT 1",
			(security_id, job_id),
		).fetchone()
		return row is not None

	def filter_untransmitted(
		self, channel: str, items: list[dict[str, Any]],
	) -> tuple[list[dict[str, Any]], int]:
		"""返回尚未传输给分析 AI 的岗位及已传输数量。"""
		new_items: list[dict[str, Any]] = []
		already = 0
		for item in items:
			job_key = self._make_watch_job_key(item)
			sid = str(item.get("security_id") or "")
			jid = str(item.get("job_id") or item.get("encryptJobId") or "")
			if (
				self.is_scout_transmitted(channel, job_key)
				or self.is_job_scouted(job_key)
				or (jid and self.is_job_scouted_by_id(jid))
				or self.is_scout_transmitted_globally(job_key=job_key, job_id=jid)
				or (sid and jid and self.is_shortlisted(sid, jid))
				or (jid and self.is_shortlisted_by_job_id(jid))
			):
				already += 1
			else:
				new_items.append(item)
		return new_items, already

	def record_scout_transmitted(self, channel: str, items: list[dict[str, Any]]) -> int:
		"""记录侦察 AI 已传输给分析 AI 的岗位。"""
		now = time.time()
		count = 0
		for item in items:
			job_key = self._make_watch_job_key(item)
			payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
			scout_score = int(item.get("scout_score") or 0)
			self._conn.execute(
				"INSERT OR REPLACE INTO scout_transmitted "
				"(channel, job_key, payload, scout_score, transmitted_at) VALUES (?, ?, ?, ?, ?)",
				(channel, job_key, payload, scout_score, now),
			)
			count += 1
		self._conn.commit()
		return count

	def count_scout_transmitted(self, channel: str) -> int:
		row = self._conn.execute(
			"SELECT COUNT(*) FROM scout_transmitted WHERE channel = ?",
			(channel,),
		).fetchone()
		return int(row[0]) if row else 0

	def clear_scout_transmitted(self, channel: str | None = None) -> int:
		if channel:
			cursor = self._conn.execute(
				"DELETE FROM scout_transmitted WHERE channel = ?",
				(channel,),
			)
		else:
			cursor = self._conn.execute("DELETE FROM scout_transmitted")
		self._conn.commit()
		return cursor.rowcount

	def record_watch_results(self, search_name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
		now = time.time()
		new_items = []
		seen_count = 0
		for item in items:
			job_key = self._make_watch_job_key(item)
			payload = json.dumps(item, ensure_ascii=False, sort_keys=True)
			row = self._conn.execute(
				"SELECT 1 FROM watch_hits WHERE search_name = ? AND job_key = ?",
				(search_name, job_key),
			).fetchone()
			if row is None:
				new_items.append(item)
				self._conn.execute(
					"INSERT INTO watch_hits (search_name, job_key, payload, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
					(search_name, job_key, payload, now, now),
				)
			else:
				seen_count += 1
				self._conn.execute(
					"UPDATE watch_hits SET payload = ?, last_seen_at = ? WHERE search_name = ? AND job_key = ?",
					(payload, now, search_name, job_key),
				)
		self._conn.commit()
		return {
			"new_count": len(new_items),
			"seen_count": seen_count,
			"new_items": new_items,
			"total_count": len(items),
		}

	def is_applied(self, security_id: str, job_id: str) -> bool:
		row = self._conn.execute(
			"SELECT 1 FROM apply_records WHERE security_id = ? AND job_id = ?",
			(security_id, job_id),
		).fetchone()
		return row is not None

	def record_apply(self, security_id: str, job_id: str) -> None:
		self._conn.execute(
			"INSERT OR REPLACE INTO apply_records (security_id, job_id, applied_at) VALUES (?, ?, ?)",
			(security_id, job_id, time.time()),
		)
		self._conn.commit()

	def is_shortlisted(self, security_id: str, job_id: str) -> bool:
		row = self._conn.execute(
			"SELECT 1 FROM shortlist_records WHERE security_id = ? AND job_id = ?",
			(security_id, job_id),
		).fetchone()
		return row is not None

	def add_shortlist(self, item: dict[str, Any]) -> None:
		self._conn.execute(
			"INSERT OR REPLACE INTO shortlist_records (security_id, job_id, title, company, city, salary, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(
				item.get("security_id", ""),
				item.get("job_id", ""),
				item.get("title", ""),
				item.get("company", ""),
				item.get("city", ""),
				item.get("salary", ""),
				item.get("source", ""),
				time.time(),
			),
		)
		self._conn.commit()

	def list_shortlist(self) -> list[dict[str, Any]]:
		rows = self._conn.execute(
			"SELECT security_id, job_id, title, company, city, salary, source, created_at FROM shortlist_records ORDER BY created_at DESC"
		).fetchall()
		return [
			{
				"security_id": row[0],
				"job_id": row[1],
				"title": row[2],
				"company": row[3],
				"city": row[4],
				"salary": row[5],
				"source": row[6],
				"created_at": row[7],
			}
			for row in rows
		]

	def remove_shortlist(self, security_id: str, job_id: str) -> bool:
		cursor = self._conn.execute(
			"DELETE FROM shortlist_records WHERE security_id = ? AND job_id = ?",
			(security_id, job_id),
		)
		self._conn.commit()
		return cursor.rowcount > 0

	def link_resume_to_job(
		self,
		resume_name: str,
		security_id: str,
		job_id: str,
		job_title: str,
		company: str,
	) -> None:
		"""将简历与职位关联"""
		now = time.time()
		self._conn.execute(
			"INSERT OR REPLACE INTO resume_job_links "
			"(resume_name, security_id, job_id, job_title, company, status, notes, linked_at, updated_at) "
			"VALUES (?, ?, ?, ?, ?, 'prepared', '', ?, ?)",
			(resume_name, security_id, job_id, job_title, company, now, now),
		)
		self._conn.commit()

	def update_job_link_status(
		self,
		resume_name: str,
		security_id: str,
		job_id: str,
		status: str,
		notes: str = "",
	) -> bool:
		"""更新关联状态"""
		now = time.time()
		cursor = self._conn.execute(
			"UPDATE resume_job_links SET status = ?, notes = ?, updated_at = ? "
			"WHERE resume_name = ? AND security_id = ? AND job_id = ?",
			(status, notes, now, resume_name, security_id, job_id),
		)
		self._conn.commit()
		return cursor.rowcount > 0

	def get_resume_applications(self, resume_name: str) -> list[dict[str, Any]]:
		"""查看某份简历投递的所有职位"""
		rows = self._conn.execute(
			"SELECT resume_name, security_id, job_id, job_title, company, status, notes, linked_at, updated_at "
			"FROM resume_job_links WHERE resume_name = ? ORDER BY updated_at DESC",
			(resume_name,),
		).fetchall()
		return [
			{
				"resume_name": row[0],
				"security_id": row[1],
				"job_id": row[2],
				"job_title": row[3],
				"company": row[4],
				"status": row[5],
				"notes": row[6],
				"linked_at": row[7],
				"updated_at": row[8],
			}
			for row in rows
		]

	def get_job_resumes(self, security_id: str, job_id: str) -> list[dict[str, Any]]:
		"""查看某职位关联的所有简历版本"""
		rows = self._conn.execute(
			"SELECT resume_name, security_id, job_id, job_title, company, status, notes, linked_at, updated_at "
			"FROM resume_job_links WHERE security_id = ? AND job_id = ? ORDER BY updated_at DESC",
			(security_id, job_id),
		).fetchall()
		return [
			{
				"resume_name": row[0],
				"security_id": row[1],
				"job_id": row[2],
				"job_title": row[3],
				"company": row[4],
				"status": row[5],
				"notes": row[6],
				"linked_at": row[7],
				"updated_at": row[8],
			}
			for row in rows
		]

	def remove_job_link(self, resume_name: str, security_id: str, job_id: str) -> bool:
		"""移除简历职位关联"""
		cursor = self._conn.execute(
			"DELETE FROM resume_job_links WHERE resume_name = ? AND security_id = ? AND job_id = ?",
			(resume_name, security_id, job_id),
		)
		self._conn.commit()
		return cursor.rowcount > 0

	def record_analysis_job(
		self,
		job: dict[str, Any],
		status: str,
		*,
		search_query: str = "",
		search_city: str = "",
		channel: str = "",
		analyzed_at: float | None = None,
	) -> None:
		"""持久化分析 AI 对单个岗位的评估结果（passed / filtered）。"""
		ts = analyzed_at if analyzed_at is not None else time.time()
		payload = json.dumps(job, ensure_ascii=False)
		self._conn.execute(
			"INSERT INTO analysis_records "
			"(security_id, job_id, status, title, company, city, salary, analysis_score, "
			"search_query, search_city, channel, payload, analyzed_at) "
			"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
			(
				str(job.get("security_id") or ""),
				str(job.get("job_id") or ""),
				status,
				str(job.get("title") or ""),
				str(job.get("company") or ""),
				str(job.get("city") or ""),
				str(job.get("salary") or ""),
				int(job.get("analysis_score") or 0),
				search_query,
				search_city or "",
				channel,
				payload,
				ts,
			),
		)
		self._conn.commit()

	def list_analysis_records(
		self,
		since_ts: float,
		until_ts: float,
		*,
		status: str | None = None,
	) -> list[dict[str, Any]]:
		"""按时间范围查询分析记录；status 为 passed 或 filtered。"""
		if status:
			rows = self._conn.execute(
				"SELECT id, security_id, job_id, status, title, company, city, salary, "
				"analysis_score, search_query, search_city, channel, payload, analyzed_at "
				"FROM analysis_records "
				"WHERE analyzed_at >= ? AND analyzed_at < ? AND status = ? "
				"ORDER BY analysis_score DESC, analyzed_at DESC",
				(since_ts, until_ts, status),
			).fetchall()
		else:
			rows = self._conn.execute(
				"SELECT id, security_id, job_id, status, title, company, city, salary, "
				"analysis_score, search_query, search_city, channel, payload, analyzed_at "
				"FROM analysis_records "
				"WHERE analyzed_at >= ? AND analyzed_at < ? "
				"ORDER BY analyzed_at DESC, analysis_score DESC",
				(since_ts, until_ts),
			).fetchall()
		result: list[dict[str, Any]] = []
		for row in rows:
			try:
				payload = json.loads(row[12])
			except json.JSONDecodeError:
				payload = {}
			result.append({
				"id": row[0],
				"security_id": row[1],
				"job_id": row[2],
				"status": row[3],
				"title": row[4],
				"company": row[5],
				"city": row[6],
				"salary": row[7],
				"analysis_score": row[8],
				"search_query": row[9],
				"search_city": row[10],
				"channel": row[11],
				"job": payload,
				"analyzed_at": row[13],
			})
		return result

	def list_recent_analysis_records(
		self,
		*,
		status: str | None = None,
		limit: int = 200,
	) -> list[dict[str, Any]]:
		"""查询最近的分析记录（默认按时间倒序）。"""
		limit = max(1, min(int(limit), 500))
		if status:
			rows = self._conn.execute(
				"SELECT id, security_id, job_id, status, title, company, city, salary, "
				"analysis_score, search_query, search_city, channel, payload, analyzed_at "
				"FROM analysis_records "
				"WHERE status = ? "
				"ORDER BY analyzed_at DESC, id DESC "
				"LIMIT ?",
				(status, limit),
			).fetchall()
		else:
			rows = self._conn.execute(
				"SELECT id, security_id, job_id, status, title, company, city, salary, "
				"analysis_score, search_query, search_city, channel, payload, analyzed_at "
				"FROM analysis_records "
				"ORDER BY analyzed_at DESC, id DESC "
				"LIMIT ?",
				(limit,),
			).fetchall()
		result: list[dict[str, Any]] = []
		for row in rows:
			try:
				payload = json.loads(row[12])
			except json.JSONDecodeError:
				payload = {}
			result.append({
				"id": row[0],
				"security_id": row[1],
				"job_id": row[2],
				"status": row[3],
				"title": row[4],
				"company": row[5],
				"city": row[6],
				"salary": row[7],
				"analysis_score": row[8],
				"search_query": row[9],
				"search_city": row[10],
				"channel": row[11],
				"job": payload,
				"analyzed_at": row[13],
			})
		return result

	def list_analysis_days(self, *, limit: int = 120) -> list[dict[str, Any]]:
		"""按本地日期汇总分析记录，供每日精选日期列表使用。"""
		rows = self._conn.execute(
			"SELECT date(analyzed_at, 'unixepoch', 'localtime') AS day, "
			"COUNT(*) AS total, "
			"SUM(CASE WHEN status = 'passed' THEN 1 ELSE 0 END) AS passed_count "
			"FROM analysis_records "
			"GROUP BY day "
			"ORDER BY day DESC "
			"LIMIT ?",
			(limit,),
		).fetchall()
		return [
			{
				"date": str(row[0]),
				"total": int(row[1] or 0),
				"passed_count": int(row[2] or 0),
			}
			for row in rows
		]

	def is_job_scouted(self, job_key: str) -> bool:
		row = self._conn.execute(
			"SELECT 1 FROM scout_history WHERE job_key = ?",
			(job_key,),
		).fetchone()
		return row is not None

	def is_job_scouted_by_id(self, job_id: str) -> bool:
		if not job_id:
			return False
		row = self._conn.execute(
			"SELECT 1 FROM scout_history WHERE job_id = ? LIMIT 1",
			(job_id,),
		).fetchone()
		return row is not None

	def get_scout_history_by_job_id(self, job_id: str) -> dict[str, Any] | None:
		if not job_id:
			return None
		row = self._conn.execute(
			"SELECT job_key, security_id, job_id, title, company, outcome, channel, "
			"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count "
			"FROM scout_history WHERE job_id = ? "
			"ORDER BY last_scouted_at DESC LIMIT 1",
			(job_id,),
		).fetchone()
		if row is None:
			return None
		return self._scout_history_row_to_dict(row)

	def is_scout_transmitted_globally(
		self,
		*,
		job_key: str = "",
		job_id: str = "",
	) -> bool:
		if job_key:
			row = self._conn.execute(
				"SELECT 1 FROM scout_transmitted WHERE job_key = ? LIMIT 1",
				(job_key,),
			).fetchone()
			if row is not None:
				return True
		if job_id:
			row = self._conn.execute(
				"SELECT 1 FROM scout_transmitted WHERE job_key LIKE ? LIMIT 1",
				(f"%:{job_id}",),
			).fetchone()
			if row is not None:
				return True
		return False

	def has_analysis_record_by_job_id(self, job_id: str) -> bool:
		if not job_id:
			return False
		row = self._conn.execute(
			"SELECT 1 FROM analysis_records WHERE job_id = ? LIMIT 1",
			(job_id,),
		).fetchone()
		return row is not None

	def is_shortlisted_by_job_id(self, job_id: str) -> bool:
		if not job_id:
			return False
		row = self._conn.execute(
			"SELECT 1 FROM shortlist_records WHERE job_id = ? LIMIT 1",
			(job_id,),
		).fetchone()
		return row is not None

	def get_scout_history(self, job_key: str) -> dict[str, Any] | None:
		row = self._conn.execute(
			"SELECT job_key, security_id, job_id, title, company, outcome, channel, "
			"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count "
			"FROM scout_history WHERE job_key = ?",
			(job_key,),
		).fetchone()
		if row is None:
			return None
		return self._scout_history_row_to_dict(row)

	@staticmethod
	def _scout_history_row_to_dict(row: Any) -> dict[str, Any]:
		try:
			payload = json.loads(row[8])
		except json.JSONDecodeError:
			payload = {}
		return {
			"job_key": row[0],
			"security_id": row[1],
			"job_id": row[2],
			"title": row[3],
			"company": row[4],
			"outcome": row[5],
			"channel": row[6],
			"analysis_score": row[7],
			"job": payload,
			"first_scouted_at": row[9],
			"last_scouted_at": row[10],
			"scout_count": row[11],
		}

	def record_scout_history(
		self,
		job: dict[str, Any],
		outcome: str,
		*,
		channel: str = "",
		analysis_score: int = 0,
	) -> None:
		"""记录岗位侦察结果；同一岗位仅保留最新 outcome。"""
		job_key = self._make_watch_job_key(job)
		jid = str(job.get("job_id") or job.get("encryptJobId") or "")
		now = time.time()
		payload = json.dumps(job, ensure_ascii=False, sort_keys=True)
		existing = self.get_scout_history(job_key)
		if not existing and jid:
			existing = self.get_scout_history_by_job_id(jid)
		if existing:
			existing_key = str(existing.get("job_key") or job_key)
			scout_count = int(existing.get("scout_count") or 1) + 1
			first_at = float(existing.get("first_scouted_at") or now)
			if existing_key != job_key:
				self._conn.execute(
					"DELETE FROM scout_history WHERE job_key = ?",
					(existing_key,),
				)
				self._conn.execute(
					"INSERT INTO scout_history "
					"(job_key, security_id, job_id, title, company, outcome, channel, "
					"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count) "
					"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
					(
						job_key,
						str(job.get("security_id") or existing.get("security_id") or ""),
						jid or str(existing.get("job_id") or ""),
						str(job.get("title") or existing.get("title") or ""),
						str(job.get("company") or existing.get("company") or ""),
						outcome,
						channel or str(existing.get("channel") or ""),
						analysis_score or int(existing.get("analysis_score") or 0),
						payload,
						first_at,
						now,
						scout_count,
					),
				)
			else:
				self._conn.execute(
					"UPDATE scout_history SET outcome = ?, channel = ?, analysis_score = ?, "
					"payload = ?, title = ?, company = ?, security_id = ?, job_id = ?, "
					"last_scouted_at = ?, scout_count = ? "
					"WHERE job_key = ?",
					(
						outcome,
						channel or existing.get("channel") or "",
						analysis_score or int(existing.get("analysis_score") or 0),
						payload,
						str(job.get("title") or existing.get("title") or ""),
						str(job.get("company") or existing.get("company") or ""),
						str(job.get("security_id") or existing.get("security_id") or ""),
						jid or str(existing.get("job_id") or ""),
						now,
						scout_count,
						job_key,
					),
				)
		else:
			self._conn.execute(
				"INSERT INTO scout_history "
				"(job_key, security_id, job_id, title, company, outcome, channel, "
				"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count) "
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
				(
					job_key,
					str(job.get("security_id") or ""),
					str(job.get("job_id") or ""),
					str(job.get("title") or ""),
					str(job.get("company") or ""),
					outcome,
					channel,
					analysis_score,
					payload,
					now,
					now,
				),
			)
		self._conn.commit()

	def count_scout_history(self, *, outcome: str | None = None) -> int:
		if outcome:
			row = self._conn.execute(
				"SELECT COUNT(*) FROM scout_history WHERE outcome = ?",
				(outcome,),
			).fetchone()
		else:
			row = self._conn.execute("SELECT COUNT(*) FROM scout_history").fetchone()
		return int(row[0]) if row else 0

	def scout_history_summary(self) -> dict[str, Any]:
		rows = self._conn.execute(
			"SELECT outcome, COUNT(*) FROM scout_history GROUP BY outcome",
		).fetchall()
		by_outcome = {str(r[0]): int(r[1]) for r in rows}
		tx_row = self._conn.execute("SELECT COUNT(*) FROM scout_transmitted").fetchone()
		return {
			"total": sum(by_outcome.values()),
			"by_outcome": by_outcome,
			"transmitted_records": int(tx_row[0]) if tx_row else 0,
		}

	def record_scout_query_exhausted(
		self,
		query: str,
		city: str | None,
		*,
		page: int | None = None,
	) -> None:
		from pet_boss.agents.scout_query_memory import query_scope_key

		key = query_scope_key(query, city)
		now = time.time()
		self._conn.execute(
			"INSERT INTO scout_query_exhausted (scope_key, query, city, last_page, exhausted_at) "
			"VALUES (?, ?, ?, ?, ?) "
			"ON CONFLICT(scope_key) DO UPDATE SET "
			"query = excluded.query, city = excluded.city, "
			"last_page = excluded.last_page, exhausted_at = excluded.exhausted_at",
			(key, str(query).strip(), str(city or "").strip(), int(page or 0), now),
		)
		self._conn.commit()

	def get_scout_query_exhausted_at(self, query: str, city: str | None) -> float | None:
		from pet_boss.agents.scout_query_memory import query_scope_key

		key = query_scope_key(query, city)
		row = self._conn.execute(
			"SELECT exhausted_at FROM scout_query_exhausted WHERE scope_key = ?",
			(key,),
		).fetchone()
		if not row:
			return None
		return float(row[0])

	def clear_scout_query_exhausted(self) -> int:
		row = self._conn.execute("SELECT COUNT(*) FROM scout_query_exhausted").fetchone()
		removed = int(row[0]) if row else 0
		self._conn.execute("DELETE FROM scout_query_exhausted")
		self._conn.commit()
		return removed

	def clear_all_scout_history(self) -> dict[str, int]:
		"""全部重置搜岗状态：侦察历史、传输记录、分析记录、候选池一并清空。"""
		history_removed = self.count_scout_history()
		tx_row = self._conn.execute("SELECT COUNT(*) FROM scout_transmitted").fetchone()
		transmitted_removed = int(tx_row[0]) if tx_row else 0
		analysis_row = self._conn.execute("SELECT COUNT(*) FROM analysis_records").fetchone()
		analysis_removed = int(analysis_row[0]) if analysis_row else 0
		shortlist_row = self._conn.execute("SELECT COUNT(*) FROM shortlist_records").fetchone()
		shortlist_removed = int(shortlist_row[0]) if shortlist_row else 0
		exhausted_removed = self.clear_scout_query_exhausted()
		self._conn.execute("DELETE FROM scout_history")
		self._conn.execute("DELETE FROM scout_transmitted")
		self._conn.execute("DELETE FROM analysis_records")
		self._conn.execute("DELETE FROM shortlist_records")
		self._conn.commit()
		return {
			"history_removed": history_removed,
			"transmitted_removed": transmitted_removed,
			"analysis_removed": analysis_removed,
			"shortlist_removed": shortlist_removed,
			"exhausted_queries_removed": exhausted_removed,
		}

	def _bootstrap_scout_history(self) -> None:
		"""首次建库时，从 scout_transmitted / analysis_records 迁移历史。"""
		row = self._conn.execute("SELECT COUNT(*) FROM scout_history").fetchone()
		if row and int(row[0]) > 0:
			return
		now = time.time()
		for channel, job_key, payload_raw, _score, ts in self._conn.execute(
			"SELECT channel, job_key, payload, scout_score, transmitted_at FROM scout_transmitted",
		):
			try:
				job = json.loads(payload_raw)
			except json.JSONDecodeError:
				job = {"security_id": "", "job_id": ""}
			parts = job_key.split(":", 1)
			self._conn.execute(
				"INSERT OR IGNORE INTO scout_history "
				"(job_key, security_id, job_id, title, company, outcome, channel, "
				"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count) "
				"VALUES (?, ?, ?, ?, ?, 'transmitted', ?, 0, ?, ?, ?, 1)",
				(
					job_key,
					parts[0] if parts else str(job.get("security_id") or ""),
					parts[1] if len(parts) > 1 else str(job.get("job_id") or ""),
					str(job.get("title") or ""),
					str(job.get("company") or ""),
					channel,
					payload_raw,
					ts or now,
					ts or now,
				),
			)
		seen_keys: set[str] = set()
		for sec_id, job_id, status, title, company, score, channel, payload_raw, ts in self._conn.execute(
			"SELECT security_id, job_id, status, title, company, analysis_score, "
			"channel, payload, analyzed_at FROM analysis_records ORDER BY analyzed_at DESC",
		):
			job_key = f"{sec_id}:{job_id}"
			if job_key in seen_keys:
				continue
			seen_keys.add(job_key)
			outcome = "passed" if status == "passed" else "filtered"
			self._conn.execute(
				"INSERT OR REPLACE INTO scout_history "
				"(job_key, security_id, job_id, title, company, outcome, channel, "
				"analysis_score, payload, first_scouted_at, last_scouted_at, scout_count) "
				"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
				(
					job_key,
					sec_id,
					job_id,
					title,
					company,
					outcome,
					channel or "",
					int(score or 0),
					payload_raw,
					ts or now,
					ts or now,
				),
			)
		self._conn.commit()

	def close(self) -> None:
		self._conn.close()

	def __enter__(self) -> "CacheStore":
		return self

	def __exit__(
		self,
		exc_type: type[BaseException] | None,
		exc_val: BaseException | None,
		exc_tb: TracebackType | None,
	) -> None:
		self.close()
