# Copyright (C) 2026 humanity687
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Phase-aware context injection — extracted from idea-to-code-sculpting skill.

Each entry is the MINIMAL constraint set for a phase: only rules whose
violation would break the workflow. No examples, no templates, no fluff.

Kept as a flat dict so that set_project can write state.phase_guidance
and _build_context() can inject it as a system message.

Sync rule: when idea-to-code-sculpting.md changes, update this file.
"""

# ── Global principles injected at EVERY phase ──────────────────────────
GLOBAL_PRINCIPLES = """## 不可违背
- 先理解→再规划→最后写代码，顺序不可颠倒
- L3 未审批不进 L6；L6 未审批不进 L7
- 不擅自扩展 L3 未定义的功能，除非通过 L3.1 获批
- 按行编辑：先 read 获取行号→edit 精准替换→立即 read 刷新行号
- 每完成一个函数立即验证，不攒到最后
- Bug 时先 read 相关代码再修改，修复根因不打补丁
- 注释语言跟随用户对话语言；所有公开函数必须有结构化注释
- v2.1 契约优先：L2 审批通过后，所有模块先并行完成 L3 签约，全部审批通过后调用 dependency define，再按拓扑序逐个迭代 L4→L7。禁止在全部 L3 签约完成前进入任何模块的 L4。
- 每层产出完成后立即调用 request_approval(phase="L{phase}", module="<当前模块>", content="<本层输出的完整Markdown>") 记录模块快照并提请用户审批。审批通过后再调用 crystallize 保存本层产物。若不记录快照，模块切换时系统无法注入契约上下文，后续阶段将缺少关键参考。
- 切换模块时调用 set_project(action="activate", project_id="<id>", phase="<Lx>", module="<新模块>")，系统会自动压缩旧模块历史并注入新模块的 L3 契约及推荐下一模块。当前模块全部完成后推进 phase；若所有模块 L7 均完成，phase 设置为 L8。
- 每次模块切换（set_project 改变 module 参数）时，系统自动注入该模块及其依赖模块的 L3 契约。每次相位回退时，系统自动注入回退目标层级的上一版本记录供参考。
- 所有模块 L7 完成并通过 L8 集成测试后，使用 archive_project(action="preview") 生成经验结晶草稿供用户审批，审批通过后 archive_project(action="confirm") 完成归档，最后 set_project(action="deactivate") 退出项目上下文。"""

# ── Phase-specific constraints ──────────────────────────────────────────
PHASE_PROMPTS = {
    "L0": """## L0 — 灵感捕获
只用 2-3 个问题把模糊想法变成有边界的需求。绝不超过 3 个问题，绝不在用户回答前做任何实现。
问完后等待用户回答，不推进到 L1。""",

    "L1": """## L1 — 架构总结
输出：【理解摘要】(一段话) + 【主干流程图】(Mermaid，≤6 节点，只画主干)
末尾必须标注：
🔒 锁定：系统目标、核心流程方向、技术栈
🌫 模糊：模块划分、接口细节、算法选择
末尾必须问：我理解得对吗？有遗漏或偏差吗？
审批通过后立即调用 set_project 和 crystallize(ArchCrystal)。""",

    "L2": """## L2 — 模块拆解
输出：【模块清单】(每个模块一句话职责+现实类比) + 【实现顺序】(简述依赖关系)
末尾必须标注：
🔒 锁定：模块边界、实现顺序
🌫 模糊：每个模块的接口细节、内部算法
末尾必须问：这个划分合理吗？有多余或缺失的部分吗？
审批通过后立即调用 dependency(command="define", ...)，然后 crystallize(ModMap)。
若 dependency 报告循环依赖，必须解决后再进 L3。简单项目可跳过 L2。""",

    "L3": """## L3 — 模块规格书（契约优先 — v2.1）

工作节奏（v2.1 契约优先）：所有模块先并行完成 L3 签约，全部审批通过后再按拓扑序逐个迭代 L4→L7。当前模块 L3 签约完成后，继续下一个未签约模块的 L3；全部签约完成后才能进入任何一个模块的 L4。

启动前确认：确保所有上游依赖模块的 L3 已签约（非实现），可通过 get_active_crystals(crystal_type="ContractCrystal") 检查。

输出：【功能目标】+【输入/输出】(带类型和示例值) +【接口契约】(带类型签名的函数头) +【边界情况】(非法输入策略、依赖不可用策略)

末尾必须标注：
🔒 锁定：接口签名、输入输出格式、边界处理策略
🌫 模糊：内部实现算法

末尾必须问：这个模块的接口契约符合你的预期吗？

完成本层产出后立即调用 request_approval(phase="L3", module="<当前模块>", content="<L3输出的完整Markdown>") 提请审批。审批通过后再调用 crystallize(ContractCrystal) 存储最终契约。

