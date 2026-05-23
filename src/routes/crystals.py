# Copyright (C) 2026 xhdlphzr
# This file is part of FranxAgent.
# FranxAgent is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# FranxAgent is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with FranxAgent.  If not, see <https://www.gnu.org/licenses/>.

"""
Crystal REST API — HTTP endpoints for external toolchain integration.

All CrystalStore methods are pure functions (no Flask dependency), so route
handlers simply validate inputs and delegate to state.crystal_store.
"""

from flask import Blueprint, request, jsonify
from src.auth import login_required
from src import state

crystals_bp = Blueprint("crystals", __name__)


# ━━━ GET /api/crystals — list active crystals ━━━

@crystals_bp.route("/api/crystals", methods=["GET"])
@login_required
def list_crystals():
    """Query active crystals with optional filters."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    results = state.crystal_store.get_active_crystals(
        project_id=request.args.get("project_id"),
        crystal_type=request.args.get("crystal_type"),
        layer=request.args.get("layer"),
        module=request.args.get("module"),
    )
    return jsonify({"crystals": results})


# ━━━ GET /api/crystals/<id> — single crystal ━━━

@crystals_bp.route("/api/crystals/<int:crystal_id>", methods=["GET"])
@login_required
def get_crystal(crystal_id):
    """Get a single crystal by its integer ID."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    crystal = state.crystal_store.get_crystal(crystal_id)
    if crystal is None:
        return jsonify({"error": "Crystal not found"}), 404
    return jsonify(crystal)


# ━━━ POST /api/crystals — create crystal ━━━

@crystals_bp.route("/api/crystals", methods=["POST"])
@login_required
def create_crystal():
    """Create a new crystal. Required fields: crystal_type, project_id, layer, module, name, content."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    required = ["crystal_type", "project_id", "layer", "module", "name", "content"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    if not isinstance(data["content"], dict):
        return jsonify({"error": "content must be a JSON object"}), 400

    try:
        crystal_id = state.crystal_store.put_crystal(
            crystal_type=data["crystal_type"],
            project_id=data["project_id"],
            layer=data["layer"],
            module=data["module"],
            name=data["name"],
            content=data["content"],
            parent_ids=data.get("parent_ids"),
        )
        return jsonify({"crystal_id": crystal_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ━━━ PUT /api/crystals/<id>/deprecate ━━━

@crystals_bp.route("/api/crystals/<int:crystal_id>/deprecate", methods=["PUT"])
@login_required
def deprecate_crystal(crystal_id):
    """Mark a crystal as deprecated (soft delete)."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    existing = state.crystal_store.get_crystal(crystal_id)
    if existing is None:
        return jsonify({"error": "Crystal not found"}), 404

    state.crystal_store.deprecate_crystal(crystal_id)
    return jsonify({"status": "deprecated", "id": crystal_id})


# ━━━ PUT /api/crystals/<id>/vitality ━━━

@crystals_bp.route("/api/crystals/<int:crystal_id>/vitality", methods=["PUT"])
@login_required
def increment_vitality(crystal_id):
    """Increment a crystal's vitality score (successful reuse)."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    existing = state.crystal_store.get_crystal(crystal_id)
    if existing is None:
        return jsonify({"error": "Crystal not found"}), 404

    state.crystal_store.increment_vitality(crystal_id)
    return jsonify({"status": "vitality incremented", "id": crystal_id})


# ━━━ PUT /api/crystals/<id>/implement ━━━

@crystals_bp.route("/api/crystals/<int:crystal_id>/implement", methods=["PUT"])
@login_required
def set_has_implementation(crystal_id):
    """Mark a ContractCrystal as having a completed implementation."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    existing = state.crystal_store.get_crystal(crystal_id)
    if existing is None:
        return jsonify({"error": "Crystal not found"}), 404

    state.crystal_store.set_has_implementation(crystal_id)
    return jsonify({"status": "has_implementation set", "id": crystal_id})


# ━━━ GET /api/crystals/<id>/trace — full ancestry chain ━━━

@crystals_bp.route("/api/crystals/<int:crystal_id>/trace", methods=["GET"])
@login_required
def get_trace(crystal_id):
    """Follow parent_ids from a crystal back to its earliest ancestor."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    existing = state.crystal_store.get_crystal(crystal_id)
    if existing is None:
        return jsonify({"error": "Crystal not found"}), 404

    trace = state.crystal_store.get_full_trace(crystal_id)
    return jsonify({"trace": trace})


# ━━━ GET /api/crystals/contracts — vector similarity search ━━━

@crystals_bp.route("/api/crystals/contracts", methods=["GET"])
@login_required
def search_contracts():
    """Find ContractCrystals similar to a query using vector similarity."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    top_k = request.args.get("top_k", 5, type=int)
    results = state.crystal_store.find_similar_contracts(query, top_k=min(top_k, 20))
    return jsonify({"contracts": results})


# ━━━ GET /api/crystals/traces — module-related traces ━━━

@crystals_bp.route("/api/crystals/traces", methods=["GET"])
@login_required
def search_traces():
    """Find TraceCrystals related to a module or function signature."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    top_k = request.args.get("top_k", 3, type=int)
    results = state.crystal_store.find_related_traces(query, top_k=min(top_k, 20))
    return jsonify({"traces": results})


# ━━━ GET /api/crystals/context — phase-aware context (for external tools) ━━━

@crystals_bp.route("/api/crystals/context", methods=["GET"])
@login_required
def get_working_context():
    """Get the phase-aware engineering context for a project."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    project_id = request.args.get("project_id", "").strip()
    phase = request.args.get("phase", "L0").strip()
    module = request.args.get("module", "").strip() or None

    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    ctx = state.crystal_store.working_context(project_id, phase, module)
    return jsonify({"context": ctx})


# ━━━ POST /api/projects/<project_id>/archive ━━━

@crystals_bp.route("/api/projects/<project_id>/archive", methods=["POST"])
@login_required
def archive_project(project_id):
    """Archive all crystals for a project into an ArchCrystal."""
    if state.crystal_store is None:
        return jsonify({"error": "CrystalStore not initialized"}), 503

    try:
        crystal_id = state.crystal_store.archive_project(project_id)
        return jsonify({"crystal_id": crystal_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
