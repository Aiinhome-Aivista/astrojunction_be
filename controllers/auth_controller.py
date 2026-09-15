import uuid
import re
from flask import request, jsonify
from mysql.connector import IntegrityError

from geopy.geocoders import Nominatim
from database.db_connection import call_procedure
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

