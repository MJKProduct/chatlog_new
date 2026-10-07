from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

from wechat_automation.config import ensure_runtime_dirs, load_config
from wechat_automation.demo.scenarios import run_happy_path
from wechat_automation.pipeline.ingest import ingest_webhook_batch
from wechat_automation.runtime_paths import allocate_run_dir, write_latest_pointer
from wechat_automation.scheduler.worker import run_worker_once
from wechat_automation.source.fixture_source import load_webhook_fixture
from wechat_automation.cli.gate_eval import evaluate_gate_from_run, run_pytest_for_gate
from wechat_automation.cli.required_tests import (
    WINDOWS_ONLY_REQUIRED_NODEIDS,
    effective_required_nodeids,
)
from wechat_automation.store.sqlite_store import SQLiteStore

REQUIREMENT_TEST_MAP = {
    "happy_path": ["test_01_single_message_happy_path", "test_f2_go_faithful_seq_creates_task"],
    "dedupe": ["test_02_duplicate_event_single_task"],
    "identity_seq": ["test_03_same_content_different_ids", "test_f2_same_second_different_seq"],
    "recovery_running": ["test_f1_recover_claimed_not_started", "test_f1_recover_unknown_after_side_effect"],
    "backfill_time_cursor": ["test_13_pagination_boundaries", "test_f4_checkpoint_isolated_per_talker"],
    "mode_guard": ["test_15_live_mode_rejected", "test_f6_rejects_simulation_false"],
}


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[3] / "configs" / "offline.example.json"


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    if args.offline and cfg_path.exists():
        cfg = load_config(cfg_path)
        ensure_runtime_dirs(cfg)
        probe_db = cfg.runtime_dir / "doctor_probe.db"
        if probe_db.exists():
            probe_db.unlink()
        store = SQLiteStore(probe_db)
        with store.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO probe (id) VALUES (1)")
        probe_db.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": cfg.mode,
                    "simulation": cfg.simulation,
                    "python_version": platform.python_version(),
                    "runtime_os": platform.system(),
                    "sqlite_writable": True,
                    "wechat_probe": "skipped_offline",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(json.dumps({"ok": False, "error": "use --offline with valid config"}))
    return 1


