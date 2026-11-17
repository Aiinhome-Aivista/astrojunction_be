import re
import ast
import json
from datetime import datetime
from typing import Dict, Any, List, Tuple

# Supported languages
SUPPORTED_LANGUAGES = ["en", "hi", "bn", "ta", "fr"]

# Unicode script ranges for Indic scripts
RE_BENGALI = re.compile(r'[\u0980-\u09FF]')
RE_DEVANAGARI = re.compile(r'[\u0900-\u097F]')
RE_TAMIL = re.compile(r'[\u0B80-\u0BFF]')
RE_FRENCH_SPECIAL = re.compile(r'[éèêëàâôûùçîïÀÂÉÈÊËÎÏÔÙÛÜÇ]', re.IGNORECASE)

# Common explicit language requests (case-insensitive)
EXPLICIT_LANG_PATTERNS = [
    # English
    (re.compile(r'\b(in english|answer in english|reply in english|speak in english|write in english|ইংরেজিতে|अंग्रेजी में|ஆங்கிலத்தில்)\b', re.IGNORECASE), "en"),
    # Hindi
    (re.compile(r'\b(in hindi|answer in hindi|reply in hindi|speak in hindi|write in hindi|हिंदी में|हिन्दी में|হিন্দিতে|ஹிந்தியில்|en hindi)\b', re.IGNORECASE), "hi"),
    # Bengali
    (re.compile(r'\b(in bengali|in bangla|answer in bengali|reply in bengali|speak in bengali|write in bengali|বাংলায়|বাংলা ভাষায়|বঙ্গভাষায়|बंगला में|வங்காளத்தில்|en bengali)\b', re.IGNORECASE), "bn"),
    # Tamil
    (re.compile(r'\b(in tamil|answer in tamil|reply in tamil|speak in tamil|write in tamil|தமிழில்|தமிழ் மொழியில்|तमिल में|তামিলে|en tamil)\b', re.IGNORECASE), "ta"),
    # French
    (re.compile(r'\b(in french|answer in french|reply in french|speak in french|write in french|en français|en francais|répondez en français|repondez en francais|ফরাসি|फ्रेंच में|பிரெஞ்சு)\b', re.IGNORECASE), "fr"),
]

# Time-based keywords for detecting questions regarding today/transit/current timing
TIME_BASED_PATTERN = re.compile(
    r'\b(today|aaj|ajke|aajke|aajker|din|day|daily|current|transit|gochara|transits|week|month|year|'
    r'আজ|আজকে|আজকের|দিন|আজকের দিন|চলতি|গোচর|বর্তমান|'
    r'आज|आजका|आज का|दिन|गोचर|वर्तमान|चालू|'
    r'இன்று|இன்றைய|தற்போதைய|கோச்சாரம்|நாள்|'
    r'aujourd\'hui|actuel|transit|journée|jour)\b',
    re.IGNORECASE
)


def resolve_target_language(prompt: str, ui_lang: str = "en") -> str:
    """
    Language Resolution Rules:
    1. Explicit user request for a language -> that language.
    2. Message in one of 5 languages (en, hi, bn, ta, fr) in its own native script -> that language.
    3. Roman-letter text (Banglish, Hinglish, Tanglish) -> selected UI language.
    4. Otherwise -> selected UI language.
    """
    clean_prompt = (prompt or "").strip()
    normalized_ui = (ui_lang or "en").strip().lower()[:2]
    if normalized_ui not in SUPPORTED_LANGUAGES:
        normalized_ui = "en"

    if not clean_prompt:
        return normalized_ui

    # 1. Check explicit language directives
    for pattern, lang_code in EXPLICIT_LANG_PATTERNS:
        if pattern.search(clean_prompt):
            return lang_code

    # 2. Check native script presence
    bn_count = len(RE_BENGALI.findall(clean_prompt))
    hi_count = len(RE_DEVANAGARI.findall(clean_prompt))
    ta_count = len(RE_TAMIL.findall(clean_prompt))

    if bn_count >= 2:
        return "bn"
    if hi_count >= 2:
        return "hi"
    if ta_count >= 2:
        return "ta"

    # French accents check if ui_lang is french or strong french indicator
    if RE_FRENCH_SPECIAL.search(clean_prompt):
        return "fr"

    # French common conversational words
    french_words = re.compile(r'\b(bonjour|merci|est-ce|pourquoi|quand|dans ma vie|maison|thème astral|soleil|lune|comment|amour|santé|travail)\b', re.IGNORECASE)
    if french_words.search(clean_prompt):
        return "fr"

    # 3. Roman-letter text (Banglish, Hinglish, Tanglish, English) -> follows selected UI language
    return normalized_ui


