import json
from datetime import datetime
from flask import request, jsonify
from services.ephemeris_service import calculate_chart_data, calculate_panchang_data
from services.chart_assembly_service import assemble_full_chart
from services.numerology_service import calculate_numerology_report
from services.llm_service import (
    get_daily_insights_response,
    get_roadmap_insights_response,
    get_interpret_response
)

def get_full_report_data():
    """
    Consolidated Server-Side Master Report Data Aggregator
    Endpoint: POST /api/reports/full-report-data
    Gathers chartData, daily panchang, numerology, daily insights, and 25-year roadmap in one unified payload.
    """
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", {})
    tradition = body.get("tradition", "parashari")
    language = body.get("language", "en")

    if not profile:
        return jsonify({"status": "error", "message": "Profile data is required"}), 400

    date_str = profile.get("birthDate") or "2000-01-01"
    time_str = profile.get("birthTime") or "12:00"
    lat = profile.get("latitude", 28.6139)
    lon = profile.get("longitude", 77.2090)
    tz_offset = profile.get("timezone", 5.5)
    full_name = profile.get("fullName") or "Seeker"

    try:
        # 1. Calculate Numerology & Lo Shu
        numerology_data = calculate_numerology_report(full_name, date_str)
        mulank = numerology_data.get("mulank", 1)

        # 2. Calculate Ephemeris Chart Data & Assemble 5 Traditions
        raw_chart = calculate_chart_data(date_str, time_str, float(lat), float(lon), float(tz_offset))
        chart_data = assemble_full_chart(raw_chart, profile)

        # 3. Calculate Today's Daily Transit Ephemeris Panchang
        today_date_str = datetime.utcnow().strftime("%Y-%m-%d")
        now_time_str = datetime.utcnow().strftime("%H:%M")
        panchang_data = calculate_panchang_data(today_date_str, now_time_str, float(tz_offset), float(lat), float(lon), int(mulank))

        # 4. Daily AI Planetary Synthesis
        daily_insights = {}
        try:
            raw_ai = get_daily_insights_response(profile, chart_data, panchang_data, numerology_data)
            daily_insights = json.loads(raw_ai)
        except Exception as ai_err:
            print(f"[FullReport] Daily AI generation fallback: {ai_err}")
            daily_insights = {
                "summary": "Today's cosmic transits favor steady progress, routine refinement, and maintaining emotional equilibrium.",
                "career": "Steady momentum supports operational tasks, documentation, and routine client interactions.",
                "love": "Balanced vibrations nurture mutual respect, shared domestic responsibilities, and supportive listening.",
                "health": "Stable physical equilibrium; maintain hydration and gentle restorative yoga or morning walks.",
                "lucky_color_desc": "Enhances calm focus & depth"
            }

        # 5. 25-Year Vedic Destiny Roadmap Insights
        roadmap_data = {}
        try:
            raw_roadmap = get_roadmap_insights_response(profile, tradition, chart_data, numerology_data, language)
            roadmap_data = json.loads(raw_roadmap)
        except Exception as rm_err:
            print(f"[FullReport] Roadmap generation fallback: {rm_err}")
            roadmap_data = {
                "milestones": [
                    {
                        "year": datetime.utcnow().year,
                        "age": 25,
                        "domain": "Career & Enterprise",
                        "title": "Foundation Phase & Strategic Consolidation",
                        "prediction": "Harmonious planetary transits activate professional growth, skill refinement, and leadership opportunities.",
                        "intensity": "High"
                    }
                ]
            }

        return jsonify({
            "status": "success",
            "data": {
                "profile": profile,
                "chartData": chart_data,
                "panchang": panchang_data,
                "numerology": numerology_data,
                "dailyInsights": daily_insights,
                "roadmap": roadmap_data,
                "tradition": tradition,
                "language": language,
                "generatedAt": datetime.utcnow().isoformat()
            }
        })

    except Exception as e:
        print(f"[ERROR] Error in get_full_report_data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
