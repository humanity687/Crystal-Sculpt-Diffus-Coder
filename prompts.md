针对 Crystal-Sculpt-Diffus-Coder 的三种压缩场景，我设计了以下专用提示词。它们遵循类似的结构（`<analysis>` + `<summary>` 分节），但指导重点因场景而异。所有压缩提示词均要求产出可供后续对话直接使用的上下文摘要，保留足够的工程决策信息，丢弃过程性细节。

---

## 1. 被动压缩：上下文超限时

**触发条件**：API 返回 context length 错误，自动调用 `memory()`。  
**核心目标**：在保护当前活跃审批链和工具调用的前提下，压缩最早的历史消息，保留全局进展与近期关键决策。

```
Your task is to create a detailed summary of the conversation so far, focusing on preserving the project state and recent decisions essential for continuing the development. Pay special attention to the active project (if any) and the current skill phase.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, chronologically scan the conversation and identify:
- The active project ID, current phase (L0-L8), and module being worked on.
- All approved contracts (ContractCrystal IDs), their signatures, and key constraints.
- The dependency graph state (if defined) and the list of completed modules with their status.
- Recent decisions, user approvals, and any pending approval requests.
- Specific file paths, code snippets, error messages, or test outcomes mentioned in the last few exchanges.
- Any L3.1 renegotiations or bug backtracking events.

Then produce a summary using the following structure:

<summary>
1. Active Project & Phase:
   [project_id, current phase, current module if any]
2. Module & Contract Status:
   - [Module name]: [status (contracted/implemented/tested)], Contract ID: [crystal_id], Signature: [function signature], Key constraints: [...]
3. Dependency Graph:
   [If defined, include topological order and any cycle warnings]
4. Recent Decisions & Approvals:
   - [Decision 1, with approval status]
   - [...]
5. Pending Actions:
   - [Approval request, next module to implement, etc.]
6. Important Recent Messages:
   [Quote the most recent user request and your response verbatim if short; otherwise summarise with key details]
7. Next Step:
   [If known, state the next expected action, aligned with the current skill phase]
</summary>
```

---

## 2. 主动压缩（1）：全部 L3 契约完成后，进入逐模块实现前

**触发条件**：所有模块的 L3 接口契约均已审批通过，即将调用 `dependency define` 并进入 L4 实现。  
**核心目标**：彻底压缩各模块 L3 的冗长协商过程，仅保留所有模块的契约摘要和依赖关系，为后续实现阶段腾出最大上下文空间。

```
You are performing a phase transition compression. The project has completed contract definition (L3) for all modules and is about to start per-module implementation (L4-L7). Your task is to create a summary that replaces all previous detailed discussion of L3 contracts, leaving only the final approved contracts and dependency relationships.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, thoroughly identify:
- Every module and its final approved contract: function signatures, preconditions, postconditions, boundary handling strategies, and the crystal ID (ContractCrystal).
- The explicitly declared dependencies between modules (from L2 ModMap) and any dependency constraints.
- Any outstanding concerns or warnings noted during L3 approval (e.g., potential performance issues, ambiguous edge cases). Do not lose these warnings.
- The decision to proceed to implementation and the expected implementation order (if already discussed).

Then produce a summary with these sections:

<summary>
1. Project & Phase Transition:
   [project_id, transitioning from L3 to L4-L7, all contracts locked]
2. Module Contract Catalog:
   For each module, provide a compact record:
   - Module: [name]
   - Contract ID: [crystal_id]
   - Signature: [function/method signature(s)]
   - Preconditions: [...]
   - Postconditions: [...]
   - Boundary handling: [...]
   - Notes/Warnings: [...]
3. Dependency Map:
   [Explicit list: ModuleA depends on ModuleB, ModuleC; ...]
   Recommended implementation order: [topological order]
4. Important Design Decisions:
   - [Any global design choices or constraints agreed during L3 phase]
5. Transition Confirmation:
   [Statement that all contracts are approved and implementation may now proceed module by module.]
</summary>
```

---

## 3. 主动压缩（2）：一个模块 L7 完成后，进入下一个模块前

**触发条件**：当前模块的 L7 实现已通过测试，`ModuleRecord(L7)` 已记录，准备切换到下一个模块。  
**核心目标**：保存当前模块的实现摘要和测试结果，丢弃 L4-L7 的详细推导过程，同时保留该模块的最终契约（若未在前次压缩中持久化）和任何 L3.1 修订。

```
You are performing a module completion compression. The module [ModuleName] has finished implementation (L7) and testing. A new module will start next. Your task is to summarize the just-completed module's outcome and any contract changes, while discarding the detailed L4-L7 design discussions.

Before providing your final summary, wrap your analysis in <analysis> tags. In your analysis, identify:
- The module name and its current contract (including any L3.1 revisions that occurred during implementation). Note the final contract crystal ID.
- The implementation files and key functions created/modified, with their paths.
- The test results (pass/fail, any significant edge cases tested).
- Any bugs encountered and how they were fixed (summarize TraceCrystal if applicable).
- The decision that this module is complete and ready for integration.

Then produce a summary:

<summary>
1. Completed Module:
   - Module: [ModuleName]
   - Status: Implemented & Tested (L7 complete)
   - Final Contract ID: [crystal_id]
   - Contract Summary: [Signature, key constraints, any revisions from L3.1]
2. Implementation Artifacts:
   - File: [path] — [function/class names] — [brief description]
   - ...
3. Test Results:
   - [Test name]: PASS/FAIL — [note if any known limitations]
4. Bug Fixes (if any):
   - [Symptom] → Root cause: [cause] → Fix: [fix]
   - TraceCrystal ID: [if applicable]
5. Next Module:
   [If known, indicate which module is next and its expected contract]
6. Transition Confirmation:
   [Module complete, context compressed; ready to start next module.]
</summary>
```

---

**设计要点**：
- 所有压缩提示词都要求以 `<analysis>` 开头组织思考，确保不漏关键信息。
- 每个场景的 `<summary>` 子项完全匹配该阶段后续对话所需的最小上下文。
- 特别保护了契约摘要、依赖关系、测试结果和 Bug 修复记录，这些是回退和涟漪调试的核心依据。
- 用语和结构参考了 Claude Code 压缩提示词，但内容完全适配 Crystal-Sculpt-Diffus-Coder 的分层开发流程。