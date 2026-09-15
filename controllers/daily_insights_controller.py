from flask import request, jsonify
import json
import threading
from datetime import datetime
from services.llm_service import get_daily_insights_response
from services.ephemeris_service import calculate_panchang_data

# Thread-safe in-memory cache to enforce single daily reading generation per user/profile
DAILY_HOROSCOPE_CACHE = {}
_cache_lock = threading.Lock()

def _get_cache_key(profile: dict, panchang: dict) -> str:
    profile_id = str(profile.get("id") or profile.get("fullName") or profile.get("birthDate") or "anonymous").strip().lower()
    date_str = str(panchang.get("date") or datetime.utcnow().strftime("%Y-%m-%d")).strip()
    return f"{profile_id}_{date_str}"

def calculate_ephemeris_panchang():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    date_str = data.get("date")
    time_str = data.get("time")
    tz_offset = data.get("timezone", 5.5)
    lat = data.get("lat")
    lon = data.get("lon")
    mulank = data.get("mulank")

    if not all([date_str, time_str, lat is not None, lon is not None, mulank is not None]):
        return jsonify({"status": "error", "message": "Missing required fields: date, time, lat, lon, mulank are mandatory."}), 400

    try:
        result = calculate_panchang_data(date_str, time_str, float(tz_offset), float(lat), float(lon), int(mulank))
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        print(f"Error in calculate_ephemeris_panchang: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def daily_horoscope():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    profile = data.get("profile", {})
    chart_data = data.get("chartData", {})
    panchang = data.get("panchang", {})
    numerology = data.get("numerology", {})

    cache_key = _get_cache_key(profile, panchang)

    # Check if already generated today for this profile
    with _cache_lock:
        if cache_key in DAILY_HOROSCOPE_CACHE:
            return jsonify({
                "status": "success",
                "insights": DAILY_HOROSCOPE_CACHE[cache_key],
                "cached": True,
                "message": "Daily reading retrieved from cache (single generation per day allowed)."
            })

    try:
        json_res = get_daily_insights_response(profile, chart_data, panchang, numerology)
        insights = json.loads(json_res)
        with _cache_lock:
            DAILY_HOROSCOPE_CACHE[cache_key] = insights
        return jsonify({
            "status": "success",
            "insights": insights,
            "cached": False,
            "message": "Daily reading successfully generated."
        })
    except Exception as e:
        print(f"Error in daily_horoscope: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
