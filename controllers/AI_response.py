import json
import re
import uuid
from flask import request, jsonify
from database.db_connection import call_procedure

# In-memory fallback store for session histories
IN_MEMORY_SESSIONS = {}
MAX_SESSION_HISTORY = 10


def extract_auto_user_and_session():
    """
    Automatically detects user_id and session_id from auth token, headers,
    or client connection details if not provided in request body.
    """
    data = request.get_json(silent=True) or {}
    
    # 1. Check if set by @require_auth decorator on request
    user_id = getattr(request, "user_id", None)
    
    # 2. Check Authorization header for Bearer token
    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                from utils.security import decode_token
                payload = decode_token(token)
                user_id = payload.get("sub")
            except Exception:
                pass

    # 3. Check custom header or request body
    if not user_id:
        user_id = (
            request.headers.get("X-User-ID") or 
            data.get("user_id") or 
            data.get("userId") or 
            ""
        ).strip()

    # Determine session_id
    session_id = (
        request.headers.get("X-Session-ID") or 
        data.get("session_id") or 
        ""
    ).strip()

    # 4. Fallback to IP address if user_id/session_id not passed
    ip_addr = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()

    if not user_id:
        user_id = f"user_{ip_addr.replace('.', '_')}"

    if not session_id:
        if user_id and not user_id.startswith("user_"):
            session_id = f"session_{user_id[:8]}"
        else:
            session_id = "default_session"

    return user_id, session_id




def extract_msg_content(msg):
    if isinstance(msg, str):
        return msg.strip()
    if isinstance(msg, dict):
        raw = (
            msg.get("content") or 
            msg.get("response") or 
            msg.get("message") or 
            msg.get("text") or 
            msg.get("body") or ""
        )
        if isinstance(raw, list):
            return "\n".join([str(x).strip() for x in raw if str(x).strip()])
        elif isinstance(raw, dict):
            return json.dumps(raw)
        return str(raw).strip()
    return ""


def extract_msg_role(msg):
    if isinstance(msg, dict):
        role = str(msg.get("role") or msg.get("sender") or msg.get("type") or "").lower()
        if role in ["user", "human", "prompt"]:
            return "User"
        if role in ["assistant", "bot", "ai", "model", "response"]:
            return "Assistant"
    return "User"


def get_db_history(user_id: str, session_id: str, limit: int = 10):
    """
    Fetches chat history from MySQL user_query_history table for user_id/session_id.
    """
    try:
        rows = call_procedure("sp_get_user_query_history", [user_id, session_id, limit])
        if not rows:
            return []
        
        # Sort ascending by creation time
        sorted_rows = sorted(rows, key=lambda x: str(x.get("created_at") or ""))
        history = []
        for r in sorted_rows:
            if r.get("user_query"):
                history.append({"role": "User", "content": r.get("user_query")})
            if r.get("response"):
                history.append({"role": "Assistant", "content": r.get("response")})
        return history
    except Exception as e:
        print(f"[DB HISTORY WARNING] Could not fetch chat history from DB: {e}")
        return []


def save_db_query_response(user_id: str, session_id: str, user_query: str, response: str):
    """
    Saves user_id, session_id, user_query, and response in MySQL user_query_history table.
    """
    try:
        record_id = str(uuid.uuid4())
        call_procedure("sp_save_user_query", [record_id, user_id, session_id, user_query, response])
        print(f"[DB SAVE SUCCESS] Saved query & response for user_id={user_id}, session_id={session_id}")
    except Exception as e:
        print(f"[DB SAVE ERROR] Could not save user query & response to DB: {e}")


