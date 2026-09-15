import uuid
import json
from flask import request, jsonify

from database.db_connection import call_procedure
from services import rag_service
from services.llm_service import get_ai_response, LLMError


def _error(message, code, http_status=400):
    return jsonify({"status": "error", "message": message, "error_code": code}), http_status


def _row_to_session(row: dict) -> dict:
    return {
        "id": row["id"],
        "profileId": row["profile_id"],
        "tradition": row["tradition"],
        "title": row["title"],
        "messageCount": row.get("message_count", 0),
        "createdAt": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        "updatedAt": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
    }


def _row_to_message(row: dict) -> dict:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "createdAt": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
    }


def list_sessions(user_id: str):
    rows = call_procedure("sp_ai_ops", ['get_sessions', '', user_id, '', '', '', '', ''])
    return jsonify({"status": "success", "data": [_row_to_session(r) for r in rows]})


def create_session(user_id: str):
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profileId")
    tradition = body.get("tradition", "parashari")
    title = body.get("title", "New Consultation")

    if not profile_id:
        return _error("profileId is required", "VALIDATION_ERROR")

    owned = call_procedure("sp_profile_ops", [
        'get_one', profile_id, user_id, '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''
    ])
    if not owned:
        return _error("Profile not found", "NOT_FOUND", 404)

    session_id = str(uuid.uuid4())
    rows = call_procedure("sp_ai_ops", ['create_session', session_id, user_id, profile_id, tradition, title, '', ''])
    if not rows:
        return _error("Could not create session", "CREATE_FAILED", 500)

    return jsonify({"status": "success", "data": _row_to_session({**rows[0], "message_count": 0})}), 201


def rename_session(user_id: str, session_id: str):
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    if not title:
        return _error("title is required", "VALIDATION_ERROR")

    rows = call_procedure("sp_ai_ops", ['rename_session', session_id, user_id, '', '', title, '', ''])
    if not rows:
        return _error("Session not found", "NOT_FOUND", 404)

    return jsonify({"status": "success", "data": _row_to_session(rows[0])})


def delete_session(user_id: str, session_id: str):
    rows = call_procedure("sp_ai_ops", ['delete_session', session_id, user_id, '', '', '', '', ''])
    deleted = rows[0]["deleted_count"] if rows else 0
    if not deleted:
        return _error("Session not found", "NOT_FOUND", 404)

    return jsonify({"status": "success", "data": {"deleted": True}})


def get_messages(user_id: str, session_id: str):
    session_rows = call_procedure("sp_ai_ops", ['get_session', session_id, user_id, '', '', '', '', ''])
    if not session_rows:
        return _error("Session not found", "NOT_FOUND", 404)

    rows = call_procedure("sp_ai_ops", ['get_messages', session_id, '', '', '', '', '', ''])
    return jsonify({"status": "success", "data": [_row_to_message(r) for r in rows]})


def send_message(user_id: str, session_id: str):
    """Persists the user's message, retrieves classical reference
    knowledge relevant to it, calls the configured LLM grounded in the
    already-calculated chart/numerology data, persists the assistant's
    reply, and returns both. Never fabricates a reply if the LLM is
    unreachable — returns a clear error instead."""
    body = request.get_json(silent=True) or {}
    text = (body.get("message") or "").strip()
    chart_summary = body.get("chartSummary", "")
    numerology_summary = body.get("numerologySummary", "")

    if not text:
        return _error("message is required", "VALIDATION_ERROR")

    session_rows = call_procedure("sp_ai_ops", ['get_session', session_id, user_id, '', '', '', '', ''])
    if not session_rows:
        return _error("Session not found", "NOT_FOUND", 404)
    session = session_rows[0]

    # Persist the user's message first, regardless of what happens next.
    call_procedure("sp_create_ai_message", [str(uuid.uuid4()), session_id, "user", text])

    history_rows = call_procedure("sp_ai_ops", ['get_messages', session_id, '', '', '', '', '', ''])
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    rag_hits = rag_service.retrieve(text)
    rag_context = "\n\n".join(hit["text"] for hit in rag_hits) if rag_hits else ""

    try:
        reply_text = get_ai_response(
            history=history,
            tradition=session["tradition"],
            chart_summary=chart_summary,
            numerology_summary=numerology_summary,
            rag_context=rag_context,
        )
    except LLMError as e:
        return _error(str(e), "LLM_UNAVAILABLE", 503)

    assistant_rows = call_procedure("sp_create_ai_message", [str(uuid.uuid4()), session_id, "assistant", reply_text])
    call_procedure("sp_ai_ops", ['touch_session', session_id, '', '', '', '', '', ''])

    return jsonify({
        "status": "success",
        "data": {
            "message": _row_to_message(assistant_rows[0]),
            "ragSources": [hit["id"] for hit in rag_hits],
        },
    })