def build_ground_truth_context(
    profile: Dict[str, Any],
    chart_data: Dict[str, Any],
    numerology: Dict[str, Any],
    prompt: str,
    tradition: str = "parashari"
) -> Tuple[str, bool]:
    """
    Builds structured, factual astrological ground truth context.
    Detects time-based queries and enriches with today's ephemeris panchang and transit data.
    """
    lines = []
    
    # User Profile
    full_name = profile.get("fullName") or profile.get("name") or "User"
    gender = profile.get("gender") or "Not specified"
    birth_date = profile.get("birthDate") or profile.get("dob") or "Not specified"
    birth_time = profile.get("birthTime") or profile.get("tob") or "Not specified"
    birth_place = profile.get("birthPlace") or profile.get("pob") or "Not specified"
    lines.append(f"- Native Name: {full_name}")
    lines.append(f"- Birth Details: Date: {birth_date}, Time: {birth_time}, Place: {birth_place}, Gender: {gender}")

    # Natal Ascendant / Lagna
    asc_info = chart_data.get("ascendant") or {}
    if isinstance(asc_info, dict):
        lagna_sign = asc_info.get("signName") or asc_info.get("sign") or "Unknown"
        lagna_deg = asc_info.get("degreeFormatted") or f"{asc_info.get('degree', '')}°"
        lagna_nak = asc_info.get("nakshatra") or "Unknown"
        lines.append(f"- Janma Lagna (Ascendant): {lagna_sign} ({lagna_deg}) in Nakshatra {lagna_nak}")
    elif isinstance(asc_info, (str, int, float)):
        lines.append(f"- Janma Lagna (Ascendant): {asc_info}")

    # Planets (Moon Sign, Sun Sign, etc.)
    planets = chart_data.get("planets") or []
    moon_sign, moon_nak = "Unknown", "Unknown"
    planet_summaries = []
    if isinstance(planets, list):
        for p in planets:
            if not isinstance(p, dict):
                continue
            p_name = p.get("name") or p.get("planet") or ""
            p_sign = p.get("signName") or p.get("sign") or p.get("rashi") or ""
            p_deg = p.get("degreeFormatted") or (f"{p.get('degree'):.2f}°" if isinstance(p.get("degree"), (int, float)) else "")
            p_house = p.get("house") or p.get("bhava") or ""
            p_nak = p.get("nakshatra") or ""
            retro = " [Retrograde]" if p.get("isRetrograde") or p.get("retrograde") else ""

            if p_name.lower() == "moon":
                moon_sign = p_sign
                moon_nak = p_nak
            
            p_str = f"{p_name}: {p_sign} (House {p_house}, {p_deg}{retro}, Nakshatra: {p_nak})"
            planet_summaries.append(p_str)

    lines.append(f"- Janma Rashi (Moon Sign): {moon_sign} (Nakshatra: {moon_nak})")
    if planet_summaries:
        lines.append("- Natal Planetary Placements:")
        for ps in planet_summaries[:10]:
            lines.append(f"    • {ps}")

    # Current Dasha (Mahadasha & Antardasha)
    dasha_info = chart_data.get("dasha") or chart_data.get("dashas") or {}
    curr_dasha = {}
    if isinstance(dasha_info, dict):
        curr_dasha = dasha_info.get("current") or dasha_info.get("active") or {}
    if curr_dasha:
        md = curr_dasha.get("mahadasha") or curr_dasha.get("major") or "Unknown"
        ad = curr_dasha.get("antardasha") or curr_dasha.get("minor") or "Unknown"
        pd = curr_dasha.get("pratyantardasha") or curr_dasha.get("sub_minor") or ""
        s_date = curr_dasha.get("startDate") or curr_dasha.get("start") or ""
        e_date = curr_dasha.get("endDate") or curr_dasha.get("end") or ""
        dasha_line = f"- Current Vimshottari Dasha: {md} Mahadasha / {ad} Antardasha"
        if pd:
            dasha_line += f" / {pd} Pratyantardasha"
        if s_date or e_date:
            dasha_line += f" (Period: {s_date} to {e_date})"
        lines.append(dasha_line)
    else:
        lines.append("- Current Vimshottari Dasha: Active Dasha computed in chart")

    # Manglik Status
    manglik_info = chart_data.get("manglik") or {}
    if isinstance(manglik_info, dict):
        is_manglik = manglik_info.get("isManglik", False)
        status_str = "Present" if is_manglik else "Not Present (Non-Manglik)"
        severity = manglik_info.get("severity") or ("Moderate" if is_manglik else "None")
        cancellation = manglik_info.get("cancellation") or manglik_info.get("isCancelled", False)
        cancel_str = f" [Cancelled: {manglik_info.get('cancellationReason', 'Yes')}]" if cancellation else ""
        lines.append(f"- Manglik Dosha: {status_str} (Severity: {severity}{cancel_str})")
    else:
        lines.append(f"- Manglik Dosha: {manglik_info}")

    # Yogas & Doshas
    yogas = chart_data.get("yogas") or []
    if yogas and isinstance(yogas, list):
        yoga_names = [y.get("name") if isinstance(y, dict) else str(y) for y in yogas[:5]]
        lines.append(f"- Key Natal Yogas: {', '.join(yoga_names)}")
    
    doshas = chart_data.get("doshas") or []
    if doshas and isinstance(doshas, list):
        dosha_names = [d.get("name") if isinstance(d, dict) else str(d) for d in doshas[:5]]
        lines.append(f"- Natal Dosha Considerations: {', '.join(dosha_names)}")

    # Numerology
    if numerology and isinstance(numerology, dict):
        mulank = numerology.get("mulank") or numerology.get("rootNumber") or "1"
        bhagyank = numerology.get("bhagyank") or numerology.get("destinyNumber") or "1"
        lucky_nums = numerology.get("luckyNumbers") or [mulank]
        lucky_colors = numerology.get("luckyColors") or ["Gold", "Yellow"]
        lines.append(f"- Numerology: Mulank (Life Path): {mulank}, Bhagyank (Destiny): {bhagyank}")
        lines.append(f"- Auspicious Numbers: {', '.join(str(n) for n in lucky_nums)}, Colors: {', '.join(str(c) for c in lucky_colors)}")

    # Time-based panchang & transits check
    is_time_based = bool(TIME_BASED_PATTERN.search(prompt))
    if is_time_based:
        try:
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            from services.ephemeris_service import get_day_stable_panchang_facts
            lat = float(profile.get("latitude") or 28.6139)
            lon = float(profile.get("longitude") or 77.2090)
            tz = float(profile.get("timezone") or 5.5)
            mulank_val = int(numerology.get("mulank", 1)) if numerology else 1

            day_facts = get_day_stable_panchang_facts(today_str, lat, lon, tz, mulank_val)
            lines.append("\n--- TODAY'S EPHEMERIS PANCHANG & TRANSIT GROUND TRUTH ---")
            lines.append(f"- Ephemeris Date: {today_str}")
            lines.append(f"- Sunrise Ascendant (Gochara Lagna at sunrise): {day_facts.get('sunriseAscendant')}")
            lines.append(f"- Sunrise Tithi: {day_facts.get('tithiName')}")
            lines.append(f"- Sunrise Nakshatra: {day_facts.get('nakshatraName')}")
            timings = day_facts.get("timings") or {}
            if timings:
                lines.append(f"- Auspicious Timings: Sunrise {timings.get('sunrise')}, Sunset {timings.get('sunset')}, Abhijit Muhurta {timings.get('abhijitStart', '')}-{timings.get('abhijitEnd', '')}")
                lines.append(f"- Rahu Kalam (Avoid Major Beginnings): {timings.get('rahuStart', '')}-{timings.get('rahuEnd', '')}")
        except Exception as e:
            lines.append(f"- Ephemeris Transit Context: Date {datetime.utcnow().strftime('%Y-%m-%d')}")

    return "\n".join(lines), is_time_based


