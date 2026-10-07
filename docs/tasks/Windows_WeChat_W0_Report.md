# Windows 微信自动化 Phase W0 实施报告

日期：2026-09-28  
执行者：Cursor  
仓库：`https://github.com/MJKProduct/chatlog_new`（本地 `c:\Users\Lenovo\Documents\chatlog_new`）

## 审计证据

| 项 | 结果 |
|----|------|
| AGENTS.md | **未找到**（工作区无该文件） |
| remote | `origin` → `https://github.com/MJKProduct/chatlog_new.git` |
| branch | `main` |
| HEAD | `a7162bca9454fa43b5950a2414670983fe180e56`（与任务基线 `a7162bc` 一致） |
| git status | 仅新增 `automation/`、修改 `.gitignore`；未执行 reset/clean |
| Go 核心 | **未修改**（符合 W0 要求） |

### HTTP / Webhook（源码核对）

- `GET /health` → `{"status":"ok"}`（`internal/chatlog/http/route.go`）
- `GET /api/v1/chatlog?format=json` 等：查询参数含 `time,talker,sender,keyword,limit,offset,format`；`format=json` 时返回消息 JSON 数组
- `GET /api/v1/contact|chatroom|session?format=json`：返回列表 JSON
- Webhook POST 信封（`internal/chatlog/webhook/webhook.go`）：`talker,sender,keyword,lastTime,length,messages[]`；消息字段与 `model.Message` JSON 一致（含 `seq,time,talker,sender,isSelf,type,content` 等）
- `seq`：源码注释为「10 位时间戳 + 3 位序号」，**未当作全局唯一消息 ID**；本模块优先 `id/msgId`，否则 `seq`（CONFIRMED 身份），否则内容哈希（不声称无碰撞）
- `isSelf`：来自消息 JSON 布尔字段；缺失则 `identity_quality=UNKNOWN` 且跳过自动回复

### Webhook 已知问题（记入审计，W0 未改 Go）

1. **内存游标** `lastTime`：进程重启会丢失
2. **提前推进游标**：在 POST 成功/持久化确认之前就更新 `lastTime`
3. **POST 失败无重试**：仅打日志
4. **空响应风险**：失败时仍 `defer resp.Body.Close()`（err 分支未 guard）

离线补查与接收逻辑在 `automation/` 中通过 **fixture + HTTP stub** 验证「重叠窗口、分页、检查点、去重」，不连接默认 `127.0.0.1` 服务。

## 变更清单

| 路径 | 说明 |
|------|------|
| `automation/` | 新建独立 Python 模块（contracts/source/rules/store/scheduler/executor/cli） |
| `automation/configs/offline.example.json` | 离线配置模板 |
| `automation/README.md` | 架构、命令、状态语义、限制 |
| `docs/tasks/Windows_WeChat_W0_Report.md` | 本报告 |
| `.gitignore` | 忽略 `automation/.runtime/`、`automation/.local-validation/`、`任务/` |
| `automation/.runtime/w0_gate_summary.json` | 门禁摘要（本地生成，已忽略） |

**未执行**：commit、push、真实微信操作、自动启动 chatlog 服务、读取真实 DB/密钥。

## 验收结果（16/16）

实际命令（Windows，在 `automation/` 目录、已激活 venv）：

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_w0_acceptance.py
python -m wechat_automation gate
python -m wechat_automation doctor --offline
python -m wechat_automation demo --scenario happy_path
```

| # | 场景 | 结果 |
|---|------|------|
| 1 | 单条合法消息 → 1 任务 `SIMULATED_SUCCEEDED` | PASS |
| 2 | 重复事件 → 任务数仍为 1 | PASS |
| 3 | 同内容不同 ID → 2 任务 | PASS |
| 4 | 重启重放 → 不重复执行已完成任务 | PASS |
| 5 | 自身消息 → 无循环 | PASS |
| 6 | 非白名单/系统/非文本/未知 isSelf → 仅记录原因 | PASS |
| 7 | 执行目标歧义 → 阻断 | PASS |
| 8 | 双 worker → 并发执行≤1 | PASS |
| 9 | 发送前临时失败 → 重试后成功 | PASS |
| 10 | 执行后结果不明 → `UNKNOWN` 不重发 | PASS |
| 11 | 事务中断 → 无脏数据 | PASS |
| 12 | Webhook + 补查交叉去重 | PASS |
| 13 | 分页边界完整补查 | PASS |
| 14 | 非法 JSON → 拒绝/隔离，服务不崩 | PASS |
| 15 | `mode=live` → 未实现报错 | PASS |
| 16 | 输出标明 simulation | PASS |

运行环境：`runtime_os=Windows`，`python_version=3.14.7`，`repo_head=a7162bca9454fa43b5950a2414670983fe180e56`。

## 门禁状态

```
OFFLINE_AUTOMATION_W0_PASS
REAL_WECHAT_ACCEPTANCE_PENDING
WINDOWS_UI_NOT_TESTED
REAL_SEND_NOT_TESTED
```

说明：离线逻辑在 Windows 上已验收；**真实微信 UI、真实发送、密钥/解密真机路径均未测试**，不得视为全平台或生产可用。

## 后续 W1 真机清单（未实施）

1. 确认 Windows + 微信版本矩阵  
2. 密钥/解密与 chatlog API 真机样例  
3. Webhook 真机载荷与延迟/完整性测量  
4. UI 控件探测与文件传输助手文本发送  
5. 指定测试会话闭环；群 @ 等扩展能力  

---

## Phase W0-R 独立复核基线（2026-09-28）

| 项 | 值 |
|----|-----|
| branch | `main` |
| HEAD | `a7162bca9454fa43b5950a2414670983fe180e56` |
| git status | 已跟踪：`.gitignore` 修改；未跟踪：`automation/`、`docs/tasks/` |
| runtime_os | Windows |
| python_version（W0 门禁机） | 3.14.7 |
| 复核包 | `automation/.local-validation/W0_Review_Package.zip` |
| 原始门禁摘要 | `automation/.runtime/w0_gate_summary.json`（**未覆盖**） |

### 复核状态（保留 W0 执行方结论）

```
OFFLINE_AUTOMATION_W0_PASS          ← W0 执行方门禁（未撤销）
INDEPENDENT_REVIEW_PENDING          ← 本轮仅整理材料，待独立复核
REAL_WECHAT_ACCEPTANCE_PENDING
WINDOWS_UI_NOT_TESTED
REAL_SEND_NOT_TESTED
```

### W0-R 证据缺口说明（不补代码）

| 缺口 | 说明 |
|------|------|
| W0 原始 pytest 终端 transcript | 当时未归档；复核包内 `evidence/pytest_w0_r_archival.log` 为 **W0-R 独立目录补跑**，非 W0 当时 stdout |
| 执行中真实进程强杀 | **未做**；`RUNNING` 滞留与崩溃恢复见 `REVIEW_INDEX.md` §4 |
| 同秒晚到专项用例 | 未单独命名测试；去重依赖 `event_key`（消息 ID 优先），见 §7 |
| Windows UI / 真实网络 | 未验证（仍为 NOT_TESTED） |

---

## W0 阶段收口（追加，2026-09-29，不修订上文）

W0 初始交付结论保留；离线自动化阶段已于 W0-F3-C4 收口。见 [W0_Closure.md](W0_Closure.md)（**OFFLINE_AUTOMATION_W0_PASS** / **REAL_WECHAT_ACCEPTANCE_PENDING**）。
