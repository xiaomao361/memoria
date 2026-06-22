"""高频时序流水：独立于长期记忆的新增、查询和汇总。"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import get_conn, init_db

DEFAULT_TIMEZONE = "Asia/Shanghai"
MAX_LIMIT = 500


class RecordValidationError(ValueError):
    """调用方提交的流水数据不合法。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(f"{field} is required")
    return value.strip()


def _parse_timezone(name: str) -> ZoneInfo:
    timezone_name = _required_text(name, "timezone")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RecordValidationError(f"unknown timezone: {timezone_name}") from exc


def _parse_aware_datetime(value: str, field: str) -> datetime:
    raw = _required_text(value, field)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RecordValidationError(f"{field} must be a valid ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecordValidationError(f"{field} must include a timezone offset")
    return parsed


def _utc_iso(value: str, field: str) -> str:
    return _parse_aware_datetime(value, field).astimezone(timezone.utc).isoformat()


def _validate_non_negative_number(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordValidationError(f"{field} must be a number")
    if value < 0:
        raise RecordValidationError(f"{field} must not be negative")


def _validate_non_negative_integer(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordValidationError(f"{field} must be an integer")
    if value < 0:
        raise RecordValidationError(f"{field} must not be negative")


def _validate_non_empty_string(value, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RecordValidationError(f"{field} must be a non-empty string")


def _validate_boolean(value, field: str) -> None:
    if not isinstance(value, bool):
        raise RecordValidationError(f"{field} must be a boolean")


def _validate_fitness_v1(data: dict) -> dict:
    validators = {
        "activity": _validate_non_empty_string,
        "steps": _validate_non_negative_integer,
        "duration_minutes": _validate_non_negative_number,
        "distance_km": _validate_non_negative_number,
        "repetitions": _validate_non_negative_integer,
        "sets": _validate_non_negative_integer,
        "completed": _validate_boolean,
    }
    unknown = sorted(set(data) - set(validators))
    if unknown:
        raise RecordValidationError(f"unknown fitness fields: {', '.join(unknown)}")
    if not data:
        raise RecordValidationError("fitness data must contain at least one field")
    for field, value in data.items():
        validators[field](value, field)
    normalized = dict(data)
    if "activity" in normalized:
        normalized["activity"] = normalized["activity"].strip()
    return normalized


SCHEMA_VALIDATORS = {
    ("fitness", 1): _validate_fitness_v1,
}


def _validate_data(record_type: str, schema_version: int, data) -> dict:
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        raise RecordValidationError("schema_version must be an integer greater than or equal to 1")
    if not isinstance(data, dict):
        raise RecordValidationError("data must be a JSON object")
    validator = SCHEMA_VALIDATORS.get((record_type, schema_version))
    if not validator:
        raise RecordValidationError(
            f"unsupported record type or schema version: {record_type} v{schema_version}"
        )
    return validator(data)


def _row_to_record(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "record_type": row["record_type"],
        "occurred_at": row["occurred_at"],
        "local_date": row["local_date"],
        "timezone": row["timezone"],
        "data": json.loads(row["data_json"]),
        "schema_version": row["schema_version"],
        "note": row["note"],
        "source": row["source"],
        "source_agent": row["source_agent"],
        "source_run_id": row["source_run_id"],
        "dedupe_key": row["dedupe_key"],
        "created_at": row["created_at"],
    }


def add_record(
    user_id: str,
    record_type: str,
    occurred_at: str,
    data: dict,
    timezone_name: str = DEFAULT_TIMEZONE,
    schema_version: int = 1,
    note: Optional[str] = None,
    source: str = "manual",
    source_agent: Optional[str] = None,
    source_run_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
) -> dict:
    """新增流水；有相同 dedupe_key 时返回原记录。"""
    normalized_user = _required_text(user_id, "user_id")
    normalized_type = _required_text(record_type, "record_type").lower()
    zone = _parse_timezone(timezone_name)
    occurred = _parse_aware_datetime(occurred_at, "occurred_at")
    occurred_utc = occurred.astimezone(timezone.utc).isoformat()
    local_date = occurred.astimezone(zone).date().isoformat()
    normalized_data = _validate_data(normalized_type, schema_version, data)
    normalized_source = _required_text(source, "source")
    normalized_dedupe = dedupe_key.strip() if isinstance(dedupe_key, str) else None
    if normalized_dedupe == "":
        normalized_dedupe = None
    record_id = str(uuid.uuid4())
    created_at = _now()
    payload = json.dumps(normalized_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    init_db()

    with get_conn() as conn:
        if normalized_dedupe:
            existing = conn.execute(
                """SELECT * FROM records
                   WHERE user_id = ? AND record_type = ? AND dedupe_key = ?""",
                (normalized_user, normalized_type, normalized_dedupe),
            ).fetchone()
            if existing:
                return {"id": existing["id"], "status": "exists", "record": _row_to_record(existing)}
        try:
            conn.execute(
                """INSERT INTO records
                   (id, user_id, record_type, occurred_at, local_date, timezone,
                    data_json, schema_version, note, source, source_agent,
                    source_run_id, dedupe_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id,
                    normalized_user,
                    normalized_type,
                    occurred_utc,
                    local_date,
                    zone.key,
                    payload,
                    schema_version,
                    note,
                    normalized_source,
                    source_agent,
                    source_run_id,
                    normalized_dedupe,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            if not normalized_dedupe:
                raise
            existing = conn.execute(
                """SELECT * FROM records
                   WHERE user_id = ? AND record_type = ? AND dedupe_key = ?""",
                (normalized_user, normalized_type, normalized_dedupe),
            ).fetchone()
            if not existing:
                raise
            return {"id": existing["id"], "status": "exists", "record": _row_to_record(existing)}

    with get_conn() as conn:
        stored = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
    if not stored:
        raise RuntimeError("record was not persisted")
    return {"id": record_id, "status": "created", "record": _row_to_record(stored)}


def query_records(
    user_id: str,
    record_type: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    local_date: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """按用户、类型和时间查询流水；时间范围为 [start, end)。"""
    normalized_user = _required_text(user_id, "user_id")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_LIMIT:
        raise RecordValidationError(f"limit must be between 1 and {MAX_LIMIT}")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise RecordValidationError("offset must not be negative")

    sql = "SELECT * FROM records WHERE user_id = ?"
    params: list = [normalized_user]
    if record_type is not None:
        normalized_type = _required_text(record_type, "record_type").lower()
        sql += " AND record_type = ?"
        params.append(normalized_type)
    if start is not None:
        sql += " AND occurred_at >= ?"
        params.append(_utc_iso(start, "start"))
    if end is not None:
        sql += " AND occurred_at < ?"
        params.append(_utc_iso(end, "end"))
    if start is not None and end is not None:
        if _parse_aware_datetime(start, "start").astimezone(timezone.utc) >= _parse_aware_datetime(end, "end").astimezone(timezone.utc):
            raise RecordValidationError("start must be earlier than end")
    if local_date is not None:
        try:
            normalized_date = datetime.strptime(local_date, "%Y-%m-%d").date().isoformat()
        except (TypeError, ValueError) as exc:
            raise RecordValidationError("local_date must use YYYY-MM-DD") from exc
        sql += " AND local_date = ?"
        params.append(normalized_date)
    sql += " ORDER BY occurred_at DESC, created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    init_db()
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def summarize_records(
    user_id: str,
    record_type: str = "fitness",
    start: Optional[str] = None,
    end: Optional[str] = None,
    local_date: Optional[str] = None,
) -> dict:
    """对 fitness v1 的固定数字字段做基础汇总。"""
    normalized_type = _required_text(record_type, "record_type").lower()
    if normalized_type != "fitness":
        raise RecordValidationError("summary currently supports fitness only")
    rows = []
    offset = 0
    while True:
        page = query_records(
            user_id=user_id,
            record_type=normalized_type,
            start=start,
            end=end,
            local_date=local_date,
            limit=MAX_LIMIT,
            offset=offset,
        )
        rows.extend(page)
        if len(page) < MAX_LIMIT:
            break
        offset += MAX_LIMIT
    totals = {
        "steps": 0,
        "duration_minutes": 0,
        "distance_km": 0,
        "repetitions": 0,
        "sets": 0,
    }
    for row in rows:
        data = row["data"]
        for field in totals:
            totals[field] += data.get(field, 0)
    return {
        "user_id": _required_text(user_id, "user_id"),
        "record_type": normalized_type,
        "start": _utc_iso(start, "start") if start is not None else None,
        "end": _utc_iso(end, "end") if end is not None else None,
        "local_date": local_date,
        "record_count": len(rows),
        "active_days": len({row["local_date"] for row in rows}),
        "total_steps": totals["steps"],
        "total_duration_minutes": totals["duration_minutes"],
        "total_distance_km": totals["distance_km"],
        "total_repetitions": totals["repetitions"],
        "total_sets": totals["sets"],
    }