def get_language_system_directive(target_lang: str) -> str:
    """
    Returns authentic script and glossary directives per language.
    Includes strict instruction to ignore previous turn language bias.
    """
    lang_names = {
        "en": "English",
        "hi": "Hindi (Devanagari script)",
        "bn": "Bengali (Bengali script)",
        "ta": "Tamil (Tamil script)",
        "fr": "French"
    }
    lang_name = lang_names.get(target_lang, "English")

    base = f"""LANGUAGE & SCRIPT STRICT DIRECTIVE:
You MUST respond EXCLUSIVELY and natively in {lang_name}.
CRITICAL: Even if the user's previous questions or previous conversation turns below were in another language (e.g. English, French, Bengali, Tamil, etc.), you MUST switch immediately and write your entire current answer and ALL follow-up questions in {lang_name}. Never continue in the previous turn's language."""

    specifics = {
        "en": (
            "Write natively in dignified, empathetic, scholarly English. "
            "Use standard Vedic terms (e.g. Lagna, Mahadasha, Nakshatra, Rashi, Upaya) naturally."
        ),
        "hi": (
            "Respond PURELY and natively in formal-polite Hindi using Devanagari script (हिंदी लिपि). "
            "Even if the user wrote in Roman-letter Hinglish or English, you MUST respond in authentic Hindi script. "
            "Use classical Jyotish terminology: लग्न (Lagna), चंद्र राशि (Moon Sign), महादशा (Mahadasha), अंतर्दशा (Antardasha), "
            "मांगलिक (Manglik), उपाय एवं साधना (Upayas). Do NOT transliterate English words into Roman letters."
        ),
        "bn": (
            "Respond PURELY and natively in formal-polite standard Bengali using Bengali script (বাংলা লিপি). "
            "Even if the user wrote in Roman-letter Banglish or English, you MUST respond in authentic Bengali script. "
            "Use classical Jyotish terminology: লগ্ন (Lagna), চন্দ্র রাশি (Moon Sign), মহাদশা (Mahadasha), অন্তর্দশা (Antardasha), "
            "মাঙ্গলিক (Manglik), প্রতিকার ও সাধনা (Upayas). Do NOT transliterate English signs (write তুলা, not 'লিব্রা')."
        ),
        "ta": (
            "Respond PURELY and natively in formal-polite standard Tamil using Tamil script (தமிழ் எழுத்துரு). "
            "Even if the user wrote in Roman-letter Tanglish or English, you MUST respond in authentic Tamil script. "
            "Use classical Jyotish terminology: லக்னம் (Lagna), சந்திர ராசி (Moon Sign), மகாதிசை (Mahadasha), அந்தர்திசை (Antardasha), "
            "பரிகாரம் (Upaya). Do NOT repeat sentences or loop phrases."
        ),
        "fr": (
            "Respond PURELY and natively in elegant, formal French with correct accents (é, è, ê, à, ç, etc.). "
            "Translate astrological concepts into refined French (e.g. Ascendant, Signe Lunaire, Période Mahadasha, Éléments, Maisons). "
            "Never mix Indic scripts in a French response."
        ),
    }
    return f"{base}\n{specifics.get(target_lang, specifics['en'])}"


