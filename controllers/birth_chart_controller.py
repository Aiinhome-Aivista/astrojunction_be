from flask import request, jsonify, g
from services.ephemeris_service import calculate_chart_data
from services.chart_assembly_service import assemble_full_chart
from database.db_connection import call_procedure

def _format_birth_time(value) -> str:
    """MySQL TIME columns come back as timedelta; normalise to HH:MM."""
    if value is None:
        return "12:00"
    if hasattr(value, "total_seconds"):
        total_minutes = int(value.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours:02d}:{minutes:02d}"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5] or "12:00"

def calculate_ephemeris_chart():
    data = request.json or {}
    profile_id = data.get("id")           # frontend sends profile.id
    user_id    = getattr(g, "user_id", None)

    # ── 1. Try to load birth data from DB (trusted source) ────────────────
    db_profile = None
    if profile_id and user_id:
        rows = call_procedure("sp_profile_ops", [
            'get_one', profile_id, user_id,
            None, None, None, None, None, None, None, None, None, None, None, None
        ])
        if rows:
            r = rows[0]
            db_profile = {
                "birthDate":      r["birth_date"].isoformat() if hasattr(r["birth_date"], "isoformat") else str(r["birth_date"]),
                "birthTime":      _format_birth_time(r.get("birth_time")),
                "latitude":       float(r["latitude"]),
                "longitude":      float(r["longitude"]),
                "timezone":       float(r["timezone_offset"]),
                "horoscopeSystem": r.get("horoscope_system", "vedic"),
            }

    # ── 2. Merge: DB data wins over frontend data ──────────────────────────
    profile = {**data, **(db_profile or {})}

    date_str  = profile.get("birthDate")
    time_str  = profile.get("birthTime") or "12:00"
    lat       = profile.get("latitude")
    lon       = profile.get("longitude")
    tz_offset = profile.get("timezone", 5.5)

    if not all([date_str, lat is not None, lon is not None]):
        return jsonify({"status": "error", "message": "Missing required fields: birthDate, latitude, longitude"}), 400

    try:
        # Step 1: Raw ephemeris (Swiss Ephemeris)
        raw = calculate_chart_data(date_str, time_str, float(lat), float(lon), float(tz_offset))
        # Step 2: Fully assembled chart (uses DB zodiac data)
        assembled = assemble_full_chart(raw, profile)
        return jsonify({"status": "success", "data": assembled})
    except Exception as e:
        print(f"Error in calculate_ephemeris_chart: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def post_interpret():
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", {})
    tradition = body.get("tradition", "parashari")
    chart_data = body.get("chartData", {})
    numerology = body.get("numerology", {})
    language = body.get("language", "en")
    
    try:
        from services.llm_service import get_interpret_response
        interpretation = get_interpret_response(profile, tradition, chart_data, numerology, language)
        return jsonify({"status": "success", "data": {"interpretation": interpretation}})
    except Exception as e:
        print(f"Error in interpret insights: {e}")
        return jsonify({"status": "error", "message": str(e), "error_code": "LLM_ERROR"}), 500