⚠️ 铁律：本模块 L3 未审批，不进入该模块的 L6。全部模块 L3 未完成，不进入任何模块的 L4。""",

    "L3.1": """## L3.1 — 契约复议
仅在 L7 实现中发现 L3 接口因技术现实严格不可行时触发。
先调用 dependency(command="impact", ...) 分析下游影响，将受影响模块清单注入复议上下文。
若受影响模块 > 3，优先考虑内部适配层而非改接口。
输出：⚠️ 契约冲突发现 → 原定契约 → 冲突原因 → 建议修订 → 影响范围 → 是否批准？
批准后更新 L3 契约，记录变更。""",

    "L4": """## L4 — 自然语言算法

v2.1 契约优先：进入 L4 前，确认所有模块的 L3 已签约完成。系统已自动注入本模块及所有直接依赖模块的 L3 契约（见上下文中的 "Dependency Contracts"），算法设计必须严格遵循这些接口契约，不得修改任何已锁定的接口。

判断：有分支/循环/状态变化/复杂数据变换 → 需要独立 L4；单一线性操作 → 合并到 L6。
输出：【处理步骤】(编号，每步写"做什么→得到什么") + 【边界情况处理】+ 【配套流程图】(有分支时必画 Mermaid)
末尾必须标注：
🔒 锁定：算法步骤、分支逻辑、边界处理
🌫 模糊：变量命名、具体语法、错误处理细节
末尾必须问：这个处理流程符合预期吗？
完成本层产出后立即调用 request_approval(phase="L4", module="<当前模块>", content="<L4输出的完整Markdown>") 提请审批。审批通过后再调用 crystallize(LogicCrystal) 存储最终算法。""",

    "L5": """## L5 — 严格伪代码
默认跳过。仅在算法复杂（递归、动态规划、状态机）或 L4→L6 跨度过大时启用。
跳过时在 L6 头部注明：# [已跳过 L5：L4 逻辑直观，直接进入代码骨架]
启用时完成伪代码产出后立即调用 request_approval(phase="L5", module="<当前模块>", content="<L5输出的完整Markdown>") 提请审批。审批通过后再调用 crystallize(SkeletonCrystal) 存储最终伪代码。跳过时无需记录快照。""",

    "L6": """## L6 — 代码骨架
基于 L3 接口 + L4 算法，用 TODO 标记待填充处。
铁律：
- 类型标注必须与 L3 接口契约严格一致
- 每个步骤注释必须对应 L4 的步骤编号
- 错误处理结构必须建立（try/except 可含 TODO），不能用空 pass
- 所有公开函数必须有结构化注释（@brief @param @returns @throws）
末尾必须标注：
🔒 锁定：函数结构、命名、注释体系、错误处理骨架
🌫 模糊：TODO 内的具体实现
末尾必须问：代码结构和命名符合预期吗？
完成本层产出后立即调用 request_approval(phase="L6", module="<当前模块>", content="<L6输出的完整Markdown>") 提请审批。审批通过后再调用 crystallize(SkeletonCrystal) 存储最终骨架。
⚠️ 铁律：本层未审批，不进 L7。""",

    "L7": """## L7 — 完整实现
操作规则（零容忍）：
1. 先 read 获取行号，绝不凭记忆
2. 用 edit 模式只替换 TODO 块，不动已确认结构
3. 每完成一个函数，立即运行最小测试
4. 每次 edit 后立即 read 刷新行号
完成前逐条自检：所有 TODO 已填充、错误处理完整（非空 pass）、命名与 L3 一致（或 L3.1 获批）、最小测试通过、未引入 L3 未定义的新行为（等价优化需注释说明）、已删除调试 print/注释掉的旧代码。
完成实现并通过自检后立即调用 request_approval(phase="L7", module="<当前模块>", content="<实现摘要与测试结果>", files=["<实现文件路径>", ...]) 提请审批。审批通过后再调用 crystallize(ImplCrystal) 存储最终实现。""",

    "L8": """## L8 — 集成测试 & Bug 回溯
Bug 定位前先调用 dependency(command="impact", ...) 划定波及范围。
决策树：
- 报错指向具体函数 → 回 L6/L7（read 后精准修改）
- 数据"正确但不符合预期" → 回 L4（算法逻辑）
- 两模块各自通过但组合出错 → 回 L3（接口脱节）→ 触发 L3.1
- 多模块受影响 → 回 L2（模块划分）→ 重新审批架构
汇报格式：现象 → 回溯层级 → 根本原因 → 修复方案 → 影响范围。
审批通过后立即调用 crystallize(TraceCrystal)。""",
}


def get_phase_context(phase: str) -> str | None:
    """Return the combined phase + global context for a given phase.

    Returns None if phase is not in PHASE_PROMPTS.
    """
    prompt = PHASE_PROMPTS.get(phase)
    if prompt is None:
        return None
    return GLOBAL_PRINCIPLES + "\n\n" + prompt
