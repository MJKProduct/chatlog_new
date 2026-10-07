"""Cross-process execution overlap probe (test support only)."""

from __future__ import annotations

from typing import Any

_state: dict[str, Any] | None = None


def bind(state: dict[str, Any]) -> None:
    global _state
    _state = state


def before_execute(task) -> None:  # type: ignore[no-untyped-def]
    if _state is None:
        return
    lock = _state["lock"]
    with lock:
        _state["active"] = int(_state.get("active", 0)) + 1
        _state["peak"] = max(int(_state.get("peak", 0)), int(_state["active"]))
        key = f"task_{task.id}_executions"
        _state[key] = int(_state.get(key, 0)) + 1
        _state["observed"] = True


def after_execute(task) -> None:  # type: ignore[no-untyped-def]
    if _state is None:
        return
    lock = _state["lock"]
    with lock:
        _state["active"] = max(0, int(_state.get("active", 0)) - 1)
