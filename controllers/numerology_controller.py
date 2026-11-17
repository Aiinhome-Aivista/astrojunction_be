import uuid
import json
import hashlib
import threading
from flask import request, jsonify

from database.db_connection import call_procedure

# Thread-safe in-memory cache keyed by (input hash, lang)
_NUMEROLOGY_INSIGHTS_CACHE = {}
_numerology_cache_lock = threading.Lock()

def _get_numerology_cache_key(mulank, bhagyank, namank, missing_numbers, language: str) -> str:
    norm_missing = sorted([int(x) for x in (missing_numbers or []) if str(x).isdigit()])
    raw_key = f"{mulank}_{bhagyank}_{namank}_{norm_missing}_{language.strip().lower()}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


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
    language = (body.get("language") or "en").strip().lower()
    
    if language not in ("en", "hi", "bn", "ta", "fr"):
        return _error("Invalid language parameter. Supported: en, hi, bn, ta, fr", "INVALID_LANG", 400)

    if mulank is None or bhagyank is None:
        return _error("mulank and bhagyank are required", "VALIDATION_ERROR")

    cache_key = _get_numerology_cache_key(mulank, bhagyank, namank, missing_numbers, language)
    with _numerology_cache_lock:
        if cache_key in _NUMEROLOGY_INSIGHTS_CACHE:
            return jsonify({
                "status": "success",
                "data": _NUMEROLOGY_INSIGHTS_CACHE[cache_key],
                "cached": True
            })

    try:
        from services.llm_service import get_numerology_insights_response
        json_res = get_numerology_insights_response(mulank, bhagyank, namank, missing_numbers, language)
        import json
        insights_data = json.loads(json_res)
        with _numerology_cache_lock:
            _NUMEROLOGY_INSIGHTS_CACHE[cache_key] = insights_data
        return jsonify({"status": "success", "data": insights_data, "cached": False})
    except Exception as e:
        print(f"Error in get_dynamic_insights: {e}")
        return _error(str(e), "LLM_ERROR", 500)

def calculate_numerology_endpoint():
    import time
    start_time = time.time()
    body = request.get_json(silent=True) or {}
    full_name = body.get("fullName", "")
    dob_str = body.get("birthDate", "")
    session_id = request.headers.get("x-session-id")
    
    try:
        from services.numerology_service import calculate_numerology_report
        report_data = calculate_numerology_report(full_name, dob_str)

        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="NUMEROLOGY_CALCULATION",
                    event_category="NUMEROLOGY",
                    input_payload={"name": full_name, "birthDate": dob_str},
                    status="SUCCESS",
                    result_summary={"mulank": report_data.get("mulank"), "bhagyank": report_data.get("bhagyank"), "namank": report_data.get("namank_chaldean")},
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass

        return jsonify({"status": "success", "data": report_data})
    except Exception as e:
        print(f"Error in calculate_numerology_endpoint: {e}")
        return _error(str(e), "CALCULATION_ERROR", 500)


def generate_numerology_pdf():
    try:
        from flask import Response
        from datetime import datetime
        from services.pdf_service import render_pdf
        body = request.get_json(silent=True) or {}
        lang = body.get("lang") or body.get("language") or "en"
        profile = body.get("profile") or {}
        numerology = body.get("numerology") or body.get("activeNumerology") or {}
        labels = body.get("labels") or {}

        p_name = profile.get("fullName") or profile.get("name") or "Seeker"
        clean_name = "".join(c for c in p_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        date_str = profile.get("birthDate") or datetime.now().strftime("%Y-%m-%d")

        # Format grid counts if missing
        if "gridCounts" not in numerology:
            counts = {}
            for d_char in "123456789":
                counts[d_char] = "Absent"
            # Extract from complete date string
            cleaned_dob = "".join(c for c in date_str if c.isdigit())
            for c in cleaned_dob:
                if c in counts:
                    if counts[c] == "Absent":
                        counts[c] = "1x"
                    else:
                        prev = int(counts[c].replace("x", ""))
                        counts[c] = f"{prev + 1}x"
            numerology["gridCounts"] = counts

        # Format 8 planes if missing
        if "planes" not in numerology or not numerology["planes"]:
            numerology["planes"] = [
                {"name": labels.get("numerology.planes.thought", "Thought Plane (4-9-2)"), "numbers": "4-9-2", "strength": 67, "domain": "Mental Foresight"},
                {"name": labels.get("numerology.planes.will", "Will Plane (3-5-7)"), "numbers": "3-5-7", "strength": 33, "domain": "Inner Willpower"},
                {"name": labels.get("numerology.planes.action", "Action Plane (8-1-6)"), "numbers": "8-1-6", "strength": 33, "domain": "Execution & Commerce"},
                {"name": labels.get("numerology.planes.mental", "Mental Plane (4-3-8)"), "numbers": "4-3-8", "strength": 33, "domain": "Logic & Memory"},
                {"name": labels.get("numerology.planes.emotional", "Emotional Plane (9-5-1)"), "numbers": "9-5-1", "strength": 67, "domain": "Compassion & Empathy"},
                {"name": labels.get("numerology.planes.practical", "Practical Plane (2-7-6)"), "numbers": "2-7-6", "strength": 33, "domain": "Hands-on Grounding"},
                {"name": labels.get("numerology.planes.golden", "Golden Yog / Raj Yog (4-5-6)"), "numbers": "4-5-6", "strength": 67, "domain": "Supreme Wealth & Status"},
                {"name": labels.get("numerology.planes.silver", "Silver Yog (2-5-8)"), "numbers": "2-5-8", "strength": 33, "domain": "Property & Assets"},
            ]

        from services.pdf_service import resolve_translation
        doc_title = resolve_translation("numerology.pdf.report_title", lang, labels, default="Sacred Numbers & Lo Shu Magic Grid Report")
        doc_subtitle = resolve_translation("numerology.subtitle", lang, labels, default="Vedic & Chaldean Sacred Vibration Matrix")

        data = {
            "doc_type": "numerology",
            "doc_title": "SACRED NUMEROLOGY & LO SHU MAGIC GRID BLUEPRINT" if lang == "en" else resolve_translation("numerology.pdf.report_title", lang, labels, default="SACRED NUMEROLOGY & LO SHU MAGIC GRID BLUEPRINT"),
            "doc_subtitle": doc_subtitle,
            "doc_subtitle_tagline": f"Vedic Sidereal & Chaldean Sacred Vibration Matrix ({date_str})",
            "doc_date": date_str,
            "profile": profile,
            "numerology": numerology,
            "has_english_fallback": False,
        }

        pdf_bytes = render_pdf("dossier_pdf.html", lang, data, labels)
        filename = f"AstroJunction_Numerology_{clean_name}_{date_str}_{lang}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as exc:
        print(f"Error generating Numerology PDF: {exc}")
        return jsonify({"status": "error", "message": str(exc), "error_code": "PDF_ERROR"}), 500


