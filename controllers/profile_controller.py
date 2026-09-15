import uuid
import json
from flask import request, jsonify

from database.db_connection import call_procedure

VALID_GENDERS = {"male", "female", "other"}
VALID_SYSTEMS = {"vedic", "western"}


def _error(message, code, http_status=400):
    return jsonify({"status": "error", "message": message, "error_code": code}), http_status


def _format_birth_time(value) -> str:
    """MySQL connector returns TIME columns as datetime.timedelta, not a
    string or time object. Format it as zero-padded HH:MM regardless of
    what type comes back."""
    if value is None:
        return ""
    if hasattr(value, "total_seconds"):
        total_minutes = int(value.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def _row_to_profile(row: dict) -> dict:
    focus_areas = row.get("focus_areas")
    if isinstance(focus_areas, str):
        try:
            focus_areas = json.loads(focus_areas)
        except (ValueError, TypeError):
            focus_areas = []
    elif focus_areas is None:
        focus_areas = []

    return {
        "id": row["id"],
        "fullName": row["full_name"],
        "gender": row["gender"],
        "birthDate": row["birth_date"].isoformat() if hasattr(row["birth_date"], "isoformat") else str(row["birth_date"]),
        "birthTime": _format_birth_time(row.get("birth_time")),
        "birthPlace": row["birth_place"],
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "timezone": float(row["timezone_offset"]),
        "focusAreas": focus_areas,
        "notes": row.get("notes") or "",
        "isPremium": bool(row.get("is_premium")),
        "horoscopeSystem": row.get("horoscope_system", "vedic"),
        "relationLabel": row.get("relation_label", "Self"),
        "createdAt": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
    }


def _extract_and_validate(body):
    required = ["fullName", "gender", "birthDate", "birthTime", "birthPlace", "latitude", "longitude", "timezone"]
    missing = [f for f in required if body.get(f) in (None, "")]
    if missing:
        return None, _error(f"Missing required field(s): {', '.join(missing)}", "VALIDATION_ERROR")

    if body["gender"] not in VALID_GENDERS:
        return None, _error("gender must be male, female, or other", "VALIDATION_ERROR")

    system = body.get("horoscopeSystem", "vedic")
    if system not in VALID_SYSTEMS:
        return None, _error("horoscopeSystem must be vedic or western", "VALIDATION_ERROR")

    try:
        lat = float(body["latitude"])
        lng = float(body["longitude"])
        tz = float(body["timezone"])
    except (TypeError, ValueError):
        return None, _error("latitude, longitude, and timezone must be numeric", "VALIDATION_ERROR")

    return {
        "full_name": body["fullName"],
        "gender": body["gender"],
        "birth_date": body["birthDate"],
        "birth_time": body["birthTime"],
        "birth_place": body["birthPlace"],
        "latitude": lat,
        "longitude": lng,
        "timezone_offset": tz,
        "focus_areas": json.dumps(body.get("focusAreas") or []),
        "notes": body.get("notes") or "",
        "horoscope_system": system,
        "relation_label": body.get("relationLabel", "Self"),
    }, None


def list_profiles(user_id: str):
    rows = call_procedure("sp_profile_ops", ['get_all', '', user_id, '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''])
    return jsonify({"status": "success", "data": [_row_to_profile(r) for r in rows]})


def create_profile(user_id: str):
    body = request.get_json(silent=True) or {}
    data, err = _extract_and_validate(body)
    if err:
        return err

    profile_id = str(uuid.uuid4())
    rows = call_procedure("sp_profile_ops", ['create', profile_id, user_id, data["full_name"], data["gender"], data["birth_date"], data["birth_time"], data["birth_place"], data["latitude"], data["longitude"], data["timezone_offset"], data["focus_areas"], data.get("notes", ""), data.get("horoscope_system", "vedic"), data.get("relation_label", "Self")])
    if not rows:
        return _error("Could not create profile", "CREATE_FAILED", 500)

    return jsonify({"status": "success", "data": _row_to_profile(rows[0])}), 201


def update_profile(user_id: str, profile_id: str):
    body = request.get_json(silent=True) or {}
    data, err = _extract_and_validate(body)
    if err:
        return err

    rows = call_procedure("sp_profile_ops", ['update', profile_id, user_id, data["full_name"], data["gender"], data["birth_date"], data["birth_time"], data["birth_place"], data["latitude"], data["longitude"], data["timezone_offset"], data["focus_areas"], data.get("notes", ""), data.get("horoscope_system", "vedic"), data.get("relation_label", "Self")])
    if not rows:
        return _error("Profile not found", "NOT_FOUND", 404)

    return jsonify({"status": "success", "data": _row_to_profile(rows[0])})


def delete_profile(user_id: str, profile_id: str):
    rows = call_procedure("sp_profile_ops", ['delete', profile_id, user_id, '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''])
    deleted = rows[0]["deleted_count"] if rows else 0
    if not deleted:
        return _error("Profile not found", "NOT_FOUND", 404)

    return jsonify({"status": "success", "data": {"deleted": True}})
