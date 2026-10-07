# W0-F3 固定收口报告

日期：2026-09-28  
基线 HEAD：`a7162bca9454fa43b5950a2414670983fe180e56`  
前置状态：`W0_F2_INDEPENDENT_REVIEW_BLOCKED` / `OFFLINE_AUTOMATION_W0_BLOCKED`（独立复核口径）

## 门禁结论（机器摘要）

以最新 `automation/.runtime/runs/gate-f3-*/w0_f3_gate_summary.json` 为准：

- **W0_F3_IMPLEMENTATION_PASS** + **INDEPENDENT_REVIEW_PENDING**（当 `tests_passed=true` 且 `required_tests.required_ok=true`）
- 历史 `w0_gate_summary.json`、`w0_f1_gate_summary.json`、`w0_f2_gate_summary.json` **未覆盖**

本地命令：

```powershell
cd automation
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m wechat_automation gate
```

## 四组收口映射（C1–C4）

### C1 身份冲突实际隔离 + 字段校验

| 项 | 实现 | 测试 nodeid | 证据 |
|---|---|---|---|
| 同事务冲突登记并取消 PENDING | `store/sqlite_store.py` `insert_event_if_new` + `isolate_pending_tasks_for_event` | `tests/test_w0_f3_fixes.py::test_f3_same_batch_conflict_blocks_executor` | 冲突后 `CANCELLED`，`execution_finished` 增量 0 |
| 晚到冲突取消未执行 | `pipeline/ingest.py` | `tests/test_w0_f3_fixes.py::test_f3_late_conflict_cancels_pending` | PENDING→CANCELLED |
| claim/执行前阻断 | `claim_next_pending_task` 排除冲突/隔离；`worker.is_task_execution_blocked` | 同上 + `test_f3_late_conflict_cancels_pending` | 无 executor 完成记录 |
| sender/type/content 严格校验 | `message_identity.py` + `chatlog_decoder.py` + `ingest_blocked` | `tests/test_w0_f3_fixes.py::test_f3_field_validation_blocks_task_creation` | `tasks_created=0` |
| isSelf 进入语义指纹 | `semantic_fingerprint(..., is_self=)` | `tests/test_w0_f3_fixes.py::test_f3_isself_affects_fingerprint_not_display_fields` | 指纹差异 |

**剩余限制**：seq 全局唯一仍为待真机契约；RUNNING/已终态任务在冲突到达时不回溯改写。

### C2 Windows 错误码与 PID 实例

| 项 | 实现 | 测试 nodeid | 证据 |
|---|---|---|---|
| `WinDLL(..., use_last_error=True)` | `process_liveness.py` | `tests/test_w0_f2_fixes.py::test_f2_liveness_current_process_alive` | Windows 实测 ALIVE |
| 访问拒绝→UNKNOWN | `check_pid_liveness` | `tests/test_w0_f3_fixes.py::test_f3_liveness_openprocess_access_denied_unknown` | **注入** OpenProcess 拒绝 |
| 子进程退出→DEAD | `check_pid_liveness` | `tests/test_w0_f3_fixes.py::test_f3_liveness_dead_child_process` | Windows 实测 |
| 创建时间实例标记 | `owner_pid_instance` + `get_process_instance_marker` | `tests/test_w0_f3_fixes.py::test_f3_pid_instance_mismatch_unknown` | UNKNOWN 时不放行第二 claim |
| recovery/claim 一致 | `recovery.py` + `_count_active_running` | `tests/test_w0_f2_fixes.py::test_f2_r1_recovery_cas_no_clobber` | CAS 不 clobber 新 owner |

**剩余限制**：PID 复用且无法读取实例标记时仍为 UNKNOWN 保守隔离，需人工介入，不宣称自动全面恢复。

### C3 真实双进程竞争与探针

| 项 | 实现 | 测试 nodeid | 证据 |
|---|---|---|---|
| 双进程 + 执行区间屏障 | `executor/mock.py` `W0_BARRIER_*` + `tests/concurrency_probe.py` | `tests/test_w0_f3_fixes.py::test_f3_two_process_peak_active_one` | `peak==1`，两任务各执行 1 次 |
| 探针负对照 | `concurrency_probe.py` | `tests/test_w0_f3_fixes.py::test_f3_probe_negative_control_allows_peak_two` | 无锁叠加时 peak=2 |
| 移除生产 tracker | 删除 `MockExecutor._track_active` | — | 源码 |
| **分类更正** | 报告/门禁 `historical_notes` | `test_f2_peak_active_one` / `test_f2_r1_recovery_cas_no_clobber` | **顺序/单进程模拟**，非并发证明 |
| 正式并发证据 | — | `test_f3_two_process_peak_active_one` | **子进程 + Manager 锁计数** |

### C4 必需门禁负例 + 稳定 nodeid

| 项 | 实现 | 测试 nodeid | 证据 |
|---|---|---|---|
| 完整 nodeid 校验 | `cli/required_tests.py` `REQUIRED_TEST_NODEIDS` + `cli/gate_eval.py` | gate `w0_f3_gate_summary.json` → `required_tests` | 缺失/失败→BLOCKED |
| 独立负例集（临时目录） | `tests/test_w0_f3_gate_negative.py` | 同文件内 4 个负例 | 不污染主 `tests/` 收集 |
| F3 gate 产物 | `cli/main.py` `gate-f3` / `w0_f3_gate_summary.json` | `.runtime/runs/gate-f3-*` | 新 run_id |

## 测试分类说明（重要）

- `test_08_two_workers_mutex`：两进程互斥与终态，**未测量 executor 重叠峰值**。
- `test_f2_peak_active_one`：单进程顺序执行，**不是** cross-process peak 证据。
- `test_f2_r1_recovery_cas_no_clobber`：同进程 CAS 交错，**不是**子进程并发 recovery 证明。
- **并发 peak==1 的正式证据**：仅 `test_f3_two_process_peak_active_one`。

## 交付物

| 路径 | 说明 |
|---|---|
| `docs/tasks/W0_F3_Report.md` | 本报告 |
| `automation/.runtime/runs/gate-f3-*/w0_f3_gate_summary.json` | 机器门禁摘要 |
| 同目录 `pytest.log`、`junit.xml` | 完整验证输出 |
| `automation/.local-validation/W0_F3_Review_Package.zip` | 独立复核包 |

## 未进入范围

W1、真实微信/UI、Go 核心修改、git commit/push、历史门禁文件覆盖。

---

## W0 阶段收口（追加，2026-09-29，不修订上文）

C1–C3 结论保留；后续 C4 门禁补丁与独立复核已通过。离线阶段定稿见 [W0_Closure.md](W0_Closure.md)（**OFFLINE_AUTOMATION_W0_PASS**）。
