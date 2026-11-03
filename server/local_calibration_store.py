"""Local-preview persistence with the same calibration fields as Supabase."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class LocalCalibrationStore:
    def __init__(self, path, user_id):
        self.path, self.user_id = Path(path), user_id

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else None

    def write(self, row):
        if row.get("user_id") != self.user_id:
            raise ValueError("Calibration belongs to another user")
        score, count, version = row.get("baseline_score"), row.get("sample_count"), row.get("model_version")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise ValueError("Invalid initial score")
        if isinstance(count, bool) or not isinstance(count, int) or not 3 <= count <= 100:
            raise ValueError("At least three valid initial windows are required")
        if not isinstance(version, str) or not version or len(version) > 100:
            raise ValueError("Model version is required")
        datetime.fromisoformat(row["calibrated_at"].replace("Z", "+00:00"))
        saved = {key: row.get(key) for key in ("user_id", "baseline_score", "sample_count", "model_version", "calibrated_at", "last_prompted_at")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(saved, allow_nan=False))
        temporary.replace(self.path)
        return saved

    def prompted(self, at):
        datetime.fromisoformat(at.replace("Z", "+00:00"))
        row = self.read()
        if row:
            self.write({**row, "last_prompted_at": at})
