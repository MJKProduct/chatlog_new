from __future__ import annotations

import sys

# Stable pytest nodeids — gate must collect and pass each (no skip/xfail/xpass/error).
REQUIRED_TEST_NODEIDS = frozenset(    {
        "tests/test_w0_acceptance.py::test_01_single_message_happy_path",
        "tests/test_w0_acceptance.py::test_02_duplicate_event_single_task",
        "tests/test_w0_acceptance.py::test_03_same_content_different_ids",
        "tests/test_w0_acceptance.py::test_04_replay_after_success_no_reexecute",
        "tests/test_w0_acceptance.py::test_05_self_message_no_loop",
        "tests/test_w0_acceptance.py::test_06_filtered_cases",
        "tests/test_w0_acceptance.py::test_07_ambiguous_target_blocks",
        "tests/test_w0_acceptance.py::test_08_two_workers_mutex",
        "tests/test_w0_acceptance.py::test_09_transient_retry",
        "tests/test_w0_acceptance.py::test_10_unknown_no_resend",
        "tests/test_w0_acceptance.py::test_11_transaction_rollback",
        "tests/test_w0_acceptance.py::test_12_backfill_dedupe_with_webhook",
        "tests/test_w0_acceptance.py::test_13_pagination_boundaries",
        "tests/test_w0_acceptance.py::test_14_invalid_json_isolated",
        "tests/test_w0_acceptance.py::test_15_live_mode_rejected",
        "tests/test_w0_acceptance.py::test_16_simulation_flags",
        "tests/test_w0_f1_fixes.py::test_f1_recover_claimed_not_started",
        "tests/test_w0_f1_fixes.py::test_f1_recover_unknown_after_side_effect",
        "tests/test_w0_f1_fixes.py::test_f1_queue_continues_after_unknown",
        "tests/test_w0_f1_fixes.py::test_f2_go_faithful_seq_creates_task",
        "tests/test_w0_f1_fixes.py::test_f2_invalid_seq_zero_collapses",
        "tests/test_w0_f1_fixes.py::test_f2_isself_must_be_bool",
        "tests/test_w0_f1_fixes.py::test_f2_no_seq_no_task",
        "tests/test_w0_f1_fixes.py::test_f2_same_second_different_seq",
        "tests/test_w0_f1_fixes.py::test_f3_pagination_failure_keeps_checkpoint",
        "tests/test_w0_f1_fixes.py::test_f3_stub_rejects_slash_date_range",
        "tests/test_w0_f1_fixes.py::test_f3_time_range_uses_tilde",
        "tests/test_w0_f1_fixes.py::test_f4_checkpoint_isolated_per_talker",
        "tests/test_w0_f1_fixes.py::test_f6_backfill_requires_transport",
        "tests/test_w0_f1_fixes.py::test_f6_rejects_simulation_false",
        "tests/test_w0_f2_fixes.py::test_f2_r1_recovery_cas_no_clobber",
        "tests/test_w0_f2_fixes.py::test_f2_r3_executor_exception_unknown",
        "tests/test_w0_f2_fixes.py::test_f2_seq_conflict_recorded",
        "tests/test_w0_f2_fixes.py::test_f2_webhook_rejects_internal_sim_id",
        "tests/test_w0_f2_fixes.py::test_f2_two_round_late_backfill",
        "tests/test_w0_f2_fixes.py::test_f2_liveness_current_process_alive",
        "tests/test_w0_f3_fixes.py::test_f3_same_batch_conflict_blocks_executor",
        "tests/test_w0_f3_fixes.py::test_f3_late_conflict_cancels_pending",
        "tests/test_w0_f3_fixes.py::test_f3_two_process_peak_active_one",
        "tests/test_w0_f3_fixes.py::test_f3_gate_eval_missing_required_nodeid",
        "tests/test_w0_f3_c4_gate_matrix.py::test_c4_gate_matrix_passes_on_happy_subset",
    }
)

# Windows-only evidence (excluded from Linux gate required set).
WINDOWS_ONLY_REQUIRED_NODEIDS = frozenset(
    {
        "tests/test_w0_f3_fixes.py::test_f3_two_process_peak_active_one",
        "tests/test_w0_f3_fixes.py::test_f3_liveness_openprocess_access_denied_unknown",
    }
)


def effective_required_nodeids() -> frozenset[str]:
    if sys.platform == "win32":
        return REQUIRED_TEST_NODEIDS
    return REQUIRED_TEST_NODEIDS - WINDOWS_ONLY_REQUIRED_NODEIDS


# Backward-compatible names (documentation only).
REQUIRED_TEST_FUNCTIONS = frozenset(n.split("::")[-1] for n in REQUIRED_TEST_NODEIDS)