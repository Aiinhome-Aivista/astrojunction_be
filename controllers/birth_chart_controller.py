import json
import re
from flask import request, jsonify, g
from services.ephemeris_service import calculate_chart_data
from services.chart_assembly_service import assemble_full_chart
from database.db_connection import call_procedure
try:
    import json_repair
except ImportError:
    json_repair = None

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
    import time
    start_time = time.time()
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

        session_id = request.headers.get("x-session-id")
        if session_id:
            try:
                from services.telemetry_service import record_event
                duration_ms = int((time.time() - start_time) * 1000)
                asc_info = assembled.get("ascendant") or {}
                moon_info = assembled.get("moon") or {}
                record_event(
                    session_id=session_id,
                    event_name="KUNDLI_CALCULATION",
                    event_category="ASTROLOGY",
                    user_id=user_id,
                    input_payload={
                        "name": profile.get("fullName"),
                        "birthDate": date_str,
                        "birthTime": time_str,
                        "place": profile.get("birthPlace"),
                        "latitude": lat,
                        "longitude": lon,
                    },
                    status="SUCCESS",
                    result_summary={
                        "ascendant": asc_info.get("signName") or asc_info.get("name"),
                        "moonSign": moon_info.get("signName") or moon_info.get("name"),
                        "planetsCount": len(assembled.get("planets") or []),
                    },
                    execution_time_ms=duration_ms,
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass

        return jsonify({"status": "success", "data": assembled})
    except Exception as e:
        print(f"Error in calculate_ephemeris_chart: {e}")
        session_id = request.headers.get("x-session-id")
        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="KUNDLI_CALCULATION",
                    event_category="ASTROLOGY",
                    user_id=user_id,
                    input_payload={"birthDate": date_str, "birthTime": time_str},
                    status="FAILURE",
                    error_message=str(e),
                    ip_address=request.remote_addr
                )
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500

def post_interpret():
    import time
    start_time = time.time()
    body = request.get_json(silent=True) or {}
    profile = body.get("profile", {})
    tradition = body.get("tradition", "parashari")
    chart_data = body.get("chartData", {})
    numerology = body.get("numerology", {})
    language = body.get("language", "en")
    session_id = request.headers.get("x-session-id")
    user_id = getattr(g, "user_id", None)
    
    try:
        from services.llm_service import get_interpret_response
        interpretation = get_interpret_response(profile, tradition, chart_data, numerology, language)
        duration_ms = int((time.time() - start_time) * 1000)
        import json
        interp_str = json.dumps(interpretation, ensure_ascii=False) if isinstance(interpretation, dict) else str(interpretation or "")

        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="ORACLE_CHART_INTERPRETATION",
                    event_category="AI_CHAT",
                    user_id=user_id,
                    input_payload={"tradition": tradition, "language": language, "name": profile.get("fullName")},
                    status="SUCCESS",
                    result_summary={"textLength": len(interp_str), "preview": interp_str[:120]},
                    execution_time_ms=duration_ms,
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent")
                )
            except Exception:
                pass

        return jsonify({"status": "success", "data": {"interpretation": interpretation}})
    except Exception as e:
        print(f"Error in interpret insights: {e}")
        if session_id:
            try:
                from services.telemetry_service import record_event
                record_event(
                    session_id=session_id,
                    event_name="ORACLE_CHART_INTERPRETATION",
                    event_category="AI_CHAT",
                    user_id=user_id,
                    input_payload={"tradition": tradition, "language": language},
                    status="FAILURE",
                    error_message=str(e),
                    ip_address=request.remote_addr
                )
            except Exception:
                pass
        return jsonify({"status": "error", "message": str(e), "error_code": "LLM_ERROR"}), 500


