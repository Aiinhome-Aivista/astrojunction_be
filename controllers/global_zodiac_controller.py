from flask import request, jsonify
import json
from services.llm_service import get_zodiac_forecast_response
from database.db_connection import call_procedure

def get_all_zodiacs():
    try:
        results = call_procedure("sp_zodiac_ops", ["get_all", None])
        # The nakshatras are stored as comma separated strings, we need to convert them to lists for the frontend
        for row in results:
            if row.get('nakshatras'):
                row['nakshatras'] = [n.strip() for n in row['nakshatras'].split(',')]
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        print(f"Error in get_all_zodiacs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def zodiac_forecast():
    data = request.json or {}
    sign = data.get("sign", "Aries")
    timeframe = data.get("timeframe", "today")
    language = data.get("language", "en")

    try:
        forecast_json_str = get_zodiac_forecast_response(sign, timeframe, language)
        forecast_data = json.loads(forecast_json_str)
        return jsonify({"data": forecast_data})
    except Exception as e:
        print(f"Error in zodiac_forecast: {e}")
        from services.llm_service import _generate_fallback_zodiac_forecast
        fallback = _generate_fallback_zodiac_forecast(sign, timeframe, language)
        return jsonify({"data": fallback})

def zodiac_compatibility():
    data = request.json or {}
    sign_a = data.get("signA", "Aries")
    sign_b = data.get("signB", "Leo")
    system = data.get("system", "tropical")
    language = data.get("language", "en")

    try:
        from services.llm_service import get_zodiac_compatibility_response
        compat_json_str = get_zodiac_compatibility_response(sign_a, sign_b, system, language)
        compat_data = json.loads(compat_json_str)
        return jsonify({"data": compat_data})
    except Exception as e:
        print(f"Error in zodiac_compatibility: {e}")
        return jsonify({"data": {
            "overallScore": 75,
            "elementSynergy": f"Harmonious alignment between {sign_a} and {sign_b}.",
            "romanceAnalysis": "Planetary energies create mutual attraction and shared vision.",
            "intellectualAnalysis": "Dynamic communication fuels positive collaboration.",
            "growthPotential": "Both signs empower each other toward spiritual and personal growth.",
            "remedialAdvice": "Maintain patience and celebrate each other's individuality."
        }})

