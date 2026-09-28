from flask import request, jsonify
from database.db_connection import get_db_connection
import json
import uuid

def _manage_subscription(action, plan_id=None, data=None):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        if action == 'get_active':
            filter_type = data.get('type') if data else None
            cursor.callproc('sp_subscription_ops', (action, '', '', '', 0, 0, '', None, 0))
            plans = []
            for result_set in cursor.stored_results():
                plans = result_set.fetchall()
                break
            
            if filter_type:
                plans = [p for p in plans if p.get('plan_type') == filter_type]
            
            
            # parse json
            for p in plans:
                if p.get('features_json'):
                    try:
                        p['features_json'] = json.loads(p['features_json'])
                    except:
                        pass
            return jsonify({"status": "success", "data": plans}), 200

        elif action == 'get_all':
            cursor.callproc('sp_subscription_ops', (action, '', '', '', 0, 0, '', None, 0))
            plans = []
            for result_set in cursor.stored_results():
                plans = result_set.fetchall()
                break
            for p in plans:
                if p.get('features_json'):
                    try:
                        p['features_json'] = json.loads(p['features_json'])
                    except:
                        pass
            return jsonify({"status": "success", "data": plans}), 200

        elif action in ['create', 'update']:
            if not data:
                return jsonify({"status": "error", "message": "No data provided"}), 400
            
            pid = plan_id if plan_id else data.get('id', str(uuid.uuid4())[:15])
            pname = data.get('plan_name', '')
            ptype = data.get('plan_type', 'ONE_TIME')
            pinr = float(data.get('price_inr', 0))
            pusd = float(data.get('price_usd', 0))
            pdesc = data.get('description', '')
            pfeat = data.get('features_json', [])
            pfeat_str = json.dumps(pfeat) if isinstance(pfeat, list) else pfeat
            pactive = int(data.get('is_active', 1))

            cursor.callproc('sp_subscription_ops', (action, pid, pname, ptype, pinr, pusd, pdesc, pfeat_str, pactive))
            conn.commit()
            return jsonify({"status": "success", "message": f"Plan {action}d successfully", "id": pid}), 200

        elif action == 'delete':
            if not plan_id:
                return jsonify({"status": "error", "message": "Plan ID required"}), 400
            cursor.callproc('sp_subscription_ops', (action, plan_id, '', '', 0, 0, '', None, 0))
            conn.commit()
            return jsonify({"status": "success", "message": "Plan deleted successfully"}), 200

    except Exception as e:
        print(f"Error in subscription ops ({action}): {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn and conn.is_connected(): conn.close()


def get_active_plans():
    # Allow filtering by type via query params (e.g., ?type=MATCHMAKING)
    filter_type = request.args.get('type')
    return _manage_subscription('get_active', data={'type': filter_type})

def admin_get_all_plans():
    return _manage_subscription('get_all')

def admin_create_plan():
    return _manage_subscription('create', data=request.get_json(silent=True))

def admin_update_plan(plan_id):
    return _manage_subscription('update', plan_id=plan_id, data=request.get_json(silent=True))

def admin_delete_plan(plan_id):
    return _manage_subscription('delete', plan_id=plan_id)
