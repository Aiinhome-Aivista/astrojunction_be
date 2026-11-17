from flask import request, jsonify
import json
import hashlib
import threading
from datetime import datetime
from services.llm_service import get_daily_insights_response
from services.ephemeris_service import calculate_panchang_data, get_day_stable_panchang_facts

# Thread-safe in-memory cache to enforce single daily reading generation per user/profile
# Key format: f"{profile_id}_{date_str}_{facts_hash}"
DAILY_HOROSCOPE_CACHE = {}
_cache_lock = threading.Lock()
# Daily forceRefresh counter per profile (key: f"{profile_id}_{date_str}")
_REFRESH_COUNTS = {}

def _evict_old_cache_entries(current_date_str: str):
    """Evicts cache and rate-limit entries from previous dates to keep memory bounded."""
    keys_to_evict = [k for k, v in list(DAILY_HOROSCOPE_CACHE.items()) if v.get("date") != current_date_str]
    for k in keys_to_evict:
        DAILY_HOROSCOPE_CACHE.pop(k, None)
    refresh_keys_to_evict = [k for k in list(_REFRESH_COUNTS.keys()) if not k.endswith(f"_{current_date_str}")]
    for k in refresh_keys_to_evict:
        _REFRESH_COUNTS.pop(k, None)

def _compute_facts_hash(score: int, sunrise_tithi: str, sunrise_nakshatra: str, sunrise_ascendant: str) -> str:
    """Computes a 12-char SHA-256 hash strictly from day-stable astronomical values."""
    raw = f"{score}_{sunrise_tithi}_{sunrise_nakshatra}_{sunrise_ascendant}".strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

