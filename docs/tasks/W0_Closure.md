# W0 离线阶段收口

日期：2026-09-29  
Git 基线（工作区未 commit）：`a7162bca9454fa43b5950a2414670983fe180e56`  
**最终技术基线：W0-F3-C4**（离线 Python 自动化环 + 结构化门禁）

## 状态定稿

```text
OFFLINE_AUTOMATION_W0_PASS
W0_F3_C4_INDEPENDENT_REVIEW_PASS
REAL_WECHAT_ACCEPTANCE_PENDING
WINDOWS_UI_NOT_TESTED
REAL_SEND_NOT_TESTED
```

**说明：** 当前完成的是离线调度与 **simulation/mock** 执行底座；真实微信自动化、UI 与发送仍待测试账号与 W1 验收。**W0 功能扩展在此停止。**

---

## 证据摘要（不覆盖历史 run）

| 维度 | 结论 | 证据位置 |
|------|------|----------|
| Windows 执行方全量回归 | **62 passed**（交付包归档；本轮独立方**未**重跑 Windows 全量） | `gate-f3-c4-20260929T015928-175dfd49/` |
| 独立 C4 正负例 | **13 passed**；非 strict XPASS 已正确 **BLOCKED** | 独立环境复跑（见 C4 补丁报告） |
| 结构化门禁重算 | **PASS**，`blocked_reasons` 为空 | `gate_verdict.json` / `w0_f3_c4_gate_summary.json` |
| C1–C3 业务实现 | 与 F3 轮相比**未变**；C4 仅门禁插件与判定模块 | 见下方源码哈希（C1–C3 区） |
| 原始 W0 门禁 | 保留 | `automation/.runtime/w0_gate_summary.json`（未覆盖） |

### 最终门禁 run（Windows 执行方，2026-09-29）

| 字段 | 值 |
|------|-----|
| run_id | `gate-f3-c4-20260929T015928-175dfd49` |
| status | `W0_F3_C4_IMPLEMENTATION_PASS` |
| pytest | 62 collected / 62 passed / 0 failed / 0 skipped / 0 xpassed |
| gate_pass | `true` |
| windows_only_gate_evidence | `EXERCISED`（Linux 门禁应为 `NOT_TESTED`） |
| 指针 | `automation/.runtime/latest/gate_f3_c4.json` |

### 历史门禁 run（保留，供审计对照）

| 阶段 | run_id | 摘要文件 |
|------|--------|----------|
| W0 原始 | （根目录） | `w0_gate_summary.json` |
| W0-F1 | `gate-f1-20260928T090758-267eb2ea` | `w0_f1_gate_summary.json` |
| W0-F2 | `gate-f2-20260928T091706-d5b5fb0e` | `w0_f2_gate_summary.json` |
| W0-F3 | `gate-f3-20260928T173115-8173ed03` | `w0_f3_gate_summary.json` |
| **W0-F3-C4（最终）** | `gate-f3-c4-20260929T015928-175dfd49` | `w0_f3_c4_gate_summary.json` |

---

## 各轮报告（历史正文保留 + 收口指针）

| 文档 | 角色 |
|------|------|
| [Windows_WeChat_W0_Report.md](Windows_WeChat_W0_Report.md) | W0 初始交付 |
| [W0_F1_Report.md](W0_F1_Report.md) | F1 修正 |
| [W0_F2_Report.md](W0_F2_Report.md) | F2 修正 |
| [W0_F3_Report.md](W0_F3_Report.md) | F3 C1–C3 收口 |
| [W0_F3_C4_Patch_Report.md](W0_F3_C4_Patch_Report.md) | C4 门禁补丁 |
| **本文** | **阶段最终收口** |

---

## 复核包（本地 `.local-validation/`，未入 Git）

| 包 | SHA-256 |
|----|---------|
| `W0_Review_Package.zip` | `af5996aafe89b3ca2d073135e24cd65b4917a1ccd148150cf1ef17ab23030f70` |
| `W0_F1_Review_Package.zip` | `ffc877d2ee3190bbbf273c3427a8c51b2aebb90d9f154bfdb11751cfc5953a81` |
| `W0_F2_Review_Package.zip` | `5291338f6d44772bf0d95f8e746ac47dc6f2d0f4e549fdd00ad58cc13eca96c1` |
| `W0_F3_Review_Package.zip` | `c429c7e77b1d088fd0d573b65be3c6fad2542fb0b4c36a5479f6c05f7f2703ce` |
| **`W0_F3_C4_Review_Package.zip`（最终）** | `89518c597abb2eab7cfd1d70c80faeb2231164ba976d156659f439e6413860c6` |

---

## 结构化证据哈希（W1 对照用）

