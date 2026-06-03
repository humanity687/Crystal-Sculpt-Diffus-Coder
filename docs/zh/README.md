# Crystal-Sculpt-Diffus-Coder

[English](../../README.md) | **中文**

一个带有 Flask 网页界面的 AI 智能体框架，让 AI 能够读取文件、执行命令、搜索网络，并与你协作完成工程项目。通过 Cloudflare Tunnel 实现远程访问——无需公网 IP。

---

## 功能特性

- **工具调用型 AI 对话** — 模型自主调用工具：读写文件、执行命令、搜索网络
- **代码审查面板** — AI 以 diff 形式提出修改建议；你审查、编辑、批准后才会写入磁盘
- **工程晶体记忆** — L0-L8 工作流，结构化产物（契约、逻辑、追踪）存储在 SQLite 中，通过向量相似度检索
- **依赖图管理** — AI 在 L2 阶段定义模块依赖关系；影响分析和拓扑排序指导实现顺序
- **MCP 协议** — 集成任何 stdio MCP 服务器；工具自动发现，格式为 `服务器名/工具名`
- **两级摘要记忆** — 摘要嵌入向量库用于检索，完整内容可通过 `recall` 工具获取
- **定时任务** — 后台守护线程在指定 HH:MM 时间执行命令
- **安全认证** — ECIES（ECDH + AES-256-GCM）+ bcrypt + JWT（1小时有效期）
- **跨平台** — Windows / Linux / macOS

---

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/humanity687/Crystal-Sculpt-Diffus-Coder.git
cd Crystal-Sculpt-Diffus-Coder

# 2. 安装（创建虚拟环境、安装依赖）
./init.sh       # macOS/Linux
init.bat        # Windows

# 3. 编辑 config.json（api_key, base_url, model）

# 4. 运行
./run.sh        # macOS/Linux
run.bat         # Windows
```

启动后，终端会显示一个 Cloudflare Tunnel 公网 URL。用任意设备打开——首次访问会引导你设置密码。

---

## 配置说明（`config.json`）

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_key` | string | — | API 密钥（必填）。Ollama 可填任意值。 |
| `base_url` | string | — | API 基础地址。Ollama：`http://localhost:11434/v1` |
| `model` | string | — | 模型名称。推荐：`glm-4.7-flash` |
| `temperature` | float | `0.8` | 随机性 0-2。值越低越确定。 |
| `thinking` | bool | `false` | 深度思考模式（仅 GLM 模型）。 |
| `knowledge_k` | int | `5` | 每次检索的知识片段数。 |
| `language` | string | `"en"` | UI 语言（`en` / `zh`）。 |
| `mcp_servers` | list | `[]` | MCP 服务器配置。每项：`{name, command, args}`。 |
| `memory_weights` | object | — | 按类型覆盖检索权重。 |
| `tools.ett` | object | — | 多模态模型配置（需使用 GLM 视觉模型）。 |

---

## 内置工具

| 工具 | 用途 |
|------|------|
| `read` | 读取文件、目录、图片、文档 |
| `write` | 提出文件修改建议 — diff 审查后写入（支持覆盖、编辑、替换、插入模式） |
| `command` | 执行 shell 命令（白名单机制；禁止删除操作） |
| `search` | 通过 DuckDuckGo 搜索网络（免费，无需 API 密钥） |
| `time` | 当前日期/时间 |
| `recall` | 通过 memory_id 从知识库获取完整文本内容 |
| `add_skill` | 保存可复用的技能 .md 文件到向量数据库 |
| `set_project` | 激活分阶段工程上下文（project_id, phase, module） |
| `crystallize` | 存储/查找思维晶体（ContractCrystal, LogicCrystal, TraceCrystal 等） |
| `dependency` | 管理模块依赖图（define, recommend, impact 分析） |
| `request_approval` | 提交 Lx 内容供用户审批，同时记录快照 |

所有工具通过统一的 `tools` 函数调用。MCP 工具使用 `服务器名/工具名` 格式。

---

## 知识库

两级摘要记忆系统：摘要嵌入在向量数据库中；完整内容存储在磁盘上，通过 `recall` 工具检索。

| 类型 | 权重 | 说明 |
|------|------|------|
| `tool_summary` | 1.0 | 工具文档 |
| `skill_summary` | 0.8 | 技能文档 |
| `experience_crystal` | 0.6 | 跨项目工程经验 |
| `conversation_summary` | 0.3 | 对话回合摘要 |

检索使用混合模式：向量相似度 + FTS5 关键词搜索，通过 RRF 融合排序。

---

## 工程晶体系统（L0-L8）

SQLite 支持的结构化记忆，服务于 idea-to-code-sculpting 工作流：

| 层级 | 晶体类型 | 内容 |
|------|---------|------|
| L1 | ArchCrystal | architecture_summary, tech_stack, core_flow |
| L2 | ModMap | modules[], dependencies{} |
| L3 | ContractCrystal | signature, preconditions, postconditions, constraints |
| L4 | LogicCrystal | algorithm_steps, boundary_handling |
| L6 | SkeletonCrystal | code_skeleton, language |
| L7 | ImplCrystal | code, tests, language |
| L8 | TraceCrystal | symptom, root_cause, fix |

另含 `DependencyGraphCrystal` 用于模块依赖追踪（define → recommend → impact）。

核心行为：活力评分、分阶段上下文注入、向量相似度搜索、追踪链遍历。

---

## 安全机制

- ECIES（ECDH + HKDF + AES-256-GCM）加密密码传输
- bcrypt 密码哈希，JWT 会话令牌（1小时有效期，仅存内存）
- `command` 工具：白名单机制，禁止删除命令，安全命令自动执行，危险命令需确认
- `write` 工具：从不直接写入——始终经过代码审查面板

---

## 免责声明

Cloudflare Tunnel 远程访问功能仅作为技术便利提供。用户需自行承担因网络暴露、设备丢失、密码泄露或第三方攻击等带来的风险。请使用强密码，仅在受信任的网络和设备上启用远程访问，并理解任何联网服务都可能存在未知安全漏洞。

项目作者及贡献者不对因使用本软件造成的任何直接或间接损失承担责任。使用即表示您已阅读并同意本声明。

---

## 许可证

[GPL v3](COPYING)
