# Phase W0-F2 定向修正报告

日期：2026-09-28  
基线 HEAD：`a7162bca9454fa43b5950a2414670983fe180e56`  
输入：独立复核 `W0_F1_INDEPENDENT_REVIEW_BLOCKED`（R1–R6）

## 状态

```
W0_F2_IMPLEMENTATION_PASS              ← 见 .runtime/runs/*/w0_f2_gate_summary.json
INDEPENDENT_REVIEW_PENDING
OFFLINE_AUTOMATION_W0_PASS             ← 历史 W0 摘要保留
REAL_WECHAT_ACCEPTANCE_PENDING
WINDOWS_UI_NOT_TESTED
REAL_SEND_NOT_TESTED
```

历史 `W0_F1_IMPLEMENTATION_PASS` / 独立方 BLOCK 结论 **不追改**，由新一轮复核裁定。

## 缺陷修复摘要

| ID | 修复 |
|----|------|
| **R1** | `claim_token` + `recover_running_task_cas`；恢复审计 `recovery_audit`；禁止按 id 无条件 force |
| **R2** | `PidLiveness` ALIVE/DEAD/UNKNOWN；Windows ctypes 原型；权限/查询失败→UNKNOWN；RUNNING 计数保守阻断 |
| **R3** | `execute` 异常→UNKNOWN；`complete_task_if_owner` 失败→`OWNERSHIP_LOST`；当前 `attempt_no` 判定 started |
| **R4** | 严格 `seq`/`isSelf`/`type`；`semantic_fingerprint` + `identity_conflicts`；Go 解码拒绝 `_internal_sim_message_id` |
| **R5** | 补查 URL 传递 `sender`/`keyword`；失败不推进 checkpoint；Strict stub 校验 talker/limit/time/sender/keyword |
| **R6** | gate 解析 **junit.xml**；`REQUIRED_TEST_FUNCTIONS` 缺失/skip/fail 即 BLOCKED |

## 验收（本机 Windows / Python 3.14.7）

```powershell
python -m pytest -q tests
python -m wechat_automation gate
```

- **38 passed**（原 30 回归 + F1/F2 定向）
- 子进程：F1 crash/recover、F2 R1 CAS 交错
- **未声称**：Linux 复核等价、Windows 句柄截断真机复现、真实微信

## 证据映射

见 `automation/.local-validation/W0_F2_Review_Package.zip` 内 `F2_DEFECT_EVIDENCE.md`（打包脚本生成）。

## 仍待独立复核

- 双 worker 重叠区间 `peak_active=1`（文件 tracker，非 OS 级通道锁）
- PID 复用与进程创建时间实例身份（当前 conservative UNKNOWN）
- 真实 chatlog API 与 Webhook 真机

---

## W0 阶段收口（追加，2026-09-29，不修订上文）

F2 结论与证据保留；后续 F3/F3-C4 已收口。见 [W0_Closure.md](W0_Closure.md)（**OFFLINE_AUTOMATION_W0_PASS**）。
