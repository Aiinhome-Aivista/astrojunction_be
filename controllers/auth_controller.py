import uuid
import re
from flask import request, jsonify
from mysql.connector import IntegrityError

from geopy.geocoders import Nominatim
from database.db_connection import call_procedure, get_db_connection
from utils.security import hash_password, verify_password, issue_token

import json
from controllers.profile_controller import _row_to_profile, _format_birth_time

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _error(message, code, http_status=400):
    return jsonify({"status": "error", "message": message, "error_code": code}), http_status


def register():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    full_name = (body.get("fullName") or body.get("name") or "").strip()
    
    # Address / Birth place
    birth_place = (body.get("birthPlace") or body.get("address") or "").strip()
    address = (body.get("address") or birth_place or "Kolkata, West Bengal, India").strip()
    if not birth_place:
        birth_place = address

    # Gender
    gender = (body.get("gender") or "male").strip().lower()
    if gender not in ["male", "female", "other"]:
        gender = "male"

    # Birth Date (YYYY-MM-DD)
    birth_date = str(body.get("birthDate") or body.get("dob") or "2000-01-01").strip()

    # Birth Time (HH:MM or HH:MM:SS)
    raw_time = str(body.get("birthTime") or body.get("time") or "12:00").strip()
    if len(raw_time) == 5:
        birth_time = f"{raw_time}:00"
    elif len(raw_time) == 8:
        birth_time = raw_time
    else:
        birth_time = "12:00:00"

    # Timezone & Horoscope System
    try:
        tz_offset = float(body.get("timezone") or body.get("timezone_offset") or 5.5)
    except (ValueError, TypeError):
        tz_offset = 5.5

    horoscope_system = body.get("horoscopeSystem", "vedic")
    if horoscope_system not in ["vedic", "western"]:
        horoscope_system = "vedic"

    focus_areas = body.get("focusAreas") or ["Career", "Health", "Finance"]
    if not isinstance(focus_areas, list):
        focus_areas = ["Career", "Health", "Finance"]
    focus_areas_json = json.dumps(focus_areas)

    notes = body.get("notes") or ""
    relation_label = body.get("relationLabel") or "Self"

    if not EMAIL_RE.match(email):
        return _error("A valid email is required", "INVALID_EMAIL")
    if len(password) < 8:
        return _error("Password must be at least 8 characters", "WEAK_PASSWORD")
    if not full_name:
        return _error("Full name is required", "INVALID_NAME")
    if not address and not birth_place:
        return _error("Full address or birth place is required", "INVALID_ADDRESS")

    # Geocode coordinates if not directly supplied in payload
    latitude = body.get("latitude")
    longitude = body.get("longitude")

    if latitude is not None and longitude is not None:
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (ValueError, TypeError):
            latitude = None
            longitude = None

    if latitude is None or longitude is None:
        search_query = address or birth_place
        try:
            geolocator = Nominatim(user_agent="astrojunction-app")
            parts = [p.strip() for p in search_query.split(',') if p.strip()]
            while parts:
                current_query = ', '.join(parts)
                location = geolocator.geocode(current_query)
                if location:
                    latitude = location.latitude
                    longitude = location.longitude
                    break
                parts.pop(0)
        except Exception as e:
            print("Geocoding error:", e)

    # Defaults if geocoding failed or returned none
    if latitude is None:
        latitude = 22.5726
    if longitude is None:
        longitude = 88.3639

    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)

    try:
        user_rows = call_procedure("sp_user_ops", ['create', user_id, email, password_hash, full_name, address, latitude, longitude])
    except IntegrityError:
        return _error("An account with this email already exists", "EMAIL_TAKEN", 409)

    if not user_rows:
        return _error("Could not create account", "REGISTER_FAILED", 500)

    user = user_rows[0]
    token = issue_token(user["id"], user["role"])

    # Automatically create the primary user profile in user_profiles table
    profile_id = str(uuid.uuid4())
    created_profile = None
    try:
        profile_rows = call_procedure("sp_profile_ops", [
            'create', profile_id, user["id"], full_name, gender, birth_date, birth_time, birth_place,
            latitude, longitude, tz_offset, focus_areas_json, notes, horoscope_system, relation_label
        ])
        if profile_rows:
            created_profile = _row_to_profile(profile_rows[0])
    except Exception as prof_err:
        print(f"[REGISTER WARNING] Could not auto-create profile: {prof_err}")

    # Instigate Registration Confirmation Email
    try:
        from services.email_service import send_registration_confirmation_email
        send_registration_confirmation_email(
            email=email,
            full_name=full_name,
            birth_date=birth_date
        )
    except Exception as email_err:
        print(f"[AUTH EMAIL WARNING] Could not dispatch registration confirmation email: {email_err}")

    return jsonify({
        "status": "success",
        "message": "User registered and primary profile created successfully",
        "data": {
            "token": token,
            "user": {
                "id": user["id"],
                "email": email,
                "fullName": user["full_name"],
                "role": user["role"],
                "address": user.get("address"),
                "latitude": float(user["latitude"]) if user.get("latitude") is not None else None,
                "longitude": float(user["longitude"]) if user.get("longitude") is not None else None,
            },
            "profile": created_profile
        },
    }), 201