def calculate_ephemeris_panchang():
    import time
    start_time = time.time()
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
        session_id = request.headers.get("x-session-id")
        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="PANCHANG_CALCULATION",
                    event_category="ASTROLOGY",
                    input_payload={"date": date_str, "time": time_str, "lat": lat, "lon": lon},
                    status="SUCCESS",
                    result_summary={"tithi": (result or {}).get("tithi"), "nakshatra": (result or {}).get("nakshatra")},
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        print(f"Error in calculate_ephemeris_panchang: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def daily_horoscope():
    import time
    start_time = time.time()
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    profile = data.get("profile", {})
    chart_data = data.get("chartData", {})
    panchang = data.get("panchang", {})
    numerology = data.get("numerology", {})

    target_lang = str(data.get("lang") or "en").strip().lower()
    if target_lang not in ["en", "hi", "bn", "ta", "fr"]:
        return jsonify({"status": "error", "message": "Invalid language. Supported: en, hi, bn, ta, fr"}), 400

    date_str = str(panchang.get("date") or datetime.utcnow().strftime("%Y-%m-%d")).strip()
    lat = float(profile.get("latitude") or 28.6139)
    lon = float(profile.get("longitude") or 77.209)
    tz_offset = float(profile.get("timezoneOffset") or 5.5)
    mulank = int(numerology.get("mulank") or 1)

    # Compute day-stable facts strictly from sunrise ephemeris
    day_facts = get_day_stable_panchang_facts(date_str, lat, lon, tz_offset, mulank)
    score = day_facts["auspiciousScore"]
    band_code = day_facts.get("bandCode", "balanced")
    sunrise_tithi = day_facts["tithiName"]
    sunrise_nak = day_facts["nakshatraName"]
    sunrise_asc = day_facts["sunriseAscendant"]

    profile_id = str(profile.get("id") or profile.get("fullName") or profile.get("birthDate") or "anonymous").strip().lower()
    facts_hash = _compute_facts_hash(score, sunrise_tithi, sunrise_nak, sunrise_asc)
    cache_key = f"{profile_id}_{date_str}_{facts_hash}_{target_lang}"

    force_refresh = bool(data.get("forceRefresh"))

    with _cache_lock:
        # Evict cache entries from previous dates
        _evict_old_cache_entries(date_str)

        # Rate-limit forceRefresh: admin-only or maximum 3 times per profile per day across all languages
        if force_refresh:
            is_admin = bool(profile.get("role") == "admin" or profile.get("isAdmin") is True)
            if not is_admin:
                refresh_key = f"{profile_id}_{date_str}"
                count = _REFRESH_COUNTS.get(refresh_key, 0)
                if count >= 3:
                    force_refresh = False
                else:
                    _REFRESH_COUNTS[refresh_key] = count + 1

        # Check if already generated today with these exact day-stable facts and language
        if not force_refresh and cache_key in DAILY_HOROSCOPE_CACHE:
            cached_entry = DAILY_HOROSCOPE_CACHE[cache_key]
            return jsonify({
                "status": "success",
                "insights": cached_entry.get("insights", cached_entry),
                "auspiciousScore": score,
                "bandCode": band_code,
                "sunriseAscendant": sunrise_asc,
                "lang": target_lang,
                "cached": True,
                "message": "Daily reading retrieved from cache (single generation per day allowed)."
            })

    try:
        from services.settings_service import get_setting
        active_engine = get_setting("ACTIVE_LLM", "not_set")
        print(f"\n[DailyHoroscope API] Generating insights for: '{profile.get('fullName', 'User')}' | Lang: [{target_lang}] | Provider: [{active_engine.upper()}] | Sunrise Ascendant: [{sunrise_asc}] | Day Score: [{score}]")
        json_res = get_daily_insights_response(profile, chart_data, panchang, numerology, day_facts=day_facts, target_lang=target_lang)
        insights = json.loads(json_res)
        with _cache_lock:
            DAILY_HOROSCOPE_CACHE[cache_key] = {
                "insights": insights,
                "date": date_str,
                "auspiciousScore": score,
                "bandCode": band_code,
                "lang": target_lang,
                "timestamp": time.time()
            }

        session_id = request.headers.get("x-session-id")
        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="DAILY_HOROSCOPE_GENERATION",
                    event_category="AI_CHAT",
                    input_payload={"name": profile.get("fullName"), "rashi": profile.get("horoscopeSystem"), "lang": target_lang},
                    status="SUCCESS",
                    result_summary={"engine": active_engine, "summary": (insights.get("summary") or "")[:150]},
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass

        return jsonify({
            "status": "success",
            "insights": insights,
            "auspiciousScore": score,
            "bandCode": band_code,
            "sunriseAscendant": sunrise_asc,
            "lang": target_lang,
            "cached": False,
            "message": "Daily reading successfully generated."
        })
    except Exception as e:
        print(f"Error in daily_horoscope: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def generate_daily_insights_pdf():
    try:
        from flask import Response
        from services.pdf_service import render_pdf
        body = request.get_json(silent=True) or {}
        lang = body.get("lang") or body.get("language") or "en"
        profile = body.get("profile") or {}
        panchang = body.get("panchang") or {}
        ai_insights = body.get("aiInsights") or {}
        labels = body.get("labels") or {}

        p_name = profile.get("fullName") or profile.get("name") or "Seeker"
        clean_name = "".join(c for c in p_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        date_str = panchang.get("date") or profile.get("birthDate") or datetime.now().strftime("%Y-%m-%d")

        # Fallback to server-side cache if frontend didn't supply aiInsights, or if wrong script detected
        import re
        if ai_insights and ai_insights.get("summary"):
            if lang in ["fr", "en"] and re.search(r'[\u0900-\u0DFF]', ai_insights.get("summary", "")):
                print(f"[Daily Insights PDF] Stale corrupted Indic text detected in {lang} AI insights. Evicting.")
                ai_insights = {}

        if not ai_insights or not ai_insights.get("summary"):
            profile_id = str(profile.get("id") or profile.get("fullName") or profile.get("birthDate") or "anonymous").strip().lower()
            with _cache_lock:
                for k, v in DAILY_HOROSCOPE_CACHE.items():
                    if k.startswith(f"{profile_id}_{date_str}") and k.endswith(f"_{lang}"):
                        candidate = v.get("insights", v)
                        if candidate and isinstance(candidate, dict):
                            cand_summary = candidate.get("summary", "")
                            if lang in ["fr", "en"] and re.search(r'[\u0900-\u0DFF]', cand_summary):
                                continue
                            ai_insights = candidate
                            break

        # If still missing, attempt on-demand generation in target lang if panchang is present
        chart_data = body.get("chartData") or {}
        if not isinstance(chart_data, dict):
            chart_data = {}
        if (not ai_insights or not ai_insights.get("summary")) and panchang.get("tithi"):
            try:
                from services.llm_service import get_daily_insights_response
                print(f"[Daily Insights PDF] On-demand generating daily insights in [{lang}] for PDF")
                json_res = get_daily_insights_response(profile, chart_data, panchang, body.get("numerology") or {}, target_lang=lang)
                ai_insights = json.loads(json_res)
            except Exception as gen_err:
                print(f"[Daily Insights PDF] On-demand AI generation fallback failed: {gen_err}")

        from services.pdf_service import resolve_translation
        doc_title = resolve_translation("dailyInsights.pdf.report_title", lang, labels, default="Daily Cosmic Insights & Vedic Panchang")
        doc_subtitle = resolve_translation("dailyInsights.pdf.precision", lang, labels, default="Authentic Vedic Ephemeris & AI Synthesis")

        chart_data = body.get("chartData") or {}
        if not isinstance(chart_data, dict):
            chart_data = {}
        if "ascendant" not in chart_data or not chart_data["ascendant"]:
            chart_data["ascendant"] = {"signName": "Pisces", "signSanskrit": "মীন" if lang == "bn" else "Meena"}

        from services.pdf_service import format_localized_digits
        tagline_map = {
            "en": f"Precision Astronomical Ephemeris • Drig-Ganita Panchanga ({date_str})",
            "hi": f"सटीक खगोलीय पंचांग • दृक-गणित पंचांग ({format_localized_digits(date_str, 'hi')})",
            "bn": f"নিখুঁত জ্যোতির্বিজ্ঞানসম্মত পঞ্জিকা • দৃক-গণিত পঞ্চাঙ্গ ({format_localized_digits(date_str, 'bn')})",
            "ta": f"துல்லிய வானியல் பஞ்சாங்கம் • திருக்கணித பஞ்சாங்கம் ({date_str})",
            "fr": f"Éphémérides Astronomiques de Précision • Panchanga Drig-Ganita ({date_str})"
        }

        data = {
            "doc_title": "DAILY VEDIC INSIGHTS & PLANETARY TRANSITS" if lang == "en" else doc_title,
            "doc_subtitle": doc_subtitle,
            "doc_subtitle_tagline": tagline_map.get(lang, tagline_map["en"]),
            "doc_date": date_str,
            "profile": profile,
            "panchang": panchang,
            "aiInsights": ai_insights,
            "chartData": chart_data,
            "numerology": body.get("numerology") or {},
            "rituals": body.get("rituals") or {},
            "has_english_fallback": lang != "en" and (ai_insights.get("isEnglishFallback") or not ai_insights.get("summary")),
        }

        pdf_bytes = render_pdf("daily_insights_pdf.html", lang, data, labels)
        filename = f"AstroJunction_Daily_Report_{clean_name}_{date_str}_{lang}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as exc:
        print(f"Error generating Daily Insights PDF: {exc}")
        return jsonify({"status": "error", "message": str(exc), "error_code": "PDF_ERROR"}), 500


