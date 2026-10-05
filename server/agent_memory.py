"""Read only the authenticated presenter's prior structured agent memory."""
from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
_METRIC_NAME = re.compile(r"^[^\s\x00-\x1f]{1,80}$")


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validated_memory(raw: dict) -> dict | None:
    """Strip prose and malformed data before it reaches decision prompts/tools."""
    if not isinstance(raw, dict):
        return None
    if not all(isinstance(raw.get(key), str) and len(raw[key]) <= limit
               for key, limit in (("sessionId", 100), ("modelVersion", 100),
                                  ("metricDefinitionVersion", 100), ("sceneLabel", 120))):
        return None
    if not _finite_number(raw.get("durationMs")) or raw["durationMs"] <= 0:
        return None
    if not isinstance(raw.get("candidates"), list):
        return None
    candidates = []
    for item in raw["candidates"][:5]:
        if not isinstance(item, dict) or not isinstance(item.get("candidateId"), str):
            continue
        value, count, quality = (item.get("observedValue"), item.get("observationCount"),
                                 item.get("measurementQuality"))
        if (not isinstance(item.get("metric"), str) or not _METRIC_NAME.fullmatch(item["metric"])
                or not _finite_number(value)
                or not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 7200
                or not _finite_number(quality) or not 0 <= quality <= 1):
            continue
        candidates.append({"candidateId": item["candidateId"][:100], "metric": item["metric"],
                           "observedValue": value, "observationCount": count,
                           "measurementQuality": quality})
    goal = raw.get("focusGoal")
    focus = ({"candidateId": goal.get("candidateId"), "metric": goal.get("metric")}
             if isinstance(goal, dict) and isinstance(goal.get("candidateId"), str)
             and isinstance(goal.get("metric"), str) and _METRIC_NAME.fullmatch(goal["metric"]) else None)
    return {"sessionId": raw["sessionId"], "modelVersion": raw["modelVersion"],
            "metricDefinitionVersion": raw["metricDefinitionVersion"],
            "sceneLabel": raw["sceneLabel"], "durationMs": int(raw["durationMs"]),
            "candidates": candidates, "focusGoal": focus}


@lru_cache(maxsize=1)
def model_version() -> str:
    root = Path(__file__).resolve().parents[1] / "weights"
    names = ("student_kd_best.pt", "cbm_bi_residual_v2_w0.8_lc4.0_best.pt")
    digest = hashlib.sha256()
    try:
        for name in names:
            with (root / name).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    except OSError:
        return "unknown"
    return "student-cbm-" + digest.hexdigest()[:16]


def load_recent_memory(supabase_url: str, publishable_key: str, token: str,
                       user_id: str | None = None) -> dict | None:
    """RLS protects the query; a user filter is an additional guard when known."""
    if not supabase_url or not publishable_key or not token:
        return None
    params = {"select": "id,agent_report", "order": "session_date.desc", "limit": "5"}
    if user_id:
        params["user_id"] = f"eq.{user_id}"
    try:
        response = requests.get(
            f"{supabase_url}/rest/v1/presentation_records",
            params=params,
            headers={"apikey": publishable_key, "Authorization": f"Bearer {token}"},
            timeout=(3, 5),
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            return None
        memories = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            report = row.get("agent_report")
            memory = report.get("agentMemory") if isinstance(report, dict) else None
            if isinstance(memory, dict) and memory.get("sessionId") == report.get("sessionId"):
                validated = _validated_memory(memory)
                if validated is not None:
                    memories.append(validated)
        if memories:
            return {**memories[0], "history": memories}
    except (requests.RequestException, ValueError, TypeError) as error:
        logger.warning("Previous agent memory unavailable (%s)", type(error).__name__)
    return None