def generate_birth_chart_pdf():
    try:
        from flask import Response
        from datetime import datetime
        from services.pdf_service import render_pdf
        body = request.get_json(silent=True) or {}
        lang = body.get("lang") or body.get("language") or "en"
        profile = body.get("profile") or {}
        chart_data = body.get("chartData") or {}
        tradition = body.get("tradition") or "parashari"
        labels = body.get("labels") or {}

        p_name = profile.get("fullName") or profile.get("name") or "Seeker"
        clean_name = "".join(c for c in p_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        date_str = profile.get("birthDate") or datetime.now().strftime("%Y-%m-%d")

        # Normalise chart_data so all template lookups succeed safely
        if not isinstance(chart_data, dict):
            chart_data = {}
        if "planets" not in chart_data or not isinstance(chart_data["planets"], list):
            chart_data["planets"] = []
        if "houses" not in chart_data or not isinstance(chart_data["houses"], list):
            chart_data["houses"] = []
        if "ascendant" not in chart_data or not chart_data["ascendant"]:
            chart_data["ascendant"] = {"signName": "Aries", "degree": 0.0}
        if "moon" not in chart_data or not chart_data["moon"]:
            moon_planet = next(
                (p for p in chart_data.get("planets", []) if isinstance(p, dict) and (p.get("id") == "moon" or (p.get("name") and p["name"].lower() == "moon"))),
                None
            )
            if moon_planet:
                chart_data["moon"] = moon_planet
            else:
                chart_data["moon"] = {"signName": "Taurus", "degree": 0.0}

        PLANET_SANSKRIT = {
            "Sun": "Surya", "Moon": "Chandra", "Mars": "Mangal", "Mercury": "Budha",
            "Jupiter": "Guru", "Venus": "Shukra", "Saturn": "Shani", "Rahu": "Rahu", "Ketu": "Ketu"
        }
        for p in chart_data.get("planets", []):
            if isinstance(p, dict):
                p_name = p.get("name", "")
                if not p.get("sanskritName"):
                    p["sanskritName"] = PLANET_SANSKRIT.get(p_name, p_name)
                if "isRetrograde" not in p and "retrograde" in p:
                    p["isRetrograde"] = p["retrograde"]

        SIGN_LORDS = {
            "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
            "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
            "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
            "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter"
        }
        SIGN_ORDER = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo", "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
        
        asc_sign = (chart_data.get("ascendant") or {}).get("signName") or "Aries"
        asc_idx = SIGN_ORDER.index(asc_sign) if asc_sign in SIGN_ORDER else 0

        HOUSE_SANSKRIT = {
            1: "(Lagna)", 2: "House 2", 3: "House 3", 4: "(Matru)",
            5: "House 5", 6: "(Roga/Rina)", 7: "(Kalatra)", 8: "(Randhra)",
            9: "(Bhagya)", 10: "House 10", 11: "(Aya)", 12: "(Moksha)"
        }

        # Build / Enrich 12 houses
        enriched_houses = []
        raw_houses = chart_data.get("houses") or []
        for i in range(1, 13):
            raw_h = next((h for h in raw_houses if isinstance(h, dict) and (h.get("houseNumber") == i or h.get("number") == i)), None)
            sign_name = raw_h.get("signName") if raw_h and raw_h.get("signName") else SIGN_ORDER[(asc_idx + i - 1) % 12]
            sign_lord = raw_h.get("signLord") if raw_h and raw_h.get("signLord") else SIGN_LORDS.get(sign_name, "Mars")
            sanskrit_name = raw_h.get("sanskritName") if raw_h and raw_h.get("sanskritName") else HOUSE_SANSKRIT.get(i, f"House {i}")
            
            # Find planets occupying this house
            occ_list = []
            if raw_h and raw_h.get("planets"):
                for p in raw_h["planets"]:
                    p_name = p.get("name") if isinstance(p, dict) else str(p)
                    if p_name: occ_list.append(p_name)
            if not occ_list:
                for p in chart_data.get("planets", []):
                    if isinstance(p, dict) and (p.get("houseNumber") == i or p.get("house") == i):
                        p_name = p.get("name") or p.get("sanskritName")
                        if p_name: occ_list.append(p_name)
            
            sub_lord = raw_h.get("kpSubLord") if raw_h else None
            
            enriched_houses.append({
                "houseNumber": i,
                "number": i,
                "signName": sign_name,
                "signLord": sign_lord,
                "sanskritName": sanskrit_name,
                "occupants": ", ".join(occ_list) if occ_list else None,
                "kpSubLord": sub_lord,
            })
        chart_data["houses"] = enriched_houses

        tradition_map = {
            "parashari": "Parashari Jyotish (Brihat Parashara Hora)",
            "jaimini": "Jaimini Sutras (Chara Karaka & Sign Aspects)",
            "lal_kitab": "Lal Kitab (Palmistry & Planetary Debts)",
            "kp_system": "KP System (Krishnamurti Padhdhati Placidus)",
            "bhrigu_nadi": "Bhrigu Nadi (Nandi Nadi Combinations)",
        }
        from services.pdf_service import resolve_translation, format_localized_digits
        trad_title = resolve_translation(f"birthChart.nav.tradition_names.{tradition}", lang, labels, default=tradition_map.get(tradition, "Vedic Multi-Tradition Synthesis"))
        doc_title = resolve_translation("birthChart.pdf.report_title", lang, labels, default="Comprehensive Vedic Horoscope & 5 Traditions Dossier")

        tradition_defaults = {
            "bn": {
                "parashari": "বৃহৎ পরাশর হোরা শাস্ত্রের বিধান অনুযায়ী আপনার কুণ্ডলীর কেন্দ্র ও ত্রিকোণ ভাবসমূহে শুভ গ্রহের স্থিতিশীল প্রভাব বিদ্যমান। অনুকূল গ্রহীয় সমন্বয় আপনার নেতৃত্ব, দূরদর্শিতা ও আধ্যাত্মিক একাগ্রতা দৃঢ় করে।",
                "jaimini": "জৈমিনী সূত্র অনুযায়ী আত্মকারক ও অমাত্যকারক গ্রহের সংস্থান কর্মজীবন ও আত্মিক উন্নয়নের জন্য গভীর সংকেত প্রদান করে।",
                "lal_kitab": "লাল কিতাবের অবস্থান অনুযায়ী শুভ আচরণ ও সহজ বৈদিক প্রতিকার আপনার ভাগ্য চক্রকে সুদৃঢ় রাখতে সহায়ক।",
                "kp_system": "কে.পি. পদ্ধতি অনুসারে ভাব অধিপতি এবং উপ-অধিপতিদের সূক্ষ্ম গণনা জীবনের প্রধান ঘটনার সময় নির্দেশ করে।",
                "bhrigu_nadi": "ভৃগু নন্দী নাড়ী অনুযায়ী পূর্বজন্মের শুভ কর্ম এবং গ্রহ সংযোগ আপনার জীবনে আধ্যাত্মিক ও বৈষয়িক সমৃদ্ধি আনয়ন করে।"
            },
            "hi": {
                "parashari": "बृहत् पाराशर होरा शास्त्र के अनुसार आपकी कुंडली के केंद्र और त्रिकोण भावों में शुभ ग्रहों का प्रभाव विद्यमान है। ग्रहों की अनुकूल स्थिति आपके नेतृत्व, विवेक एवं प्रतिष्ठा को सुदृढ़ करती है।",
                "jaimini": "जैमिनी सूत्रों के अनुसार आत्मकारक और अमात्यकारक का संबंध आपके जीवन की दिशा और आध्यात्मिक प्रगति को प्रकट करता है।",
                "lal_kitab": "लाल किताब के अनुसार शुभ आचरण और सरल उपाय आपके भाग्य पथ को सशक्त बनाए रखने में सहायक हैं।",
                "kp_system": "के.पी. पद्धति के अनुसार उप-नक्षत्र स्वामियों की गणना महत्वपूर्ण जीवन घटनाओं के सटीक समय का संकेत देती है।",
                "bhrigu_nadi": "भृगु नंदी नाड़ी के अनुसार पूर्वजन्म के कर्म और ग्रह संबंध आपके जीवन में आध्यात्मिक एवं भौतिक प्रगति सुनिश्चित करते हैं।"
            },
            "ta": {
                "parashari": "பராசர ஹோரா சாஸ்திரத்தின்படி உங்கள் ஜாதகத்தில் கேந்திர மற்றும் திரிகோண ஸ்தானங்களில் சுப கிரகங்களின் ஆதிக்கம் நன்மைகளைத் தருகிறது.",
                "jaimini": "ஜெமினி சூத்திரங்களின்படி ஆத்மகாரகன் மற்றும் அமாத்யகாரகன் நிலைகள் உன்னதமான வாழ்க்கை வழிகாட்டலை அளிக்கின்றன.",
                "lal_kitab": "லால் கிதாப் முறையின்படி எளிய பரிகாரங்கள் உங்கள் அதிர்ஷ்டத்தை வலுப்படுத்த உதவும்.",
                "kp_system": "கே.பி. முறையின்படி உப-அதிபதிகளின் கணிப்பு துல்லியமான நிகழ்வுகளின் காலத்தை சுட்டிக்காட்டுகிறது.",
                "bhrigu_nadi": "பிருகு நந்தி நாடியின்படி முற்பிறவி கர்ம வினைகள் மற்றும் குரு-சனி சேர்க்கை சிறப்பான முன்னேற்றத்தை அளிக்கின்றன."
            },
            "fr": {
                "parashari": "Selon le Brihat Parashara Hora Shastra, la configuration des maisons angulaires et trigones reflète une résilience et un discernement stratégique majeurs.",
                "jaimini": "Selon les sutras de Jaimini, l'Atmakaraka et l'Amatyakaraka indiquent une évolution spirituelle et professionnelle profonde.",
                "lal_kitab": "Selon le Lal Kitab, des remèdes harmonieux soutiennent l'équilibre karmique et matériel.",
                "kp_system": "Le système KP précise les alignements temporels par les seigneurs sous-jacents (Sub-Lords).",
                "bhrigu_nadi": "Le Bhrigu Nandi Nadi révèle la synchronisation karmique et l'épanouissement personnel."
            },
            "en": {
                "parashari": "According to Brihat Parashara Hora Shastra, the benefic alignment across Kendra and Trikona houses reinforces analytical acumen, ethical leadership, and enduring spiritual resilience.",
                "jaimini": "Under Jaimini Sutras, the dynamic interplay of Atmakaraka and Amatyakaraka reveals key developmental turning points and leadership destiny.",
                "lal_kitab": "Lal Kitab planetary dynamics indicate practical remedies and disciplined habits maintain optimal karmic momentum.",
                "kp_system": "Krishnamurti Padhdhati (KP) sub-lord rulers delineate decisive timelines and outcomes for focal life ambitions.",
                "bhrigu_nadi": "Bhrigu Nandi Nadi indicates past-life merit and major planetary conjunctions drive purposeful spiritual and material evolution."
            }
        }
        trad_synthesis = body.get("traditionSynthesis")
        parsed_synthesis_sections = []

        if trad_synthesis:
            if isinstance(trad_synthesis, str):
                trimmed_synth = trad_synthesis.strip()
                loaded = None
                if "```" in trimmed_synth:
                    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', trimmed_synth)
                    if m:
                        trimmed_synth = m.group(1).strip()
                if "{" in trimmed_synth and "}" in trimmed_synth:
                    s_idx = trimmed_synth.find("{")
                    e_idx = trimmed_synth.rfind("}")
                    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
                        candidate_json = trimmed_synth[s_idx:e_idx+1]
                        try:
                            loaded = json.loads(candidate_json)
                        except Exception:
                            if json_repair:
                                try:
                                    loaded = json_repair.loads(candidate_json)
                                except Exception:
                                    pass
                if isinstance(loaded, dict) and "sections" in loaded and isinstance(loaded["sections"], list):
                    parsed_synthesis_sections = loaded["sections"]
            elif isinstance(trad_synthesis, dict) and "sections" in trad_synthesis and isinstance(trad_synthesis["sections"], list):
                parsed_synthesis_sections = trad_synthesis["sections"]

        # Ensure trad_synthesis is never output as raw JSON string
        if parsed_synthesis_sections:
            trad_synthesis = ""
        else:
            if isinstance(trad_synthesis, str) and (trad_synthesis.strip().startswith("{") or "{\"sections\"" in trad_synthesis or "sections" in trad_synthesis):
                lang_dict = tradition_defaults.get(lang, tradition_defaults["en"])
                trad_synthesis = lang_dict.get(tradition, lang_dict.get("parashari", ""))
            elif not trad_synthesis:
                lang_dict = tradition_defaults.get(lang, tradition_defaults["en"])
                trad_synthesis = lang_dict.get(tradition, lang_dict.get("parashari", ""))

        tagline_map = {
            "en": f"Precision Astronomical Ephemeris • Parashari • Jaimini • Lal Kitab • KP • Nadi ({date_str})",
            "hi": f"सटीक खगोलीय पंचांग • पाराशर • जैमिनी • लाल किताब • के.पी. • नाड़ी ({format_localized_digits(date_str, 'hi')})",
            "bn": f"নিখুঁত জ্যোতির্বিজ্ঞানসম্মত পঞ্জিকা • পরাশর • জৈমিনী • লাল কিতাব • কে.পি. • নাড়ী ({format_localized_digits(date_str, 'bn')})",
            "ta": f"துல்லிய வானியல் பஞ்சாங்கம் • பராசர • ஜெமினி • லால் கிதாப் • கே.பி. • நாடி ({date_str})",
            "fr": f"Éphémérides Astronomiques de Précision • Parashari • Jaimini • Lal Kitab • KP • Nadi ({date_str})"
        }

        data = {
            "doc_title": "VEDIC BIRTH CHART & NATAL ANALYSIS" if lang == "en" else resolve_translation("birthChart.pdf.report_title", lang, labels, default="VEDIC BIRTH CHART & NATAL ANALYSIS"),
            "doc_subtitle": trad_title,
            "doc_subtitle_tagline": tagline_map.get(lang, tagline_map["en"]),
            "doc_date": date_str,
            "profile": profile,
            "chartData": chart_data,
            "tradition": tradition,
            "tradition_title": trad_title,
            "tradition_synthesis": trad_synthesis if not parsed_synthesis_sections else "",
            "parsed_synthesis_sections": parsed_synthesis_sections,
            "has_english_fallback": lang != "en" and body.get("isEnglishFallback", False),
        }

        pdf_bytes = render_pdf("birth_chart_pdf.html", lang, data, labels)
        filename = f"AstroJunction_BirthChart_{tradition}_{clean_name}_{date_str}_{lang}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as exc:
        print(f"Error generating Birth Chart PDF: {exc}")
        return jsonify({"status": "error", "message": str(exc), "error_code": "PDF_ERROR"}), 500


