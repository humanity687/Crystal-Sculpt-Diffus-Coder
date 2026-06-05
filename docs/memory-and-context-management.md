# Crystal-Sculpt-Diffus-Coder 记忆管理与上下文管理机制

Crystal-Sculpt-Diffus-Coder 使用一套**双层记忆体系**：短期记忆（消息历史）确保单次对话的连贯性，长期记忆（向量知识库）实现跨会话的知识复用。两者配合上下文压缩、孤消息清理、混合检索等机制，构成完整的记忆管理架构。

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Crystal-Sculpt-Diffus-Coder                               │
├─────────────────────────────────────────────────────────────────┤
│  短期记忆层 (Short-term Memory)                                   │
│  ├─ self.messages: list[dict]     ← 完整消息历史                  │
│  ├─ messages.json                 ← 磁盘持久化                    │
│  ├─ memory()                      ← 上下文压缩                    │
│  ├─ _clean_orphan_tool_messages() ← 孤消息清理                    │
│  └─ _find_safe_cut_index()        ← 安全切割点查找                │
├─────────────────────────────────────────────────────────────────┤
│  长期记忆层 (Long-term Memory / RAG)                              │
│  ├─ knowledge/knowledge.db        ← SQLite 向量库 + FTS5          │
│  ├─ knowledge/memories/           ← 对话记忆备份 (.md)             │
│  ├─ search()                      ← 混合检索 (向量 + 关键词)       │
│  ├─ add_conversation()            ← 实时写入对话记忆               │
│  └─ incremental_update()          ← 增量索引更新                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 短期记忆 — 消息历史

### 2.1 数据结构

`Crystal-Sculpt-Diffus-Coder` 在 `src/agent.py:311` 中维护一个 `self.messages: list[dict]`，它是与 AI 模型交互的完整消息历史。遵循 OpenAI Chat Completion 格式：

| 索引 | role | 说明 |
|------|------|------|
| `[0]` | `system` | 固定的基础系统提示，包含 `USER_GUIDE`（工具使用说明）+ `user_settings`（用户自定义设置） |
| `[1:]` | 混合 | 用户消息 (`user`)、助手回复 (`assistant`)、工具调用结果 (`tool`)，按时间顺序排列 |

### 2.2 初始化与恢复

```python
# src/agent.py:311-319
self.messages = [{}]
if os.path.exists("messages.json"):
    with open("messages.json", "r", encoding="utf-8") as f:
        self.messages = json.load(f)

self.base_system_prompt = f"{USER_GUIDE}\n\n---\n\n{self.user_settings}"
self.messages[0] = {"role": "system", "content": self.base_system_prompt}
```

每次实例化 `Crystal-Sculpt-Diffus-Coder` 时：
1. 尝试从 `messages.json` 恢复上次会话的完整消息历史
2. 用当前的 `USER_GUIDE` + `user_settings` 覆盖 `self.messages[0]`，确保系统提示始终是最新的
3. 注：`chat_agent` 和 `tasks_agent` 各自拥有独立的 `Crystal-Sculpt-Diffus-Coder` 实例和独立的消息历史

### 2.3 单轮对话中的消息生命周期

```
用户发送消息
  │
  ├─ 1. self.messages.append({"role": "user", "content": msg})
  │      用户消息立即持久化到消息历史
  │
  ├─ 2. search(msg, k=knowledge_k)
  │      检索相关知识，注入为临时系统消息（不持久化到 self.messages）
  │
  ├─ 3. 构建 api_messages = [base_system_prompt] + [knowledge] + self.messages[1:]
  │      api_messages 是发送给模型的完整上下文副本
  │
  └─ 4. 进入工具调用循环:
        │
        while True:
          │
          ├─ 调用模型 (streaming)
          │
          ├─ 收到 assistant_message → 追加到 current_api_messages
          │
          ├─ 没有 tool_calls?
          │   └─ self.messages.append(assistant_message)
          │       _save_messages()
          │       return  ← 本轮结束
          │
          ├─ 有 tool_calls? → 逐个执行:
          │   ├─ 执行工具 → 得到 result
          │   ├─ 构建 tool_message = {"role": "tool", ...}
          │   ├─ current_api_messages.append(tool_message)
          │   └─ self.messages.append(tool_message)
          │
          └─ 循环继续 (模型基于工具结果再次推理)
```