def direct_response_generate():
    data = request.get_json(silent=True) or {}
    
    # Auto detect user_id and session_id
    user_id, session_id = extract_auto_user_and_session()

    # Handle history reset
    if data.get("clear_history") is True or data.get("reset") is True:
        IN_MEMORY_SESSIONS[session_id] = []
        try:
            call_procedure("sp_clear_user_query_history", [user_id, session_id])
        except Exception as e:
            print(f"[DB CLEAR WARNING] {e}")

    prompt = (data.get("prompt") or data.get("userquery") or data.get("query") or "").strip()
    history = (
        data.get("history") or 
        data.get("messages") or 
        data.get("conversation_history") or 
        data.get("chat_history") or 
        data.get("previous_messages") or 
        data.get("turns") or []
    )

    # Auto-load from DB if history not explicitly provided in request
    if not history:
        history = get_db_history(user_id, session_id, limit=MAX_SESSION_HISTORY)
        if not history:
            history = list(IN_MEMORY_SESSIONS.get(session_id, []))

    # If prompt is not explicitly passed, extract from last user message in history
    if isinstance(history, list) and history and not prompt:
        last_msg = history[-1]
        if extract_msg_role(last_msg) == "User":
            prompt = extract_msg_content(last_msg)
            history = history[:-1]

    if not prompt:
        return jsonify({"status": "error", "message": "Prompt is required"}), 400

    # Privacy: Log request metadata WITHOUT logging user message or keys
    ui_lang = (data.get("lang") or data.get("language") or "en").strip().lower()
    print(f"[AI_CHAT] user_id: '{user_id}', session_id: '{session_id}', prompt_chars: {len(prompt)}, ui_lang: '{ui_lang}'")

    # Extract Chart Data, Profile, and Numerology from request
    profile = data.get("profile") or {}
    chart_data = data.get("chartData") or data.get("chart_data") or {}
    numerology = data.get("numerology") or {}
    tradition = data.get("tradition") or "parashari"

    # If profile is missing or incomplete, attempt to retrieve from DB
    if not profile or not profile.get("birthDate"):
        try:
            p_rows = call_procedure("sp_profile_ops", ['get_all', '', user_id, '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''])
            if p_rows:
                db_p = p_rows[0]
                profile = {
                    "id": db_p.get("id"),
                    "fullName": db_p.get("full_name"),
                    "gender": db_p.get("gender"),
                    "birthDate": db_p.get("birth_date"),
                    "birthTime": db_p.get("birth_time"),
                    "birthPlace": db_p.get("birth_place"),
                    "latitude": db_p.get("latitude"),
                    "longitude": db_p.get("longitude"),
                    "timezone": db_p.get("timezone_offset", 5.5),
                }
        except Exception as e:
            print(f"[AI_CHAT WARNING] Could not auto-fetch user profile from DB: {e}")

    # If chart_data is missing but profile exists, compute chart data on the fly
    if not chart_data and profile and profile.get("birthDate") and profile.get("birthTime"):
        try:
            from services.ephemeris_service import calculate_chart_data
            from services.chart_assembly_service import assemble_full_chart
            b_date = str(profile.get("birthDate"))
            b_time = str(profile.get("birthTime"))[:5]
            lat = float(profile.get("latitude") or 28.6139)
            lon = float(profile.get("longitude") or 77.2090)
            tz = float(profile.get("timezone") or 5.5)
            ephem = calculate_chart_data(b_date, b_time, tz, lat, lon)
            chart_data = assemble_full_chart(ephem, profile)
        except Exception as e:
            print(f"[AI_CHAT WARNING] Could not auto-calculate chart data: {e}")

    # If numerology is missing but profile exists, compute numerology
    if not numerology and profile and profile.get("birthDate"):
        try:
            from services.numerology_service import calculate_numerology_report
            numerology = calculate_numerology_report(str(profile.get("birthDate")), profile.get("fullName", ""))
        except Exception as e:
            print(f"[AI_CHAT WARNING] Could not auto-calculate numerology: {e}")

    try:
        from services.chat_service import (
            resolve_target_language,
            build_ground_truth_context,
            build_chat_system_prompt,
            parse_and_repair_chat_response
        )
        from services.llm_service import generate_chat_counselling_response

        # 1. Resolve Target Language & Script
        target_lang = resolve_target_language(prompt, ui_lang=ui_lang)

        # 2. Build Astrological Ground Truth Context (including time-based panchang if applicable)
        ground_truth_context, _ = build_ground_truth_context(
            profile=profile,
            chart_data=chart_data,
            numerology=numerology,
            prompt=prompt,
            tradition=tradition
        )

        # 3. Build System Prompt with strict Language and Ground Truth directives
        system_prompt = build_chat_system_prompt(ground_truth_context, target_lang, tradition)

        # 4. Format conversation turns for LLM
        history_turns = []
        if isinstance(history, list):
            for msg in history:
                content = extract_msg_content(msg)
                if content:
                    role = extract_msg_role(msg).lower()
                    if role in ["assistant", "bot", "ai", "model"]:
                        history_turns.append({"role": "assistant", "content": content})
                    else:
                        history_turns.append({"role": "user", "content": content})

        # Append current user prompt as the active turn
        history_turns.append({"role": "user", "content": prompt})

        # 5. Call LLM through services.llm_service
        raw_res = generate_chat_counselling_response(system_prompt, history_turns)

        # 6. Parse and repair JSON output safely
        clean_answer, clean_follow_ups = parse_and_repair_chat_response(raw_res, target_lang)

        # 7. Persist to DB
        save_db_query_response(
            user_id=user_id,
            session_id=session_id,
            user_query=prompt,
            response=clean_answer
        )

        # 8. Append turn to in-memory fallback session history
        if session_id not in IN_MEMORY_SESSIONS:
            IN_MEMORY_SESSIONS[session_id] = []

        IN_MEMORY_SESSIONS[session_id].append({"role": "user", "content": prompt})
        IN_MEMORY_SESSIONS[session_id].append({"role": "assistant", "content": clean_answer})

        if len(IN_MEMORY_SESSIONS[session_id]) > MAX_SESSION_HISTORY * 2:
            IN_MEMORY_SESSIONS[session_id] = IN_MEMORY_SESSIONS[session_id][-MAX_SESSION_HISTORY * 2:]

        return jsonify({
            "status": "success",
            "answer": clean_answer,
            "follow_ups": clean_follow_ups,
            "response": clean_answer,
            "suggested_questions": clean_follow_ups,
            "user_id": user_id,
            "session_id": session_id,
            "lang": target_lang
        })

    except Exception as e:
        print(f"[AI_CHAT ERROR] direct_generate failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def get_chat_history(target_user_id=None):
    """
    Endpoint controller to fetch saved question/response history strictly for a specific user_id.
    """
    if target_user_id:
        user_id = target_user_id
        session_id = ""
    else:
        # Check if set by @require_auth decorator on request
        user_id = getattr(request, "user_id", None)
        session_id = ""

        # If not authenticated, check query params or headers
        if not user_id:
            user_id = (request.args.get("user_id") or request.args.get("userId") or "").strip()
            session_id = (request.args.get("session_id") or "").strip()
            if not user_id and not session_id:
                auto_u, auto_s = extract_auto_user_and_session()
                user_id = auto_u
                session_id = auto_s if not user_id else ""

    limit = int(request.args.get("limit", 50))

    try:
        rows = call_procedure("sp_get_user_query_history", [user_id, session_id, limit])
        formatted_data = []
        for r in rows:
            formatted_data.append({
                "id": r.get("id"),
                "user_id": r.get("user_id"),
                "session_id": r.get("session_id"),
                "user_query": r.get("user_query"),
                "response": r.get("response"),
                "created_at": r["created_at"].isoformat() if hasattr(r.get("created_at"), "isoformat") else r.get("created_at"),
            })
        return jsonify({
            "status": "success",
            "user_id": user_id,
            "total_records": len(formatted_data),
            "data": formatted_data
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500




def clear_chat_history():
    """
    Endpoint controller to clear saved question/response history.
    Auto-detects user_id and session_id if not passed.
    """
    user_id, session_id = extract_auto_user_and_session()

    try:
        rows = call_procedure("sp_clear_user_query_history", [user_id, session_id])
        deleted_count = rows[0]["deleted_count"] if rows else 0
        if session_id in IN_MEMORY_SESSIONS:
            IN_MEMORY_SESSIONS[session_id] = []
        return jsonify({"status": "success", "user_id": user_id, "session_id": session_id, "deleted_count": deleted_count})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
