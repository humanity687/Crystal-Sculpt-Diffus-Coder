# Copyright (C) 2026 xhdlphzr
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
- 每层审批通过后立即更新项目进度：调用 set_project 推进 phase 到下一层，调用 crystallize 保存本层产物。若项目所有模块的 L7 均完成，phase 设置为 L8。"""

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

    "L3": """## L3 — 模块规格书
工作节奏：一个模块的 L3→L7 全部完成后再开下一个模块。
启动前调用 dependency(command="recommend", ...)，确认模块在 "Ready to Implement" 列表中。
输出：【功能目标】+【输入/输出】(带类型和示例值) +【接口契约】(带类型签名的函数头) +【边界情况】(非法输入策略、依赖不可用策略)
末尾必须标注：
🔒 锁定：接口签名、输入输出格式、边界处理策略
🌫 模糊：内部实现算法
末尾必须问：这个模块的接口契约符合你的预期吗？
审批通过后立即调用 crystallize(ContractCrystal)。
⚠️ 铁律：本层未审批，不进 L6。""",

    "L3.1": """## L3.1 — 契约复议
仅在 L7 实现中发现 L3 接口因技术现实严格不可行时触发。
先调用 dependency(command="impact", ...) 分析下游影响，将受影响模块清单注入复议上下文。
若受影响模块 > 3，优先考虑内部适配层而非改接口。
输出：⚠️ 契约冲突发现 → 原定契约 → 冲突原因 → 建议修订 → 影响范围 → 是否批准？
批准后更新 L3 契约，记录变更。""",

    "L4": """## L4 — 自然语言算法
判断：有分支/循环/状态变化/复杂数据变换 → 需要独立 L4；单一线性操作 → 合并到 L6。
输出：【处理步骤】(编号，每步写"做什么→得到什么") + 【边界情况处理】+ 【配套流程图】(有分支时必画 Mermaid)
末尾必须标注：
🔒 锁定：算法步骤、分支逻辑、边界处理
🌫 模糊：变量命名、具体语法、错误处理细节
末尾必须问：这个处理流程符合预期吗？
审批通过后立即调用 crystallize(LogicCrystal)。""",

    "L5": """## L5 — 严格伪代码
默认跳过。仅在算法复杂（递归、动态规划、状态机）或 L4→L6 跨度过大时启用。
跳过时在 L6 头部注明：# [已跳过 L5：L4 逻辑直观，直接进入代码骨架]""",

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
审批通过后立即调用 crystallize(SkeletonCrystal)。
⚠️ 铁律：本层未审批，不进 L7。""",

    "L7": """## L7 — 完整实现
操作规则（零容忍）：
1. 先 read 获取行号，绝不凭记忆
2. 用 edit 模式只替换 TODO 块，不动已确认结构
3. 每完成一个函数，立即运行最小测试
4. 每次 edit 后立即 read 刷新行号
完成前逐条自检：所有 TODO 已填充、错误处理完整（非空 pass）、命名与 L3 一致（或 L3.1 获批）、最小测试通过、未引入 L3 未定义的新行为（等价优化需注释说明）、已删除调试 print/注释掉的旧代码。
审批通过后立即调用 crystallize(ImplCrystal)。""",

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