**关键设计决策**：知识检索结果（`relevant`）只追加到 `api_messages` 而**不**追加到 `self.messages`。这意味着：
- 每次 API 调用都携带着为当前查询动态检索的最新相关知识
- 知识内容不会污染持久化的消息历史
- 上下文压缩后重建 `api_messages` 时，会再次使用同一批检索结果

---

## 3. 上下文压缩 (Context Compression)

当模型返回上下文长度超限错误时，Crystal-Sculpt-Diffus-Coder 自动压缩消息历史。

### 3.1 触发条件

```python
# src/agent.py:645-671
except Exception as e:
    error_str = str(e).lower()
    if ("context length" in error_str
        or "token" in error_str
        or "too long" in error_str):
        self.memory()           # 执行压缩
        # 重建 api_messages（保持系统提示 + 知识注入）
        current_api_messages = [
            {"role": "system", "content": self.base_system_prompt}
        ]
        if relevant:
            current_api_messages.append(...)
        current_api_messages.extend(self.messages[1:])
        continue                 # 重试
```

错误信息中的 `context length`、`token`、`too long` 三个关键字任意命中即触发。

### 3.2 安全切割算法 — `_find_safe_cut_index()`

直接按索引截断会导致 **tool_call 与 tool_result 对分离**——模型发了工具调用的那条 assistant 消息还在历史中，但对应的工具执行结果被删掉了，或者反过来。这会破坏 API 的消息格式约束。

```python
# src/agent.py:691-720
def _find_safe_cut_index(self):
    # 1. 建立双向索引
    call_positions = {}     # tool_call_id → 消息索引
    result_positions = {}   # tool_call_id → 消息索引

    for i, msg in enumerate(self.messages):
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                call_positions[tc["id"]] = i
        elif msg["role"] == "tool":
            cid = msg.get("tool_call_id")
            if cid:
                result_positions[cid] = i

    # 2. 只关心成对存在的 ID（双向匹配）
    paired_ids = set(call_positions.keys()) & set(result_positions.keys())

    # 3. 从索引 2 开始扫描，找第一个安全切割点
    for cut_idx in range(2, len(self.messages)):
        safe = True
        for cid in paired_ids:
            call_before = call_positions[cid] < cut_idx   # call 在切割点之前?
            result_before = result_positions[cid] < cut_idx  # result 在切割点之前?
            if call_before != result_before:
                # 跨越了切割边界——不安全
                safe = False
                break
        if safe:
            return cut_idx
    return None
```

**算法核心**：对每一对 `(tool_call, tool_result)`，两者要么**都在**切割点之前（一起被删除），要么**都在**切割点之后（一起保留），不允许一个在左一个在右。

从索引 2 开始扫描（保留 `[0]=system prompt` 和 `[1]` 至少一条消息），返回第一个不破坏任何 pair 的索引。

### 3.3 压缩执行 — `memory()`

```python
# src/agent.py:722-744
def memory(self):
    # 1. 先清理既有孤消息
    self._clean_orphan_tool_messages()

    # 2. 消息太少则不压缩
    if len(self.messages) <= 5:
        return

    # 3. 寻找安全切割点
    cut_idx = self._find_safe_cut_index()

    # 4. 回退策略：无安全点，或安全点太靠后/太靠前
    if cut_idx is None or cut_idx >= len(self.messages) - 1 or cut_idx <= 1:
        cut_idx = len(self.messages) // 2 + 1   # 强制从中段切割

    # 5. 保留 [0]=system prompt + [cut_idx:] 之后的内容
    self.messages = [self.messages[0]] + self.messages[cut_idx:]

    # 6. 再次清理（切割可能产生新的孤消息）
    self._clean_orphan_tool_messages()
```

