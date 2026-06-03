# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
CrystalObserver — Automatic crystal extraction from conversation turns.

When active_project is set, analyzes the last turn after the agent finishes
responding (no more tool calls). Uses a lightweight LLM probe to determine
whether the agent produced structured output matching a crystal type, and
if so, extracts and stores it automatically.

This is a supplementary mechanism — the primary path is the crystallize tool.
"""

import json
import sys

VALID_CRYSTAL_TYPES = {
    "ArchCrystal", "ModMap", "ContractCrystal", "LogicCrystal",
    "SkeletonCrystal", "ImplCrystal", "TraceCrystal", "ModuleRecord",
    "ExperienceCrystal",
}

# Required fields per crystal type for content schema validation
CRYSTAL_REQUIRED_FIELDS = {
    "ArchCrystal": ("architecture_summary", "tech_stack", "core_flow"),
    "ModMap": ("modules", "dependencies"),
    "ContractCrystal": ("signature", "preconditions", "postconditions"),
    "LogicCrystal": ("algorithm_steps",),
    "SkeletonCrystal": ("code_skeleton", "language"),
    "ImplCrystal": ("code", "language"),
    "TraceCrystal": ("symptom", "root_cause", "fix"),
    "ModuleRecord": ("record_type",),
    "ExperienceCrystal": ("title", "summary"),
}

EXTRACTION_PROMPT = """你是一个结晶提取探针。分析以下对话回合，判断 Agent 是否产出了值得结晶的工程结构化产物。

当前项目: {project_id}
当前阶段: {phase}
当前模块: {module}

根据当前阶段，判断是否应提取对应类型的结晶：

- L1 → ArchCrystal: architecture_summary（架构摘要）, tech_stack（技术栈列表）, core_flow（核心流程）
- L2 → ModMap: modules（模块列表，每项含 name 和 responsibility）, dependencies（依赖关系 dict）
- L3 → ContractCrystal: signature（函数签名）, preconditions（前置条件列表）, postconditions（后置条件列表）, constraints（约束列表）
- L4 → LogicCrystal: algorithm_steps（算法步骤列表）, boundary_handling（边界处理 dict）
- L6 → SkeletonCrystal: code_skeleton（代码骨架）, language（编程语言）
- L7 → ImplCrystal: code（完整代码）, tests（测试列表）, language（编程语言）
- L8 → TraceCrystal: symptom（症状）, root_cause（根因）, fix（修复方案）

只返回一个 JSON 对象。如果不应该提取，返回：
{{"extract": false}}

如果应该提取，返回：
{{
  "extract": true,
  "crystal_type": "ContractCrystal",
  "module": "模块名",
  "name": "描述性名称",
  "content": {{ ... 与 crystal_type 匹配的结构化内容 ... }}
}}

重要：content 字段必须严格匹配 crystal_type 的 schema。不要发明新字段。
只在 Agent 明确产出了对应阶段的结构化输出时才提取。

对话回合：
{conversation}"""


class CrystalObserver:
    """Auto-extracts crystals from conversation turns using LLM analysis."""

    def __init__(self, api_key: str, base_url: str, model: str, crystal_store):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=30.0)
        self.model = model
        self.crystal_store = crystal_store

    def analyze_turn(
        self, messages: list[dict], active_project: dict | None
    ) -> str | None:
        """
        Analyze the last turn and auto-extract a crystal if warranted.

        Only activates when active_project is set and crystal_store is
        available. Uses a lightweight LLM call (stream=False, low
        temperature) to minimize latency.

        Args:
            messages: Recent messages from the conversation (user, assistant, tool).
            active_project: Current active project state dict.

        Returns:
            crystal_id string if a crystal was extracted, None otherwise.
        """
        if active_project is None or self.crystal_store is None:
            return None

        # Build conversation text from recent messages
        conversation_parts = []
        for msg in messages[-6:]:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                # Truncate very long messages for the extraction probe
                truncated = content[:2000] if len(content) > 2000 else content
                conversation_parts.append(f"[{role}]: {truncated}")
        conversation_text = "\n".join(conversation_parts)

        if not conversation_text.strip():
            return None

        prompt = EXTRACTION_PROMPT.format(
            project_id=active_project.get("project_id", "unknown"),
            phase=active_project.get("phase", "L0"),
            module=active_project.get("module", "none"),
            conversation=conversation_text,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
            result_text = (response.choices[0].message.content or "").strip()

            # Strip markdown code fences if present
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                result_text = "\n".join(lines)

            result = json.loads(result_text)

            if not result.get("extract"):
                return None

            crystal_type = result.get("crystal_type")
            module = result.get("module", active_project.get("module", "unknown"))
            name = result.get("name", "auto-extracted")
            content = result.get("content", {})

            if not crystal_type or not content or not isinstance(content, dict):
                return None

            # Validate crystal_type is a known type
            if crystal_type not in VALID_CRYSTAL_TYPES:
                print(
                    f"[CrystalObserver] Unknown crystal_type '{crystal_type}', skipping",
                    file=sys.stderr,
                )
                return None

            # Validate content has required fields for the crystal type
            required = CRYSTAL_REQUIRED_FIELDS.get(crystal_type, ())
            missing = [f for f in required if f not in content]
            if missing:
                print(
                    f"[CrystalObserver] {crystal_type} missing required fields: {missing}, skipping",
                    file=sys.stderr,
                )
                return None

            crystal_id = self.crystal_store.put_crystal(
                crystal_type=crystal_type,
                project_id=active_project.get("project_id", ""),
                layer=active_project.get("phase", "L0"),
                module=module,
                name=name,
                content=content,
            )

            return crystal_id

        except json.JSONDecodeError as e:
            print(f"[CrystalObserver] Extraction skipped (invalid JSON): {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[CrystalObserver] Non-fatal error: {e}", file=sys.stderr)
            return None
