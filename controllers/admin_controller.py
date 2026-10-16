from flask import jsonify
from database.db_connection import get_db_connection
import uuid

import datetime

def _serialize_dates(obj):
    if isinstance(obj, dict):
        return {k: _serialize_dates(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_dates(i) for i in obj]
    elif isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    return obj

def _get_data(data_type):
    """Helper to fetch data using the master SP sp_get_admin_data."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_admin_data', (data_type,))
        
        data = []
        for result_set in cursor.stored_results():
            if data_type in ['dashboard_stats', 'revenue_stats']:
                data = result_set.fetchone()
            else:
                data = result_set.fetchall()
            break
            
        return jsonify({"status": "success", "data": _serialize_dates(data)}), 200
    except Exception as e:
        print(f"Error fetching {data_type}: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to retrieve {data_type}"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def _manage_user(action, user_id, value=""):
    """Helper to manage users using the master SP sp_manage_user."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.callproc('sp_manage_user', (action, user_id, str(value)))
        conn.commit()
        return jsonify({"status": "success", "message": f"User action {action} completed successfully"}), 200
    except Exception as e:
        print(f"Error in {action} for user: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to {action} user"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def log_system_error(level, message, module="system"):
    """Helper to log system errors to database using sp_add_system_log."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        log_id = str(uuid.uuid4())
        cursor.callproc('sp_add_system_log', (log_id, level, str(message)[:5000], module))
        conn.commit()
    except Exception as e:
        print(f"Failed to write to system logs: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# Public controller methods called by app.py

def get_dashboard_stats():
    return _get_data('dashboard_stats')

def get_all_users():
    return _get_data('users')

def get_ai_logs():
    return _get_data('ai_logs')

def get_system_logs():
    return _get_data('system_logs')

def get_revenue_stats():
    return _get_data('revenue_stats')

def get_all_transactions():
    return _get_data('transactions')

def update_user_role(user_id, role):
    if role not in ['user', 'admin']:
        return jsonify({"status": "error", "message": "Invalid role"}), 400
    return _manage_user('update_role', user_id, role)

def update_user_status(user_id, is_active):
    return _manage_user('update_status', user_id, int(is_active))

def delete_user(user_id):
    return _manage_user('delete', user_id)

def get_llm_config():
    from services.settings_service import get_llm_config as fetch_llm_config
    try:
        config = fetch_llm_config()
        return jsonify({"status": "success", "data": config}), 200
    except Exception as e:
        print(f"Error fetching LLM config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def update_llm_config():
    from flask import request
    from services.settings_service import update_llm_config as save_llm_config, get_llm_config as fetch_llm_config
    try:
        payload = request.get_json(silent=True) or {}
        
        # Extract email from JWT token for updated_by
        admin_email = "admin"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                from utils.security import decode_token
                token_payload = decode_token(token)
                admin_email = token_payload.get("sub", "admin")
            except Exception:
                pass
                
        save_llm_config(payload, updated_by=admin_email)
        updated_config = fetch_llm_config()
        return jsonify({
            "status": "success",
            "message": "LLM configuration updated successfully",
            "data": updated_config
        }), 200
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400
    except Exception as e:
        print(f"Error updating LLM config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def test_llm_connection():
    from flask import request
    from services.settings_service import test_llm_connection as run_test, test_all_providers
    try:
        payload = request.get_json(silent=True) or {}
        provider = payload.get("provider", "mistral_local")
        config = payload.get("config", {})

        if provider == "all":
            results = test_all_providers()
            return jsonify({"status": "success", "data": results}), 200

        result = run_test(provider, config)
        return jsonify({
            "status": "success",
            "data": {
                "provider": provider,
                "status": "ok" if result.get("success") else "error",
                "message": result.get("message", "Test completed"),
                "latency_ms": result.get("latency_ms", 0),
            }
        }), 200
    except Exception as e:
        print(f"Error testing LLM connection: {e}")
        return jsonify({
            "status": "success",
            "data": {
                "provider": provider if 'provider' in locals() else "unknown",
                "status": "error",
                "message": str(e),
                "latency_ms": 0,
            }
        }), 200


def get_seo_config():
    import json
    from services.settings_service import get_setting
    try:
        raw = get_setting("seo_config", "")
        if raw:
            try:
                data = json.loads(raw)
                return jsonify({"status": "success", "data": data}), 200
            except Exception:
                pass
        return jsonify({"status": "success", "data": {}}), 200
    except Exception as e:
        print(f"Error fetching SEO config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def update_seo_config():
    import json
    from flask import request
    from services.settings_service import set_setting
    try:
        payload = request.get_json(silent=True) or {}
        json_str = json.dumps(payload)
        set_setting("seo_config", json_str, updated_by="admin", description="Dynamic SEO and Meta Tags")
        return jsonify({
            "status": "success",
            "message": "SEO configuration updated successfully",
            "data": payload
        }), 200
    except Exception as e:
        print(f"Error updating SEO config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def get_telemetry_stats():
    from flask import request
    from services.telemetry_service import get_telemetry_stats as fetch_stats
    try:
        timeout_minutes = int(request.args.get('timeout_minutes', 10))
        stats = fetch_stats(timeout_minutes=timeout_minutes)
        return jsonify({"status": "success", "data": stats}), 200
    except Exception as e:
        print(f"Error fetching telemetry stats: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def get_telemetry_sessions():
    from flask import request
    from services.telemetry_service import get_admin_sessions
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))
        search = request.args.get('search', '').strip()
        status_filter = request.args.get('status', 'all').strip()
        timeout_minutes = int(request.args.get('timeout_minutes', 10))

        data = get_admin_sessions(page=page, page_size=page_size, search=search, status_filter=status_filter, timeout_minutes=timeout_minutes)
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        print(f"Error fetching telemetry sessions: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def get_telemetry_events():
    from flask import request
    from services.telemetry_service import get_admin_events
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 25))
        search = request.args.get('search', '').strip()
        session_id = request.args.get('session_id', '').strip()
        user_id = request.args.get('user_id', '').strip()
        category = request.args.get('category', 'all').strip()
        status = request.args.get('status', 'all').strip()

        data = get_admin_events(page=page, page_size=page_size, search=search, session_id=session_id, user_id=user_id, category=category, status=status)
        return jsonify({"status": "success", "data": data}), 200
    except Exception as e:
        print(f"Error fetching telemetry events: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def get_session_timeline(session_id):
    from services.telemetry_service import get_session_timeline as fetch_timeline
    try:
        timeline = fetch_timeline(session_id)
        if not timeline:
            return jsonify({"status": "error", "message": "Session not found"}), 404
        return jsonify({"status": "success", "data": timeline}), 200
    except Exception as e:
        print(f"Error fetching session timeline: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def track_client_event():
    from flask import request
    from services.telemetry_service import record_event
    try:
        payload = request.get_json(silent=True) or {}
        session_id = payload.get('session_id') or request.headers.get('x-session-id')
        if not session_id:
            return jsonify({"status": "error", "message": "session_id required"}), 400

        user_id = payload.get('user_id')
        if not user_id:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    from utils.security import decode_token
                    decoded = decode_token(auth_header.split(" ", 1)[1])
                    user_id = decoded.get("sub")
                except Exception:
                    pass

        event_name = payload.get('event_name', 'USER_ACTION')
        event_category = payload.get('event_category', 'CLIENT')
        input_payload = payload.get('input_payload')
        status = payload.get('status', 'SUCCESS')
        result_summary = payload.get('result_summary')
        execution_time_ms = payload.get('execution_time_ms', 0)
        error_message = payload.get('error_message')
        from services.telemetry_service import get_client_ip
        ip_address = get_client_ip(request, payload=payload)
        user_agent = request.headers.get('User-Agent')

        record_event(
            session_id=session_id,
            event_name=event_name,
            event_category=event_category,
            user_id=user_id,
            input_payload=input_payload,
            status=status,
            result_summary=result_summary,
            execution_time_ms=execution_time_ms,
            error_message=error_message,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return jsonify({"status": "success", "message": "Event recorded"}), 200
    except Exception as e:
        print(f"Error in track_client_event: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