**回退策略的两种情况**：
- `cut_idx is None`：所有切割点都破坏至少一对 tool_call/tool_result，无解
- `cut_idx >= len(self.messages) - 1`：安全点在末尾，等于没压缩
- `cut_idx <= 1`：安全点在开头，会删掉所有对话历史

这些情况下使用 `len(self.messages) // 2 + 1` 作为切割点——宁可破坏一两对 pair 也要完成压缩（后续的 `_clean_orphan_tool_messages()` 会清理残骸）。

---

## 4. 孤消息清理 (Orphan Cleanup)

### 4.1 什么算"孤消息"

- **孤立的 tool_call**：assistant 消息中有一个 tool_call，但没有对应的 tool 角色消息
- **孤立的 tool 结果**：tool 角色消息存在，但没有 assistant 消息中的 tool_call 与之对应

这两种情况会破坏 API 的消息格式要求。

### 4.2 清理算法

```python
# src/agent.py:342-381
def _clean_orphan_tool_messages(self):
    # 1. 收集所有 assistant 发出的 tool_call ID
    assistant_call_ids = set()
    for msg in self.messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                assistant_call_ids.add(tc["id"])

    # 2. 收集所有 tool 消息的 tool_call_id
    tool_message_ids = set()
    for msg in self.messages:
        if msg.get("role") == "tool":
            cid = msg.get("tool_call_id")
            if cid:
                tool_message_ids.add(cid)

    # 3. 只有同时出现在两边的 ID 才是有效的
    valid_ids = assistant_call_ids & tool_message_ids

    # 4. 重建消息列表
    new_messages = []
    for msg in self.messages:
        if role == "assistant" and msg.get("tool_calls"):
            # 过滤掉无效的 tool_calls，保留文本内容
            filtered = [tc for tc in msg["tool_calls"] if tc["id"] in valid_ids]
            new_msg = msg.copy()
            if filtered:
                new_msg["tool_calls"] = filtered
            else:
                new_msg.pop("tool_calls", None)  # 全部无效则删除 tool_calls 字段
            new_messages.append(new_msg)
        elif role == "tool":
            if msg.get("tool_call_id") in valid_ids:
                new_messages.append(msg)
            # 无效的 tool 消息直接丢弃
        else:
            new_messages.append(msg)

    self.messages = new_messages
```

**关键行为**：
- assistant 消息如果所有 tool_call 都无效，只删除 `tool_calls` 字段，保留 `content`（文本回复仍然有价值）
- tool 角色的消息如果无效，整条丢弃

### 4.3 调用时机

1. **压缩前**：`memory()` 的第一步
2. **压缩后**：`memory()` 的最后一步（切割可能产生新的孤消息）
3. **GeneratorExit 时**：用户中断生成时，如果已有对话进展，清理后保存

---

## 5. 消息持久化

### 5.1 原子写入

```python
# src/agent.py:335-340
def _save_messages(self):
    tmp_path = "./messages.json.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(self.messages, f, ensure_ascii=False, indent=4)
    os.replace(tmp_path, "./messages.json")
```

使用先写临时文件再 `os.replace()` 的模式实现**原子写入**，防止写入过程中进程崩溃导致 `messages.json` 损坏。`os.replace()` 在同一文件系统内是原子操作。

### 5.2 保存时机

| 时机 | 说明 |
|------|------|
| 每轮对话完成 | 助手回复结束后立即保存 |
| 上下文压缩后 | 压缩完成后通过循环中的 `continue` 重试（重建 api_messages 后未显式保存，但紧接着的下一次 API 成功或最终 return 会触发保存） |
| 进程退出 | 通过 `atexit.register(_safe_save)` 注册，进程正常退出时保存 |
| GeneratorExit | 用户中断 SSE 流时保存 |