def build_chat_system_prompt(
    ground_truth_context: str,
    target_lang: str,
    tradition: str = "parashari"
) -> str:
    lang_directive = get_language_system_directive(target_lang)

    system_prompt = f"""You are the AstroJunction Daivajna, a revered Vedic astrology counsellor.
You are providing personal, grounded astrological guidance directly based on the user's authentic calculated natal chart and ephemeris.

{lang_directive}

CRITICAL GROUND TRUTH RULES:
1. The user's chart data provided below is 100% computed ground truth:
{ground_truth_context}
2. NEVER ask the user for data you already have (birth date, birth time, place, Lagna, Moon sign, current Dasha, etc.).
3. NEVER invent or hallucinate different signs, houses, nakshatras, dashas, or dates.
4. NEVER contradict the user's computed chart data. Quote the exact Lagna, Moon sign, or current Mahadasha/Antardasha when relevant.
5. If the user asks about today or transits, distinguish Janma Lagna (natal ascendant) from the Sunrise Ascendant (Gochara Lagna at sunrise).

EDITORIAL & QUALITY RULES:
1. Practical, empathetic, specific to the user's chart, organized in short, readable paragraphs.
2. Guidance and tendencies only: NEVER make absolute fatalistic claims, never use fear language, never provide medical diagnoses or legal/financial guarantees. Offer simple, sattvic Vedic remedies/upayas (e.g. Surya Arghya, mantra chanting, acts of charity) when helpful.
3. If the user asks an off-topic question (e.g. general programming, politics, or stock speculation), politely guide them with authentic Daivajna boundary in {target_lang}, explaining your sacred role as an astrological counselor for life and soul tendencies, and provide relevant astrological follow-up questions.
4. OUTPUT FORMAT: You MUST reply ONLY with a valid JSON object matching this schema, without code fences or any outer markdown:
{{
  "answer": "Your detailed, compassionate answer string in {target_lang}",
  "follow_ups": [
    "Relevant follow-up question 1?",
    "Relevant follow-up question 2?",
    "Relevant follow-up question 3?"
  ]
}}
- "answer": MUST be a single string (not a nested dictionary or object).
- "follow_ups": At most 3 items, each a genuine question (8 to 120 characters), in the EXACT same language and script as the answer. No prefixes like 'Ask:', no JSON quotes or brackets inside strings.
"""
    return system_prompt


