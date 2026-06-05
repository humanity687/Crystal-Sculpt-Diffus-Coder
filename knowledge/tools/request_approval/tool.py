# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

schema = {
    "type": "function",
    "function": {
        "name": "request_approval",
        "description": (
            "Store a ModuleRecord snapshot for the current Lx phase output and request user approval. "
            "Call this after completing a phase deliverable (L3 contract, L7 implementation, etc.). "
            "The content is shown to the user in an approval modal. On approval, the workflow continues. "
            "On rejection, you must revise and call request_approval again."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phase": {"type": "string", "description": "Workflow phase. One of: L0, L1, L2, L3, L3.1, L4, L5, L6, L7, L8."},
                "module": {"type": "string", "description": "Module name (e.g. 'Auth', 'MemoryManager')."},
                "content": {"type": "string", "description": "Approval request body in Markdown — describe the deliverable, key decisions, test results, etc."},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Optional list of file paths to attach for preview."},
                "summary": {"type": "string", "description": "One-line summary for the snapshot index."},
            },
            "required": ["phase", "module", "content"],
        },
    },
}


def execute(phase: str, module: str, content: str,
            files: list = None, summary: str = "") -> str:
    """
    Store a ModuleRecord snapshot for the current Lx phase output.

    This replaces set_project(action="record", ...).  The model passes Lx
    content DIRECTLY as a parameter — no backward-message-scanning, no
    timing issues, no delimiter guessing.

    Args:
        phase: Workflow phase. One of L3..L7, L3.1
        module: Module name (e.g. "Auth", "MemoryManager")
        content: Approval request body in Markdown — natural language
                 description, summary, test results, etc.
        files: Attachments (附件).  File paths — code files, drafts,
               test outputs, etc.  Tool reads each and includes its
               content for preview.  Mainly used in L7 but any layer
               may attach files.
        summary: One-line summary for snapshot index.

    Returns:
        JSON string: {"status": "stored", "crystal_id": "...", ...}
        or error message.
    """
    import json
    from pathlib import Path
    from src import state

    if state.crystal_store is None:
        return "Error: CrystalStore is not initialized."
    if not state.active_project:
        return "Error: No active project. Call set_project(action=\"activate\", ...) first."

    valid_phases = {f"L{i}" for i in range(9)}
    valid_phases.add("L3.1")
    if phase not in valid_phases:
        return f"Error: Invalid phase '{phase}'. Must be L0-L8 or L3.1."

    if not module or not module.strip():
        return "Error: module is required."
    if not content or not content.strip():
        return "Error: content is required."

    # Normalize files: model may pass a JSON string, a single path string,
    # or a proper list.  Always convert to a list before iterating.
    if files is not None and not isinstance(files, list):
        if isinstance(files, str):
            try:
                parsed = json.loads(files)
                if isinstance(parsed, list):
                    files = parsed
                elif isinstance(parsed, str):
                    files = [parsed]
                else:
                    files = []
            except json.JSONDecodeError:
                files = [files]  # plain path string
        else:
            files = []
    elif files is None:
        files = []

    file_contents = {}
    for fpath in files:
        if not isinstance(fpath, str):
            continue
        try:
            p = Path(fpath).expanduser().resolve()
            file_contents[fpath] = p.read_text(encoding="utf-8")
        except Exception as e:
            file_contents[fpath] = f"[Error reading file: {e}]"

    record_type = f"{phase}_snapshot"
    snapshot = {
        "record_type": record_type,
        "phase": phase,
        "module": module.strip(),
        "content": content,
        "summary": summary or "",
    }
    if file_contents:
        snapshot["files"] = file_contents

    proj_id = state.active_project["project_id"]
    name = f"{module.strip()}-{record_type}"

    try:
        cid = state.crystal_store.put_crystal(
            crystal_type="ModuleRecord",
            project_id=proj_id,
            layer=phase,
            module=module.strip(),
            name=name,
            content=snapshot,
        )
        return json.dumps({
            "status": "stored",
            "crystal_id": cid,
            "phase": phase,
            "module": module.strip(),
            "content": content,
            "files": files or [],
            "file_contents": file_contents,
        }, ensure_ascii=False)
    except Exception as e:
        return f"Error storing ModuleRecord: {e}"
