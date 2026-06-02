# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Chat Route - /chat SSE stream
"""

import json
import queue
import sys
import uuid
import markdown
from flask import Blueprint, request, jsonify, Response, stream_with_context
from src.auth import login_required
from src import state
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from knowledge import search, add_conversation, add_conversation_with_llm

chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400

    def generate():
        full_response = ""

        try:
            # Knowledge retrieval (two-level summary memory system)
            try:
                k = getattr(state.chat_agent, "knowledge_k", 5)
                relevant = search(user_message, k=k)
                for item in relevant:
                    # Copy to avoid mutating shared results and to prevent
                    # item's own "type" key from overwriting SSE event type
                    knowledge_item = dict(item)
                    doc_type = knowledge_item.pop("type", "generic")
                    knowledge_item["doc_type"] = doc_type
                    yield f"data: {json.dumps({'type': 'knowledge', **knowledge_item})}\n\n"
            except Exception as e:
                print(f"Knowledge retrieval failed: {e}")

            # Crystal search — display matching crystals in frontend
            try:
                agent = state.chat_agent
                if agent and agent.crystal_store and state.active_project:
                    crystal_k = getattr(agent, "crystal_k", 3)
                    phase = state.active_project.get("phase", "")
                    module = state.active_project.get("module", "")
                    crystal_items = []

                    def _safe_list(val):
                        if isinstance(val, list):
                            return ", ".join(val)
                        if isinstance(val, str):
                            return val
                        return str(val) if val else ""

                    def _fmt_contract(c):
                        content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                        return {
                            "title": f"{c.get('module', '')}/{c.get('name', '')}",
                            "text": f"**ContractCrystal v{c.get('vitality', 0)}**\n\n"
                                    f"项目: {c.get('project_id', '')}\n\n"
                                    f"签名: {content.get('signature', 'N/A')}\n\n"
                                    f"前置条件: {_safe_list(content.get('preconditions'))}\n\n"
                                    f"后置条件: {_safe_list(content.get('postconditions'))}",
                            "icon": "🔮",
                            "doc_type": "crystal_contract",
                            "memory_id": f"crystal:{c.get('crystal_id', '')}",
                            "score": c.get("_score", 0),
                        }

                    def _fmt_trace(t):
                        content = t.get("content", {}) if isinstance(t.get("content"), dict) else {}
                        return {
                            "title": t.get("name", ""),
                            "text": f"**TraceCrystal**\n\n"
                                    f"症状: {content.get('symptom', 'N/A')}\n\n"
                                    f"根因: {content.get('root_cause', 'N/A')}\n\n"
                                    f"修复: {content.get('fix', 'N/A')}",
                            "icon": "🔍",
                            "doc_type": "crystal_trace",
                            "memory_id": f"crystal:{t.get('crystal_id', '')}",
                            "score": t.get("_score", 0),
                        }

                    # L3/L4/L5: contracts + traces; L6/L7/L8: traces only
                    if phase in ("L3", "L4", "L5"):
                        contracts = agent.crystal_store.find_similar_contracts(
                            user_message, top_k=crystal_k
                        )
                        traces = agent.crystal_store.find_related_traces(
                            module or user_message, top_k=max(1, crystal_k - 1)
                        )
                        for c in contracts:
                            crystal_items.append(_fmt_contract(c))
                        for t in traces:
                            crystal_items.append(_fmt_trace(t))
                    elif phase in ("L6", "L7", "L8"):
                        traces = agent.crystal_store.find_related_traces(
                            module or user_message, top_k=crystal_k
                        )
                        for t in traces:
                            crystal_items.append(_fmt_trace(t))

                    if crystal_items:
                        print(
                            f"[CrystalSSE] Sending {len(crystal_items)} crystal items "
                            f"for phase={phase}", file=sys.stderr
                        )
                    for item in crystal_items:
                        yield f"data: {json.dumps({'type': 'crystal', **item})}\n\n"
            except Exception as e:
                import traceback
                print(f"Crystal search failed: {e}", file=sys.stderr)
                traceback.print_exc()

            # Phase rollback notification — push SSE event to frontend
            try:
                if state.phase_rollback_notice:
                    notice = state.phase_rollback_notice
                    # Also fetch the last contract for the module to show in the notice
                    contract_info = None
                    if notice.get("module") and state.chat_agent and state.chat_agent.crystal_store:
                        contracts = state.chat_agent.crystal_store.get_active_crystals(
                            project_id=state.active_project.get("project_id", ""),
                            crystal_type="ContractCrystal",
                            module=notice["module"],
                        )
                        if contracts:
                            c = contracts[0]
                            content = c.get("content", {}) if isinstance(c.get("content"), dict) else {}
                            contract_info = {
                                "name": c.get("name", ""),
                                "signature": content.get("signature", ""),
                                "preconditions": content.get("preconditions", []),
                                "postconditions": content.get("postconditions", []),
                            }
                    yield f"data: {json.dumps({'type': 'phase_rollback', 'from': notice['from'], 'to': notice['to'], 'module': notice.get('module', ''), 'contract': contract_info})}\n\n"
                    print(
                        f"[PhaseRollback] SSE event sent: {notice['from']} -> {notice['to']} "
                        f"(module={notice.get('module', '')})", file=sys.stderr
                    )
            except Exception as e:
                print(f"Phase rollback SSE failed: {e}", file=sys.stderr)

            agent_gen = state.chat_agent.input(user_message)
            gen_exhausted = False

            while not gen_exhausted:
                try:
                    item = next(agent_gen)
                except StopIteration:
                    gen_exhausted = True
                    break

                # Text content chunk
                if isinstance(item, str):
                    full_response += item
                    yield f"data: {json.dumps({'type': 'content', 'text': item})}\n\n"

                # Tool call event
                elif isinstance(item, dict) and item.get("type") == "tool_call":
                    yield f"data: {json.dumps(item)}\n\n"

                # Tool result event
                elif isinstance(item, dict) and item.get("type") == "tool_result":
                    yield f"data: {json.dumps(item)}\n\n"

                # System injection notice (set_project / dependency tool context)
                elif isinstance(item, dict) and item.get("type") == "system_injection":
                    yield f"data: {json.dumps(item)}\n\n"

                # Context compression notice
                elif isinstance(item, dict) and item.get("type") == "compression":
                    yield f"data: {json.dumps(item)}\n\n"

                # Token usage report (input/output/total from API)
                elif isinstance(item, dict) and item.get("type") == "token_usage":
                    yield f"data: {json.dumps(item)}\n\n"

                # Project state change (set_project activate/deactivate)
                elif isinstance(item, dict) and item.get("type") == "project_state":
                    yield f"data: {json.dumps(item)}\n\n"

                # Outer-loop restart — signal frontend to create a new bubble
                elif isinstance(item, dict) and item.get("type") == "context_restart":
                    yield f"data: {json.dumps(item)}\n\n"

                # Confirmation request – wait for user approval instead of auto‑approving
                elif (
                    isinstance(item, dict)
                    and item.get("type") == "confirmation_required"
                ):
                    confirm_id = item.get("confirm_id", str(uuid.uuid4()))
                    # Ensure the item carries the confirm_id so the frontend can use it
                    item["confirm_id"] = confirm_id

                    # Register queue BEFORE yielding so frontend can immediately
                    # POST to /api/confirm_tool without racing
                    confirm_queue = queue.Queue()

                    with state.pending_lock:
                        state.pending_confirmations[confirm_id] = {
                            "generator": agent_gen,
                            "queue": confirm_queue,
                        }

                    # Send the confirmation request to the frontend
                    yield f"data: {json.dumps(item)}\n\n"

                    # Block until the user approves or rejects via /api/confirm_tool.
                    # Short timeout + keepalive yield allows GeneratorExit to be
                    # delivered when the client disconnects.
                    approved = None
                    while approved is None:
                        try:
                            approved = confirm_queue.get(timeout=1)
                        except queue.Empty:
                            yield f": keepalive\n\n"

                    with state.pending_lock:
                        state.pending_confirmations.pop(confirm_id, None)

                    # Feed the user's decision back into the generator
                    try:
                        next_item = agent_gen.send(approved)
                        if isinstance(next_item, dict):
                            if next_item.get("type") == "tool_result":
                                yield f"data: {json.dumps(next_item)}\n\n"
                            else:
                                # In case something else comes back, send it as generic
                                yield f"data: {json.dumps(next_item)}\n\n"
                        elif isinstance(next_item, str):
                            full_response += next_item
                            yield f"data: {json.dumps({'type': 'content', 'text': next_item})}\n\n"
                    except StopIteration:
                        gen_exhausted = True

                # Write proposal – send AI content to frontend, wait for user's final content
                elif (
                    isinstance(item, dict)
                    and item.get("type") == "write_proposal"
                ):
                    confirm_id = item.get("confirm_id", str(uuid.uuid4()))
                    item["confirm_id"] = confirm_id

                    # Register queue BEFORE yielding so frontend can immediately
                    # POST to /api/confirm_tool without racing
                    confirm_queue = queue.Queue()

                    with state.pending_lock:
                        state.pending_confirmations[confirm_id] = {
                            "generator": agent_gen,
                            "queue": confirm_queue,
                        }

                    # Send the write proposal to the frontend
                    yield f"data: {json.dumps(item)}\n\n"

                    # Block until the user returns the final content via /api/confirm_tool
                    final_content = None
                    while final_content is None:
                        try:
                            final_content = confirm_queue.get(timeout=1)
                        except queue.Empty:
                            yield f": keepalive\n\n"

                    with state.pending_lock:
                        state.pending_confirmations.pop(confirm_id, None)

                    # Feed the user's final content back into the generator
                    try:
                        next_item = agent_gen.send(final_content)
                        if isinstance(next_item, dict):
                            if next_item.get("type") == "tool_result":
                                yield f"data: {json.dumps(next_item)}\n\n"
                            else:
                                yield f"data: {json.dumps(next_item)}\n\n"
                        elif isinstance(next_item, str):
                            full_response += next_item
                            yield f"data: {json.dumps({'type': 'content', 'text': next_item})}\n\n"
                    except StopIteration:
                        gen_exhausted = True

                # Approval request — show Lx content in Markdown, wait for approve/reject
                elif (
                    isinstance(item, dict)
                    and item.get("type") == "approval_required"
                ):
                    confirm_id = item.get("confirm_id", str(uuid.uuid4()))
                    item["confirm_id"] = confirm_id

                    # Register queue BEFORE yielding so frontend can immediately
                    # POST to /api/confirm_tool without racing
                    confirm_queue = queue.Queue()
                    with state.pending_lock:
                        state.pending_confirmations[confirm_id] = {
                            "generator": agent_gen,
                            "queue": confirm_queue,
                        }

                    # Send to frontend
                    yield f"data: {json.dumps(item)}\n\n"

                    # Block until the user approves or rejects via /api/confirm_tool
                    approved = None
                    while approved is None:
                        try:
                            approved = confirm_queue.get(timeout=1)
                        except queue.Empty:
                            yield f": keepalive\n\n"

                    with state.pending_lock:
                        state.pending_confirmations.pop(confirm_id, None)

                    # Feed the user's decision back into the generator
                    try:
                        next_item = agent_gen.send(approved)
                        if isinstance(next_item, dict):
                            if next_item.get("type") == "tool_result":
                                yield f"data: {json.dumps(next_item)}\n\n"
                            else:
                                yield f"data: {json.dumps(next_item)}\n\n"
                        elif isinstance(next_item, str):
                            full_response += next_item
                            yield f"data: {json.dumps({'type': 'content', 'text': next_item})}\n\n"
                    except StopIteration:
                        gen_exhausted = True

                else:
                    print(f"Unknown item from agent generator: {item}")

            # Markdown rendering for full response
            if full_response:
                try:
                    html = markdown.markdown(
                        full_response, extensions=["tables", "fenced_code"]
                    )
                    yield f"data: {json.dumps({'type': 'html', 'html': html})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'text': f'Markdown rendering failed: {str(e)}'})}\n\n"

            # Conversation history (two-level summary memory)
            if full_response:
                agent = state.chat_agent
                if agent and hasattr(agent, "client") and agent.client:
                    # Prefer lightweight model for summarization (cheaper/faster)
                    try:
                        from knowledge.lightweight import is_available, get_model as _lw_model
                        from knowledge.lightweight import _get_client as _lw_client
                        if is_available():
                            add_conversation_with_llm(
                                user_message,
                                full_response,
                                client=_lw_client(),
                                model=_lw_model(),
                                background=True,
                            )
                        else:
                            raise RuntimeError("lightweight unavailable")
                    except Exception:
                        add_conversation_with_llm(
                            user_message,
                            full_response,
                            client=agent.client,
                            model=agent.model,
                            background=True,
                        )
                else:
                    add_conversation(user_message, full_response)

            # Done signal
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except GeneratorExit:
            # Client disconnected – clean up any pending confirmations
            with state.pending_lock:
                for confirm_id, info in list(state.pending_confirmations.items()):
                    if info.get("generator") is agent_gen:
                        try:
                            info["queue"].put(False)
                        except Exception:
                            pass
                        del state.pending_confirmations[confirm_id]
            raise  # Re-raise to properly terminate the generator
        except Exception as e:
            import traceback

            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'text': f'Agent crashed: {str(e)}'})}\n\n"
        finally:
            # Always clear phase rollback notice to prevent stale state leaking
            # into the next request (handles both normal completion and disconnect)
            state.phase_rollback_notice = None

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@chat_bp.route("/api/confirm_tool", methods=["POST"])
@login_required
def confirm_tool():
    """
    Called by the frontend when the user clicks Approve or Reject.
    For write tools: sends the user's final content back to the generator.
    For command tools: sends True/False to approve or reject.
    """
    data = request.get_json()
    confirm_id = data.get("confirm_id")
    approved = data.get("approved", False)
    final_content = data.get("final_content", None)
    rejection_reason = data.get("rejection_reason", None)

    if not confirm_id:
        return jsonify({"error": "Missing confirm_id"}), 400

    with state.pending_lock:
        info = state.pending_confirmations.get(confirm_id)
        if info and "queue" in info:
            if final_content is not None:
                # write tool: send the user's final content back to the generator
                info["queue"].put(final_content)
            elif rejection_reason is not None:
                # approval tool with rejection feedback
                info["queue"].put({"approved": approved, "reason": rejection_reason})
            else:
                # command tool: send True/False
                info["queue"].put(approved)
            return jsonify({"status": "ok"})

    return jsonify({"error": "No pending confirmation found for this id"}), 404


@chat_bp.route("/api/read_file", methods=["POST"])
@login_required
def read_file():
    """
    Read the content of a file at the given path.
    Returns the file content as UTF-8 text.
    """
    data = request.get_json()
    path = data.get("path", "")

    if not path:
        return jsonify({"error": "Missing path"}), 400

    try:
        p = Path(path).expanduser().resolve()
        # Restrict file access to the project directory and safe subdirectories
        project_root = Path(__file__).parent.parent.parent.resolve()
        try:
            p.relative_to(project_root)
        except ValueError:
            return jsonify({"error": "Access denied: path outside project directory"}), 403
        if not p.exists():
            return jsonify({"content": ""}), 200
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content}), 200
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_SENSITIVE_FILENAMES = {
    "config.json", "config.json.tmp", "private.key", ".env",
    "crystals.db", "messages.json",
}

@chat_bp.route("/api/write_file", methods=["POST"])
@login_required
def write_file():
    """
    Write content to a file at the given path.
    Creates parent directories if they don't exist.
    """
    data = request.get_json()
    path = data.get("path", "")
    content = data.get("content", "")

    if not path:
        return jsonify({"error": "Missing path"}), 400

    try:
        p = Path(path).expanduser().resolve()
        # Restrict file access to the project directory and safe subdirectories
        project_root = Path(__file__).parent.parent.parent.resolve()
        try:
            p.relative_to(project_root)
        except ValueError:
            return jsonify({"error": "Access denied: path outside project directory"}), 403
        if p.name in _SENSITIVE_FILENAMES:
            return jsonify({"error": f"Access denied: writing to {p.name} is not permitted via the web API"}), 403
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"status": "ok"}), 200
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403
    except Exception as e:
      return jsonify({"error": str(e)}), 500
