from flask import jsonify
from database.db_connection import get_db_connection
import uuid

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
            
        return jsonify({"status": "success", "data": data}), 200
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
        save_llm_config(payload, updated_by="admin")
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