def cmd_demo(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    if args.scenario != "happy_path":
        print(json.dumps({"ok": False, "error": f"unknown scenario: {args.scenario}"}))
        return 1
    result = run_happy_path(cfg_path)
    ok = result["summary"].get("tasks_by_status", {}).get("SIMULATED_SUCCEEDED", 0) == 1
    print(json.dumps({"ok": ok, "simulation": True, **result}, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


def cmd_replay(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    ensure_runtime_dirs(cfg)
    store = SQLiteStore(cfg.database_path)
    fixture = Path(args.fixture)
    envelope = load_webhook_fixture(fixture)
    stats = ingest_webhook_batch(cfg, store, envelope)
    processed = 0
    if args.run_worker:
        processed = run_worker_once(cfg, store, max_tasks=args.max_tasks)
    print(
        json.dumps(
            {
                "ok": True,
                "simulation": True,
                "ingest": stats,
                "worker_processed": processed,
                "summary": store.status_summary(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    ensure_runtime_dirs(cfg)
    store = SQLiteStore(cfg.database_path)
    if args.once:
        count = run_worker_once(cfg, store, max_tasks=args.max_tasks)
    else:
        count = run_worker_once(cfg, store, max_tasks=10_000)
    print(json.dumps({"ok": True, "processed": count, "simulation": True}, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    store = SQLiteStore(cfg.database_path)
    payload = {
        "mode": cfg.mode,
        "simulation": cfg.simulation,
        "account_id": cfg.account_id,
        "runtime_os": platform.system(),
        "real_wechat": "NOT_TESTED",
        "windows_ui": "NOT_TESTED",
        **store.status_summary(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload)
    return 0


def _repo_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_default_config_path().parents[1],
            text=True,
        )
        return out.strip()
    except Exception:
        return None


def _parse_pytest_summary(output: str) -> dict:
    collected = 0
    passed = 0
    failed = 0
    skipped = 0
    m = re.search(r"(\d+) passed", output)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", output)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) skipped", output)
    if m:
        skipped = int(m.group(1))
    collected = passed + failed + skipped
    return {
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def cmd_gate(args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[3]
    cfg = load_config(Path(args.config))
    ensure_runtime_dirs(cfg)
    run_id, run_dir = allocate_run_dir(cfg.runtime_dir, prefix="gate-f3-c4")
    log_path = run_dir / "pytest.log"
    report_path = run_dir / "gate_report.json"
    verdict_path = run_dir / "gate_verdict.json"
    junit_path = run_dir / "junit.xml"

    gate_run = run_pytest_for_gate(
        root, ["tests"], report_path, log_path=log_path, junit_path=junit_path
    )
    counts = gate_run.counts
    req = evaluate_gate_from_run(gate_run, effective_required_nodeids())
    passed = bool(req.get("gate_pass"))

    windows_only_status = "EXERCISED" if platform.system() == "Windows" else "NOT_TESTED"
    summary = {
        "simulation": True,
        "run_id": run_id,
        "runtime_os": platform.system(),
        "python_version": platform.python_version(),
        "repo_head": _repo_head(),
        "pytest": counts,
        "gate_evaluation": req,
        "required_tests": req,
        "requirement_test_map": REQUIREMENT_TEST_MAP,
        "windows_only_required": sorted(WINDOWS_ONLY_REQUIRED_NODEIDS),
        "windows_only_gate_evidence": windows_only_status,
        "tests_passed": passed,
        "historical_notes": [
            "w0_gate_summary.json preserved",
            "w0_f1_gate and w0_f2_gate summaries preserved under .runtime/runs/",
            "w0_f3_gate summaries preserved under .runtime/runs/ (not overwritten)",
            "test_f2_peak_active_one and test_f2_r1_recovery_cas_no_clobber are sequential simulation, not cross-process concurrency proof",
            "cross-process peak==1 evidence (Windows): tests/test_w0_f3_fixes.py::test_f3_two_process_peak_active_one",
            "test_f3_probe_sequential_counter_self_check_peak_two is in-process probe self-check, not dual-process negative control",
            "Gate verdict uses structured gate_report.json (wasxfail/xpass), not JUnit alone",
        ],
        "status": "W0_F3_C4_IMPLEMENTATION_PASS" if passed else "W0_F3_C4_BLOCKED",
        "independent_review": "INDEPENDENT_REVIEW_PENDING",
        "real_wechat_acceptance": "REAL_WECHAT_ACCEPTANCE_PENDING",
        "windows_ui": "WINDOWS_UI_NOT_TESTED",
        "real_send": "REAL_SEND_NOT_TESTED",
    }
    summary_path = run_dir / "w0_f3_c4_gate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    verdict_path.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    write_latest_pointer(cfg.runtime_dir, "gate_f3_c4", run_id, run_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wechat-auto")
    p.add_argument("--config", default=str(_default_config_path()))
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor")
    d.add_argument("--offline", action="store_true")
    d.set_defaults(func=cmd_doctor)

    demo = sub.add_parser("demo")
    demo.add_argument("--scenario", default="happy_path")
    demo.set_defaults(func=cmd_demo)

    rep = sub.add_parser("replay")
    rep.add_argument("--fixture", required=True)
    rep.add_argument("--run-worker", action="store_true")
    rep.add_argument("--max-tasks", type=int, default=100)
    rep.set_defaults(func=cmd_replay)

    w = sub.add_parser("worker")
    w.add_argument("--once", action="store_true")
    w.add_argument("--max-tasks", type=int, default=100)
    w.set_defaults(func=cmd_worker)

    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_status)

    g = sub.add_parser("gate")
    g.set_defaults(func=cmd_gate)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    rc = args.func(args)
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