| 文件 | SHA-256 |
|------|---------|
| `automation/.runtime/w0_gate_summary.json` | `b0680437ed8610976153aa26f8d7a18055150015dba1b58c4b673d8ca9a714c6` |
| `.../gate-f3-c4-.../w0_f3_c4_gate_summary.json` | `2f86262a392e704eab0566bb96eb0a6bb8116370f9d7f14529431e5c19745e73` |
| `.../gate-f3-c4-.../gate_report.json` | `e5cb803f1f9185a0375cd4dba253ae2b595e147cd028324c961f7cc54cfe1913` |
| `.../gate-f3-c4-.../gate_verdict.json` | `e8e38ef7c9ec58a4dd837930b588b78f1d30b3e1c5075312945773fe39726a73` |

路径前缀：`automation/.runtime/runs/gate-f3-c4-20260929T015928-175dfd49/`

---

## 最终源码清单与哈希

### C4 门禁（相对 F3 有差异）

| 文件 | SHA-256 |
|------|---------|
| `automation/src/wechat_automation/pytest_gate_report.py` | `854ea41b366175ba1f3d63bbb91df431e434e7b193c81c56b13d85ec8e27875c` |
| `automation/src/wechat_automation/cli/gate_eval.py` | `d4721129cf80a0018355ef5973cd870be55d9ed47980e75776ced27daf73e65e` |
| `automation/src/wechat_automation/cli/main.py`（gate 子命令） | `bbb4f3657426551b59287ced25a2e7b94c5ffac4b4b4590c9c74bab08b223073` |
| `automation/src/wechat_automation/cli/required_tests.py` | `22fcad39b53a11bfcd1e6af3919b8623a546f8220091794d4ff7ac91b3cbc3f7` |
| `automation/tests/test_w0_f3_c4_gate_matrix.py` | `e229b416cb5b4827f9683124398f5d741fee66e82b9a4bddb59c3077732c90b5` |
| `automation/pyproject.toml`（pytest11 插件入口） | 见 Git 工作区（未单独归档哈希） |

### C1–C3 核心（与 F3 轮一致；独立复核确认 C4 未改业务路径）

| 文件 | SHA-256 |
|------|---------|
| `store/sqlite_store.py` | `416eda4dfae0c6bb55e12aef3a562205868fa98533d0323e80ab1df18ba4d616` |
| `pipeline/ingest.py` | `9b85a8534245b1e457f17cbf50105d9b05ab0e2d77de9ba6c79823d8f13d6e88` |
| `process_liveness.py` | `32cc6953319fb9ec65c72cfdb931912ee1067ed1b3916969987444da5f1e4ed7` |
| `recovery.py` | `b59c7f22ff0a55b1c4247d20863d33f626f5c1de8238ab31fc25bcfee7c585e7` |
| `executor/mock.py` | `969c3d5d7e0c52196ca206eacf7071904fb6a1db2383078f18d3b996ed1ac99e` |
| `scheduler/worker.py` | `92048daa8d48fcfef8013d241dc401f5b263fbaf3bf3fc5a434d15f954826e99` |
| `source/message_identity.py` | `a49a3a107d023be6ea79fae9effcf0f7af0c91251f3cfe231a40f4821c4d1542` |
| `tests/test_w0_f3_fixes.py` | `3d5ee5a372ebcfa86414f0e5226deac8aae2c482c7bf76e25a5cb5cf68cd9387` |
| `tests/concurrency_probe.py` | `b20ac32e8e8ffd60bdaea08826540e7c22c64974e26d807d4ed871d3b9dee447` |

（上表路径均相对于 `automation/src/wechat_automation/` 或 `automation/tests/`。）

### 文档

| 文件 | SHA-256 |
|------|---------|
| `docs/tasks/Windows_WeChat_W0_Report.md` | `51ed4938ef5a3a5faba9c5fad276366a3cd7aee477126320c1a04405e5294f93` |
| `docs/tasks/W0_F1_Report.md` | `64d156d7d81bd325b21441bfe4045b63e64fe60af86029e418cabd88dbdad936` |
| `docs/tasks/W0_F2_Report.md` | `4c83b699cb071394c0b9a0c7bf863a5fdbf2c257be4e529e35cd1b7e3defe629` |
| `docs/tasks/W0_F3_Report.md` | `82d69da0e5d323f53def1a4a3ce100e0f2b14643882df6bcded9fef41e524306` |
| `docs/tasks/W0_F3_C4_Patch_Report.md` | `5d0f1a4cc57413d7116b00fbd5c9f0d8d0e368b273d6542d9995e7341926d754` |

---

## W1 入口条件（不在 W0 执行）

1. 测试账号与目标 Windows 微信版本就绪。  
2. 验证：真实数据读取、会话定位、发送状态与 UI 自动化（超出 mock/offline）。  
3. 以本文哈希与 `W0_F3_C4_Review_Package.zip` 为对照基线，避免与 W0 证据混淆。

---

## 收口声明

- **不**操作真实微信；**不**修改 Go 核心；**不** commit/push（除非后续显式要求）。  
- 历史门禁 JSON / run 目录**未覆盖**；最终结论以 **W0-F3-C4** run 与独立 C4 复核为准。  
- 独立方：**C4 补丁复核通过** → 离线阶段可收口；真实微信验收仍 **PENDING**。