---

## 6. GeneratorExit 处理

```python
# src/agent.py:677-689
except GeneratorExit:
    if (len(self.messages) == original_len + 1
        and self.messages[-1]["role"] == "user"):
        # 只有用户消息被追加，没有助手回复 → 回滚
        self.messages = self.messages[:original_len]
    else:
        # 已有部分进展 → 清理孤消息
        self._clean_orphan_tool_messages()
    self._save_messages()
    return
```

**两种情况**：
- 用户刚发消息，流还没开始返回内容就被中断 → 回滚用户消息，保持历史干净
- 已经有部分工具调用/回复正在进行 → 保留已提交的消息，清理可能残废的 tool pair

---

## 7. 长期记忆 — 向量知识库 (RAG)

### 7.1 存储结构

SQLite 数据库 `knowledge/knowledge.db` 包含三张表：

```
┌─ vectors ────────────────────────────────────────┐
│ id INTEGER PRIMARY KEY AUTOINCREMENT              │
│ text TEXT NOT NULL          ← 文档全文             │
│ embedding BLOB NOT NULL     ← 向量 (384维 float32) │
│ source TEXT                 ← 来源路径              │
│ type TEXT                   ← 文档类型              │
└───────────────────────────────────────────────────┘

┌─ fts (FTS5 虚拟表) ──────────────────────────────┐
│ rowid ──→ vectors.id                             │
│ text     ← 全文索引 (unicode61 tokenizer)          │
└───────────────────────────────────────────────────┘

┌─ file_versions ──────────────────────────────────┐
│ path TEXT PRIMARY KEY        ← 相对路径            │
│ mtime REAL                   ← 文件修改时间          │
│ last_updated REAL            ← 上次索引时间          │
└───────────────────────────────────────────────────┘
```

### 7.2 向量编码

使用 `sentence-transformers` 的 `all-MiniLM-L12-v2` 模型：
- 输出维度：384
- 使用余弦相似度作为向量距离度量
- 模型在首次使用时加载（单例模式），全局共享

### 7.3 文档类型与权重

| 类型 | 权重 | 来源 | 说明 |
|------|------|------|------|
| `tool` | 1.0 | `knowledge/tools/*/README.md` | 工具说明文档，最高优先级 |
| `skill` | 0.8 | `knowledge/skills/` | 用户定义的技能/工作流 |
| `conversation` | 0.2 | `knowledge/memories/` | 历史对话记录，权重最低 |
| `hyw` / 其他 | 1.0 | `knowledge/` 其他 .md 文件 | 默认权重 |

权重在向量相似度计算阶段生效：`final_score = cosine_similarity * weight`

### 7.4 增量索引更新

`incremental_update()` 在每次启动时执行：

1. 扫描 `knowledge/` 下所有 `.md` 文件，获取当前 `(path → mtime)` 快照
2. 与 `file_versions` 表中记录的上次状态对比：
   - **新增/修改**：重新编码向量，替换旧记录，同步 FTS 索引
   - **删除**：从 vectors、fts、file_versions 三表中删除对应记录
3. 清理孤立的 conversation 记忆（备份文件已删除但向量记录仍在）

首次运行（vectors 表为空）时自动触发 `full_rebuild()`，执行全量构建。

### 7.5 对话记忆写入

```python
# knowledge/memory.py
def add_conversation(user_msg: str, ai_msg: str):
    text = f"User: {user_msg}\nAI: {ai_msg}"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"{timestamp}.md"
    backup_path = MEMORIES_DIR / backup_filename
    source = str(backup_path.relative_to(KNOWLEDGE_ROOT))

    # 实时写入向量库
    add_document(text, source=source, doc_type="conversation")

    # 备份到磁盘
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(text)
```

