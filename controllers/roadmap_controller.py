import json
import uuid
from flask import request, jsonify, Response
from database.db_connection import call_procedure
from services.report_service import generate_roadmap_report_pdf

def get_user_roadmap():
    """Fetches user's saved 25-Year Roadmap from MySQL database."""
    try:
        user_id = request.args.get("user_id") or request.args.get("userId") or "guest_user"
        rows = call_procedure("sp_get_user_roadmap", [str(user_id)])
        if not rows:
            return jsonify({"status": "success", "data": None})

        row = dict(rows[0])
        horizons_json = row.get("horizons_generated_json")
        milestones_data = row.get("milestones_data")

        if isinstance(horizons_json, str):
            try:
                horizons_json = json.loads(horizons_json)
            except Exception:
                horizons_json = {}

        if isinstance(milestones_data, str):
            try:
                milestones_data = json.loads(milestones_data)
            except Exception:
                milestones_data = []

        return jsonify({
            "status": "success",
            "data": {
                "id": row.get("id"),
                "userId": row.get("user_id"),
                "profileName": row.get("profile_name"),
                "birthDate": str(row.get("birth_date")),
                "selectedHorizon": row.get("selected_horizon"),
                "generatedHorizons": horizons_json or {},
                "milestones": milestones_data or []
            }
        })
    except Exception as e:
        print(f"Error fetching roadmap from DB: {e}")
        return jsonify({"status": "error", "message": str(e), "error_code": "DB_FETCH_ERROR"}), 500


def post_roadmap_insights():
    """Generates roadmap predictions and stores them in MySQL database."""
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", {})
    tradition = body.get("tradition", "Vedic")
    language = body.get("language", "en")
    selected_horizon = body.get("horizon", "0-5 Years")
    
    chart_data = body.get("chartData", {})
    numerology = body.get("numerology", {})
    
    try:
        from services.llm_service import get_roadmap_insights_response
        json_res = get_roadmap_insights_response(profile, tradition, chart_data, numerology, language)
        insights_data = json.loads(json_res)

        # Database Upsert
        try:
            user_id = str(profile.get("id") or profile.get("userId") or "guest_user")
            profile_name = profile.get("fullName") or profile.get("name") or "Seeker"
            birth_date = profile.get("birthDate") or profile.get("dob") or None
            
            # Format date if needed
            if birth_date and len(str(birth_date)) > 10:
                birth_date = str(birth_date)[:10]

            milestones = insights_data.get("milestones") or []
            horizons_map = {selected_horizon: True}
            
            roadmap_id = f"rm_{user_id}_{selected_horizon.replace(' ', '_').lower()}"
            
            call_procedure("sp_upsert_user_roadmap", [
                roadmap_id,
                user_id,
                profile_name,
                birth_date,
                selected_horizon,
                json.dumps(horizons_map),
                json.dumps(milestones)
            ])
        except Exception as db_err:
            print(f"Database save warning (Roadmap): {db_err}")

        return jsonify({"status": "success", "data": insights_data})
    except Exception as e:
        print(f"Error in roadmap insights: {e}")
        return jsonify({"status": "error", "message": str(e), "error_code": "LLM_ERROR"}), 500


