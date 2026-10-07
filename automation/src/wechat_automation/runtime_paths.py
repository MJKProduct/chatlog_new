from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def new_run_id(prefix: str = "run") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{ts}-{uuid4().hex[:8]}"


def allocate_run_dir(runtime_root: Path, prefix: str = "run") -> tuple[str, Path]:
    run_id = new_run_id(prefix)
    path = runtime_root / "runs" / run_id
    path.mkdir(parents=True, exist_ok=False)
    return run_id, path


def write_latest_pointer(runtime_root: Path, name: str, run_id: str, path: Path) -> None:
    latest_dir = runtime_root / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    payload = {"run_id": run_id, "path": str(path), "updated_at": datetime.now(timezone.utc).isoformat()}
    (latest_dir / f"{name}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
