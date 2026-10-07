from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class KeywordRule:
    rule_id: str
    keywords: list[str]
    reply_text: str


@dataclass
class AppConfig:
    mode: str
    simulation: bool
    account_id: str
    rule_version: str
    runtime_dir: Path
    database_path: Path
    log_dir: Path
    display_timezone: str
    allowed_conversation_ids: list[str]
    keyword_rules: list[KeywordRule]
    executor: str
    mock_executor: dict[str, Any]
    backfill: dict[str, Any]
    worker: dict[str, Any]
    config_path: Path | None = None

    @property
    def is_offline(self) -> bool:
        return self.mode == "offline"

    @property
    def max_retries(self) -> int:
        return int(self.worker.get("max_retries", 3))

    @property
    def lock_ttl_seconds(self) -> int:
        return int(self.worker.get("lock_ttl_seconds", 120))


def _require(data: dict[str, Any], key: str) -> Any:
    if key not in data:
        raise ValueError(f"missing config key: {key}")
    return data[key]


def load_config(path: Path) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    mode = str(_require(raw, "mode"))
    if mode != "offline":
        raise ValueError(f"W0-F1 accepts mode=offline only, got {mode!r}")
    simulation = bool(_require(raw, "simulation"))
    if not simulation:
        raise ValueError("W0-F1 requires simulation=true")
    executor = str(raw.get("executor", "mock"))
    if executor != "mock":
        raise ValueError(f"W0-F1 requires executor=mock, got {executor!r}")

    account_id = str(_require(raw, "account_id")).strip()
    if not account_id:
        raise ValueError("account_id must be non-empty")

    allowed = list(raw.get("allowed_conversation_ids") or [])
    rules_raw = _require(raw, "keyword_rules")
    seen_rule_ids: set[str] = set()
    rules: list[KeywordRule] = []
    for r in rules_raw:
        rule_id = str(r["rule_id"])
        if rule_id in seen_rule_ids:
            raise ValueError(f"duplicate rule_id: {rule_id}")
        seen_rule_ids.add(rule_id)
        keywords = [str(k).strip() for k in r["keywords"]]
        if not keywords or any(not k for k in keywords):
            raise ValueError(f"rule {rule_id} requires non-empty keywords")
        rules.append(
            KeywordRule(
                rule_id=rule_id,
                keywords=keywords,
                reply_text=str(r["reply_text"]),
            )
        )

    max_retries = int(raw.get("worker", {}).get("max_retries", 3))
    if max_retries < 0 or max_retries > 20:
        raise ValueError("max_retries out of allowed range 0..20")

    automation_root = path.resolve().parent.parent if path.parent.name == "configs" else path.resolve().parent
    runtime_rel = Path(str(raw.get("runtime_dir", ".runtime")))
    runtime = runtime_rel if runtime_rel.is_absolute() else automation_root / runtime_rel
    db_raw = Path(str(raw.get("database_path", ".runtime/w0.db")))
    if db_raw.is_absolute():
        database_path = db_raw
    elif str(db_raw).startswith(".runtime") or str(db_raw).startswith("runtime"):
        database_path = automation_root / db_raw
    else:
        database_path = runtime / db_raw.name
    return AppConfig(
        mode=mode,
        simulation=simulation,
        account_id=account_id,
        rule_version=str(_require(raw, "rule_version")),
        runtime_dir=runtime,
        database_path=database_path,
        log_dir=runtime / "logs",
        display_timezone=str(raw.get("display_timezone", "Asia/Shanghai")),
        allowed_conversation_ids=allowed,
        keyword_rules=rules,
        executor=executor,
        mock_executor=dict(raw.get("mock_executor", {})),
        backfill=dict(raw.get("backfill", {})),
        worker=dict(raw.get("worker", {})),
        config_path=path,
    )


def ensure_runtime_dirs(cfg: AppConfig) -> None:
    cfg.runtime_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    cfg.database_path.parent.mkdir(parents=True, exist_ok=True)
