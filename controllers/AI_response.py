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
    print("\n================ [AI_RESPONSE REQUEST RECEIVED] ================")
    print("Raw Request Data:", json.dumps(data, indent=2))
    
    # Auto detect user_id and session_id
    user_id, session_id = extract_auto_user_and_session()
    print(f"Auto-Detected -> user_id: '{user_id}', session_id: '{session_id}'")

    # Handle history reset
    if data.get("clear_history") is True or data.get("reset") is True:
        IN_MEMORY_SESSIONS[session_id] = []
        try:
            call_procedure("sp_clear_user_query_history", [user_id, session_id])
            print(f"[SESSION {session_id} / USER {user_id}] History cleared in DB and memory.")
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
        print("[AI_RESPONSE ERROR] No prompt provided.")
        return jsonify({"status": "error", "message": "Prompt is required"}), 400

    # Build conversation history text for prompt context
    history_text = ""
    if isinstance(history, list) and len(history) > 0:
        history_parts = []
        for msg in history:
            content = extract_msg_content(msg)
            if content:
                role = extract_msg_role(msg)
                history_parts.append(f"{role}: {content}")
        if history_parts:
            history_text = "Previous Conversation History:\n" + "\n".join(history_parts) + "\n\n"
            print("--- PARSED CONVERSATION HISTORY ---")
            print(history_text)
    else:
        print("--- NO HISTORY SENT OR FOUND ---")

    try:
        from services.llm_service import generate_raw_completion
        
        system_instruction = (
            "You are a helpful Astrology AI Assistant. Answer the user's current question accurately based on the conversation history provided below.\n\n"
            "INSTRUCTIONS FOR CONVERSATION HISTORY & CONTEXT:\n"
            "1. Pay close attention to the Previous Conversation History below to resolve pronouns (such as 'this', 'it', 'these') and follow-up questions.\n"
            "2. Always focus on the MOST RECENT topic discussed in the conversation history or the user's current question.\n"
            "3. If the user asks about a new topic, switch topics and answer the new topic directly.\n"
            "If the question is completely unrelated to astrology, horoscopes, planets, or numerology (like coding, politics, or general chat), reply EXACTLY with: 'This is not my content, I am an astro AI'.\n\n"
            "For astrology questions, you MUST reply ONLY with a valid JSON object in this format (no markdown code blocks, no text outside JSON):\n"
            "{\n"
            '  "answer": "Your detailed answer to the question",\n'
            '  "suggested_questions": [\n'
            '    "Suggested question 1?",\n'
            '    "Suggested question 2?",\n'
            '    "Suggested question 3?",\n'
            '    "Suggested question 4?"\n'
            '  ]\n'
            "}\n\n"
            f"{history_text}"
            f"Current Question: {prompt}"
        )

        full_prompt = system_instruction
        result = generate_raw_completion(full_prompt)
        
        if "This is not my content" in result:
            return jsonify({
                "status": "error",
                "message": "This is not my content, I am an astro AI"
            }), 400

        # Clean up markdown code blocks if present
        clean_result = result.strip()
        if clean_result.startswith("```json"):
            clean_result = clean_result[7:]
        elif clean_result.startswith("```"):
            clean_result = clean_result[3:]
        if clean_result.endswith("```"):
            clean_result = clean_result[:-3]
        clean_result = clean_result.strip()

        formatted_response = []
        suggested_questions = []

        try:
            parsed_data = json.loads(clean_result)
            if isinstance(parsed_data, dict):
                raw_answer = parsed_data.get("answer", "")
                if isinstance(raw_answer, list):
                    formatted_response = [str(line).strip() for line in raw_answer if str(line).strip()]
                else:
                    formatted_response = [line.strip() for line in str(raw_answer).split('\n') if line.strip()]

                raw_suggestions = parsed_data.get("suggested_questions") or parsed_data.get("suggestions") or []
                if isinstance(raw_suggestions, list):
                    suggested_questions = [str(q).strip() for q in raw_suggestions if str(q).strip()]
        except Exception:
            lines = [line.strip() for line in result.split('\n') if line.strip()]
            answer_lines = []
            q_lines = []
            in_suggestions = False
            for line in lines:
                if any(k in line.lower() for k in ["suggested", "follow-up", "questions"]):
                    in_suggestions = True
                    continue
                if in_suggestions:
                    clean_q = re.sub(r'^[0-9+*.\-\s]+', '', line).strip()
                    if clean_q:
                        q_lines.append(clean_q)
                else:
                    answer_lines.append(line)

            formatted_response = answer_lines if answer_lines else lines
            suggested_questions = q_lines

        # Guarantee at least 4 suggested questions
        if len(suggested_questions) < 4:
            default_suggestions = [
                "How does this astrological position affect my career and future growth?",
                "What remedies or gemstones are recommended for balancing these planetary energies?",
                "How will upcoming planetary transits influence this aspect of my life?",
                "What timing or Dasha period is most favorable for taking action regarding this?"
            ]
            for ds in default_suggestions:
                if ds not in suggested_questions:
                    suggested_questions.append(ds)
                if len(suggested_questions) >= 4:
                    break

        answer_text_summary = "\n".join(formatted_response) if isinstance(formatted_response, list) else str(formatted_response)

        # 1. Save in MySQL Database (userid, userquery, response)
        save_db_query_response(
            user_id=user_id,
            session_id=session_id,
            user_query=prompt,
            response=answer_text_summary
        )

        # 2. Append turn to in-memory fallback session history
        if session_id not in IN_MEMORY_SESSIONS:
            IN_MEMORY_SESSIONS[session_id] = []

        IN_MEMORY_SESSIONS[session_id].append({"role": "user", "content": prompt})
        IN_MEMORY_SESSIONS[session_id].append({"role": "assistant", "content": answer_text_summary})

        if len(IN_MEMORY_SESSIONS[session_id]) > MAX_SESSION_HISTORY * 2:
            IN_MEMORY_SESSIONS[session_id] = IN_MEMORY_SESSIONS[session_id][-MAX_SESSION_HISTORY * 2:]

        return jsonify({
            "status": "success",
            "user_id": user_id,
            "session_id": session_id,
            "user_query": prompt,
            "response": formatted_response,
            "suggested_questions": suggested_questions,
        })
    except Exception as e:
        print(f"Error in direct_generate: {e}")
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