def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    rows = call_procedure("sp_user_ops", ['get_by_email', '', email, '', '', '', None, None])
    if not rows:
        return _error("Invalid email or password", "INVALID_CREDENTIALS", 401)

    user = rows[0]
    if not user["is_active"]:
        return _error("This account has been deactivated", "ACCOUNT_DISABLED", 403)
    if not verify_password(password, user["password_hash"]):
        return _error("Invalid email or password", "INVALID_CREDENTIALS", 401)

    token = issue_token(user["id"], user["role"])

    # Also load user profiles
    profiles_data = []
    try:
        prof_rows = call_procedure("sp_profile_ops", ['get_all', '', user["id"], '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''])
        profiles_data = [_row_to_profile(r) for r in prof_rows]
    except Exception as pe:
        print(f"[LOGIN PROFILE LOAD WARNING] {pe}")

    primary_profile = profiles_data[0] if profiles_data else None

    return jsonify({
        "status": "success",
        "data": {
            "token": token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "fullName": user["full_name"],
                "role": user["role"],
                "address": user.get("address"),
                "latitude": float(user["latitude"]) if user.get("latitude") is not None else None,
                "longitude": float(user["longitude"]) if user.get("longitude") is not None else None,
            },
            "profile": primary_profile,
            "profiles": profiles_data
        },
    })


def me(user_id):
    rows = call_procedure("sp_user_ops", ['get_by_id', user_id, '', '', '', '', None, None])
    if not rows:
        return _error("User not found", "NOT_FOUND", 404)

    user = rows[0]
    return jsonify({
        "status": "success",
        "data": {
            "id": user["id"],
            "email": user["email"],
            "fullName": user["full_name"],
            "role": user["role"],
            "address": user.get("address"),
            "latitude": float(user["latitude"]) if user.get("latitude") is not None else None,
            "longitude": float(user["longitude"]) if user.get("longitude") is not None else None,
            "createdAt": user["created_at"].isoformat() if user.get("created_at") else None,
        },
    })


def google_auth():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    full_name = (body.get("fullName") or "").strip() or "Google User"

    if not email or not EMAIL_RE.match(email):
        return _error("A valid Google email is required", "INVALID_EMAIL")

    # Check if user already exists
    rows = call_procedure("sp_get_user_by_email", [email])
    if rows:
        user = rows[0]
        if not user["is_active"]:
            return _error("This account has been deactivated", "ACCOUNT_DISABLED", 403)
        token = issue_token(user["id"], user["role"])
        return jsonify({
            "status": "success",
            "data": {
                "token": token,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "fullName": user["full_name"],
                    "role": user["role"],
                },
            },
        })

    # If user doesn't exist, create a new user account with a secure generated password hash
    user_id = str(uuid.uuid4())
    random_pw = uuid.uuid4().hex + "G00gle!"
    password_hash = hash_password(random_pw)

    try:
        new_rows = call_procedure("sp_create_user", [user_id, email, password_hash, full_name])
    except IntegrityError:
        # Fallback if race condition occurred
        existing = call_procedure("sp_get_user_by_email", [email])
        if existing:
            user = existing[0]
            token = issue_token(user["id"], user["role"])
            return jsonify({
                "status": "success",
                "data": {
                    "token": token,
                    "user": {
                        "id": user["id"],
                        "email": user["email"],
                        "fullName": user["full_name"],
                        "role": user["role"],
                    },
                },
            })
        return _error("An account with this email already exists", "EMAIL_TAKEN", 409)

    if not new_rows:
        return _error("Could not create account via Google", "REGISTER_FAILED", 500)

    user = new_rows[0]
    token = issue_token(user["id"], user["role"])

    return jsonify({
        "status": "success",
        "data": {
            "token": token,
            "user": {
                "id": user["id"],
                "email": email,
                "fullName": user["full_name"],
                "role": user["role"],
            },
        },
    }), 201


def change_password():
    user_id = getattr(request, "user_id", None)
    user_role = getattr(request, "user_role", None)
    if not user_id:
        return _error("Authentication required", "AUTH_REQUIRED", 401)
    if user_role != "admin":
        return _error("Only administrators are permitted to change passwords", "FORBIDDEN", 403)

    body = request.get_json(silent=True) or {}
    current_password = (body.get("currentPassword") or body.get("current_password") or "").strip()
    new_password = (body.get("newPassword") or body.get("new_password") or "").strip()

    if not current_password or not new_password:
        return _error("Both current password and new password are required", "MISSING_FIELDS", 400)

    if len(new_password) < 6:
        return _error("New password must be at least 6 characters long", "INVALID_PASSWORD", 400)

    if current_password == new_password:
        return _error("New password cannot be the same as your current password", "SAME_PASSWORD", 400)

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, email, password_hash FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        if not user:
            return _error("User account not found", "USER_NOT_FOUND", 404)

        if not verify_password(current_password, user["password_hash"]):
            return _error("Current password is incorrect", "INCORRECT_PASSWORD", 400)

        new_hash = hash_password(new_password)
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
        conn.commit()

        return jsonify({
            "status": "success",
            "message": "Password changed successfully."
        }), 200
    except Exception as e:
        print(f"[AUTH CHANGE PASSWORD ERROR] {e}")
        return _error(f"Failed to change password: {str(e)}", "SERVER_ERROR", 500)
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


