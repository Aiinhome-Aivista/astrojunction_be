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