def validate_and_filter_follow_ups(follow_ups: Any, target_lang: str) -> List[str]:
    """
    Validates and cleans follow-up questions according to strict rules:
    - At most 3
    - 8 to 120 characters
    - No JSON punctuation or prefixes like 'Ask:'
    - Unique
    - Must match target language script
    """
    if not isinstance(follow_ups, list):
        return []

    cleaned = []
    seen = set()

    for item in follow_ups:
        if not isinstance(item, str):
            continue
        text = item.strip()
        # Remove common prefixes
        text = re.sub(r'^(Ask\s*:|Q\s*:|Question\s*:|\d+[\.\)]|\-\s*|\*\s*)', '', text, flags=re.IGNORECASE).strip()
        # Remove unwanted punctuation
        text = text.replace('{', '').replace('}', '').replace('[', '').replace(']', '').replace('"', '').replace('`', '').strip()

        if len(text) < 8 or len(text) > 120:
            continue

        # Check script consistency
        if target_lang == "hi" and not RE_DEVANAGARI.search(text):
            continue
        if target_lang == "bn" and not RE_BENGALI.search(text):
            continue
        if target_lang == "ta" and not RE_TAMIL.search(text):
            continue

        normalized_key = text.lower()
        if normalized_key in seen:
            continue

        seen.add(normalized_key)
        cleaned.append(text)
        if len(cleaned) >= 3:
            break

    return cleaned


def _extract_text_from_answer_obj(val: Any) -> str:
    """
    Safely extracts clean string from string, list, or nested dictionary.
    """
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return "\n\n".join(str(x).strip() for x in val if str(x).strip())
    if isinstance(val, dict):
        parts = []
        for v in val.values():
            if isinstance(v, (str, list, dict)):
                extracted = _extract_text_from_answer_obj(v)
                if extracted:
                    parts.append(extracted)
        return "\n\n".join(parts) if parts else ""
    return str(val).strip() if val else ""


def parse_and_repair_chat_response(raw_text: str, target_lang: str) -> Tuple[str, List[str]]:
    """
    Safely parses JSON response from LLM with ast fallback, single-step repair, and clean plain text fallback.
    Guarantees no raw JSON, code fences, braces, or 'answer' key in the final answer.
    """
    if not raw_text:
        return "", []

    text = raw_text.strip()

    # Step 1: Strip markdown code blocks
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Step 2: Extract JSON candidate
    first_brace = text.find("{")
    last_brace = text.rfind("}")

    parsed = None
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace:last_brace + 1]
        try:
            parsed = json.loads(candidate)
        except Exception:
            # Try Python dict literal parsing (handles single quotes: {'answer': ...})
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                # Step 3: Attempt safe regex repair for unescaped newlines and trailing commas
                repaired = re.sub(r'(?<!\\)\n', r'\\n', candidate)
                repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                try:
                    parsed = json.loads(repaired)
                except Exception:
                    try:
                        parsed = ast.literal_eval(repaired)
                    except Exception:
                        parsed = None

    if isinstance(parsed, dict):
        raw_ans = parsed.get("answer") or parsed.get("response") or parsed.get("content") or ""
        clean_answer = _extract_text_from_answer_obj(raw_ans)

        raw_fu = parsed.get("follow_ups") or parsed.get("suggested_questions") or parsed.get("suggestions") or []
        clean_follow_ups = validate_and_filter_follow_ups(raw_fu, target_lang)
        
        if clean_answer:
            # Ensure no stray outer quotes or braces remain
            clean_answer = clean_answer.strip()
            return clean_answer, clean_follow_ups

    # Step 4: Fallback to clean plain text (completely strip any JSON artifacts)
    plain_text = text
    # Strip leading json keys: {"answer": or "answer": or {'answer':
    plain_text = re.sub(r'^\s*\{\s*["\']?(?:answer|response)["\']?\s*:\s*["\']?', '', plain_text)
    # Strip trailing follow_ups block
    plain_text = re.sub(r'["\']?\s*,\s*["\']?(?:follow_ups|suggested_questions)["\']?\s*:.*$', '', plain_text, flags=re.DOTALL)
    # Strip leading/trailing braces, brackets, and quotes
    plain_text = re.sub(r'^[\{\}\[\]"\']+', '', plain_text)
    plain_text = re.sub(r'[\{\}\[\]"\']+$', '', plain_text)
    # Remove any leftover literal "answer": prefixes
    plain_text = re.sub(r'^["\']?answer["\']?\s*:\s*', '', plain_text, flags=re.IGNORECASE)
    plain_text = plain_text.strip()

    return plain_text, []
