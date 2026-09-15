import uuid
import json
from flask import request, jsonify

from database.db_connection import call_procedure


def _error(message, code, http_status=400):
    return jsonify({"status": "error", "message": message, "error_code": code}), http_status


def _row_to_report(row: dict) -> dict:
    report_json = row.get("report_json")
    if isinstance(report_json, str):
        report_json = json.loads(report_json)

    return {
        "id": row["id"],
        "profileId": row["profile_id"],
        "mulank": row["mulank"],
        "bhagyank": row["bhagyank"],
        "namankChaldean": row["namank_chaldean"],
        "namankPythagorean": row["namank_pythagorean"],
        "report": report_json,
        "createdAt": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
    }


def save_numerology(user_id: str):
    """Persists a numerology report the frontend already computed via
    astroEngine.ts. The backend does not recompute or validate the
    numerology math itself — it only stores the deterministic result
    against the owning profile, after confirming that profile belongs
    to this user (enforced by requiring profile_id + user_id together
    in the stored procedure's WHERE-equivalent insert path below)."""
    body = request.get_json(silent=True) or {}
    profile_id = body.get("profileId")
    report = body.get("report")

    if not profile_id or not isinstance(report, dict):
        return _error("profileId and report are required", "VALIDATION_ERROR")

    required = ["mulank", "bhagyank", "namankChaldean", "namankPythagorean"]
    missing = [f for f in required if f not in report]
    if missing:
        return _error(f"report is missing field(s): {', '.join(missing)}", "VALIDATION_ERROR")

    # Check if the profile exists in the DB for this user.
    owned = call_procedure("sp_profile_ops", [
        'get_one', profile_id, user_id, '', '', '2000-01-01', '00:00:00', '', 0, 0, 0, '[]', '', '', ''
    ])
    if not owned:
        # Profile is a local/default frontend profile — auto-create a
        # minimal stub so the FK constraint on numerology_reports is satisfied.
        profile_data = body.get("profile", {})
        call_procedure("sp_profile_ops", [
            'create', profile_id, user_id,
            profile_data.get("fullName", "User"),
            profile_data.get("gender", "other"),
            profile_data.get("birthDate", "2000-01-01"),
            profile_data.get("birthTime", "00:00:00"),
            profile_data.get("birthPlace", "Unknown"),
            profile_data.get("latitude", 0),
            profile_data.get("longitude", 0),
            profile_data.get("timezone", 0),
            json.dumps(profile_data.get("focusAreas", [])),
            profile_data.get("notes", ""),
            profile_data.get("horoscopeSystem", "vedic"),
            profile_data.get("relationLabel", "Self"),
        ])

    report_id = str(uuid.uuid4())
    rows = call_procedure("sp_numerology_ops", [
        'save', report_id, profile_id, user_id,
        int(report["mulank"]), int(report["bhagyank"]),
        int(report["namankChaldean"]), int(report["namankPythagorean"]),
        json.dumps(report),
    ])
    if not rows:
        return _error("Could not save numerology report", "SAVE_FAILED", 500)

    return jsonify({"status": "success", "data": _row_to_report(rows[0])}), 201


def get_numerology(user_id: str, profile_id: str):
    rows = call_procedure("sp_numerology_ops", ['get', '', profile_id, user_id, 0, 0, 0, 0, '[]'])
    if not rows:
        return _error("No saved numerology report for this profile", "NOT_FOUND", 404)

    return jsonify({"status": "success", "data": _row_to_report(rows[0])})


def get_dynamic_insights():
    body = request.get_json(silent=True) or {}
    mulank = body.get("mulank")
    bhagyank = body.get("bhagyank")
    namank = body.get("namank")
    missing_numbers = body.get("missingNumbers", [])
    language = body.get("language", "en")
    
    if mulank is None or bhagyank is None:
        return _error("mulank and bhagyank are required", "VALIDATION_ERROR")
        
    try:
        from services.llm_service import get_numerology_insights_response
        json_res = get_numerology_insights_response(mulank, bhagyank, namank, missing_numbers, language)
        import json
        insights_data = json.loads(json_res)
        return jsonify({"status": "success", "data": insights_data})
    except Exception as e:
        print(f"Error in get_dynamic_insights: {e}")
        return _error(str(e), "LLM_ERROR", 500)

def calculate_numerology_endpoint():
    body = request.get_json(silent=True) or {}
    full_name = body.get("fullName", "")
    dob_str = body.get("birthDate", "")
    
    try:
        from services.numerology_service import calculate_numerology_report
        report_data = calculate_numerology_report(full_name, dob_str)
        return jsonify({"status": "success", "data": report_data})
    except Exception as e:
        print(f"Error in calculate_numerology_endpoint: {e}")
        return _error(str(e), "CALCULATION_ERROR", 500)