def download_roadmap_pdf():
    try:
        body = request.get_json(silent=True) or {}
        profile = body.get("profile", {})
        p_name = profile.get("fullName") or profile.get("name") or "Seeker"
        clean_name = "".join(c for c in p_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")

        pdf_bytes = generate_roadmap_report_pdf(body)
        filename = f"Vedic_25Year_Roadmap_{clean_name}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as exc:
        print(f"Error generating Roadmap PDF: {exc}")
        return jsonify({"status": "error", "message": str(exc), "error_code": "PDF_GEN_ERROR"}), 500


def post_filtered_roadmap_predictions():
    """Generates 8-topic Kundli life roadmap predictions for a specified timeframe horizon (0-5, 0-10, 0-15, 0-20, 0-25)."""
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", {})
    tradition = body.get("tradition", "Vedic")
    language = body.get("language", "en")
    # Accept both 'filter' and 'horizon' from input JSON payload
    raw_horizon = str(body.get("filter") or body.get("horizon") or "0-5 Years").strip()
    
    # Normalize inputs like '0 -10', '0 - 10', '0-10', '0-10 Years'
    clean_horizon = raw_horizon.lower().replace(" ", "").replace("years", "")
    
    horizon_map = {
        "0-5": "0-5 Years",
        "0-10": "0-10 Years",
        "0-15": "0-15 Years",
        "0-20": "0-20 Years",
        "0-25": "0-25 Years"
        
    }
    filter_map = {
        "0-5": "0-5",
        "0-10": "0-10",
        "0-15": "0-15",
        "0-20": "0-20",
        "0-25": "0-25"
    }
    selected_horizon = horizon_map.get(clean_horizon, horizon_map.get(raw_horizon, "0-5 Years"))
    filter_value = filter_map.get(clean_horizon, "0-5")
    allowed_horizons = ["0-5 Years", "0-10 Years", "0-15 Years", "0-20 Years", "0-25 Years"]
    if selected_horizon not in allowed_horizons:
        selected_horizon = "0-5 Years"

    chart_data = body.get("chartData", {})
    numerology = body.get("numerology", {})
    
    # 1. Extract user_id from JWT Token (Authorization header), request context, or headers
    user_id = getattr(request, "user_id", None)
    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                from utils.security import decode_token
                payload = decode_token(token)
                user_id = payload.get("sub")
            except Exception as token_err:
                print(f"Token decode warning: {token_err}")

    if not user_id:
        user_id = (
            request.headers.get("X-User-ID") or 
            body.get("user_id") or 
            body.get("userId") or 
            request.args.get("user_id") or 
            request.args.get("userId") or 
            "guest_user"
        ).strip()
    
    if not profile:
        profile = {"id": user_id, "fullName": "Seeker", "birthDate": "2000-01-01", "birthTime": "12:00", "latitude": 28.6139, "longitude": 77.2090, "timezone": 5.5}
        # Try fetching saved roadmap/profile from DB using token's user_id
        try:
            db_rows = call_procedure("sp_get_user_roadmap", [user_id])
            if db_rows and len(db_rows) > 0:
                row = dict(db_rows[0])
                profile["fullName"] = row.get("profile_name") or "Seeker"
                if row.get("birth_date"):
                    profile["birthDate"] = str(row.get("birth_date"))
        except Exception as fetch_err:
            print(f"Auto-fetch profile warning: {fetch_err}")

    # Auto-calculate numerology if missing
    if not numerology:
        try:
            from services.numerology_service import calculate_numerology_report
            p_name = profile.get("fullName") or profile.get("name") or "Seeker"
            b_date = profile.get("birthDate") or profile.get("dob") or "2000-01-01"
            numerology = calculate_numerology_report(p_name, str(b_date))
        except Exception as num_err:
            print(f"Auto-calculate numerology warning: {num_err}")
            numerology = {"mulank": "3", "bhagyank": "7"}

    # Auto-calculate chartData if missing
    if not chart_data:
        try:
            from services.ephemeris_service import calculate_chart_data
            from services.chart_assembly_service import assemble_full_chart
            date_str = str(profile.get("birthDate") or profile.get("dob") or "2000-01-01")
            if len(date_str) > 10:
                date_str = date_str[:10]
            time_str = str(profile.get("birthTime") or profile.get("tob") or "12:00")
            lat = float(profile.get("latitude") or profile.get("lat") or 28.6139)
            lon = float(profile.get("longitude") or profile.get("lng") or profile.get("lon") or 77.2090)
            tz = float(profile.get("timezone") or profile.get("tz") or 5.5)
            
            raw_chart = calculate_chart_data(date_str, time_str, lat, lon, tz)
            chart_data = assemble_full_chart(raw_chart, profile)
        except Exception as chart_err:
            print(f"Auto-calculate chartData warning: {chart_err}")
            chart_data = {}

    try:
        from services.llm_service import get_filtered_roadmap_predictions_response
        json_res = get_filtered_roadmap_predictions_response(
            profile=profile,
            tradition=tradition,
            chart_data=chart_data,
            numerology=numerology,
            horizon=selected_horizon,
            language=language
        )
        insights_data = json.loads(json_res)
        
        if isinstance(insights_data, dict):
            insights_data["filter"] = filter_value

        return jsonify({
            "status": "success",
            "filter": filter_value,
            "data": insights_data
        })
    except Exception as e:
        print(f"Error in filtered roadmap predictions: {e}")
        return jsonify({"status": "error", "message": str(e), "error_code": "LLM_ERROR"}), 500



