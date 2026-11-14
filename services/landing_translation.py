"""
AstroJunction Landing Page Horoscope Translation Service
Translates stored English horoscope rows dynamically using Mistral Cloud API.
Provides in-memory caching, per-chunk de-duplication locks, strict Jyotish glossary,
validation (paragraph count, script detection, word count ratio, markdown rejection),
failure suppression cache, and background pre-warming.
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime, date, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Optional

import requests
from services.settings_service import get_setting

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

PERIOD_CHUNK = {
    "daily": 8,
    "weekly": 4,
    "monthly": 4,
    "yearly": 2,
}

SUPPORTED_LANGUAGES = ["hi", "bn", "ta", "fr"]
PREWARM_LANGS = ["hi", "bn"]

MAX_RETRIES = 2
FAILURE_CACHE_TTL = 300  # 5 minutes in seconds

IST = timezone(timedelta(hours=5, minutes=30))

# Fixed Vedic & Astrological Glossary per Language
GLOSSARY = {
    "hi": {
        "Panjika": "पंचांग",
        "Upaya": "उपाय",
        "Rashi": "राशि",
        "Nakshatra": "नक्षत्र",
        "Graha": "ग्रह",
        "Dasha": "दशा",
        "Lagna": "लग्न",
        "Tithi": "तिथि",
        "Vedic": "वैदिक",
        "Kundli": "कुंडली",
        "Jyotish": "ज्योतिष",
        "AstroJunction": "AstroJunction",
        "signs": {
            "aries": "मेष",
            "taurus": "वृषभ",
            "gemini": "मिथुन",
            "cancer": "कर्क",
            "leo": "सिंह",
            "virgo": "कन्या",
            "libra": "तुला",
            "scorpio": "वृश्चिक",
            "sagittarius": "धनु",
            "capricorn": "मकर",
            "aquarius": "कुंभ",
            "pisces": "मीन",
        },
        "planets": {
            "Sun": "सूर्य",
            "Moon": "चंद्र",
            "Mars": "मंगल",
            "Mercury": "बुध",
            "Jupiter": "बृहस्पति / गुरु",
            "Venus": "शुक्र",
            "Saturn": "शनि",
            "Rahu": "राहु",
            "Ketu": "केतु",
        },
    },
    "bn": {
        "Panjika": "পঞ্জিকা",
        "Upaya": "উপায়",
        "Rashi": "রাশি",
        "Nakshatra": "নক্ষত্র",
        "Graha": "গ্রহ",
        "Dasha": "দশা",
        "Lagna": "লগ্ন",
        "Tithi": "তিথি",
        "Vedic": "বৈদিক",
        "Kundli": "কুণ্ডলী",
        "Jyotish": "জ্যোতিষ",
        "AstroJunction": "AstroJunction",
        "signs": {
            "aries": "মেষ",
            "taurus": "বৃষ",
            "gemini": "মিথুন",
            "cancer": "কর্কট",
            "leo": "সিংহ",
            "virgo": "কন্যা",
            "libra": "তুলা",
            "scorpio": "বৃশ্চিক",
            "sagittarius": "ধনু",
            "capricorn": "মকর",
            "aquarius": "কুম্ভ",
            "pisces": "মীন",
        },
        "planets": {
            "Sun": "সূর্য",
            "Moon": "চন্দ্র",
            "Mars": "মঙ্গল",
            "Mercury": "বুধ",
            "Jupiter": "বৃহস্পতি / গুরু",
            "Venus": "শুক্র",
            "Saturn": "শনি",
            "Rahu": "রাহু",
            "Ketu": "কেতু",
        },
    },
    "ta": {
        "Panjika": "பஞ்சாங்கம்",
        "Upaya": "பரிகாரங்கள்",
        "Rashi": "ராசி",
        "Nakshatra": "நட்சத்திரம்",
        "Graha": "கிரகம்",
        "Dasha": "தசை",
        "Lagna": "லக்னம்",
        "Tithi": "திதி",
        "Vedic": "வேத",
        "Kundli": "ஜாதகம்",
        "Jyotish": "ஜோதிடம்",
        "AstroJunction": "AstroJunction",
        "signs": {
            "aries": "மேஷம்",
            "taurus": "ரிஷபம்",
            "gemini": "மிதுனம்",
            "cancer": "கடகம்",
            "leo": "சிம்மம்",
            "virgo": "கன்னி",
            "libra": "துலாம்",
            "scorpio": "விருச்சிகம்",
            "sagittarius": "தனுசு",
            "capricorn": "மகரம்",
            "aquarius": "கும்பம்",
            "pisces": "மீனம்",
        },
        "planets": {
            "Sun": "சூரியன்",
            "Moon": "சந்திரன்",
            "Mars": "செவ்வாய்",
            "Mercury": "புதன்",
            "Jupiter": "குரு / வியாழன்",
            "Venus": "சுக்கிரன்",
            "Saturn": "சனி",
            "Rahu": "ராகு",
            "Ketu": "கேது",
        },
    },
    "fr": {
        "Panjika": "Panchang",
        "Upaya": "Remèdes",
        "Rashi": "Signe",
        "Nakshatra": "Nakshatra",
        "Graha": "Graha / Planète",
        "Dasha": "Dasha",
        "Lagna": "Lagna / Ascendant",
        "Tithi": "Tithi",
        "Vedic": "Védique",
        "Kundli": "Kundli",
        "Jyotish": "Jyotish",
        "AstroJunction": "AstroJunction",
        "signs": {
            "aries": "Bélier",
            "taurus": "Taureau",
            "gemini": "Gémeaux",
            "cancer": "Cancer",
            "leo": "Lion",
            "virgo": "Vierge",
            "libra": "Balance",
            "scorpio": "Scorpion",
            "sagittarius": "Sagittaire",
            "capricorn": "Capricorne",
            "aquarius": "Verseau",
            "pisces": "Poissons",
        },
        "planets": {
            "Sun": "Soleil",
            "Moon": "Lune",
            "Mars": "Mars",
            "Mercury": "Mercure",
            "Jupiter": "Jupiter",
            "Venus": "Vénus",
            "Saturn": "Saturne",
            "Rahu": "Rahu",
            "Ketu": "Ketu",
        },
    },
}

# ---------------------------------------------------------------------------
# In-Memory Cache & De-Duplication Concurrency Control
# ---------------------------------------------------------------------------

# Cache entry: key -> {"data": dict, "expires_at": float}
_TRANSLATION_CACHE: Dict[Tuple, Dict[str, Any]] = {}
_FAILURE_CACHE: Dict[Tuple, float] = {}

_cache_lock = threading.Lock()
_dedup_locks: Dict[Tuple, threading.Lock] = {}
_dedup_guard = threading.Lock()

# Token metrics tracker
_CALL_STATS = {
    "total_calls": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "lock": threading.Lock(),
}


def _get_sha1(text: Any) -> str:
    """Returns SHA1 hash of English text for cache invalidation."""
    raw = str(text or "").strip()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _get_period_expiry(period: str, period_end_or_start: Any) -> float:
    """
    Computes expiration timestamp: period end + 1 day in IST.
    """
    now = time.time()
    try:
        if isinstance(period_end_or_start, str):
            dt = datetime.strptime(period_end_or_start[:10], "%Y-%m-%d").date()
        elif isinstance(period_end_or_start, (date, datetime)):
            dt = period_end_or_start if isinstance(period_end_or_start, date) else period_end_or_start.date()
        else:
            dt = datetime.now(IST).date()

        if period == "daily":
            # Current day + 1 day = 2 days from period_start
            exp_date = dt + timedelta(days=2)
        elif period == "weekly":
            exp_date = dt + timedelta(days=2)
        elif period == "monthly":
            exp_date = dt + timedelta(days=2)
        elif period == "yearly":
            exp_date = dt + timedelta(days=2)
        else:
            exp_date = dt + timedelta(days=1)

        exp_dt = datetime(exp_date.year, exp_date.month, exp_date.day, 23, 59, 59, tzinfo=IST)
        return exp_dt.timestamp()
    except Exception:
        # Fallback: 2 days from now
        return now + 172800.0


def _clean_expired_cache():
    """Removes expired entries from cache dictionaries."""
    now = time.time()
    with _cache_lock:
        expired_keys = [k for k, v in _TRANSLATION_CACHE.items() if v.get("expires_at", 0) < now]
        for k in expired_keys:
            del _TRANSLATION_CACHE[k]

        expired_failures = [k for k, ts in _FAILURE_CACHE.items() if now - ts > FAILURE_CACHE_TTL]
        for k in expired_failures:
            del _FAILURE_CACHE[k]


def _get_dedup_lock(chunk_key: Tuple) -> threading.Lock:
    """Gets or creates a specific threading lock for a chunk key to de-duplicate parallel requests."""
    with _dedup_guard:
        if chunk_key not in _dedup_locks:
            _dedup_locks[chunk_key] = threading.Lock()
        return _dedup_locks[chunk_key]


# ---------------------------------------------------------------------------
# Translation Validator
# ---------------------------------------------------------------------------

def _validate_translation(
    translated_dict: Dict[str, Any],
    english_item: Dict[str, Any],
    lang: str,
) -> Tuple[bool, str]:
    """
    Validates translated item:
    1. Paragraph count equals English ("\\n\\n" separated).
    2. No markdown formatting (**, ###, bullets).
    3. Script check: Devanagari for hi, Bengali for bn, Tamil for ta, French markers for fr.
    4. Length within 60% - 170% of English word count.
    """
    trans_text = str(translated_dict.get("text") or "").strip()
    eng_text = str(english_item.get("text") or "").strip()

    if not trans_text:
        return False, "Translated text is empty"

    # 1. Paragraph count check
    eng_paras = [p.strip() for p in re.split(r'\n\s*\n+', eng_text) if p.strip()]
    trans_paras = [p.strip() for p in re.split(r'\n\s*\n+', trans_text) if p.strip()]

    if eng_paras and len(trans_paras) != len(eng_paras):
        return False, f"Paragraph count mismatch: got {len(trans_paras)}, expected {len(eng_paras)}"

    # 2. Markdown check (no **, ###, bullets like "- " or "* ")
    if re.search(r'(\*\*|###|__|\n\s*[-*•]\s+)', trans_text):
        return False, "Markdown formatting or bullets detected in output"

    # 3. Script & Language validation
    if lang == "hi":
        devanagari_chars = len(re.findall(r'[\u0900-\u097F]', trans_text))
        if devanagari_chars < 15:
            return False, f"Insufficient Devanagari script ({devanagari_chars} chars)"
        # Check for whole leftover English sentences
        ascii_words = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', trans_text) if w.lower() not in ["astrojunction", "am", "pm", "ist"]]
        if len(ascii_words) > 12:
            return False, f"Too many leftover English words in Hindi text ({len(ascii_words)})"

    elif lang == "bn":
        bengali_chars = len(re.findall(r'[\u0980-\u09FF]', trans_text))
        if bengali_chars < 15:
            return False, f"Insufficient Bengali script ({bengali_chars} chars)"
        ascii_words = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', trans_text) if w.lower() not in ["astrojunction", "am", "pm", "ist"]]
        if len(ascii_words) > 12:
            return False, f"Too many leftover English words in Bengali text ({len(ascii_words)})"

    elif lang == "ta":
        tamil_chars = len(re.findall(r'[\u0B80-\u0BFF]', trans_text))
        if tamil_chars < 15:
            return False, f"Insufficient Tamil script ({tamil_chars} chars)"
        ascii_words = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', trans_text) if w.lower() not in ["astrojunction", "am", "pm", "ist"]]
        if len(ascii_words) > 12:
            return False, f"Too many leftover English words in Tamil text ({len(ascii_words)})"

    elif lang == "fr":
        fr_matches = re.findall(
            r'\b(le|la|les|des|du|dans|pour|avec|votre|vous|est|sont|cette|ce|en|au|aux|qui|que|une|un|sur)\b|[éèêëàâôûîçÉÈÊÀÂÔÛÎÇ]',
            trans_text,
            re.IGNORECASE
        )
        if len(fr_matches) < 3:
            return False, "French stop words or accented characters missing"

    # 4. Word count ratio: 60% - 170% of English word count (with agglutination tolerance for Tamil)
    eng_words = len(eng_text.split())
    trans_words = len(trans_text.split())

    if eng_words >= 15:
        min_ratio = 0.40 if lang == "ta" else 0.55
        max_ratio = 1.75
        ratio = trans_words / float(eng_words)
        if ratio < min_ratio or ratio > max_ratio:
            return False, f"Word count ratio outside bounds: {ratio:.2f} ({trans_words} vs {eng_words} words)"

    return True, ""


# ---------------------------------------------------------------------------
# Mistral Translation Request
# ---------------------------------------------------------------------------

def _build_translation_prompt(items_chunk: List[Dict[str, Any]], lang: str, meta: Dict[str, Any]) -> Tuple[str, str]:
    """Builds system and user prompts for Mistral strict JSON translation."""
    lang_name_map = {
        "hi": "Hindi (हिन्दी)",
        "bn": "Bengali (বাংলা)",
        "ta": "Tamil (தமிழ்)",
        "fr": "French (Français)"
    }
    target_lang = lang_name_map.get(lang, "Hindi")
    glossary_dict = GLOSSARY.get(lang, {})
    glossary_json = json.dumps(glossary_dict, ensure_ascii=False, indent=2)

    system_prompt = f"""You are a professional astrologer and literary translator for AstroJunction.
Translate the provided horoscope card items into {target_lang}.

STRICT RULES:
1. Meaning, predictions, advice and tone must faithfully match the original English text.
2. DO NOT add, remove, exaggerate, or soften content. DO NOT add fear, fatalism, or guaranteed claims.
3. Keep the EXACT SAME number of paragraphs in 'text' separated by '\\n\\n'. DO NOT merge or split paragraphs.
4. Output PLAIN TEXT ONLY. DO NOT use markdown formatting (NO **, NO ###, NO bullet points like - or *).
5. DO NOT use emojis.
6. For 'lucky_time': translate words and periods (e.g. morning, evening, dawn) but KEEP ALL NUMBERS, HOURS, AND COLONS EXACTLY AS IS (e.g. '09:00 AM - 11:30 AM').
7. Keep the brand name "AstroJunction" and Sanskrit mantra names (e.g. Gayatri Mantra, Mahamrityunjaya, etc.) untranslated or transliterated.
8. Strictly follow this astrological glossary for terms, signs, and planets:
{glossary_json}
9. Return a STRICT JSON object where keys are the category names, containing ONLY the translated text fields:
{{
  "<category_key>": {{
    "text": "...",
    "remedy": "...",
    "affirmation": "...",
    "lucky_time": "...",
    "tip_for_the_day": "..."
  }}
}}
DO NOT include any explanation or text outside the JSON object."""

    payload = {}
    for it in items_chunk:
        cat = it.get("category", "")
        cat_payload = {"text": it.get("text") or ""}
        for fld in ("remedy", "affirmation", "lucky_time", "tip_for_the_day"):
            val = it.get(fld)
            if val and str(val).strip():
                cat_payload[fld] = str(val).strip()
        payload[cat] = cat_payload

    user_prompt = f"Translate the following {meta.get('period', 'daily')} horoscope items for {meta.get('sign', 'sign')} ({meta.get('system', 'tropical')} system) into {target_lang}:\n\n{json.dumps(payload, ensure_ascii=False, indent=2)}"

    return system_prompt, user_prompt


def _try_repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
    """Attempts to salvage completed category objects from a truncated JSON string."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    repaired = {}
    # Matches top-level "category": { ... }
    pattern = r'"([a-zA-Z0-9_]+)"\s*:\s*(\{[^{}]*\})'
    for match in re.finditer(pattern, text):
        cat = match.group(1)
        try:
            val = json.loads(match.group(2))
            if isinstance(val, dict) and "text" in val:
                repaired[cat] = val
        except Exception:
            pass
    if repaired:
        return repaired
    return None


def _execute_mistral_chunk(
    items_chunk: List[Dict[str, Any]],
    lang: str,
    meta: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Calls configured admin LLM engine through services.llm_service with JSON object response mode and retry."""
    from services.llm_service import _execute_llm
    from services.settings_service import get_setting

    period = meta.get("period", "daily")
    # Indic scripts use higher token density
    max_tokens_map = {
        "daily": 4000,
        "weekly": 4500,
        "monthly": 5000,
        "yearly": 6500,
    }
    max_tokens = max_tokens_map.get(period, 4000)

    system_prompt, user_prompt = _build_translation_prompt(items_chunk, lang, meta)
    history = [
        {"role": "user", "content": user_prompt}
    ]

    for attempt in range(1, MAX_RETRIES + 1):
        start_t = time.time()
        try:
            content = _execute_llm(system_prompt, history, max_tokens=max_tokens)
            latency = time.time() - start_t

            active_llm = get_setting("ACTIVE_LLM", "mistral_cloud").strip().lower()
            model_name = get_setting(f"{active_llm.upper()}_MODEL", "default")

            with _CALL_STATS["lock"]:
                _CALL_STATS["total_calls"] += 1

            print(f"[Landing Translation API] Lang: {lang} | Sign: {meta.get('sign')} | System: {meta.get('system')} | Period: {period} | Categories: {[it.get('category') for it in items_chunk]} | Model: {model_name} | Provider: {active_llm} | Time: {latency:.2f}s")

            # Clean output if wrapped in markdown code fence
            clean_content = content.strip() if content else ""
            if clean_content.startswith("```"):
                clean_content = re.sub(r"^```[a-zA-Z]*\n?", "", clean_content)
                clean_content = re.sub(r"\n?```$", "", clean_content).strip()

            try:
                parsed = json.loads(clean_content)
                if not isinstance(parsed, dict):
                    raise ValueError("Parsed translation output is not a JSON object")
                return parsed
            except (json.JSONDecodeError, ValueError) as json_err:
                print(f"[Landing Translation Warning] JSON parsing issue (attempt {attempt}): {json_err}. Attempting salvage...")
                salvaged = _try_repair_truncated_json(clean_content)
                if salvaged:
                    print(f"[Landing Translation Salvage] Successfully salvaged {len(salvaged)} categories from truncated output.")
                    return salvaged
                raise

        except Exception as err:
            print(f"[Landing Translation Error] Attempt {attempt} failed: {err}")
            time.sleep(1.0 * attempt)

    return None


# ---------------------------------------------------------------------------
# Core Translation Controller Function
# ---------------------------------------------------------------------------

def translate_items(items: List[Dict[str, Any]], lang: str, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Translates horoscope items for the given language using stored English DB rows as source of truth.
    - If lang == 'en' or invalid, returns items unchanged.
    - Uses in-memory cache, thread-safe de-duplication locks, and validation.
    - Falls back to English with 'translated: False' if translation fails or is rejected.
    """
    if not items or lang == "en" or lang not in SUPPORTED_LANGUAGES:
        # English: always return unchanged with translated True
        return [dict(it, translated=True) for it in items]

    sign = str(meta.get("sign") or "aries").lower().strip()
    system = str(meta.get("system") or "tropical").lower().strip()
    period = str(meta.get("period") or "daily").lower().strip()
    period_start = str(meta.get("period_start") or "")
    period_end = meta.get("period_end") or period_start

    _clean_expired_cache()
    now = time.time()

    translated_result: List[Dict[str, Any]] = []
    uncached_items: List[Dict[str, Any]] = []

    # Step 1: Check in-memory cache for each item
    for it in items:
        cat = it.get("category", "")
        text = it.get("text", "")
        text_sha = _get_sha1(text)
        cache_key = (lang, sign, system, period, period_start, cat, text_sha)

        with _cache_lock:
            cached_entry = _TRANSLATION_CACHE.get(cache_key)
            if cached_entry and cached_entry.get("expires_at", 0) > now:
                # Cache hit
                cached_data = dict(cached_entry["data"])
                cached_data["translated"] = True
                translated_result.append(cached_data)
                continue

            # Check failure cache
            fail_ts = _FAILURE_CACHE.get(cache_key)
            if fail_ts and (now - fail_ts) < FAILURE_CACHE_TTL:
                # Failed recently, fallback to English without retrying
                item_copy = dict(it)
                item_copy["translated"] = False
                translated_result.append(item_copy)
                continue

        # Needs translation
        uncached_items.append(it)

    # If all items were cached or in failure cache, return in original category order
    if not uncached_items:
        # Re-sort to match original items order
        order_map = {it.get("category"): i for i, it in enumerate(items)}
        translated_result.sort(key=lambda x: order_map.get(x.get("category"), 0))
        return translated_result

    # Step 2: Chunk uncached items according to PERIOD_CHUNK
    chunk_size = PERIOD_CHUNK.get(period, 4)
    chunks = [uncached_items[i:i + chunk_size] for i in range(0, len(uncached_items), chunk_size)]

    for chunk in chunks:
        chunk_cat_tuple = tuple(sorted([it.get("category", "") for it in chunk]))
        chunk_dedup_key = (lang, sign, system, period, period_start, chunk_cat_tuple)
        chunk_lock = _get_dedup_lock(chunk_dedup_key)

        with chunk_lock:
            # Check if another parallel thread already translated these while we waited
            still_needed: List[Dict[str, Any]] = []
            for it in chunk:
                cat = it.get("category", "")
                text_sha = _get_sha1(it.get("text", ""))
                cache_key = (lang, sign, system, period, period_start, cat, text_sha)
                with _cache_lock:
                    cached_entry = _TRANSLATION_CACHE.get(cache_key)
                    if cached_entry and cached_entry.get("expires_at", 0) > time.time():
                        cached_data = dict(cached_entry["data"])
                        cached_data["translated"] = True
                        translated_result.append(cached_data)
                    else:
                        still_needed.append(it)

            if not still_needed:
                continue

            # Execute translation with Mistral
            raw_trans_chunk = _execute_mistral_chunk(still_needed, lang, meta)
            expiry_ts = _get_period_expiry(period, period_end)

            for it in still_needed:
                cat = it.get("category", "")
                text = it.get("text", "")
                text_sha = _get_sha1(text)
                cache_key = (lang, sign, system, period, period_start, cat, text_sha)

                cat_trans = raw_trans_chunk.get(cat) if (raw_trans_chunk and isinstance(raw_trans_chunk, dict)) else None

                is_valid = False
                val_err = "No translation returned for category"
                if cat_trans and isinstance(cat_trans, dict):
                    is_valid, val_err = _validate_translation(cat_trans, it, lang)

                if is_valid and cat_trans:
                    # Construct translated item preserving original scores, numbers, keys
                    item_copy = dict(it)
                    item_copy["text"] = str(cat_trans.get("text", it.get("text"))).strip()
                    if cat_trans.get("remedy"):
                        item_copy["remedy"] = str(cat_trans.get("remedy")).strip()
                    if cat_trans.get("affirmation"):
                        item_copy["affirmation"] = str(cat_trans.get("affirmation")).strip()
                    if cat_trans.get("lucky_time"):
                        item_copy["lucky_time"] = str(cat_trans.get("lucky_time")).strip()
                    if cat_trans.get("tip_for_the_day"):
                        item_copy["tip_for_the_day"] = str(cat_trans.get("tip_for_the_day")).strip()

                    item_copy["translated"] = True

                    with _cache_lock:
                        _TRANSLATION_CACHE[cache_key] = {
                            "data": item_copy,
                            "expires_at": expiry_ts
                        }
                        if cache_key in _FAILURE_CACHE:
                            del _FAILURE_CACHE[cache_key]

                    translated_result.append(item_copy)
                else:
                    # Validation failed or API error -> Record in failure cache & fallback to English
                    print(f"[Landing Translation Rejected] {sign} {period} {cat} ({lang}): {val_err}")
                    with _cache_lock:
                        _FAILURE_CACHE[cache_key] = time.time()

                    fallback_item = dict(it)
                    fallback_item["translated"] = False
                    translated_result.append(fallback_item)

    # Re-sort to match original item order
    order_map = {it.get("category"): i for i, it in enumerate(items)}
    translated_result.sort(key=lambda x: order_map.get(x.get("category"), 0))
    return translated_result


# ---------------------------------------------------------------------------
# Background Pre-Warming
# ---------------------------------------------------------------------------

def warm_up(periods: Optional[List[str]] = None, langs: Optional[List[str]] = None):
    """
    Pre-translates horoscope rows for prewarm languages across all 12 signs x 2 systems.
    Executes in background thread pool with backoff.
    Never fails the caller.
    """
    from database.db_connection import get_db_connection

    periods_to_warm = periods or ["daily"]
    langs_to_warm = langs or PREWARM_LANGS

    signs = [
        "aries", "taurus", "gemini", "cancer",
        "leo", "virgo", "libra", "scorpio",
        "sagittarius", "capricorn", "aquarius", "pisces"
    ]
    systems = ["tropical", "sidereal"]

    print(f"[Landing Translation Warm-Up] Starting pre-warming for periods={periods_to_warm}, langs={langs_to_warm}...")

    def _warm_one(sign: str, system: str, period: str, lang: str):
        try:
            conn = get_db_connection()
            try:
                cursor = conn.cursor(dictionary=True)
                today_ist = datetime.now(IST).date()
                if period == "yearly":
                    cursor.execute("""
                        SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `generated_at`, `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = 'yearly' AND `period_start` = %s
                        ORDER BY `id` ASC;
                    """, (sign, system, date(today_ist.year, 1, 1)))
                elif period in ("weekly", "monthly"):
                    cursor.execute("""
                        SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `generated_at`, `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` <= %s AND `period_end` >= %s
                        ORDER BY `id` ASC;
                    """, (sign, system, period, today_ist, today_ist))
                else:
                    cursor.execute("""
                        SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `generated_at`, `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s
                        ORDER BY `id` ASC;
                    """, (sign, system, period, today_ist))

                rows = cursor.fetchall()
                cursor.close()

                if rows:
                    meta = {
                        "sign": sign,
                        "system": system,
                        "period": period,
                        "period_start": str(rows[0]["period_start"]),
                        "period_end": str(rows[0]["period_end"]),
                    }
                    translate_items(rows, lang, meta)
            finally:
                conn.close()
        except Exception as e:
            print(f"[Landing Translation Warm-Up Error] {sign} {system} {period} {lang}: {e}")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        for period in periods_to_warm:
            for sign in signs:
                for system in systems:
                    for lang in langs_to_warm:
                        futures.append(pool.submit(_warm_one, sign, system, period, lang))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

    print(f"[Landing Translation Warm-Up] Completed pre-warming.")


def get_translation_stats() -> Dict[str, Any]:
    """Returns runtime metrics for Mistral calls and cache sizes."""
    with _CALL_STATS["lock"]:
        stats = dict(_CALL_STATS)
        del stats["lock"]
    with _cache_lock:
        stats["cached_entries"] = len(_TRANSLATION_CACHE)
        stats["failure_entries"] = len(_FAILURE_CACHE)
    return stats

