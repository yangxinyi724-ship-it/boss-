"""User Profile Intelligence System — 持久化存储。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pet_boss.profile.models import (
	CareerDirection,
	InterviewSession,
	ParsedResume,
	UserPreferences,
	UserProfile,
)


class ProfileStore:
	"""画像、偏好、反馈与学习数据存储。"""

	def __init__(self, data_dir: Path) -> None:
		self._dir = data_dir / "profile"
		self._dir.mkdir(parents=True, exist_ok=True)
		self._db_path = self._dir / "profile.db"
		self._conn = sqlite3.connect(str(self._db_path))
		self._conn.execute("PRAGMA journal_mode=WAL")
		self._init_tables()

	def close(self) -> None:
		self._conn.close()

	def __enter__(self) -> ProfileStore:
		return self

	def __exit__(self, *args: Any) -> None:
		self.close()

	def _init_tables(self) -> None:
		self._conn.executescript("""
			CREATE TABLE IF NOT EXISTS profile_feedback (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				title TEXT DEFAULT '',
				company TEXT DEFAULT '',
				action TEXT NOT NULL,
				notes TEXT DEFAULT '',
				created_at REAL NOT NULL
			);
			CREATE TABLE IF NOT EXISTS profile_weights (
				dimension TEXT PRIMARY KEY,
				weight REAL NOT NULL DEFAULT 1.0,
				updated_at REAL NOT NULL
			);
			CREATE TABLE IF NOT EXISTS ai_memory (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				agent TEXT NOT NULL,
				category TEXT NOT NULL,
				content TEXT NOT NULL,
				source_job_key TEXT DEFAULT '',
				weight REAL NOT NULL DEFAULT 1.0,
				created_at REAL NOT NULL,
				updated_at REAL NOT NULL
			);
			CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_memory_unique
				ON ai_memory(agent, category, content);
			CREATE TABLE IF NOT EXISTS preference_learning_log (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				security_id TEXT NOT NULL,
				job_id TEXT NOT NULL,
				title TEXT DEFAULT '',
				company TEXT DEFAULT '',
				user_tags TEXT DEFAULT '[]',
				user_reason TEXT DEFAULT '',
				analysis_score INTEGER,
				analysis_reason TEXT DEFAULT '[]',
				analysis_risk TEXT DEFAULT '[]',
				weight_changes TEXT DEFAULT '[]',
				preference_instructions TEXT DEFAULT '[]',
				ai_memory_added TEXT DEFAULT '[]',
				created_at REAL NOT NULL
			);
		""")
		self._conn.commit()

	def _write_json(self, name: str, data: dict[str, Any]) -> None:
		path = self._dir / name
		path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

	def _read_json(self, name: str) -> dict[str, Any] | None:
		path = self._dir / name
		if not path.exists():
			return None
		raw = path.read_text(encoding="utf-8").strip()
		if not raw:
			return None
		try:
			result = json.loads(raw)
		except json.JSONDecodeError:
			return None
		return result if isinstance(result, dict) else None

	def save_parsed_resume(self, parsed: ParsedResume) -> None:
		self._write_json("parsed_resume.json", parsed.to_dict())

	def load_parsed_resume(self) -> ParsedResume | None:
		data = self._read_json("parsed_resume.json")
		return ParsedResume.from_dict(data) if data else None

	def save_secretary_portrait(self, portrait: dict[str, Any]) -> None:
		self._write_json("secretary_portrait.json", portrait)

	def load_secretary_portrait(self) -> dict[str, Any] | None:
		return self._read_json("secretary_portrait.json")

	def save_preference_instructions(self, payload: dict[str, Any]) -> None:
		self._write_json("preference_instructions.json", payload)

	def load_preference_instructions(self) -> dict[str, Any] | None:
		return self._read_json("preference_instructions.json")

	def save_daily_action_plan(self, payload: dict[str, Any]) -> None:
		self._write_json("daily_action_plan.json", payload)

	def load_daily_action_plan(self) -> dict[str, Any] | None:
		return self._read_json("daily_action_plan.json")

	def save_scout_strategy_plan(self, payload: dict[str, Any]) -> None:
		self._write_json("latest_scout_strategy.json", payload)

	def load_scout_strategy_plan(self) -> dict[str, Any] | None:
		return self._read_json("latest_scout_strategy.json")

	def save_preferences(self, prefs: UserPreferences) -> None:
		self._write_json("preferences.json", prefs.to_dict())

	def load_preferences(self) -> UserPreferences | None:
		data = self._read_json("preferences.json")
		return UserPreferences.from_dict(data) if data else None

	def save_career(self, career: CareerDirection) -> None:
		self._write_json("career_direction.json", career.to_dict())

	def load_career(self) -> CareerDirection | None:
		data = self._read_json("career_direction.json")
		return CareerDirection.from_dict(data) if data else None

	def save_interview_session(self, session: InterviewSession) -> None:
		self._write_json("interview_session.json", session.to_dict())

	def load_interview_session(self) -> InterviewSession | None:
		data = self._read_json("interview_session.json")
		return InterviewSession.from_dict(data) if data else None

	def clear_interview_session(self) -> None:
		path = self._dir / "interview_session.json"
		path.unlink(missing_ok=True)

	def save_profile(self, profile: UserProfile) -> None:
		profile.updated_at = datetime.now().isoformat()
		self._write_json("user_profile.json", profile.to_dict())

	def load_profile(self) -> UserProfile:
		data = self._read_json("user_profile.json")
		if data:
			return UserProfile.from_dict(data)
		return UserProfile(
			parsed_resume=self.load_parsed_resume(),
			preferences=self.load_preferences(),
			career=self.load_career(),
		)

	def save_memory_summary(self, summary: str) -> None:
		profile = self.load_profile()
		profile.memory_summary = summary
		self.save_profile(profile)

	def record_feedback(
		self,
		*,
		security_id: str,
		job_id: str,
		action: str,
		title: str = "",
		company: str = "",
		notes: str = "",
	) -> None:
		self._conn.execute(
			"""INSERT INTO profile_feedback
			(security_id, job_id, title, company, action, notes, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?)""",
			(security_id, job_id, title, company, action, notes, time.time()),
		)
		self._conn.commit()

	def list_feedback(self, limit: int = 100) -> list[dict[str, Any]]:
		rows = self._conn.execute(
			"""SELECT security_id, job_id, title, company, action, notes, created_at
			FROM profile_feedback ORDER BY created_at DESC LIMIT ?""",
			(limit,),
		).fetchall()
		return [
			{
				"security_id": r[0],
				"job_id": r[1],
				"title": r[2],
				"company": r[3],
				"action": r[4],
				"notes": r[5],
				"created_at": r[6],
			}
			for r in rows
		]

	def has_feedback_action(self, security_id: str, job_id: str, action: str) -> bool:
		if not security_id or not job_id:
			return False
		row = self._conn.execute(
			"SELECT 1 FROM profile_feedback WHERE security_id = ? AND job_id = ? AND action = ? LIMIT 1",
			(security_id, job_id, action),
		).fetchone()
		return row is not None

	def clear_scout_job_feedback(self) -> int:
		"""清空与搜岗去重相关的岗位反馈（不感兴趣 / 候选池）。"""
		cursor = self._conn.execute(
			"DELETE FROM profile_feedback WHERE action IN ('rejected', 'shortlisted')",
		)
		self._conn.commit()
		return cursor.rowcount

	def clear_analysis_ai_memory(self) -> int:
		"""清空分析 AI 从岗位中学到的记忆（全部重置时调用）。"""
		cursor = self._conn.execute("DELETE FROM ai_memory WHERE agent = 'analysis'")
		self._conn.commit()
		return cursor.rowcount

	def get_dimension_weights(self) -> dict[str, float]:
		rows = self._conn.execute("SELECT dimension, weight FROM profile_weights").fetchall()
		defaults = {
			"skill_match": 1.0,
			"industry_match": 1.0,
			"growth": 1.0,
			"salary": 1.0,
			"preference_fit": 1.0,
			"work_intensity": 1.0,
			"company_stage": 1.0,
			"city_match": 1.0,
			"career_goal": 1.0,
		}
		for dim, weight in rows:
			defaults[dim] = weight
		return defaults

	def set_dimension_weight(self, dimension: str, weight: float) -> None:
		self._conn.execute(
			"""INSERT OR REPLACE INTO profile_weights (dimension, weight, updated_at)
			VALUES (?, ?, ?)""",
			(dimension, weight, time.time()),
		)
		self._conn.commit()

	def add_ai_memory(
		self,
		agent: str,
		category: str,
		content: str,
		*,
		source_job_key: str = "",
		weight: float = 1.0,
	) -> None:
		text = content.strip()[:500]
		if not text:
			return
		now = time.time()
		row = self._conn.execute(
			"SELECT id, weight FROM ai_memory WHERE agent = ? AND category = ? AND content = ?",
			(agent, category, text),
		).fetchone()
		if row:
			new_weight = min(3.0, float(row[1]) + 0.15 * weight)
			self._conn.execute(
				"UPDATE ai_memory SET weight = ?, updated_at = ?, source_job_key = ? WHERE id = ?",
				(new_weight, now, source_job_key or "", row[0]),
			)
		else:
			self._conn.execute(
				"""INSERT INTO ai_memory
				(agent, category, content, source_job_key, weight, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?)""",
				(agent, category, text, source_job_key or "", weight, now, now),
			)
		self._conn.commit()

	def list_ai_memory(
		self,
		*,
		agent: str | None = None,
		category: str | None = None,
		limit: int = 30,
	) -> list[dict[str, Any]]:
		query = (
			"SELECT id, agent, category, content, source_job_key, weight, created_at, updated_at "
			"FROM ai_memory"
		)
		params: list[Any] = []
		clauses: list[str] = []
		if agent:
			clauses.append("agent = ?")
			params.append(agent)
		if category:
			clauses.append("category = ?")
			params.append(category)
		if clauses:
			query += " WHERE " + " AND ".join(clauses)
		query += " ORDER BY weight DESC, updated_at DESC LIMIT ?"
		params.append(limit)
		rows = self._conn.execute(query, params).fetchall()
		return [
			{
				"id": r[0],
				"agent": r[1],
				"category": r[2],
				"content": r[3],
				"source_job_key": r[4],
				"weight": r[5],
				"created_at": r[6],
				"updated_at": r[7],
			}
			for r in rows
		]

	def delete_ai_memory(self, agent: str, category: str, content: str) -> bool:
		text = content.strip()[:500]
		if not text:
			return False
		cursor = self._conn.execute(
			"DELETE FROM ai_memory WHERE agent = ? AND category = ? AND content = ?",
			(agent, category, text),
		)
		self._conn.commit()
		return cursor.rowcount > 0

	def delete_ai_memory_by_job_key(self, source_job_key: str) -> int:
		key = str(source_job_key or "").strip()
		if not key:
			return 0
		cursor = self._conn.execute(
			"DELETE FROM ai_memory WHERE source_job_key = ?",
			(key,),
		)
		self._conn.commit()
		return cursor.rowcount

	def remove_preference_instructions(self, to_remove: set[str]) -> int:
		if not to_remove:
			return 0
		removed = 0
		data = self.load_preference_instructions()
		if data:
			old = [str(x) for x in (data.get("instructions") or [])]
			new = [x for x in old if x not in to_remove]
			removed += len(old) - len(new)
			if new:
				data["instructions"] = new
				self.save_preference_instructions(data)
			else:
				path = self._dir / "preference_instructions.json"
				if path.exists():
					path.unlink()
		prefs = self.load_preferences()
		if prefs:
			notes = dict(prefs.extra_notes or {})
			old = [str(x) for x in (notes.get("secretary_instructions") or [])]
			new = [x for x in old if x not in to_remove]
			removed += len(old) - len(new)
			if new:
				notes["secretary_instructions"] = new
			elif "secretary_instructions" in notes:
				del notes["secretary_instructions"]
			prefs.extra_notes = notes
			self.save_preferences(prefs)
		return removed

	def clear_preference_learning_logs(self) -> int:
		cursor = self._conn.execute("DELETE FROM preference_learning_log")
		self._conn.commit()
		return cursor.rowcount

	def add_preference_learning_log(self, entry: dict[str, Any]) -> int:
		cursor = self._conn.execute(
			"""INSERT INTO preference_learning_log
			(security_id, job_id, title, company, user_tags, user_reason,
			 analysis_score, analysis_reason, analysis_risk, weight_changes,
			 preference_instructions, ai_memory_added, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
			(
				str(entry.get("security_id") or ""),
				str(entry.get("job_id") or ""),
				str(entry.get("title") or ""),
				str(entry.get("company") or ""),
				json.dumps(entry.get("user_tags") or [], ensure_ascii=False),
				str(entry.get("user_reason") or ""),
				entry.get("analysis_score"),
				json.dumps(entry.get("analysis_reason") or [], ensure_ascii=False),
				json.dumps(entry.get("analysis_risk") or [], ensure_ascii=False),
				json.dumps(entry.get("weight_changes") or [], ensure_ascii=False),
				json.dumps(entry.get("preference_instructions") or [], ensure_ascii=False),
				json.dumps(entry.get("ai_memory_added") or [], ensure_ascii=False),
				float(entry.get("created_at") or time.time()),
			),
		)
		self._conn.commit()
		return int(cursor.lastrowid or 0)

	def list_preference_learning_logs(self, *, limit: int = 100) -> list[dict[str, Any]]:
		rows = self._conn.execute(
			"""SELECT id, security_id, job_id, title, company, user_tags, user_reason,
			 analysis_score, analysis_reason, analysis_risk, weight_changes,
			 preference_instructions, ai_memory_added, created_at
			FROM preference_learning_log ORDER BY created_at DESC LIMIT ?""",
			(max(1, min(limit, 500)),),
		).fetchall()
		items: list[dict[str, Any]] = []
		for row in rows:
			items.append({
				"id": row[0],
				"security_id": row[1],
				"job_id": row[2],
				"title": row[3],
				"company": row[4],
				"user_tags": _json_list(row[5]),
				"user_reason": row[6],
				"analysis_score": row[7],
				"analysis_reason": _json_list(row[8]),
				"analysis_risk": _json_list(row[9]),
				"weight_changes": _json_list(row[10]),
				"preference_instructions": _json_list(row[11]),
				"ai_memory_added": _json_list(row[12]),
				"created_at": row[13],
			})
		return items


def _json_list(raw: str | None) -> list[Any]:
	if not raw:
		return []
	try:
		data = json.loads(raw)
	except json.JSONDecodeError:
		return []
	return data if isinstance(data, list) else []
