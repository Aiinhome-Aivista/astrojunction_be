import json
import uuid
import datetime
from concurrent.futures import ThreadPoolExecutor
from database.db_connection import get_db_connection

# Worker pool for async logging so main requests are never delayed
_telemetry_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="telemetry_worker")

def _sanitize_data(data):
    """Recursively removes sensitive keys from dicts before storing."""
    if isinstance(data, dict):
        clean = {}
        for k, v in data.items():
            lower_k = str(k).lower()
            if any(secret in lower_k for secret in ['password', 'token', 'secret', 'authorization', 'api_key', 'card_number', 'cvv']):
                clean[k] = "[REDACTED]"
            else:
                clean[k] = _sanitize_data(v)
        return clean
    elif isinstance(data, list):
        return [_sanitize_data(item) for item in data]
    return data

def _to_json_str(data):
    if data is None:
        return None
    if isinstance(data, str):
        return data
    try:
        sanitized = _sanitize_data(data)
        return json.dumps(sanitized, default=str)
    except Exception:
        return str(data)

def _detect_device_type(user_agent: str) -> str:
    if not user_agent:
        return "desktop"
    ua = user_agent.lower()
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    if "tablet" in ua or "ipad" in ua:
        return "tablet"
    return "desktop"

def _is_admin_actor(user_id=None, session_id=None):
    """Returns True if the actor is an admin user, preventing admin tracking."""
    if not user_id and not session_id:
        return False
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        if user_id:
            cursor.execute("SELECT role, email FROM users WHERE id = %s", (str(user_id),))
            u = cursor.fetchone()
            if u and (u.get('role') == 'admin' or 'admin' in (u.get('email') or '').lower()):
                return True
        if session_id:
            cursor.execute("""
                SELECT u.role, u.email 
                FROM user_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.id = %s
            """, (str(session_id),))
            u = cursor.fetchone()
            if u and (u.get('role') == 'admin' or 'admin' in (u.get('email') or '').lower()):
                return True
    except Exception:
        pass
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
    return False

def get_client_ip(req=None, payload=None):
    """
    Accurately detects client public IP address:
    1. Checks payload dict for 'client_ip' or 'ip_address'
    2. Checks request headers: x-client-ip, CF-Connecting-IP, X-Real-IP, X-Forwarded-For, True-Client-IP
    3. Falls back to request.remote_addr or '127.0.0.1'
    """
    if isinstance(payload, dict):
        p_ip = payload.get("client_ip") or payload.get("ip_address")
        if p_ip and isinstance(p_ip, str) and p_ip.strip() and p_ip.strip() != "127.0.0.1":
            return p_ip.strip()

    if not req:
        try:
            from flask import request as req
        except Exception:
            req = None

    if req:
        # Header sent by frontend tracker / api client
        for h in ["x-client-ip", "X-Client-IP", "x-forwarded-client-ip"]:
            val = req.headers.get(h)
            if val and val.strip() and val.strip() != "127.0.0.1":
                return val.strip()

        # Cloudflare Connecting IP
        cf_ip = req.headers.get("CF-Connecting-IP")
        if cf_ip and cf_ip.strip() and cf_ip.strip() != "127.0.0.1":
            return cf_ip.strip()

        # Standard X-Forwarded-For (take the first IP in comma-separated list)
        xff = req.headers.get("X-Forwarded-For")
        if xff:
            first_ip = xff.split(",")[0].strip()
            if first_ip and first_ip != "127.0.0.1":
                return first_ip

        # X-Real-IP
        x_real = req.headers.get("X-Real-IP")
        if x_real and x_real.strip() and x_real.strip() != "127.0.0.1":
            return x_real.strip()

        # True-Client-IP
        t_ip = req.headers.get("True-Client-IP")
        if t_ip and t_ip.strip() and t_ip.strip() != "127.0.0.1":
            return t_ip.strip()

        if req.remote_addr:
            return req.remote_addr

    return "127.0.0.1"

