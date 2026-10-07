from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wechat_automation.contracts import ExecutionResult, ReplyTask, TaskStatus

ALLOWED_MOCK_OUTCOMES = frozenset(
    {
        "success",
        "target_missing",
        "ambiguous_name",
        "focus_fail",
        "transient",
        "unknown_after_start",
        "crash_after_side_effect",
        "raise_exception",
        "barrier_hold",
    }
)


@dataclass
class MockExecutorConfig:
    default_outcome: str = "success"
    target_map: dict[str, str] | None = None
    scenario_overrides: dict[str, str] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MockExecutorConfig":
        outcome = str(data.get("default_outcome", "success"))
        if outcome not in ALLOWED_MOCK_OUTCOMES:
            raise ValueError(f"unknown mock outcome: {outcome}")
        overrides = dict(data.get("scenario_overrides") or {})
        for v in overrides.values():
            if str(v) not in ALLOWED_MOCK_OUTCOMES:
                raise ValueError(f"unknown mock outcome override: {v}")
        return cls(
            default_outcome=outcome,
            target_map=dict(data.get("target_map") or {}),
            scenario_overrides=overrides,
        )


class MockExecutor:
    """Simulation-only executor. Does not touch WeChat UI."""

    def __init__(self, cfg: MockExecutorConfig) -> None:
        self.cfg = cfg

    def _outcome_for(self, task: ReplyTask) -> str:
        if self.cfg.scenario_overrides:
            key = f"{task.conversation_id}:{task.event_key}"
            if key in self.cfg.scenario_overrides:
                return self.cfg.scenario_overrides[key]
            if task.conversation_id in self.cfg.scenario_overrides:
                return self.cfg.scenario_overrides[task.conversation_id]
        return self.cfg.default_outcome

    def _run_concurrency_probe(self, phase: str, task: ReplyTask) -> None:
        mod_name = os.environ.get("W0_CONCURRENCY_PROBE")
        if not mod_name:
            return
        import importlib

        mod = importlib.import_module(mod_name)
        hook = getattr(mod, phase, None)
        if callable(hook):
            hook(task)

    def execute(self, task: ReplyTask) -> ExecutionResult:
        self._run_concurrency_probe("before_execute", task)
        try:
            return self._execute_inner(task)
        finally:
            self._run_concurrency_probe("after_execute", task)

    def _maybe_barrier_hold(self, task: ReplyTask) -> None:
        hold_id = os.environ.get("W0_BARRIER_TASK_ID")
        sync = os.environ.get("W0_BARRIER_SYNC_FILE")
        if not hold_id or str(task.id) != hold_id or not sync:
            return
        p = Path(sync)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("entered", encoding="utf-8")
        for _ in range(6000):
            if p.read_text(encoding="utf-8").strip() == "release":
                return
            import time

            time.sleep(0.05)

    def _execute_inner(self, task: ReplyTask) -> ExecutionResult:
        self._maybe_barrier_hold(task)
        outcome = self._outcome_for(task)
        if outcome not in ALLOWED_MOCK_OUTCOMES:
            return ExecutionResult(
                success=False,
                status=TaskStatus.FAILED,
                detail="mock_unknown_outcome",
            )

        targets = self.cfg.target_map or {}
        mapped = targets.get(task.conversation_id)

        if outcome == "target_missing":
            return ExecutionResult(success=False, status=TaskStatus.FAILED, detail="mock_target_missing")
        if outcome == "ambiguous_name":
            return ExecutionResult(success=False, status=TaskStatus.FAILED, detail="mock_ambiguous_target")
        if outcome == "focus_fail":
            return ExecutionResult(success=False, status=TaskStatus.FAILED, detail="mock_focus_failure")
        if outcome == "transient" and task.retry_count < 1:
            return ExecutionResult(success=False, status=TaskStatus.FAILED, detail="mock_transient_error")
        if outcome == "unknown_after_start":
            return ExecutionResult(success=False, status=TaskStatus.UNKNOWN, detail="mock_result_unknown")
        if outcome == "raise_exception":
            raise RuntimeError("mock_executor_raise")
        if outcome == "barrier_hold":
            sync = os.environ.get("W0_BARRIER_SYNC_FILE")
            if sync:
                p = Path(sync)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("entered", encoding="utf-8")
                for _ in range(6000):
                    if p.read_text(encoding="utf-8").strip() == "release":
                        break
                    import time

                    time.sleep(0.05)
            mapped = (self.cfg.target_map or {}).get(task.conversation_id)
            if mapped is None:
                return ExecutionResult(
                    success=False,
                    status=TaskStatus.FAILED,
                    detail="mock_no_target_mapping",
                )
            return ExecutionResult(
                success=True,
                status=TaskStatus.SIMULATED_SUCCEEDED,
                detail=f"mock_sent_to:{mapped}",
            )
        if outcome == "crash_after_side_effect":
            marker = os.environ.get("W0_SIM_SIDE_EFFECT_MARKER")
            if marker:
                Path(marker).write_text("simulated_side_effect=1", encoding="utf-8")
            os._exit(23)

        if mapped is None:
            return ExecutionResult(
                success=False,
                status=TaskStatus.FAILED,
                detail="mock_no_target_mapping",
            )

        return ExecutionResult(
            success=True,
            status=TaskStatus.SIMULATED_SUCCEEDED,
            detail=f"mock_sent_to:{mapped}",
        )


class WindowsExecutor:
    def __init__(self) -> None:
        raise NotImplementedError(
            "WindowsExecutor is NOT implemented / NOT tested (W0 simulation only)"
        )