每条对话记忆写入时做了两件事：
1. **实时向量化**：立即进入向量库，后续查询即可命中（`add_document` 会先查重）
2. **磁盘备份**：保存为 `knowledge/memories/YYYYMMDDHHmmss.md`，供下次启动时的增量索引使用

调用时机：在 `src/routes/chat.py` 中，每轮 SSE 流正常结束后调用。

---

## 8. 混合检索 (Hybrid Search)

### 8.1 算法：Reciprocal Rank Fusion (RRF)

`knowledge/search.py:search()` 实现了**向量语义相似度 + 关键词全文搜索**的混合检索，使用 RRF 融合两者排名。

```
RRF_score(doc) = Σ ( weight_i / (K + rank_i) )
```

其中 `K=60`（平滑常数），`weight_vector=0.7`，`weight_fts=0.3`。

### 8.2 检索流程

```
用户查询
  │
  ├─ 1. 向量检索
  │     ├─ query → SentenceTransformer → q_emb (384维)
  │     ├─ 遍历 vectors 表所有 embedding → 计算 cosine_similarity
  │     ├─ 乘以文档类型权重 → final_score
  │     └─ 按 final_score 降序排列 → [(score, doc_id, text, type), ...]
  │
  ├─ 2. FTS5 关键词检索
  │     ├─ 清洗查询（去标点，保留中英文及数字）
  │     ├─ SELECT rowid, rank FROM fts WHERE text MATCH ? ORDER BY rank
  │     └─ 获得 top (k*2) 结果
  │
  ├─ 3. RRF 融合
  │     ├─ 向量排名 → RRF_score = 0.7 / (60 + rank)
  │     ├─ FTS 排名  → RRF_score = 0.3 / (60 + rank)
  │     ├─ 对同一 doc_id 累加 RRF 分数
  │     └─ 按总分降序取 top k
  │
  └─ 4. 不足 k 条时，用纯向量结果补充
```

### 8.3 知识注入到上下文

检索结果被注入为一条**临时系统消息**，位置紧随基础系统提示之后：

```python
# src/agent.py:402-416
api_messages = [{"role": "system", "content": self.base_system_prompt}]
if relevant:
    knowledge_text = "\n\n".join(relevant)
    api_messages.append({
        "role": "system",
        "content": f"## Related Content\n\n{knowledge_text}"
    })
api_messages.extend(self.messages[1:])
```

这条知识消息**仅存在于 `api_messages`（API 调用副本）**，不会写入 `self.messages`（持久化历史）。上下文压缩后重建 `api_messages` 时，会使用同一次查询的同一批检索结果重新注入。

---

## 9. 完整生命周期图示

```
应用启动
  │
  ├─ knowledge/__init__.py 启动序列:
  │   ├─ load_builtin_tools()     → 加载 knowledge/tools/*/
  │   ├─ load_mcp_servers()       → 启动 MCP 子进程
  │   └─ check_and_update()       → 增量/全量构建向量库
  │
  ├─ Crystal-Sculpt-Diffus-Coder.__init__():
  │   ├─ 从 messages.json 恢复消息历史
  │   ├─ self.messages[0] = base_system_prompt
  │   └─ 注册 atexit 清理回调
  │
  └─ 用户发起对话:
      │
      ├─ input(msg)
      │   ├─ self.messages.append(user_msg)
      │   ├─ search(msg) → 知识注入 (临时)
      │   ├─ API 调用循环:
      │   │   ├─ 成功 → 保存 → 返回
      │   │   └─ context_length 错误 → memory() → 重试
      │   │
      │   └─ 流结束后:
      │       ├─ add_conversation(user_msg, full_response)
      │       │   └─ 写入向量库 + 磁盘备份
      │       └─ _save_messages() → messages.json
      │
      └─ 下次对话: search() 即可检索到之前的对话记忆 (权重 0.2)
```