def _sync_upsert_session(session_id, user_id=None, ip_address=None, user_agent=None, device_type=None):
    if not session_id or _is_admin_actor(user_id=user_id, session_id=session_id):
        return
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        dev_type = device_type or _detect_device_type(user_agent)
        if not ip_address or ip_address == "127.0.0.1":
            ip_address = get_client_ip()

        sql = """
            INSERT INTO user_sessions (id, user_id, ip_address, user_agent, device_type, started_at, last_activity_at, is_active)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), 1)
            ON DUPLICATE KEY UPDATE
                user_id = COALESCE(VALUES(user_id), user_id),
                last_activity_at = NOW(),
                is_active = 1,
                ip_address = CASE 
                    WHEN VALUES(ip_address) IS NOT NULL AND VALUES(ip_address) != '127.0.0.1' THEN VALUES(ip_address)
                    ELSE COALESCE(user_sessions.ip_address, VALUES(ip_address))
                END,
                user_agent = COALESCE(VALUES(user_agent), user_agent),
                device_type = COALESCE(VALUES(device_type), device_type)
        """
        cursor.execute(sql, (str(session_id), user_id, ip_address, (user_agent[:1000] if user_agent else None), dev_type))
        conn.commit()
    except Exception as e:
        print(f"[Telemetry Warning] Could not record session: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def _format_row_dates(row):
    if not row:
        return row
    for k in ['created_at', 'started_at', 'last_activity_at', 'ended_at']:
        if k in row and row[k] and hasattr(row[k], 'strftime'):
            row[k] = row[k].strftime("%Y-%m-%dT%H:%M:%S+05:30")
    return row

def _sync_insert_event(session_id, event_name, event_category='GENERAL', user_id=None,
                       input_payload=None, status='SUCCESS', result_summary=None,
                       execution_time_ms=0, error_message=None, ip_address=None, user_agent=None):
    if not session_id or not event_name or _is_admin_actor(user_id=user_id, session_id=session_id):
        return

    # Auto-resolve real client IP if missing or localhost
    if not ip_address or ip_address == "127.0.0.1":
        ip_address = get_client_ip(payload=input_payload if isinstance(input_payload, dict) else None)

    # First ensure session exists
    _sync_upsert_session(session_id, user_id, ip_address, user_agent)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        payload_str = _to_json_str(input_payload)
        summary_str = _to_json_str(result_summary)
        err_str = str(error_message)[:2000] if error_message else None

        # Anti-Spam / Deduplication: Skip identical event within last 15 seconds
        dedup_sql = """
            SELECT id FROM user_event_logs
            WHERE session_id = %s AND event_name = %s
              AND created_at >= NOW() - INTERVAL 15 SECOND
              AND (input_payload = %s OR (input_payload IS NULL AND %s IS NULL))
            LIMIT 1
        """
        cursor.execute(dedup_sql, (str(session_id), str(event_name)[:100], payload_str, payload_str))
        if cursor.fetchone():
            return

        event_id = str(uuid.uuid4())
        sql = """
            INSERT INTO user_event_logs
            (id, session_id, user_id, event_name, event_category, input_payload, status,
             result_summary, execution_time_ms, error_message, ip_address, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(sql, (
            event_id,
            str(session_id),
            user_id,
            str(event_name)[:100],
            str(event_category)[:50],
            payload_str,
            status if status in ['SUCCESS', 'FAILURE', 'PENDING', 'CANCELLED'] else 'SUCCESS',
            summary_str,
            int(execution_time_ms or 0),
            err_str,
            ip_address
        ))
        conn.commit()
    except Exception as e:
        print(f"[Telemetry Warning] Could not record event '{event_name}': {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# Public asynchronous entry points
def record_session(session_id, user_id=None, ip_address=None, user_agent=None, device_type=None):
    if not session_id:
        return
    if not ip_address or ip_address == "127.0.0.1":
        ip_address = get_client_ip()
    # Resolve user_id and check admin role from Authorization header if not passed
    if not user_id:
        try:
            from flask import request
            auth_h = request.headers.get("Authorization", "")
            if auth_h.startswith("Bearer "):
                from utils.security import decode_token
                pld = decode_token(auth_h.split(" ", 1)[1])
                if pld:
                    if pld.get("role") == "admin":
                        return  # Do not record admin session
                    user_id = pld.get("sub")
        except Exception:
            pass
    _telemetry_executor.submit(_sync_upsert_session, session_id, user_id, ip_address, user_agent, device_type)

def record_event(session_id, event_name, event_category='GENERAL', user_id=None,
                 input_payload=None, status='SUCCESS', result_summary=None,
                 execution_time_ms=0, error_message=None, ip_address=None, user_agent=None):
    if not session_id or not event_name:
        return

    if not ip_address or ip_address == "127.0.0.1":
        ip_address = get_client_ip(payload=input_payload if isinstance(input_payload, dict) else None)

    # Reject any payload containing admin indicators
    payload_str_check = str(input_payload or '').lower()
    if 'admin@' in payload_str_check or '"admin"' in payload_str_check or "'admin'" in payload_str_check:
        return

    # Check if this session or user already identified as admin
    if _is_admin_actor(user_id=user_id, session_id=session_id):
        return

    # Resolve user_id and check admin role from Authorization header if not passed
    if not user_id:
        try:
            from flask import request
            auth_h = request.headers.get("Authorization", "")
            if auth_h.startswith("Bearer "):
                from utils.security import decode_token
                pld = decode_token(auth_h.split(" ", 1)[1])
                if pld:
                    if pld.get("role") == "admin":
                        return  # Do not record admin actions
                    user_id = pld.get("sub")
        except Exception:
            pass

    _telemetry_executor.submit(
        _sync_insert_event,
        session_id, event_name, event_category, user_id,
        input_payload, status, result_summary,
        execution_time_ms, error_message, ip_address, user_agent
    )

# Synchronous Query Methods for Admin Dashboard
def get_telemetry_stats(timeout_minutes=10):
    """Returns top KPI cards for admin dashboard."""
    conn = None
    cursor = None
    try:
        timeout_m = max(1, int(timeout_minutes or 10))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Active sessions in last N minutes
        cursor.execute(f"""
            SELECT COUNT(*) AS active_sessions_now
            FROM user_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE s.is_active = 1 AND s.last_activity_at >= NOW() - INTERVAL {timeout_m} MINUTE
              AND (u.role IS NULL OR u.role != 'admin')
              AND (u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')
        """)
        active_res = cursor.fetchone() or {}
        active_sessions_now = active_res.get('active_sessions_now', 0)

        # 2. Total events today, success count, failure count
        cursor.execute("""
            SELECT
                COUNT(*) AS total_events_today,
                SUM(CASE WHEN e.status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_events_today,
                SUM(CASE WHEN e.status = 'FAILURE' THEN 1 ELSE 0 END) AS failed_events_today,
                AVG(e.execution_time_ms) AS avg_latency_ms
            FROM user_event_logs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE e.created_at >= CURDATE()
              AND (u.role IS NULL OR u.role != 'admin')
              AND (u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')
              AND (e.input_payload IS NULL OR (LOWER(e.input_payload) NOT LIKE '%"admin"%' AND LOWER(e.input_payload) NOT LIKE '%admin@%' AND LOWER(e.input_payload) NOT LIKE '%''admin''%'))
        """)
        today_res = cursor.fetchone() or {}
        total_events_today = today_res.get('total_events_today') or 0
        success_events_today = today_res.get('success_events_today') or 0
        failed_events_today = today_res.get('failed_events_today') or 0
        avg_latency_ms = round(float(today_res.get('avg_latency_ms') or 0), 1)

        success_rate = 100.0 if total_events_today == 0 else round((success_events_today / total_events_today) * 100, 1)

        # 3. All-time totals
        cursor.execute("""
            SELECT COUNT(*) AS total_all_time_events
            FROM user_event_logs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE (u.role IS NULL OR u.role != 'admin')
              AND (u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')
              AND (e.input_payload IS NULL OR (LOWER(e.input_payload) NOT LIKE '%"admin"%' AND LOWER(e.input_payload) NOT LIKE '%admin@%'))
        """)
        total_all_time_events = (cursor.fetchone() or {}).get('total_all_time_events', 0)

        cursor.execute("""
            SELECT COUNT(*) AS total_all_time_sessions
            FROM user_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE (u.role IS NULL OR u.role != 'admin')
              AND (u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')
        """)
        total_all_time_sessions = (cursor.fetchone() or {}).get('total_all_time_sessions', 0)

        # 4. Category breakdown today
        cursor.execute("""
            SELECT e.event_category, COUNT(*) AS count
            FROM user_event_logs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE e.created_at >= CURDATE()
              AND (u.role IS NULL OR u.role != 'admin')
              AND (u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')
            GROUP BY e.event_category
            ORDER BY count DESC
            LIMIT 6
        """)
        category_breakdown = cursor.fetchall() or []

        return {
            "active_sessions_now": active_sessions_now,
            "total_events_today": total_events_today,
            "success_rate": success_rate,
            "failed_events_today": failed_events_today,
            "avg_latency_ms": avg_latency_ms,
            "total_all_time_events": total_all_time_events,
            "total_all_time_sessions": total_all_time_sessions,
            "category_breakdown": category_breakdown
        }
    except Exception as e:
        print(f"[Telemetry Error] get_telemetry_stats: {e}")
        return {
            "active_sessions_now": 0,
            "total_events_today": 0,
            "success_rate": 100.0,
            "failed_events_today": 0,
            "avg_latency_ms": 0,
            "total_all_time_events": 0,
            "total_all_time_sessions": 0,
            "category_breakdown": []
        }
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_admin_sessions(page=1, page_size=20, search='', status_filter='all', timeout_minutes=10):
    """Returns paginated sessions list with user email and events count."""
    conn = None
    cursor = None
    try:
        timeout_m = max(1, int(timeout_minutes or 10))
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        offset = max(0, (page - 1) * page_size)
        where_clauses = [
            "1=1",
            "(u.role IS NULL OR u.role != 'admin')",
            "(u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')"
        ]
        params = []

        if search:
            where_clauses.append("(s.id LIKE %s OR u.email LIKE %s OR u.full_name LIKE %s OR EXISTS (SELECT 1 FROM user_event_logs e WHERE e.session_id = s.id AND (e.event_name LIKE %s OR e.input_payload LIKE %s)))")
            wild = f"%{search}%"
            params.extend([wild, wild, wild, wild, wild])

        if status_filter == 'active':
            where_clauses.append(f"s.is_active = 1 AND s.last_activity_at >= NOW() - INTERVAL {timeout_m} MINUTE")
        elif status_filter == 'inactive':
            where_clauses.append(f"(s.is_active = 0 OR s.last_activity_at < NOW() - INTERVAL {timeout_m} MINUTE)")
        elif status_filter == 'FAILURE':
            where_clauses.append("EXISTS (SELECT 1 FROM user_event_logs e WHERE e.session_id = s.id AND e.status = 'FAILURE')")
        elif status_filter == 'SUCCESS':
            where_clauses.append("EXISTS (SELECT 1 FROM user_event_logs e WHERE e.session_id = s.id AND e.status = 'SUCCESS')")

        where_sql = " AND ".join(where_clauses)

        # Count total
        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM user_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE {where_sql}
        """
        cursor.execute(count_sql, tuple(params))
        total_count = (cursor.fetchone() or {}).get('total', 0)

        # Fetch records
        fetch_sql = f"""
            SELECT
                s.id,
                s.user_id,
                COALESCE(u.email, (
                    SELECT JSON_UNQUOTE(JSON_EXTRACT(e.input_payload, '$.email'))
                    FROM user_event_logs e
                    WHERE e.session_id = s.id AND e.input_payload LIKE '%"email"%'
                    ORDER BY e.created_at DESC LIMIT 1
                )) AS user_email,
                COALESCE(u.full_name, (
                    SELECT JSON_UNQUOTE(JSON_EXTRACT(e.input_payload, '$.name'))
                    FROM user_event_logs e
                    WHERE e.session_id = s.id AND e.input_payload LIKE '%"name"%'
                    ORDER BY e.created_at DESC LIMIT 1
                ), (
                    SELECT JSON_UNQUOTE(JSON_EXTRACT(e.input_payload, '$.fullName'))
                    FROM user_event_logs e
                    WHERE e.session_id = s.id AND e.input_payload LIKE '%"fullName"%'
                    ORDER BY e.created_at DESC LIMIT 1
                )) AS user_name,
                s.ip_address,
                s.user_agent,
                COALESCE(s.device_type, 'desktop') AS device_type,
                s.started_at,
                s.last_activity_at,
                CASE 
                    WHEN s.last_activity_at >= NOW() - INTERVAL {timeout_m} MINUTE THEN 1
                    ELSE 0
                END AS is_active,
                (SELECT COUNT(*) FROM user_event_logs e WHERE e.session_id = s.id) AS event_count,
                (SELECT COUNT(*) FROM user_event_logs e WHERE e.session_id = s.id AND e.status = 'FAILURE') AS error_count,
                (SELECT e.event_name FROM user_event_logs e WHERE e.session_id = s.id ORDER BY e.created_at DESC LIMIT 1) AS last_action,
                (SELECT e.status FROM user_event_logs e WHERE e.session_id = s.id ORDER BY e.created_at DESC LIMIT 1) AS last_status
            FROM user_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE {where_sql}
            ORDER BY s.last_activity_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(fetch_sql, tuple(params + [page_size, offset]))
        rows = [_format_row_dates(r) for r in (cursor.fetchall() or [])]

        return {
            "sessions": rows,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total_count + page_size - 1) // page_size)
        }
    except Exception as e:
        print(f"[Telemetry Error] get_admin_sessions: {e}")
        return {"sessions": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 1}
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_admin_events(page=1, page_size=25, search='', session_id='', user_id='', category='all', status='all'):
    """Returns paginated event logs with full details."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        offset = max(0, (page - 1) * page_size)
        where_clauses = [
            "1=1",
            "(u.role IS NULL OR u.role != 'admin')",
            "(u.email IS NULL OR LOWER(u.email) NOT LIKE '%admin%')",
            "(e.input_payload IS NULL OR (LOWER(e.input_payload) NOT LIKE '%\"admin\"%' AND LOWER(e.input_payload) NOT LIKE '%admin@%'))"
        ]
        params = []

        if session_id:
            where_clauses.append("e.session_id = %s")
            params.append(session_id)

        if user_id:
            where_clauses.append("e.user_id = %s")
            params.append(user_id)

        if category and category != 'all':
            where_clauses.append("e.event_category = %s")
            params.append(category)

        if status and status != 'all':
            where_clauses.append("e.status = %s")
            params.append(status)

        if search:
            where_clauses.append("(e.event_name LIKE %s OR e.input_payload LIKE %s OR e.result_summary LIKE %s OR e.ip_address LIKE %s OR u.email LIKE %s)")
            wild = f"%{search}%"
            params.extend([wild, wild, wild, wild, wild])

        where_sql = " AND ".join(where_clauses)

        # Count total
        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM user_event_logs e
            LEFT JOIN users u ON e.user_id = u.id
            WHERE {where_sql}
        """
        cursor.execute(count_sql, tuple(params))
        total_count = (cursor.fetchone() or {}).get('total', 0)

        # Fetch records
        fetch_sql = f"""
            SELECT
                e.id,
                e.session_id,
                e.user_id,
                u.email AS user_email,
                u.full_name AS user_name,
                COALESCE(s.device_type, 'desktop') AS device_type,
                e.event_name,
                e.event_category,
                e.input_payload,
                e.status,
                e.result_summary,
                e.execution_time_ms,
                e.error_message,
                e.ip_address,
                e.created_at
            FROM user_event_logs e
            LEFT JOIN users u ON e.user_id = u.id
            LEFT JOIN user_sessions s ON e.session_id = s.id
            WHERE {where_sql}
            ORDER BY e.created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(fetch_sql, tuple(params + [page_size, offset]))
        rows = [_format_row_dates(r) for r in (cursor.fetchall() or [])]

        return {
            "events": rows,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total_count + page_size - 1) // page_size)
        }
    except Exception as e:
        print(f"[Telemetry Error] get_admin_events: {e}")
        return {"events": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 1}
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_session_timeline(session_id):
    """Returns complete timeline of a single session with its events."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch session
        cursor.execute("""
            SELECT
                s.id,
                s.user_id,
                u.email AS user_email,
                u.full_name AS user_name,
                s.ip_address,
                s.user_agent,
                s.device_type,
                s.started_at,
                s.last_activity_at,
                s.is_active
            FROM user_sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE s.id = %s
        """, (session_id,))
        session = _format_row_dates(cursor.fetchone())

        if not session:
            return None

        # Fetch all events in this session in chronological order
        cursor.execute("""
            SELECT
                id,
                event_name,
                event_category,
                input_payload,
                status,
                result_summary,
                execution_time_ms,
                error_message,
                ip_address,
                created_at
            FROM user_event_logs
            WHERE session_id = %s
            ORDER BY created_at ASC
        """, (session_id,))
        events = [_format_row_dates(r) for r in (cursor.fetchall() or [])]

        session['events'] = events
        return session
    except Exception as e:
        print(f"[Telemetry Error] get_session_timeline: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
