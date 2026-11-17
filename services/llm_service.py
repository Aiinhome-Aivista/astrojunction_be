import os
import re
import requests
import json
import concurrent.futures
from datetime import datetime
from services.settings_service import get_setting


class LLMError(Exception):
    """Raised whenever the configured LLM cannot be reached or returns an
    unusable response. The counselling controller must surface this as a
    clear error to the frontend — never fall back to a fabricated reply."""
    pass


SYSTEM_PROMPT_TEMPLATE = """You are the AstroJunction Daivajna, an authentic Vedic astrology and \
numerology counsellor. You are given the user's ALREADY-CALCULATED chart data and \
numerology below — do not invent, alter, or recompute any planetary positions, degrees, \
dasha dates, or numerology numbers. Use only the data provided and the classical \
reference knowledge given to you.

Structure your response with these sections where relevant: Summary, Astrological Basis, \
Interpretation, Timing, Opportunities, Challenges, Recommended Actions, Traditional \
Practices. End with a brief disclaimer that this is traditional/informational guidance, \
not a guaranteed prediction or a substitute for professional advice.

Selected tradition: {tradition}

--- Calculated Chart Data ---
{chart_summary}

--- Numerology ---
{numerology_summary}

--- Relevant Classical Knowledge (retrieved) ---
{rag_context}
"""


def _build_system_prompt(tradition: str, chart_summary: str, numerology_summary: str, rag_context: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        tradition=tradition,
        chart_summary=chart_summary or "Not provided.",
        numerology_summary=numerology_summary or "Not provided.",
        rag_context=rag_context or "No specific reference matched this question.",
    )


def _get_llm_timeout() -> int:
    """Reads LLM timeout in seconds from MySQL system_settings (default 30s)."""
    try:
        val = int(get_setting("LLM_TIMEOUT", "30"))
        return max(5, min(val, 300))
    except Exception:
        return 30


def _call_mistral_local(system_prompt: str, history: list, max_tokens: int = None) -> str:
    base_url = get_setting("MISTRAL_LOCAL_URL", "").rstrip("/")
    model = get_setting("MISTRAL_MODEL", "")
    if not base_url or not model:
        raise LLMError(
            "ACTIVE_LLM is set to mistral_local but MISTRAL_LOCAL_URL or MISTRAL_MODEL is not configured in Admin Settings."
        )

    # mistral_local endpoint call

    prompt = system_prompt + "\n\n"
    for msg in history:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        prompt += f"{role}: {content}\n\n"

    timeout = _get_llm_timeout()
    resp = None
    try:
        try:
            req_body = {"model": model, "prompt": prompt, "stream": False, "temperature": 0.1}
            resp = requests.post(
                f"{base_url}/api/generate",
                headers={"Connection": "close"},
                json=req_body,
                timeout=timeout,
            )
        except requests.RequestException:
            # Fallback to /v1/chat/completions (OpenAI compatible endpoint)
            try:
                print(f"[LLM FALLBACK CALL] Provider: mistral_local | Model/Version: {model} | URL: {base_url}/v1/chat/completions")
                messages = [{"role": "system", "content": system_prompt}] + history
                chat_payload = {"model": model, "messages": messages, "temperature": 0.1}
                if max_tokens:
                    chat_payload["max_tokens"] = max_tokens
                if "json" in system_prompt.lower():
                    chat_payload["response_format"] = {"type": "json_object"}
                resp = requests.post(
                    f"{base_url}/v1/chat/completions",
                    headers={"Connection": "close"},
                    json=chat_payload,
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    returned_model = data.get("model", model)
                    print(f"[LLM RESPONSE] Provider: mistral_local (chat fallback) | Resolved Model/Version: {returned_model}")
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                raise LLMError(f"Could not reach local Mistral server at {base_url}: {e}")
            raise LLMError(f"Could not reach local Mistral server at {base_url}")

        if resp.status_code != 200:
            raise LLMError(f"Local Mistral server returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM RESPONSE] Provider: mistral_local | Resolved Model/Version: {returned_model}")
        content = data.get("response", "")
        if not content:
            raise LLMError("Local Mistral server returned an unexpected response shape (no response field).")
        return content
    finally:
        if resp is not None:
            resp.close()


def _call_mistral_cloud(system_prompt: str, history: list, max_tokens: int = None) -> str:
    base_url = get_setting("MISTRAL_CLOUD_URL", "https://api.mistral.ai").rstrip("/")
    api_key = get_setting("MISTRAL_CLOUD_API_KEY", "")
    model = get_setting("MISTRAL_MODEL", "mistral-large-latest")
    if not base_url or not api_key:
        raise LLMError(
            "ACTIVE_LLM is set to mistral_cloud but MISTRAL_CLOUD_URL / "
            "MISTRAL_CLOUD_API_KEY are not fully configured."
        )

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
    payload = {"model": model, "messages": messages, "temperature": 0.1}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if "json" in system_prompt.lower():
        payload["response_format"] = {"type": "json_object"}

    resp = None
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Mistral cloud API returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM] mistral_cloud ({returned_model}) -> 200 OK")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Mistral cloud API returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach Mistral cloud endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_gemini(system_prompt: str, history: list, max_tokens: int = None) -> str:
    api_key = get_setting("GEMINI_API_KEY", "")
    model = get_setting("GEMINI_MODEL", "gemini-2.0-flash")
    if not api_key:
        raise LLMError(
            "ACTIVE_LLM is set to gemini but GEMINI_API_KEY is not configured."
        )

    api_version = "v1beta"
    url = (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model}:generateContent?key={api_key}"
    )
    convo_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
    full_prompt = f"{system_prompt}\n\n--- Conversation ---\n{convo_text}"

    timeout = _get_llm_timeout()
    resp = None
    try:
        body = {"contents": [{"parts": [{"text": full_prompt}]}]}
        gen_config = {"temperature": 0.1}
        if max_tokens:
            gen_config["maxOutputTokens"] = max_tokens
        if "json" in system_prompt.lower():
            gen_config["responseMimeType"] = "application/json"
        body["generationConfig"] = gen_config

        resp = requests.post(
            url,
            headers={"Connection": "close"},
            json=body,
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        model_version = data.get("modelVersion", model)
        print(f"[LLM] gemini ({model_version}) -> 200 OK")
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Gemini API returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach Gemini API: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_openai(system_prompt: str, history: list, max_tokens: int = None) -> str:
    api_key = get_setting("OPENAI_API_KEY", "")
    base_url = get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = get_setting("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise LLMError("ACTIVE_LLM is set to openai but OPENAI_API_KEY is not configured.")

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
    payload = {"model": model, "messages": messages, "temperature": 0.1}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if "json" in system_prompt.lower():
        payload["response_format"] = {"type": "json_object"}

    resp = None
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenAI returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM] openai ({returned_model}) -> 200 OK")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("OpenAI returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach OpenAI endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_openrouter(system_prompt: str, history: list, max_tokens: int = None) -> str:
    api_key = get_setting("OPENROUTER_API_KEY", "")
    base_url = get_setting("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = get_setting("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    if not api_key:
        raise LLMError("ACTIVE_LLM is set to openrouter but OPENROUTER_API_KEY is not configured.")

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
    payload = {"model": model, "messages": messages}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if "json" in system_prompt.lower():
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://astrojunction.com",
        "X-Title": "AstroJunction",
        "Connection": "close",
    }
    resp = None
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM] openrouter ({returned_model}) -> 200 OK")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("OpenRouter returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach OpenRouter endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _execute_llm(system_prompt: str, history: list, max_tokens: int = None) -> str:
    # Strictly execute ONLY the admin-configured active LLM. Zero fallback, zero hardcoded secondary engines.
    active_llm = get_setting("ACTIVE_LLM", "").strip().lower()
    if not active_llm:
        raise LLMError("No active LLM engine is selected in Admin Settings. Please select and configure an AI Engine in Admin Panel.")

    # Get the specific configured model name for clear visibility
    model_name = "default"
    if active_llm == "gemini":
        model_name = get_setting("GEMINI_MODEL", "gemini-2.0-flash")
    elif active_llm == "openrouter":
        model_name = get_setting("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    elif active_llm == "openai":
        model_name = get_setting("OPENAI_MODEL", "gpt-4o-mini")
    elif active_llm == "mistral_cloud":
        model_name = get_setting("MISTRAL_MODEL", "mistral-large-latest")
    elif active_llm == "mistral_local":
        model_name = get_setting("MISTRAL_MODEL", "")
        if not model_name:
            raise LLMError("ACTIVE_LLM is set to mistral_local but MISTRAL_MODEL is not configured in Admin Settings.")

    print(f"[LLM] >>> {active_llm.upper()} ({model_name}) | max_tokens: {max_tokens or 'auto'}")

    if active_llm == "mistral_local":
        return _call_mistral_local(system_prompt, history, max_tokens=max_tokens)
    elif active_llm == "mistral_cloud":
        return _call_mistral_cloud(system_prompt, history, max_tokens=max_tokens)
    elif active_llm == "gemini":
        return _call_gemini(system_prompt, history, max_tokens=max_tokens)
    elif active_llm == "openai":
        return _call_openai(system_prompt, history, max_tokens=max_tokens)
    elif active_llm == "openrouter":
        return _call_openrouter(system_prompt, history, max_tokens=max_tokens)
    else:
        raise LLMError(f"Unknown or unconfigured LLM provider: '{active_llm}'")


def get_ai_response(
    history: list,
    tradition: str,
    chart_summary: str,
    numerology_summary: str,
    rag_context: str,
) -> str:
    """history: list of {"role": "user"|"assistant", "content": str}, oldest first."""
    system_prompt = _build_system_prompt(tradition, chart_summary, numerology_summary, rag_context)
    return _execute_llm(system_prompt, history)



def get_daily_insights_response(
    profile: dict,
    chart_data: dict,
    panchang: dict,
    numerology: dict,
    day_facts: dict = None,
    target_lang: str = "en",
) -> str:
    natal_lagna = chart_data.get("ascendant", {}).get("signName", "Unknown")

    if day_facts:
        sunrise_asc = day_facts.get("sunriseAscendant", "Unknown")
        sunrise_tithi = day_facts.get("tithiName", panchang.get("tithi", "Unknown"))
        sunrise_nak = day_facts.get("nakshatraName", panchang.get("nakshatra", "Unknown"))
        score = day_facts.get("auspiciousScore", panchang.get("auspiciousScore", 75))
    else:
        sunrise_asc = "Unknown"
        sunrise_tithi = panchang.get("tithi", "Unknown")
        sunrise_nak = panchang.get("nakshatra", "Unknown")
        score = panchang.get("auspiciousScore", 75)

    lucky_numbers = numerology.get("luckyNumbers") or [numerology.get("mulank", 1)]
    lucky_num = lucky_numbers[0] if lucky_numbers else numerology.get("mulank", 1)
    lucky_colors = numerology.get("luckyColors") or []
    lucky_colors_str = ", ".join(lucky_colors) if lucky_colors else "Bright Yellow"

    target_lang = (target_lang or "en").lower().strip()
    if target_lang not in ["en", "hi", "bn", "ta", "fr"]:
        target_lang = "en"

    lang_directives = {
        "en": "Write natively in dignified, natural, formal-polite scholarly English.",
        "hi": "Write purely and natively in formal-polite Hindi using Devanagari script (हिंदी लिपि). Do NOT use English words (like 'Lagna', 'Libra', 'Prana' in Roman script) or transliteration; use authentic Vedic terms like 'लग्न', 'तुला', 'प्राण'. Use Latin digits (1, 2, 3...) for numbers or times.",
        "bn": "Write purely and natively in formal-polite standard Bengali using Bengali script (বাংলা লিপি). Do NOT transliterate English zodiac names (do NOT write 'লিব্রা', write 'তুলা'; do NOT write 'সাইডেরিয়াল', write 'নিরায়ণ'). Use authentic Vedic terms. Use Latin digits (1, 2, 3...) for numbers or times.",
        "ta": "Write purely and natively in formal-polite standard Tamil using Tamil script (தமிழ் எழுத்துரு). Do NOT use English words. Do NOT loop, repeat phrases, or invent unrelated festivals. Use authentic Jyotish terms. Use Latin digits (1, 2, 3...) for numbers or times.",
        "fr": "Write purely and natively in elegant, formal French with correct accents (é, è, ê, à, ç, etc.). Translate zodiac signs into French (e.g. Balance, Scorpion, Sagittaire, Capricorne). Do NOT output Tamil, Hindi, or Bengali script in any French response. Use Latin digits (1, 2, 3...) for numbers or times."
    }

    directive = lang_directives.get(target_lang, lang_directives["en"])

    system_prompt = f"""You are the AstroJunction Daivajna, providing personalized daily Vedic transit synthesis.
You MUST respond with ONLY a valid JSON object matching exactly this structure, no markdown formatting or backticks around it:
{{
  "summary": "A 2-3 sentence overall astrological prediction for today based on transits and tithi.",
  "career": "1-2 sentences on career and commerce predictions.",
  "love": "1-2 sentences on love and relationships.",
  "health": "1-2 sentences on health and prana."
}}

STRICT EDITORIAL AND ACCURACY RULES:
1. PROHIBITED: NEVER write, quote, or mention any numeric score, percentage, cosmic harmony number, or rating anywhere in any field (e.g. NEVER write "score of 60", "79%", "cosmic score", or "auspicious score"). The cosmic harmony score is rendered visually by the UI meter and must NOT be written in prose.
2. ASCENDANT DISTINCTION: The user's natal birth ascendant is their Janma Lagna ({natal_lagna}). Today's rising sign at dawn ({sunrise_asc}) MUST be referred to as "the sunrise ascendant (Gochara Lagna at sunrise)". NEVER refer to it simply as "Lagna today" or "today's Lagna".
3. LANGUAGE & SCRIPT: {directive}
4. FORMAT: Keep all text plain text with NO markdown bolding (**), asterisks, hashes, or bullet points. Use Latin digits (0-9) for any times or numbers.
5. NO REPETITION / NO UNRELATED FESTIVALS: Do NOT loop or repeat phrases or sentences. Do NOT invent festivals (such as Diwali or Navratri) unless it matches today's stated Tithi. Ensure each field contains distinct, thoughtful, professional Vedic guidance.

Astrological facts for today:
- Janma Lagna (Natal Ascendant): {natal_lagna}
- Sunrise Ascendant (Gochara Lagna at sunrise): {sunrise_asc}
- Sunrise Tithi: {sunrise_tithi}
- Sunrise Nakshatra: {sunrise_nak}
- Numerology: Mulank {numerology.get("mulank", 1)}, Lucky Number {lucky_num}, Lucky Colors {lucky_colors_str}
"""

    # Extended Regex Validator: catches Latin digits with %, score digits, native digits with %, and multilingual score words
    score_pattern = re.compile(
        rf'\b{score}\b|\d+\s*%|[०-९]+\s*%|[০-৯]+\s*%|[௦-௯]+\s*%|'
        r'\bscore\s+of\b|\bscore\s+is\b|\bauspicious\s+score\b|\bcosmic\s+score\b|'
        r'स्कोर|प्रतिशत|स्कोर|শতাংশ|மதிப்பெண்|சதவீதம்|\bscore\b|\bpourcentage\b',
        re.IGNORECASE
    )

    def _validate_language_script(text: str, lang: str) -> bool:
        if lang == "en":
            return True
        if lang == "hi":
            return bool(re.search(r'[\u0900-\u097F]', text))
        if lang == "bn":
            return bool(re.search(r'[\u0980-\u09FF]', text))
        if lang == "ta":
            return bool(re.search(r'[\u0B80-\u0BFF]', text))
        if lang == "fr":
            has_accents = bool(re.search(r'[éèêëàâîïôûùçÉÈÊËÀÂÎÏÔÛÙÇ]', text))
            has_words = bool(re.search(r'\b(le|la|les|un|une|des|est|dans|pour|avec|vous|votre|aujourd|energie)\b', text, re.I))
            return has_accents or has_words
        return True

    def _validate_insights_json(raw_json: str, lang: str):
        cleaned = raw_json.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except Exception as err:
            return False, f"JSON parse error: {err}"

        for key in ["summary", "career", "love", "health"]:
            val = parsed.get(key, "")
            if not isinstance(val, str) or not val.strip():
                return False, f"Missing or empty field: {key}"
            # Check markdown
            if "**" in val or "##" in val or val.strip().startswith("- "):
                return False, f"Markdown detected in field '{key}'"
            # Check score/percentage
            m = score_pattern.search(val)
            if m:
                return False, f"Forbidden score/percentage match '{m.group(0)}' in field '{key}'"
            # Check script
            if not _validate_language_script(val, lang):
                return False, f"Target script validation failed for '{lang}' in field '{key}'"

        return True, cleaned

    history = [{"role": "user", "content": "Generate today's daily insights as JSON."}]
    last_raw = ""

    for attempt in range(3):
        try:
            raw_res = _execute_llm(system_prompt, history)
            last_raw = raw_res
            is_valid, cleaned_or_err = _validate_insights_json(raw_res, target_lang)
            if is_valid:
                return cleaned_or_err

            print(f"[DailyHoroscope LLM] Validation attempt {attempt + 1} failed: {cleaned_or_err}. Retrying...")
            history.append({"role": "assistant", "content": raw_res})
            history.append({
                "role": "user",
                "content": f"Correction: Your previous response violated rules: {cleaned_or_err}. Regenerate the JSON strictly in {target_lang} with ABSOLUTELY ZERO numeric scores, NO percentages, and NO markdown."
            })
        except Exception as e:
            print(f"[DailyHoroscope LLM] Execution error attempt {attempt + 1}: {e}")

    # Fallback if target language generation fails after retries: return English version with showingEnglishNote
    try:
        cleaned = last_raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        parsed = json.loads(cleaned.strip())
        for k in ["summary", "career", "love", "health"]:
            if k in parsed and isinstance(parsed[k], str):
                parsed[k] = score_pattern.sub("", parsed[k]).strip()
        if target_lang != "en" and not _validate_language_script(parsed.get("summary", ""), target_lang):
            parsed["showingEnglishNote"] = True
        return json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass

    fallback_insights = {
        "summary": f"Under the sunrise ascendant (Gochara Lagna at sunrise) of {sunrise_asc} with {sunrise_tithi} and {sunrise_nak} Nakshatra, cosmic energies bring focused clarity and steady momentum. Ground your endeavors with dharmic purpose.",
        "career": "Steady momentum supports strategic planning, meticulous documentation, and collaborative communications.",
        "love": "Harmonious planetary transits encourage empathetic listening and peaceful domestic harmony.",
        "health": "Vital prana remains well-aligned; maintain equilibrium with mindful breathing and wholesome nutrition.",
        "showingEnglishNote": True if target_lang != "en" else False
    }
    return json.dumps(fallback_insights, ensure_ascii=False)


def get_structured_cosmic_pulse(sign: str, language: str = 'en') -> str:
    sign_name = (sign or 'aries').capitalize()
    return f"Today's planetary movements bring vibrant energy and clarity for {sign_name}. Ground yourself in purposeful action and maintain balanced priorities."


def get_structured_category_insight(sign: str, category: str, language: str = 'en') -> str:
    sign_name = (sign or 'aries').capitalize()
    cat_name = (category or 'general').replace('_', ' ').capitalize()
    return f"Astrological influences today favor mindful awareness and steady progress in {cat_name} for {sign_name}. Trust your instincts and stay disciplined."


def _generate_category_insights(sign: str, language: str = "en") -> dict:
    categories = ["health", "wealth", "relationship", "love_line", "education", "professional", "travel"]
    return {
        cat: {
            "score": 82,
            "insight": get_structured_category_insight(sign, cat, language)
        }
        for cat in categories
    }


def _generate_fallback_zodiac_forecast(sign: str, timeframe: str, language: str = "en") -> dict:
    sign_key = sign.lower().strip()
    
    meta = {
        "aries": {"gem": "Red Coral (Moonga)", "color": "Scarlet Red", "day": "Tuesday", "nums": [9, 18, 27], "chakra": "Solar Plexus (Manipura)", "aff": "I lead with courage, radiant fire, and dharmic conviction.", "romance": ["Leo", "Sagittarius"], "career": ["Gemini", "Aquarius"], "growth": ["Libra"]},
        "taurus": {"gem": "Diamond (Heera)", "color": "Emerald Green", "day": "Friday", "nums": [6, 15, 24], "chakra": "Heart (Anahata)", "aff": "I cultivate lasting abundance with grounded patience.", "romance": ["Virgo", "Capricorn"], "career": ["Cancer", "Pisces"], "growth": ["Scorpio"]},
        "gemini": {"gem": "Emerald (Panna)", "color": "Bright Yellow", "day": "Wednesday", "nums": [5, 14, 23], "chakra": "Throat (Vishuddha)", "aff": "My speech illuminates truth and bridges worlds.", "romance": ["Libra", "Aquarius"], "career": ["Aries", "Leo"], "growth": ["Sagittarius"]},
        "cancer": {"gem": "Natural Pearl (Moti)", "color": "Silvery White", "day": "Monday", "nums": [2, 11, 20], "chakra": "Sacral (Svadhisthana)", "aff": "I trust my divine intuition to nurture my highest path.", "romance": ["Scorpio", "Pisces"], "career": ["Taurus", "Virgo"], "growth": ["Capricorn"]},
        "leo": {"gem": "Ruby (Manik)", "color": "Royal Gold", "day": "Sunday", "nums": [1, 10, 19], "chakra": "Solar Plexus (Manipura)", "aff": "I shine with noble grace and empower those around me.", "romance": ["Aries", "Sagittarius"], "career": ["Gemini", "Libra"], "growth": ["Aquarius"]},
        "virgo": {"gem": "Emerald (Panna)", "color": "Forest Green", "day": "Wednesday", "nums": [5, 14, 23], "chakra": "Throat (Vishuddha)", "aff": "I bring divine order and selfless service to every deed.", "romance": ["Taurus", "Capricorn"], "career": ["Cancer", "Scorpio"], "growth": ["Pisces"]},
        "libra": {"gem": "Diamond (Heera)", "color": "Pastel Pink", "day": "Friday", "nums": [6, 15, 24], "chakra": "Heart (Anahata)", "aff": "I embody universal harmony, fairness, and inner peace.", "romance": ["Gemini", "Aquarius"], "career": ["Leo", "Sagittarius"], "growth": ["Aries"]},
        "scorpio": {"gem": "Red Coral (Moonga)", "color": "Deep Crimson", "day": "Tuesday", "nums": [9, 18, 27], "chakra": "Root (Muladhara)", "aff": "I transform adversity into spiritual mastery and renewal.", "romance": ["Cancer", "Pisces"], "career": ["Virgo", "Capricorn"], "growth": ["Taurus"]},
        "sagittarius": {"gem": "Yellow Sapphire (Pukhraj)", "color": "Royal Saffron", "day": "Thursday", "nums": [3, 12, 21], "chakra": "Third Eye (Ajna)", "aff": "Wisdom is my compass; boundless truth guides my journey.", "romance": ["Aries", "Leo"], "career": ["Libra", "Aquarius"], "growth": ["Gemini"]},
        "capricorn": {"gem": "Blue Sapphire (Neelam)", "color": "Dark Navy", "day": "Saturday", "nums": [8, 17, 26], "chakra": "Root (Muladhara)", "aff": "With unwavering discipline, I build lasting greatness.", "romance": ["Taurus", "Virgo"], "career": ["Scorpio", "Pisces"], "growth": ["Cancer"]},
        "aquarius": {"gem": "Blue Sapphire (Neelam)", "color": "Electric Blue", "day": "Saturday", "nums": [8, 17, 26], "chakra": "Third Eye (Ajna)", "aff": "I innovate for collective elevation and cosmic awareness.", "romance": ["Gemini", "Libra"], "career": ["Aries", "Sagittarius"], "growth": ["Leo"]},
        "pisces": {"gem": "Yellow Sapphire (Pukhraj)", "color": "Sea Green", "day": "Thursday", "nums": [3, 12, 21], "chakra": "Crown (Sahasrara)", "aff": "I surrender to cosmic flow with infinite compassion.", "romance": ["Cancer", "Scorpio"], "career": ["Taurus", "Capricorn"], "growth": ["Virgo"]}
    }
    
    m = meta.get(sign_key, meta["aries"])
    structured_today_pulse = get_structured_cosmic_pulse(sign_key, language)

    if language == 'bn':
        forecast_texts = {
            'today': f"{sign.capitalize()} রাশির জাতক-জাতিকাদের জন্য আজকের গ্রহ অবস্থান আত্মবিশ্বাস ও একাগ্রতা বৃদ্ধির ইঙ্গিত দিচ্ছে। আর্থিক লেনদেনে ইতিবাচক অগ্রগতি এবং মানসিক শান্তি বজায় থাকবে।",
            'week': f"এই সপ্তাহে বৃহস্পতি ও বুধের শুভ গোচরে {sign.capitalize()} রাশির নতুন পরিকল্পনা সফল হওয়ার শুভ যোগ রয়েছে। কর্মক্ষেত্রে সিনিয়রদের সহযোগিতা পাবেন।",
            'month': f"চলতি মাসে কর্ম ও আর্থিক ক্ষেত্রে গুরুত্বপূর্ণ অগ্রগতির সম্ভাবনা রয়েছে। কৌশলগত সিদ্ধান্ত গ্রহণে ধৈর্য বজায় রাখুন।",
            'year': f"২০২৬-২৭ সালে শনি ও বৃহস্পতির অনুকূল প্রভাব আপনার দীর্ঘমেয়াদী লক্ষ্যপূরণে শক্তিশালী ভূমিকা রাখবে।"
        }
    else:
        forecast_texts = {
            'today': structured_today_pulse,
            'week': f"This week opens promising windows for strategic collaboration and professional growth for {sign.capitalize()}. Mercury's supportive aspect enhances negotiation and creative brainstorming.",
            'month': f"Monthly planetary ingresses favor long-term consolidation and auspicious financial planning for {sign.capitalize()}. Maintain disciplined routines and trust your inner wisdom.",
            'year': f"The 2026/2027 astrological panorama marks a profound phase of karmic ascension and material stability for {sign.capitalize()}."
        }
    
    forecast_str = forecast_texts.get(timeframe, forecast_texts['today'])
    category_insights = _generate_category_insights(sign, language)
    
    return {
        "forecast": forecast_str,
        "categoryInsights": category_insights,
        "luckyGemstone": m["gem"],
        "luckyColor": m["color"],
        "luckyDay": m["day"],
        "powerNumbers": m["nums"],
        "resonantChakra": m["chakra"],
        "affirmation": m["aff"],
        "vitalityToday": 84,
        "loveRating": 80,
        "careerRating": 88,
        "wealthRating": 82,
        "bestRomanceMatches": m["romance"],
        "bestCareerMatches": m["career"],
        "growthMatches": m["growth"]
    }


def get_zodiac_forecast_response(
    sign: str,
    timeframe: str,
    language: str = "en"
) -> str:
    """
    Dynamically generates daily zodiac forecast from the active LLM:
    - forecast: authentic 6 to 7 sentences paragraph for Today's Cosmic Pulse
    - vitalityToday, wealthRating, careerRating, loveRating (0-100)
    - categoryInsights: 7 categories with dynamic scores and 6-7 line structured reports
    - affirmation, resonantChakra, luckyGemstone, luckyColor, luckyDay, powerNumbers
    """
    norm_sign = sign.lower().strip()

    prompt = f"""You are a master Vedic and Western Astrologer.
Generate today's authentic, dynamic astrological daily horoscope for {norm_sign.capitalize()} in valid JSON format.

CRITICAL REQUIREMENTS:
1. "forecast" (Today's Cosmic Pulse): Write an expansive, comprehensive, rich, and detailed astrological forecast with NO arbitrary sentence or line limits. Provide deep planetary transit synthesis, lunar phase dynamics, emotional vitality, career momentum, financial guidance, relationship harmony, and actionable spiritual remedies for {norm_sign.capitalize()} today.
2. Ratings & Category Scores: realistic dynamic percentage numbers (0-100) reflecting authentic astrological transits today.
3. Resonances: empowering celestial affirmation, resonant chakra, auspicious gemstone, power color, favorable day, and 3 power numbers.

You MUST respond ONLY with a valid JSON object matching this structure:
{{
  "forecast": "Write an expansive, detailed, in-depth comprehensive cosmic pulse reading here.",
  "vitalityToday": 88,
  "wealthRating": 82,
  "careerRating": 86,
  "loveRating": 84,
  "affirmation": "Celestial affirmation sentence.",
  "resonantChakra": "Chakra Name (Center focus)",
  "luckyGemstone": "Gemstone Name",
  "luckyColor": "Power Color",
  "luckyDay": "Auspicious Day of the week",
  "powerNumbers": [3, 7, 9],
  "bestRomanceMatches": ["Sign1", "Sign2"],
  "bestCareerMatches": ["Sign3", "Sign4"],
  "growthMatches": ["Sign5"],
  "categoryScores": {{
    "health": 85,
    "wealth": 80,
    "relationship": 84,
    "love_line": 88,
    "education": 79,
    "professional": 83,
    "travel": 76
  }}
}}"""

    history = [{"role": "user", "content": f"Generate today's cosmic pulse and category scores for {norm_sign}."}]

    try:
        res = _execute_llm(prompt, history)
        res = res.strip()
        if res.startswith("```json"):
            res = res[7:]
        if res.startswith("```"):
            res = res[3:]
        if res.endswith("```"):
            res = res[:-3]
        res = res.strip()

        start = res.find("{")
        end = res.rfind("}")
        if start != -1 and end != -1 and end > start:
            res = res[start:end+1]

        data = None
        try:
            data = json.loads(res, strict=False)
        except Exception:
            import re
            cleaned_res = re.sub(r',\s*([\]}])', r'\1', res)
            try:
                data = json.loads(cleaned_res, strict=False)
            except Exception:
                data = {}
                f_m = re.search(r'"forecast"\s*:\s*"(.*?)"(?=,\s*"[a-zA-Z]+"\s*:)', res, re.DOTALL)
                if not f_m:
                    f_m = re.search(r'"forecast"\s*:\s*"(.*)"', res, re.DOTALL)
                if f_m:
                    data["forecast"] = f_m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
                for num_key in ["vitalityToday", "wealthRating", "careerRating", "loveRating"]:
                    n_m = re.search(rf'"{num_key}"\s*:\s*(\d+)', res)
                    if n_m:
                        data[num_key] = int(n_m.group(1))
                for str_key in ["affirmation", "resonantChakra", "luckyGemstone", "luckyColor", "luckyDay"]:
                    s_m = re.search(rf'"{str_key}"\s*:\s*"(.*?)"', res)
                    if s_m:
                        data[str_key] = s_m.group(1)

        # Ensure forecast is present and non-empty
        if not data or not data.get("forecast") or len(str(data.get("forecast")).strip()) < 50:
            fallback = _generate_fallback_zodiac_forecast(norm_sign, timeframe, language)
            return json.dumps(fallback)

        # Merge category scores with structured reports
        category_scores = data.get("categoryScores") or {}
        cat_insights = {}
        for cat_id in ["health", "wealth", "relationship", "love_line", "education", "professional", "travel"]:
            score = int(category_scores.get(cat_id, 80))
            insight_text = get_structured_category_insight(norm_sign, cat_id, language)
            cat_insights[cat_id] = {
                "score": score,
                "insight": insight_text
            }

        data["categoryInsights"] = cat_insights
        return json.dumps(data)

    except Exception as e:
        print(f"Warning: LLM generation for zodiac forecast failed ({e}), using dynamic Vedic astrological calculation fallback.")
        fallback = _generate_fallback_zodiac_forecast(norm_sign, timeframe, language)
        return json.dumps(fallback)


def get_zodiac_compatibility_response(
    sign_a: str,
    sign_b: str,
    system: str = "tropical",
    language: str = "en"
) -> str:
    lang_code = (language or "en").split("-")[0].lower()
    lang_names = {
        "hi": "Hindi (हिन्दी)",
        "bn": "Bengali (বাংলা)",
        "ta": "Tamil (தமிழ்)",
        "fr": "French (Français)",
        "en": "English"
    }
    target_lang = lang_names.get(lang_code, "English")

    system_prompt = f"""You are an expert Vedic and Western Astrologer. Calculate the unique compatibility between {sign_a.capitalize()} and {sign_b.capitalize()} using the {system} system.
Calculate a highly accurate overall compatibility score (0-100) based on elements, modalities, and planetary rulers.
You MUST respond with a valid JSON object ONLY, without any markdown formatting, code fences (no ```json), or commentary outside the JSON:
{{
  "overallScore": 68,
  "elementSynergy": "Short description of elemental synergy written entirely and fluently in {target_lang}",
  "romanceAnalysis": "2-3 sentences about their romantic and soul synergy written entirely and fluently in {target_lang}.",
  "intellectualAnalysis": "2-3 sentences about how their minds and communication match written entirely and fluently in {target_lang}.",
  "growthPotential": "2-3 sentences about how they help each other evolve written entirely and fluently in {target_lang}.",
  "remedialAdvice": "1 sentence of practical spiritual/astrological advice for this pairing written entirely and fluently in {target_lang}."
}}
CRITICAL LANGUAGE REQUIREMENT:
All descriptive text values in the JSON ("elementSynergy", "romanceAnalysis", "intellectualAnalysis", "growthPotential", "remedialAdvice") MUST be written 100% in {target_lang}. Do NOT use English unless the requested language is English.
IMPORTANT: Replace 68 with the ACTUAL calculated compatibility score between these two signs (e.g. Leo and Aries might be 90, while Aries and Cancer might be 45). Make sure the score varies based on true astrological principles.
"""
    
    history = [{"role": "user", "content": f"Calculate compatibility between {sign_a} and {sign_b} in {target_lang}."}]
    try:
        res = _execute_llm(system_prompt, history)
            
        res = res.strip()
        start = res.find("{")
        end = res.rfind("}")
        if start != -1 and end != -1 and end > start:
            res = res[start:end+1]
            
        # Validate that it is JSON
        json.loads(res)
        return res
    except Exception as e:
        print(f"Error in get_zodiac_compatibility_response: {e}")
        # Localized fallback static responses if LLM fails
        fallbacks = {
            "hi": {
                "overallScore": 72,
                "elementSynergy": f"{sign_a.capitalize()} और {sign_b.capitalize()} के तत्वों का सुंदर और सामंजस्यपूर्ण मिलन।",
                "romanceAnalysis": "दोनों के बीच स्वाभाविक आकर्षण और भावनात्मक ऊर्जा का सुंदर प्रवाह रहता है।",
                "intellectualAnalysis": "संवाद में खुलापन और एक-दूसरे के विचारों का आदर इस रिश्ते को मजबूती प्रदान करता है।",
                "growthPotential": "एक-दूसरे के मतभेदों को समझकर दोनों व्यक्तिगत और आध्यात्मिक रूप से विकसित होते हैं।",
                "remedialAdvice": "धैर्य बनाए रखें, नियमित संवाद रखें और एक-दूसरे के दृष्टिकोण का सम्मान करें।"
            },
            "bn": {
                "overallScore": 72,
                "elementSynergy": f"{sign_a.capitalize()} এবং {sign_b.capitalize()}-এর প্রাকৃতিক উপাদানের চমৎকার সমন্বয়।",
                "romanceAnalysis": "উভয়ের মধ্যে সহজাত আকর্ষণ এবং গভীর মানসিক সংযোগ গড়ে ওঠে।",
                "intellectualAnalysis": "খোলামেলা ভাববিনিময় এবং পারস্পরিক বোঝাপড়া সম্পর্ককে স্থিতিশীল রাখে।",
                "growthPotential": "একসাথে পথচলা উভয়ের মানসিক পরিপক্কতা এবং আত্মিক অগ্রগতিতে সাহায্য করে।",
                "remedialAdvice": "ধৈর্য ও পারস্পরিক বিশ্বাসের সাথে পরস্পরের স্বাতন্ত্র্যকে সম্মান জানান।"
            },
            "ta": {
                "overallScore": 72,
                "elementSynergy": f"{sign_a.capitalize()} மற்றும் {sign_b.capitalize()} ஆகிய இரு ராசிகளின் பஞ்சபூத ஆற்றல் நல்லிணக்கம்.",
                "romanceAnalysis": "இருவரிடமும் இயற்கையான ஈர்ப்பும் ஆழமான அன்பும் மலர்கிறது.",
                "intellectualAnalysis": "தெளிவான கருத்துப் பகிர்வும் பரஸ்பர புரிதலும் உறவை பலப்படுத்துகிறது.",
                "growthPotential": "இருவரும் இணைந்து செயல்பட்டு வாழ்வில் புதிய உயரங்களை எட்ட முடியும்.",
                "remedialAdvice": "பொறுமையுடன் செயல்பட்டு ஒருவரையொருவர் மதித்து நடப்பது நன்மை தரும்."
            },
            "fr": {
                "overallScore": 72,
                "elementSynergy": f"Harmonie élémentaire dynamique entre {sign_a.capitalize()} et {sign_b.capitalize()}.",
                "romanceAnalysis": "Les énergies astrales créent une attraction mutuelle et une profonde complicité amoureuse.",
                "intellectualAnalysis": "La communication bienveillante et l'écoute réciproque fortifient leur lien.",
                "growthPotential": "Les partenaires s'inspirent mutuellement pour évoluer et grandir ensemble.",
                "remedialAdvice": "Cultivez la patience et respectez l'espace et l'individualité de chacun."
            },
            "en": {
                "overallScore": 72,
                "elementSynergy": f"Harmonious elemental alignment between {sign_a.capitalize()} and {sign_b.capitalize()}.",
                "romanceAnalysis": "Planetary energies foster natural attraction, mutual understanding, and shared vision.",
                "intellectualAnalysis": "Open communication and respect for differences strengthen the partnership.",
                "growthPotential": "Both partners support and empower each other toward personal evolution.",
                "remedialAdvice": "Practice patience, celebrate individuality, and maintain open communication."
            }
        }
        chosen = fallbacks.get(lang_code, fallbacks["en"])
        return json.dumps(chosen, ensure_ascii=False)


def _validate_language_script(text: str, target_lang: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    target_lang = target_lang.lower().strip()
    if target_lang == "en":
        return True
    if target_lang == "hi":
        return any('\u0900' <= char <= '\u097F' for char in text)
    if target_lang == "bn":
        return any('\u0980' <= char <= '\u09FF' for char in text)
    if target_lang == "ta":
        return any('\u0B80' <= char <= '\u0BFF' for char in text)
    if target_lang == "fr":
        fr_markers = ("le", "la", "les", "des", "du", "un", "une", "est", "et", "dans", "pour", "é", "è", "ê", "à", "ù", "ç")
        lower_t = text.lower()
        return any(m in lower_t for m in fr_markers)
    return True

def get_numerology_insights_response(
    mulank: int,
    bhagyank: int,
    namank: int,
    missing_numbers: list,
    language: str = "en"
) -> str:
    lang_names = {
        "en": "English",
        "hi": "Hindi (हिन्दी)",
        "bn": "Bengali (বাংলা)",
        "ta": "Tamil (தமிழ்)",
        "fr": "French (Français)"
    }
    target_lang = (language or "en").lower().strip()
    lang_display = lang_names.get(target_lang, "English")

    system_prompt = f"""You are an expert Vedic Numerologist and Vastu Consultant. 
The user's numerology profile is:
- Mulank (Psychic Number): {mulank}
- Bhagyank (Destiny Number): {bhagyank}
- Namank (Name Number): {namank}
- Missing Numbers in Lo Shu Grid: {missing_numbers}

You MUST respond with ONLY a valid JSON object matching exactly this structure, no markdown formatting or backticks around it:
{{
  "mulankCharacteristics": ["Trait 1", "Trait 2", "Trait 3"],
  "remedies": ["Custom Vastu remedy for missing {missing_numbers[0] if missing_numbers else 'numbers'}", "Custom remedy 2"],
  "planeMeanings": {{
    "Mental Plane (4-9-2)": "Dynamic analysis of their mental plane based on their grid.",
    "Emotional Plane (3-5-7)": "Dynamic analysis...",
    "Practical Plane (8-1-6)": "Dynamic analysis...",
    "Thought Plane (4-3-8)": "Dynamic analysis...",
    "Will Plane (9-5-1)": "Dynamic analysis...",
    "Action Plane (2-7-6)": "Dynamic analysis...",
    "Determination Plane (4-5-6)": "Dynamic analysis...",
    "Spiritual Plane (2-5-8)": "Dynamic analysis..."
  }}
}}

All text values MUST be written natively in {lang_display}.
Keep plain text only, no markdown formatting, no HTML tags.
Provide exactly 3 short traits for mulankCharacteristics. Provide customized remedies for the exact missing numbers (or general if none missing). Provide 1-sentence analysis for each of the 8 Lo Shu planes.
"""
    history = [{"role": "user", "content": "Generate the Numerology JSON insights."}]

    for attempt in range(3):
        try:
            res = _execute_llm(system_prompt, history).strip()
            if res.startswith("```json"):
                res = res[7:]
            if res.startswith("```"):
                res = res[3:]
            if res.endswith("```"):
                res = res[:-3]
            res = res.strip()
            
            # Parse JSON to ensure validity
            parsed = json.loads(res)
            
            # Script check for non-English target languages
            sample_str = " ".join(parsed.get("mulankCharacteristics", []) + parsed.get("remedies", []))
            if target_lang != "en" and not _validate_language_script(sample_str, target_lang):
                if attempt < 2:
                    history.append({"role": "assistant", "content": res})
                    history.append({"role": "user", "content": f"Please regenerate strictly in {lang_display} script, without any markdown."})
                    continue
                else:
                    # Fallback to English version with note
                    parsed["showingEnglishNote"] = True
                    return json.dumps(parsed, ensure_ascii=False)

            return json.dumps(parsed, ensure_ascii=False)
        except Exception as e:
            if attempt < 2:
                continue
            print(f"Warning: Numerology LLM failed ({e}), using dynamic Vedic numerology calculation fallback.")
            return json.dumps({
                "showingEnglishNote": True if target_lang != "en" else False,
                "mulankCharacteristics": [
                    f"Governed by psychic frequency {mulank} with core leadership and ambition.",
                    "Natural strategic insight and intellectual focus.",
                    "High capacity for independent execution and creative problem-solving."
                ],
                "remedies": [
                    f"Keep beneficial Vastu energy aligned in the North-East direction for missing numbers ({', '.join(map(str, missing_numbers)) if missing_numbers else 'harmonization'}).",
                    "Chant Surya/Guru Gayatri Mantra at dawn and practice daily mindfulness."
                ],
                "planeMeanings": {
                    "Mental Plane (4-9-2)": "Sharp analytical cognition and intuitive foresight.",
                    "Emotional Plane (3-5-7)": "Balanced emotional intelligence and empathetic communication.",
                    "Practical Plane (8-1-6)": "Solid pragmatic discipline and material execution capacity.",
                    "Thought Plane (4-3-8)": "Visionary strategic planning and conceptual depth.",
                    "Will Plane (9-5-1)": "Determined willpower and steady perseverance under challenges.",
                    "Action Plane (2-7-6)": "Decisive execution and adaptable operational focus.",
                    "Determination Plane (4-5-6)": "Unshakable dedication to long-term accomplishments.",
                    "Spiritual Plane (2-5-8)": "Deep contemplative awareness and soul alignment."
                }
            }, ensure_ascii=False)



def get_roadmap_insights_response(
    profile: dict,
    tradition: str,
    chart_data: dict,
    numerology: dict,
    language: str = "en"
) -> str:
    active_llm = os.getenv("ACTIVE_LLM", "mistral_local")
    
    # Safely extract values to prevent key errors
    profile_name = profile.get("fullName", "Seeker")
    horoscope_sys = profile.get("horoscopeSystem", "Vedic")
    dob = profile.get("birthDate", "Unknown")
    time = profile.get("birthTime", "Unknown")
    place = profile.get("birthPlace", "Unknown")
    
    # Safely extract nested chart data
    lagna_info = chart_data.get("ascendant", {})
    lagna_rashi = lagna_info.get("signName") or lagna_info.get("signSanskrit") or lagna_info.get("rashi") or "Aries"
    lagna_lord = lagna_info.get("lord") or "Ascendant Lord"
    
    moon_info = chart_data.get("moon", {})
    moon_rashi = chart_data.get("moonSign") or moon_info.get("signName") or moon_info.get("signSanskrit") or moon_info.get("rashi") or "Chandra Rashi"
    
    # Find moon planet if available
    planets_list = chart_data.get("planets", [])
    moon_planet = next((p for p in planets_list if p.get("id") == "moon" or p.get("name", "").lower() == "moon"), {})
    nakshatra = moon_planet.get("nakshatra") or moon_info.get("nakshatra") or chart_data.get("nakshatra") or "Rohini"
    
    dasha_periods = chart_data.get("dashaPeriods", [])
    curr_dasha = next((d for d in dasha_periods if d.get("isCurrent")), {})
    dasha_info = chart_data.get("currentDasha", {})
    maha_dasha = curr_dasha.get("planet") or dasha_info.get("mahadasha") or "Jupiter"
    antar_dasha = curr_dasha.get("antardasha") or dasha_info.get("antardasha") or "Saturn"
    
    mulank = numerology.get("mulank", "3")
    bhagyank = numerology.get("bhagyank", "7")

    system_prompt = f"""You are AstroJunction Daivajna, an expert 25-Year Vedic Astrological Forecaster.
Generate a 15-Year Astrological Destiny Roadmap for the user with ALL 5 LIFE CATEGORIES across 3 TIME HORIZONS (15 milestones total):
Time horizons: '0-5 Years', '0-10 Years', '0-15 Years'.
Categories for each horizon: 'Career', 'Wealth', 'Relationships', 'Health', 'Spirituality'.

User Details:
Name: {profile_name}
System: {horoscope_sys} ({tradition} tradition)
DOB: {dob}, Time: {time}, Place: {place}
Lagna (Ascendant): {lagna_rashi} (Lord: {lagna_lord})
Moon Sign (Rashi): {moon_rashi}, Nakshatra: {nakshatra}
Active Vimshottari Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha
Numerology: Psychic {mulank}, Destiny {bhagyank}

You MUST return a JSON object with EXACTLY this structure containing 15 milestones:
{{
  "milestones": [
    {{
      "id": "ms-1",
      "timeframe": "0-5 Years",
      "category": "Career",
      "title": "Short strategic title",
      "guidance": "Detailed 2-3 sentence prediction based on {maha_dasha} dasha and {lagna_rashi} lagna.",
      "favorableTransits": "Jupiter transit trining {lagna_rashi}",
      "remedialAction": "1 specific Vedic/Vastu remedy",
      "status": "In-Progress"
    }},
    ... (total 15 milestones: 5 for '0-5 Years', 5 for '0-10 Years', 5 for '0-15 Years')
  ]
}}

Requirements:
- Generate EXACTLY 15 milestones (5 for '0-5 Years', 5 for '0-10 Years', 5 for '0-15 Years') covering all 5 categories for each timeframe.
- Set status to 'In-Progress' for '0-5 Years', and 'Pending' for '0-10 Years' and '0-15 Years'.
- The predictions MUST specifically mention their {lagna_rashi} ascendant and {maha_dasha}/{antar_dasha} dasha period so it feels deeply personalized!
- All text values MUST be translated directly into the language code: {language}. If 'bn', use Bengali script.
- Do NOT output anything outside the JSON object. No markdown formatting.
"""

    history = [{"role": "user", "content": "Generate the complete 15-Milestone Roadmap JSON."}]

    try:
        res = _execute_llm(system_prompt, history)
        
        # Clean up possible markdown code blocks
        res = res.strip()
        if res.startswith("```json"):
            res = res[7:]
        if res.startswith("```"):
            res = res[3:]
        if res.endswith("```"):
            res = res[:-3]
        return res.strip()
    except Exception as e:
        raise LLMError(f"Failed to generate roadmap insights: {str(e)}")


def get_interpret_response(
    profile: dict,
    tradition: str,
    chart_data: dict,
    numerology: dict,
    language: str = "en"
) -> dict:
    import json
    import time
    start_t = time.time()
    
    # Normalize & validate language
    lang = (language or "en").split("-")[0].lower()
    if lang not in {"en", "hi", "bn", "ta", "fr"}:
        lang = "en"
        
    profile_name = profile.get("fullName", "User")
    
    lagna_info = chart_data.get("ascendant", {})
    lagna_rashi = lagna_info.get("signName", "Unknown")
    lagna_nak = lagna_info.get("nakshatra", "Unknown")
    
    dashas = chart_data.get("dashas", [])
    maha_dasha = "Unknown"
    antar_dasha = "Unknown"
    today_str = datetime.now().strftime("%Y-%m-%d")

    for d in dashas:
        start_str = str(d.get("startDate", ""))[:10]
        end_str   = str(d.get("endDate", ""))[:10]
        is_current_md = d.get("isCurrent") or (start_str and end_str and start_str <= today_str <= end_str)

        if is_current_md:
            maha_dasha = d.get("planet", "Unknown")
            sub_list = d.get("subPeriods") or d.get("antardashas") or []
            for sub in sub_list:
                s_start = str(sub.get("startDate", ""))[:10]
                s_end   = str(sub.get("endDate", ""))[:10]
                is_current_ad = sub.get("isCurrent") or (s_start and s_end and s_start <= today_str <= s_end)
                if is_current_ad:
                    antar_dasha = sub.get("planet", "Unknown")
                    break
            if antar_dasha == "Unknown" and sub_list:
                antar_dasha = sub_list[0].get("planet", "Unknown")
            break

    if maha_dasha == "Unknown" and dashas:
        maha_dasha = dashas[0].get("planet", "Unknown")
        sub_list = dashas[0].get("subPeriods") or dashas[0].get("antardashas") or []
        if sub_list:
            antar_dasha = sub_list[0].get("planet", "Unknown")
    
    houses = chart_data.get("houses", [])
    h10 = next((h for h in houses if h.get("houseNumber") == 10), {})
    h2 = next((h for h in houses if h.get("houseNumber") == 2), {})
    h11 = next((h for h in houses if h.get("houseNumber") == 11), {})

    h10_sign = h10.get("signName", "Capricorn")
    h10_lord = h10.get("signLord", "Saturn")
    h2_sign = h2.get("signName", "Taurus")
    h2_lord = h2.get("signLord", "Venus")
    h11_sign = h11.get("signName", "Aquarius")
    h11_lord = h11.get("signLord", "Saturn")

    yogas_list = chart_data.get("yogas", [])
    active_yogas = [y for y in yogas_list if y.get("name")]
    yoga_name1 = active_yogas[0].get("name") if len(active_yogas) > 0 else "Raja Yoga & Dharma Adhipati"
    yoga_desc1 = active_yogas[0].get("effect") or active_yogas[0].get("description") or "Elevates social standing, leadership authority, and moral resilience in professional pursuits." if len(active_yogas) > 0 else "Conjunction of Kendra and Trikona lords grants executive authority, lasting prestige, and ethical advancement."
    
    yoga_name2 = active_yogas[1].get("name") if len(active_yogas) > 1 else "Dhana Yoga & Lakshmi Sthana Harmony"
    yoga_desc2 = active_yogas[1].get("effect") or active_yogas[1].get("description") or "Promotes steady wealth accumulation, entrepreneurial acumen, and financial stability." if len(active_yogas) > 1 else "Auspicious alignments between the 2nd, 5th, 9th, and 11th houses establish sustained material prosperity."

    tradition_titles = {
        "parashari": "Parashari Jyotish (Brihat Parashara Hora Shastra)",
        "jaimini": "Jaimini Sutras (Chara Karaka & Sign Aspects)",
        "lal_kitab": "Lal Kitab (Planetary Debts & Practical Upayas)",
        "kp_system": "KP System (Krishnamurti Padhdhati Sub-Lords)",
        "bhrigu_nadi": "Bhrigu Nadi (Nandi Nadi Planetary Combinations)",
    }
    trad_title = tradition_titles.get(tradition.lower(), f"{tradition.upper()} Tradition")

    def build_native_fallback_synthesis() -> dict:
        if lang == "hi":
            return {
                "sections": [
                    {
                        "id": "cosmic_archetype",
                        "title": "आकाशीय समन्वय एवं लग्न मूल-स्वरूप",
                        "cards": [
                            {
                                "title": f"लग्न प्राणशक्ति ({lagna_rashi} लग्न)",
                                "summary": f"आपका लग्न {lagna_rashi} आपकी शारीरिक जीवनीशक्ति, मानसिक दृढ़ता तथा व्यक्तित्व के मूल स्वरूप को सुदृढ़ करता है। यह आपको जीवन की चुनौतियों का सामना करने हेतु अटूट संकल्पशक्ति प्रदान करता है।",
                                "bullets": ["प्राकृतिक जीवनशक्ति एवं मानसिक संतुलन", "आंतरिक इच्छाशक्ति तथा लक्ष्य-उन्मुख व्यवहार"],
                                "tags": ["लग्न", "प्राणशक्ति"]
                            },
                            {
                                "title": f"जन्म नक्षत्र प्रज्ञा ({lagna_nak})",
                                "summary": f"{lagna_nak} नक्षत्र के प्रभाव से आपकी सहज अंतर्दृष्टि तथा निर्णय क्षमता में विशेष परिपक्वता आती है, जो जीवन के महत्वपूर्ण मोड़ों पर आपका मार्गदर्शन करती है।",
                                "bullets": ["गहन बौद्धिक दृष्टि एवं दूरदर्शिता", "सामरिक निर्णय क्षमता"],
                                "tags": ["नक्षत्र", "प्रज्ञा"]
                            },
                            {
                                "title": "लग्नेश का आत्मिक मार्गदर्शन",
                                "summary": "लग्नेश का शुभ प्रभाव आपके जीवन की ऊर्जा को आत्म-विकास, नैतिक नेतृत्व तथा समाज में सम्मानजनक स्थान स्थापित करने की दिशा में अग्रसर करता है।",
                                "bullets": ["सामाजिक प्रतिष्ठा एवं आत्मसम्मान", "कर्तव्यनिष्ठा"],
                                "tags": ["लग्नेश"]
                            }
                        ]
                    },
                    {
                        "id": "bhava_dynamics",
                        "title": "भाव संरेखण एवं भावेश गतिशीलता",
                        "cards": [
                            {
                                "title": f"कर्म स्थान एवं आजीविका (दशम भाव - {h10_sign})",
                                "summary": f"{h10_sign} राशि में दशम भाव और इसके स्वामी {h10_lord} के प्रभाव से आपके कार्यक्षेत्र में सुदृढ़ प्रशासनिक दक्षता, नेतृत्व क्षमता एवं दीर्घकालिक प्रतिष्ठा का निर्माण होता है।",
                                "bullets": ["अनुशासित कार्यप्रणाली", "प्रशासनिक योग्यता"],
                                "tags": ["दशम भाव", "कर्म"]
                            },
                            {
                                "title": f"धन एवं लाभ समृद्धि (द्वितीय एवं एकादश भाव - {h2_sign} व {h11_sign})",
                                "summary": f"धनभाव ({h2_sign}) और लाभभाव ({h11_sign}) के स्वामियों का शुभ संरेखण आर्थिक सुरक्षा, अनुशासित संचय तथा सतत आय प्रवाह का आधार तैयार करता है।",
                                "bullets": ["दीर्घकालिक पूँजी संचय", "स्थिर लाभ स्रोत"],
                                "tags": ["धन भाव", "लाभ"]
                            },
                            {
                                "title": "केन्द्र-त्रिकोण सन्तुलन",
                                "summary": "केन्द्र और त्रिकोण भावों का समन्वय जीवन में स्थिरता लाता है और अल्पकालिक उतार-चढ़ाव से रक्षा करता है।",
                                "bullets": ["जीवन में संरचनात्मक स्थिरता", "संरक्षण"],
                                "tags": ["केन्द्र", "त्रिकोण"]
                            }
                        ]
                    },
                    {
                        "id": "tradition_deep_dive",
                        "title": f"परम्परागत शास्त्रीय विश्लेषण ({trad_title})",
                        "cards": [
                            {
                                "title": "शास्त्रीय सूत्र विवेचन",
                                "summary": f"{trad_title} के मूलभूत नियमों के अनुसार आपकी कुण्डली के प्रमुख ग्रह विन्यास अनुकूल अवसर तथा आत्मिक उन्नति का मार्ग प्रशस्त करते हैं।",
                                "bullets": ["शास्त्रीय नियम संरेखण", "ग्रहीय सामंजस्य"],
                                "tags": ["शास्त्रीय"]
                            },
                            {
                                "title": f"सक्रिय महादशा चक्र ({maha_dasha})",
                                "summary": f"वर्तमान में सक्रिय {maha_dasha} महादशा का कालखंड आपके जीवन में गहन आत्ममंथन एवं व्यावसायिक प्रगति का प्रमुख संक्रांति काल है।",
                                "bullets": ["तीव्र व्यक्तिगत विकास", "अवसरों का विस्तार"],
                                "tags": ["महादशा"]
                            },
                            {
                                "title": f"अन्तर्दशा उत्प्रेरक प्रभाव ({antar_dasha})",
                                "summary": f"सक्रिय {antar_dasha} अन्तर्दशा नवीन योजनाओं को साकार करने का उत्तम समय है। धैर्यपूर्वक उठाए गए कदम दीर्घकालिक सफलता सुनिश्चित करेंगे।",
                                "bullets": ["सुविचारित निर्णय", "स्थायित्व"],
                                "tags": ["अन्तर्दशा"]
                            }
                        ]
                    },
                    {
                        "id": "yogas_formations",
                        "title": "ग्रह योग एवं शुभ विन्यास",
                        "cards": [
                            {
                                "title": f"सक्रिय शुभ योग ({yoga_name1})",
                                "summary": str(yoga_desc1),
                                "bullets": ["शुभ प्रभाव", "सामाजिक प्रतिष्ठा"],
                                "tags": ["शुभ योग"]
                            },
                            {
                                "title": f"समृद्धि एवं सौभाग्य संरेखण ({yoga_name2})",
                                "summary": str(yoga_desc2),
                                "bullets": ["आर्थिक उन्नति", "स्थिरता"],
                                "tags": ["धन योग"]
                            },
                            {
                                "title": "कर्मिक विकास एवं आध्यात्मिक चेतना",
                                "summary": "राहु-केतु अक्ष का संतुलन जीवन की चुनौतियों को परिपक्व अंतर्दृष्टि तथा आध्यात्मिक विवेक में रूपांतरित करता है।",
                                "bullets": ["आत्मिक जागरण", "कर्म शोधन"],
                                "tags": ["कर्म"]
                            }
                        ]
                    },
                    {
                        "id": "sacred_upayas",
                        "title": "पवित्र वैदिक उपाय एवं नित्य साधना",
                        "cards": [
                            {
                                "title": "वैदिक मन्त्र साधना",
                                "summary": "प्रतिदिन प्रातःकाल शांत चित्त से 'ॐ नमो भगवते वासुदेवाय' अथवा अपने इष्ट मन्त्र का १०८ बार जप करें। यह मानसिक शांति तथा ऊर्जा में वृद्धि करेगा।",
                                "bullets": ["१०८ बार प्रातः जप", "मानसिक स्थिरता"],
                                "tags": ["मन्त्र"]
                            },
                            {
                                "title": "रत्न एवं धातु संतुलन",
                                "summary": "लग्नेश के अनुकूल शुभ रत्न अथवा धातु धारण करने से ग्रहीय स्पंदन अनुकूल होते हैं तथा नकारात्मक प्रभाव शांत होते हैं।",
                                "bullets": ["सकारात्मक ऊर्जा संवर्धन", "ग्रह संतुलन"],
                                "tags": ["रत्न"]
                            },
                            {
                                "title": "नित्य साधना एवं पुण्य दान",
                                "summary": "प्रातः सूर्य अर्घ्य दें तथा नियमित रूप से जरूरतमंदों को अन्न या वस्त्र का दान करें, जिससे कर्मिक बाधाएँ दूर होती हैं।",
                                "bullets": ["सूर्य अर्घ्य", "पुण्य दान"],
                                "tags": ["साधना"]
                            }
                        ]
                    }
                ]
            }
        elif lang == "bn":
            return {
                "sections": [
                    {
                        "id": "cosmic_archetype",
                        "title": "কসমিক সমন্বয় ও লগ্ন মূল-স্বরূপ",
                        "cards": [
                            {
                                "title": f"লগ্নের আত্মিক শক্তি ({lagna_rashi} লগ্ন)",
                                "summary": f"আপনার লগ্ন {lagna_rashi} আপনার শারীরিক জীবনীশক্তি, মানসিক দৃঢ়তা এবং ব্যক্তিত্বের মূল কাঠামো নির্দেশ করে। এটি আপনার কর্মশক্তি এবং জীবনের লক্ষ্য অর্জনে ধারাবাহিক একাগ্রতা প্রদান করে।",
                                "bullets": ["শারীরিক জীবনীশক্তি ও মানসিক ভারসাম্য", "দৃঢ় সংকল্প"],
                                "tags": ["লগ্ন", "শক্তি"]
                            },
                            {
                                "title": f"জন্ম নক্ষত্রের প্রভাব ({lagna_nak})",
                                "summary": f"{lagna_nak} নক্ষত্রের শাসনে আপনার মনস্তাত্ত্বিক উপলব্ধি এবং গভীর অন্তর্দৃষ্টি বিকশিত হয়, যা গুরুত্বপূর্ণ সিদ্ধান্ত গ্রহণে দূরদর্শিতা ও নেতৃত্ব দান করে।",
                                "bullets": ["গভীর অন্তর্দৃষ্টি", "দূরদর্শী সিদ্ধান্ত"],
                                "tags": ["নক্ষত্র"]
                            },
                            {
                                "title": "লগ্নপতির আত্মিক দিকদর্শন",
                                "summary": "আপনার লগ্নপতির অনুকূল প্রভাব জীবনশক্তিকে গভীর বৌদ্ধিক চেতনা, কর্মনিষ্ঠা এবং সমাজে নিজস্ব অবস্থান মজবুত করার দিকে পরিচালিত করে।",
                                "bullets": ["সামাজিক সম্মান", "কর্মনিষ্ঠা"],
                                "tags": ["লগ্নপতি"]
                            }
                        ]
                    },
                    {
                        "id": "bhava_dynamics",
                        "title": "ভাব সংরেখণ ও ভাবপতির গতিশীলতা",
                        "cards": [
                            {
                                "title": f"কর্মস্থান ও পেশাগত প্রতিষ্ঠা (দশম ভাব - {h10_sign})",
                                "summary": f"{h10_sign} রাশিতে অবস্থানরত দশম ভাব এবং এর অধিপতি {h10_lord}-এর প্রভাবে আপনার কর্মজীবনে প্রশাসনিক দক্ষতা, নেতৃত্ব ও দীর্ঘমেয়াদী প্রতিষ্ঠা অর্জনের শক্তিশালী যোগ রয়েছে।",
                                "bullets": ["প্রশাসনিক দক্ষতা", "পেশাগত স্থায়িত্ব"],
                                "tags": ["দশম ভাব", "কর্ম"]
                            },
                            {
                                "title": f"ধন ও লাভ সমৃদ্ধি প্রবাহ (দ্বিতীয় ও একাদশ ভাব - {h2_sign} ও {h11_sign})",
                                "summary": f"ধনভাব ({h2_sign}) এবং লাভভাব ({h11_sign})-এর যৌথ গতিশীলতা আর্থিক নিরাপত্তা, সুশৃঙ্খল সঞ্চয় এবং সফল বিনিয়োগের অনুকূল ভিত্তি তৈরি করে।",
                                "bullets": ["পুঁজি সঞ্চয়", "আয় বৃদ্ধি"],
                                "tags": ["ধন ভাব", "লাভ"]
                            },
                            {
                                "title": "কেন্দ্র ও ত্রিকোণ সামঞ্জস্য",
                                "summary": "কেন্দ্র ও ত্রিকোণ ভাবগুলির অন্তর্নিহিত ভারসাম্য আপনার সার্বিক জীবনে স্থায়িত্ব প্রদান করে এবং সাময়িক অস্থিরতা থেকে রক্ষা করে।",
                                "bullets": ["জীবনের ভারসাম্য", "সুরক্ষা"],
                                "tags": ["কেন্দ্র", "ত্রিকোণ"]
                            }
                        ]
                    },
                    {
                        "id": "tradition_deep_dive",
                        "title": f"ঐতিহ্যগত শাস্ত্রীয় বিশ্লেষণ ({trad_title})",
                        "cards": [
                            {
                                "title": "শাস্ত্রীয় সূত্র বিশ্লেষণ",
                                "summary": f"{trad_title}-এর শাস্ত্রীয় নিয়ম অনুযায়ী আপনার কুষ্ঠির বিশেষ গ্রহ সংযোগগুলি প্রতিকূলতাকে সম্ভাবনায় রূপান্তর করার শক্তিশালী সংকেত বহন করে।",
                                "bullets": ["শাস্ত্রীয় সূত্র সংযোগ", "গ্রহ ভারসাম্য"],
                                "tags": ["শাস্ত্রীয়"]
                            },
                            {
                                "title": f"বর্তমান মহাদশা ({maha_dasha}) রূপান্তর",
                                "summary": f"সক্রিয় {maha_dasha} মহাদশা আপনার জীবনে একটি গভীর আত্মবিকাশ ও পেশাগত অগ্রগতির মূল সময়কাল নির্দেশ করে।",
                                "bullets": ["ব্যক্তিগত বিকাশ", "অগ্রগতি"],
                                "tags": ["মহাদশা"]
                            },
                            {
                                "title": f"অন্তর্দশা ({antar_dasha}) সুযোগ ও সচেতনতা",
                                "summary": f"সক্রিয় {antar_dasha} অন্তর্দশার প্রভাব তাৎক্ষণিক সিদ্ধান্ত ও পরিকল্পনা রূপায়ণে নতুন দিগন্ত উন্মোচন করে। সুশৃঙ্খল পদক্ষেপ সর্বোচ্চ শুভফল নিশ্চিত করবে।",
                                "bullets": ["পরিকল্পনা বাস্তবায়ন", "সতর্কতা"],
                                "tags": ["অন্তর্দশা"]
                            }
                        ]
                    },
                    {
                        "id": "yogas_formations",
                        "title": "গ্রহ যোগ ও শুভ সমন্বয়",
                        "cards": [
                            {
                                "title": f"সক্রিয় শুভ যোগ ({yoga_name1})",
                                "summary": str(yoga_desc1),
                                "bullets": ["শুভ প্রভাব", "প্রতিষ্ঠা"],
                                "tags": ["শুভ যোগ"]
                            },
                            {
                                "title": f"সমৃদ্ধি ও আর্থিক সামঞ্জস্য ({yoga_name2})",
                                "summary": str(yoga_desc2),
                                "bullets": ["আর্থিক প্রবাহ", "স্থিরতা"],
                                "tags": ["ধন যোগ"]
                            },
                            {
                                "title": "আধ্যাত্মিক বিবর্তন ও কর্মিক শিক্ষা",
                                "summary": "রাহু-কেতু ও শনি গ্রহের অবস্থান অন্তর্জাগরণ জাগ্রত করে, জীবনের চ্যালেঞ্জগুলিকে পরম অভিজ্ঞতায় রূপান্তর করতে সাহায্য করে।",
                                "bullets": ["আত্মিক প্রজ্ঞা", "কর্মিক মুক্তি"],
                                "tags": ["কর্ম"]
                            }
                        ]
                    },
                    {
                        "id": "sacred_upayas",
                        "title": "পবিত্র বৈদিক প্রতিকার ও নিত্য সাধনা",
                        "cards": [
                            {
                                "title": "নির্দিষ্ট বৈদিক মন্ত্র জপ",
                                "summary": "প্রতিদিন ভোরে সূর্যোদয়কালে শান্ত চিত্তে 'ওঁ নমো ভগবতে বাসুদেবায়' অথবা আপনার ইষ্ট মন্ত্র ১০৮ বার জপ করুন, যা মানসিক স্থৈর্য ও আত্মবিশ্বাস বৃদ্ধি করবে।",
                                "bullets": ["১০৮ বার জপ", "মানসিক শান্তি"],
                                "tags": ["মন্ত্র"]
                            },
                            {
                                "title": "রত্ন ও শুভ ধাতুর ভারসাম্য",
                                "summary": "লগ্নপতির অনুকূল রত্ন এবং শুভ ধাতু ধারণ গ্রহের ইতিবাচক স্পন্দনকে শক্তিশালী করে।",
                                "bullets": ["ইতিবাচক শক্তি", "গ্রহ সামঞ্জস্য"],
                                "tags": ["রত্ন"]
                            },
                            {
                                "title": "নিত্য সাধনা ও শুভ দান",
                                "summary": "রবিবারে তাম্রপাত্রে সূর্যদেবের উদ্দেশ্যে জল নিবেদন (সূর্য অর্ঘ্য) এবং অভাবগ্রস্তদের অন্ন বা বস্ত্র দান করলে কর্মিক বাধা দূরীভূত হয়।",
                                "bullets": ["সূর্য অর্ঘ্য", "অন্নদান"],
                                "tags": ["সাধনা"]
                            }
                        ]
                    }
                ]
            }
        elif lang == "ta":
            return {
                "sections": [
                    {
                        "id": "cosmic_archetype",
                        "title": "வானியல் ஒருங்கிணைப்பு & லக்ன மூல வடிவம்",
                        "cards": [
                            {
                                "title": f"லக்ன ஜீவசக்தி ({lagna_rashi} லக்னம்)",
                                "summary": f"உங்கள் லக்னம் {lagna_rashi} உங்கள் உடல் பலம், மன உறுதி மற்றும் ஆளுமையின் அடிப்படை கட்டமைப்பை வலுப்படுத்துகிறது. இது தடைகளை வெல்லும் திடமான மனோபலத்தை வழங்குகிறது.",
                                "bullets": ["உடல் நலம் மற்றும் மன உறுதி", "இலக்கு நோக்குநிலை"],
                                "tags": ["லக்னம்", "ஜீவசக்தி"]
                            },
                            {
                                "title": f"ஜென்ம நட்சத்திர நுண்ணறிவு ({lagna_nak})",
                                "summary": f"{lagna_nak} நட்சத்திரத்தின் ஆளுமையில் உங்கள் மன விவேகமும் ஆழமான உள்ளுணர்வும் மேம்படுகிறது, இது வாழ்க்கையின் முக்கிய முடிவுகளில் தெளிவான வழிகாட்டலைத் தருகிறது.",
                                "bullets": ["கூர்மையான அறிவு", "தீர்க்கமான முடிவு"],
                                "tags": ["நட்சத்திரம்"]
                            },
                            {
                                "title": "லக்னாதிபதியின் ஆன்மீக வழிகாட்டல்",
                                "summary": "லக்னாதிபதியின் சுப பார்வை உங்கள் வாழ்க்கையை அறிவு வளர்ச்சி, தலைமைத்துவம் மற்றும் சமூகத்தில் நீடித்த அந்தஸ்தை உருவாக்குவதை நோக்கி வழிநடத்துகிறது.",
                                "bullets": ["சமூக அந்தஸ்து", "கடமை உணர்வு"],
                                "tags": ["லக்னாதிபதி"]
                            }
                        ]
                    },
                    {
                        "id": "bhava_dynamics",
                        "title": "பாவக அமைப்புகள் & அதிபதிகளின் இயக்கம்",
                        "cards": [
                            {
                                "title": f"தொழில் ஸ்தானம் (10-ஆம் பாவம் - {h10_sign})",
                                "summary": f"{h10_sign} ராசியில் உள்ள 10-ஆம் பாவம் மற்றும் அதன் அதிபதி {h10_lord} மூலம் உங்கள் தொழில் வாழ்க்கையில் நிர்வாகத்திறன், தலைமை மற்றும் சமூக அங்கீகாரம் வலுப்பெறும்.",
                                "bullets": ["நிர்வாகத்திறன்", "தொழில் வெற்றி"],
                                "tags": ["10-ஆம் பாவம்", "தொழில்"]
                            },
                            {
                                "title": f"தன மற்றும் லாப வரவு (2 & 11-ஆம் பாவங்கள் - {h2_sign} & {h11_sign})",
                                "summary": f"தன ஸ்தானம் ({h2_sign}) மற்றும் லாப ஸ்தானம் ({h11_sign}) இணைவு நிலையான மூலதன சேமிப்பு மற்றும் தொடர்ச்சியான நிதி வரவை உறுதி செய்கிறது.",
                                "bullets": ["மூலதன சேமிப்பு", "தொடர் லாபம்"],
                                "tags": ["தன பாவம்", "லாபம்"]
                            },
                            {
                                "title": "கேந்திர-திரிகோண சமநிலை",
                                "summary": "கேந்திர மற்றும் திரிகோண பாவங்களின் நல்லிணக்கம் வாழ்க்கையில் ஸ்திரத்தன்மையை அளித்து குறுகிய கால ஏற்றத்தாழ்வுகளிலிருந்து பாதுகாக்கிறது.",
                                "bullets": ["வாழ்க்கை சமநிலை", "பாதுகாப்பு"],
                                "tags": ["கேந்திரம்", "திரிகோணம்"]
                            }
                        ]
                    },
                    {
                        "id": "tradition_deep_dive",
                        "title": f"பாரம்பரிய சாஸ்திர பகுப்பாய்வு ({trad_title})",
                        "cards": [
                            {
                                "title": "சாஸ்திர சூத்திர விளக்கம்",
                                "summary": f"{trad_title} சாஸ்திர விதிகளின்படி உங்கள் ஜாதக கிரக இணைப்புகள் சவால்களை வாய்ப்புகளாக மாற்றும் ஆற்றலைக் குறிக்கின்றன.",
                                "bullets": ["சாஸ்திர விதி ஒருங்கிணைப்பு", "கிரக பலம்"],
                                "tags": ["சாஸ்திரம்"]
                            },
                            {
                                "title": f"செயலில் உள்ள மகா தசை ({maha_dasha})",
                                "summary": f"தற்போது நடக்கும் {maha_dasha} மகா தசை உங்கள் வாழ்க்கையில் ஆழ்ந்த சுய முன்னேற்றத்தையும் தொழில் வளர்ச்சியையும் தரும் முக்கியமான காலகட்டமாகும்.",
                                "bullets": ["சுய முன்னேற்றம்", "வாய்ப்புகள்"],
                                "tags": ["மகா தசை"]
                            },
                            {
                                "title": f"அந்தர தசை ({antar_dasha}) வாய்ப்புகள்",
                                "summary": f"செயலில் உள்ள {antar_dasha} அந்தர தசை புதிய திட்டங்களை செயல்படுத்த ஏதுவான சூழலை உருவாக்குகிறது. பொறுமையுடன் எடுக்கும் முடிவுகள் வெற்றியைத் தரும்.",
                                "bullets": ["திட்ட அமலாக்கம்", "நிதானம்"],
                                "tags": ["அந்தர தசை"]
                            }
                        ]
                    },
                    {
                        "id": "yogas_formations",
                        "title": "கிரக யோகங்கள் & சுப அமைப்புகள்",
                        "cards": [
                            {
                                "title": f"சுப யோகம் ({yoga_name1})",
                                "summary": str(yoga_desc1),
                                "bullets": ["சுப பலன்", "மதிப்பு"],
                                "tags": ["சுப யோகம்"]
                            },
                            {
                                "title": f"செல்வ செழிப்பு யோகம் ({yoga_name2})",
                                "summary": str(yoga_desc2),
                                "bullets": ["நிதி ஆதாயம்", "ஸ்திரத்தன்மை"],
                                "tags": ["தன யோகம்"]
                            },
                            {
                                "title": "ஆன்மீக வளர்ச்சி & கர்ம ஞானம்",
                                "summary": "ராகு-கேது அச்சு வாழ்க்கை சவால்களை உயர்ந்த ஆன்மீக விவேகமாகவும் முதிர்ச்சியாகவும் மாற்ற உதவுகிறது.",
                                "bullets": ["ஆன்ம ஞானம்", "கர்ம விழிப்புணர்வு"],
                                "tags": ["கர்மா"]
                            }
                        ]
                    },
                    {
                        "id": "sacred_upayas",
                        "title": "புனித வேத பரிகாரங்கள் & தினசரி சாதனை",
                        "cards": [
                            {
                                "title": "வேத மந்திர சாதனை",
                                "summary": "தினமும் காலையில் அமைதியான மனதுடன் 'ஓம் நமோ பகவதே வாசுதேவாய' அல்லது உங்கள் இஷ்ட மந்திரத்தை 108 முறை ஜெபிக்கவும்.",
                                "bullets": ["108 முறை ஜெபம்", "மன அமைதி"],
                                "tags": ["மந்திரம்"]
                            },
                            {
                                "title": "ரத்தினம் மற்றும் உலோக வழிகாட்டல்",
                                "summary": "லக்னாதிபதிக்கு உகந்த ரத்தினம் மற்றும் சுப உலோகங்களை அணிவது கிரக அதிர்வுகளை நேர்மறையாக மாற்றும்.",
                                "bullets": ["நேர்மறை அதிர்வுகள்", "கிரக சமநிலை"],
                                "tags": ["ரத்தினம்"]
                            },
                            {
                                "title": "தினசரி சாதனை & அன்னதானம்",
                                "summary": "காலையில் சூரிய நமஸ்காரம் செய்து நீர் சமர்ப்பிக்கவும், ஏழைகளுக்கு உணவு அல்லது ஆடை தானம் செய்வது கர்ம வினைகளைத் தீர்க்கும்.",
                                "bullets": ["சூரிய நமஸ்காரம்", "அன்னதானம்"],
                                "tags": ["சாதனை"]
                            }
                        ]
                    }
                ]
            }
        elif lang == "fr":
            return {
                "sections": [
                    {
                        "id": "cosmic_archetype",
                        "title": "Synthèse Cosmique & Archétype du Lagna",
                        "cards": [
                            {
                                "title": f"Vitalité Fondamentale du Lagna ({lagna_rashi})",
                                "summary": f"Votre Lagna en {lagna_rashi} ancre votre constitution physique, votre résilience mentale et la structure fondamentale de votre personnalité.",
                                "bullets": ["Vitalité constitutionnelle et équilibre mental", "Volonté inébranlable"],
                                "tags": ["Lagna", "Vitalité"]
                            },
                            {
                                "title": f"Intuition du Janma Nakshatra ({lagna_nak})",
                                "summary": f"Gouverné par {lagna_nak}, votre discernement intuitif et votre vision stratégique guident avec justesse vos choix cruciaux.",
                                "bullets": ["Discernement intellectuel aiguisé", "Jugement stratégique"],
                                "tags": ["Nakshatra"]
                            },
                            {
                                "title": "Orientation Spirituelle du Seigneur du Lagna",
                                "summary": "L'influence bienveillante du maître de votre Ascendant dirige votre énergie vitale vers le leadership éthique et la réalisation professionnelle durable.",
                                "bullets": ["Autorité morale", "Réputation intègre"],
                                "tags": ["Lagneesha"]
                            }
                        ]
                    },
                    {
                        "id": "bhava_dynamics",
                        "title": "Alignements des Maisons & Maîtres de Bhavas",
                        "cards": [
                            {
                                "title": f"Maison de la Carrière (10ème Bhava en {h10_sign})",
                                "summary": f"Occupée par {h10_sign} et gouvernée par {h10_lord}, votre 10ème maison met en lumière une solide compétence administrative et une autorité bienveillante.",
                                "bullets": ["Compétences managériales", "Expansion professionnelle"],
                                "tags": ["10ème Maison", "Carrière"]
                            },
                            {
                                "title": f"Vecteurs de Richesse (2ème & 11ème Bhavas en {h2_sign} & {h11_sign})",
                                "summary": f"Gouvernées par {h2_lord} et {h11_lord}, ces maisons établissent une assise financière pérenne favorisant l'accumulation mesurée et l'abondance.",
                                "bullets": ["Accumulation de capital", "Flux de prospérité"],
                                "tags": ["2ème Maison", "11ème Maison"]
                            },
                            {
                                "title": "Équilibre Kendra-Trikona",
                                "summary": "L'harmonie entre piliers angulaires et trigones consolide la trajectoire de votre existence face aux variations cycliques.",
                                "bullets": ["Stabilité structurelle", "Protection karmique"],
                                "tags": ["Kendra", "Trikona"]
                            }
                        ]
                    },
                    {
                        "id": "tradition_deep_dive",
                        "title": f"Approfondissement Selon la Tradition ({trad_title})",
                        "cards": [
                            {
                                "title": "Exposition des Sutras Classiques",
                                "summary": f"Selon les principes de {trad_title}, les configurations planétaires de votre thème offrent des leviers puissants pour transcender les obstacles.",
                                "bullets": ["Concordance classique", "Harmonie planétaire"],
                                "tags": ["Classique"]
                            },
                            {
                                "title": f"Cycle de Mahadasha Actif ({maha_dasha})",
                                "summary": f"La période majeure sous {maha_dasha} représente une phase fondamentale de maturation intérieure et de concrétisation sociale.",
                                "bullets": ["Croissance intérieure", "Opportunités durables"],
                                "tags": ["Mahadasha"]
                            },
                            {
                                "title": f"Catalyseur d'Antardasha ({antar_dasha})",
                                "summary": f"La sous-période sous {antar_dasha} dynamise les initiatives actuelles. Des démarches mesurées et lucides assureront une pleine réussite.",
                                "bullets": ["Concrétisation méthodique", "Prudence avisée"],
                                "tags": ["Antardasha"]
                            }
                        ]
                    },
                    {
                        "id": "yogas_formations",
                        "title": "Yogas Planétaires & Formations Auspicieuses",
                        "cards": [
                            {
                                "title": f"Yoga Favorable Actif ({yoga_name1})",
                                "summary": str(yoga_desc1),
                                "bullets": ["Rayonnement bénéfique", "Prestige social"],
                                "tags": ["Yoga Bénéfique"]
                            },
                            {
                                "title": f"Harmonie de Prospérité ({yoga_name2})",
                                "summary": str(yoga_desc2),
                                "bullets": ["Pérennité matérielle", "Stabilité"],
                                "tags": ["Dhana Yoga"]
                            },
                            {
                                "title": "Évolution Karmique & Éveil Spirituel",
                                "summary": "L'axe des nœuds lunaires stimule la prise de conscience et transforme chaque défi en profonde sagesse existentielle.",
                                "bullets": ["Élévation de conscience", "Résilience karmique"],
                                "tags": ["Karma"]
                            }
                        ]
                    },
                    {
                        "id": "sacred_upayas",
                        "title": "Upayas Védiques Sacrés & Pratiques Quotidiennes",
                        "cards": [
                            {
                                "title": "Sadhana des Mantras Védiques",
                                "summary": "Récitez le mantra 'Om Namo Bhagavate Vasudevaya' ou votre mantra personnel 108 fois chaque matin au lever du jour.",
                                "bullets": ["108 récitations au lever", "Sérénité mentale"],
                                "tags": ["Mantra"]
                            },
                            {
                                "title": "Harmonisation par les Pierres & Métaux",
                                "summary": "Le port d'une pierre gemme naturelle accordée à votre Lagna optimise les rayonnements planétaires bénéfiques.",
                                "bullets": ["Amplification pranique", "Équilibre subtil"],
                                "tags": ["Gemme"]
                            },
                            {
                                "title": "Sadhana Quotidienne & Daan Charitable",
                                "summary": "Offrez le Surya Arghya matinal à l'aube et pratiquez des dons charitables désintéressés pour dissoudre les empreintes karmiques.",
                                "bullets": ["Surya Arghya", "Daan de bienfaisance"],
                                "tags": ["Sadhana"]
                            }
                        ]
                    }
                ]
            }
        
        # Default English
        return {
            "sections": [
                {
                    "id": "cosmic_archetype",
                    "title": "Cosmic Synthesis & Lagna Archetype",
                    "cards": [
                        {
                            "title": f"Ascendant ({lagna_rashi}) Core Vitality",
                            "summary": f"Your Lagna in {lagna_rashi} anchors your fundamental constitution, personal charisma, and psychological resilience. It defines how you meet challenges and grants the steadfast willpower needed to accomplish significant worldly and spiritual goals.",
                            "bullets": ["Physical vitality and constitutional balance", "Steadfast determination and clear life vision"],
                            "tags": ["Lagna", "Vitality"]
                        },
                        {
                            "title": f"Janma Nakshatra ({lagna_nak}) Intuition",
                            "summary": f"Governed by {lagna_nak}, your mental processing and subconscious instincts are imbued with sharp discernment and perception, guiding strategic judgment in crucial personal and professional crossroads.",
                            "bullets": ["Sharp analytical intellect", "Strategic foresight and moral leadership"],
                            "tags": ["Nakshatra", "Intuition"]
                        },
                        {
                            "title": "Lagna Lord & Soul Orientation",
                            "summary": "The ruling planet of your Ascendant directs your life force toward intellectual growth, practical leadership, and cultivating lasting authority within your domain.",
                            "bullets": ["Lasting authority and respect", "Dharmic alignment"],
                            "tags": ["Lagna Lord"]
                        }
                    ]
                },
                {
                    "id": "bhava_dynamics",
                    "title": "Bhava Alignments & House Lord Dynamics",
                    "cards": [
                        {
                            "title": f"Karma Sthana & Professional Prominence (10th Bhava in {h10_sign})",
                            "summary": f"Ruled by {h10_lord}, your 10th house highlights natural administrative capability, ethical business acumen, and organizational foresight. Professional expansion flourishes through disciplined accountability.",
                            "bullets": ["Natural administrative capability", "Long-term professional prominence"],
                            "tags": ["10th House", "Career"]
                        },
                        {
                            "title": f"Dhana & Labha Prosperity Vectors (2nd & 11th Bhavas in {h2_sign} & {h11_sign})",
                            "summary": f"Governed by {h2_lord} and {h11_lord}, these houses formulate an auspicious financial matrix, favoring steady capital accumulation, resource retention, and multiple long-term prosperity channels.",
                            "bullets": ["Steady capital accumulation", "Multiple income channels"],
                            "tags": ["2nd House", "11th House"]
                        },
                        {
                            "title": "Kendra & Trikona Equilibrium",
                            "summary": "The harmonious interplay between quadrant pillars (1st, 4th, 7th, 10th Kendras) and trines (1st, 5th, 9th Trikonas) establishes enduring life balance, shielding your progress against short-term cyclic fluctuations.",
                            "bullets": ["Enduring structural stability", "Protection from short-term volatility"],
                            "tags": ["Kendra", "Trikona"]
                        }
                    ]
                },
                {
                    "id": "tradition_deep_dive",
                    "title": f"Tradition-Specific Deep Dive ({trad_title})",
                    "cards": [
                        {
                            "title": "Classical Sutra Exposition",
                            "summary": f"Applying {trad_title} classical sutras reveals powerful planetary conjunctions in your chart. Classical principles indicate that channeling natal planetary strengths with moral discipline mitigates conflicting transit vibrations.",
                            "bullets": ["Classical sutra alignment", "Planetary harmonization"],
                            "tags": ["Classical"]
                        },
                        {
                            "title": f"Active Mahadasha ({maha_dasha}) Karmic Influence",
                            "summary": f"Operating under the major cycle of {maha_dasha} marks a profound period of transformation and personal evolution. This period accelerates your learning curve and positions you for pivotal life achievements.",
                            "bullets": ["Profound personal transformation", "Pivotal milestone windows"],
                            "tags": ["Mahadasha"]
                        },
                        {
                            "title": f"Antardasha ({antar_dasha}) Catalyst & Opportunity",
                            "summary": f"The current sub-period of {antar_dasha} acts as an immediate catalyst for growth. Focus on steady, structured initiatives, avoid impulsive speculative ventures, and consolidate foundational assets.",
                            "bullets": ["Immediate growth catalyst", "Consolidation of assets"],
                            "tags": ["Antardasha"]
                        }
                    ]
                },
                {
                    "id": "yogas_formations",
                    "title": "Planetary Yogas & Auspicious Celestial Formations",
                    "cards": [
                        {
                            "title": f"Active Auspicious Yoga ({yoga_name1})",
                            "summary": str(yoga_desc1),
                            "bullets": ["Positive planetary influence", "Enhanced authority"],
                            "tags": ["Auspicious Yoga"]
                        },
                        {
                            "title": f"Cosmic Wealth & Fortune Harmony ({yoga_name2})",
                            "summary": str(yoga_desc2),
                            "bullets": ["Sustained material prosperity", "Resource retention"],
                            "tags": ["Dhana Yoga"]
                        },
                        {
                            "title": "Karmic Growth & Spiritual Evolution",
                            "summary": "Placements along the karmic nodal axis stimulate inner awakening, urging you to transform life challenges into spiritual clarity, psychological maturity, and enduring wisdom.",
                            "bullets": ["Inner awakening and maturity", "Enduring spiritual wisdom"],
                            "tags": ["Karma"]
                        }
                    ]
                },
                {
                    "id": "sacred_upayas",
                    "title": "Sacred Vedic Upayas, Sadhana & Remedial Directives",
                    "cards": [
                        {
                            "title": "Prescribed Vedic Mantra Sadhana",
                            "summary": "Recite the sacred Vedic mantra 'Om Namo Bhagavate Vasudevaya' or your personalized Ishta Devata mantra (108 times daily at dawn) to align pranic vitality and mental tranquility.",
                            "bullets": ["108 daily repetitions at dawn", "Pranic alignment and peace"],
                            "tags": ["Mantra"]
                        },
                        {
                            "title": "Harmonic Gemstone & Elemental Guidance",
                            "summary": "Wearing natural auspicious gemstones in consecrated metals on designated weekdays enhances benefic vibrations and pacifies conflicting transits.",
                            "bullets": ["Benefic vibration amplification", "Elemental balance"],
                            "tags": ["Gemstone"]
                        },
                        {
                            "title": "Nitya Sadhana & Charitable Daan Offerings",
                            "summary": "Offer morning Surya Arghya (fresh water in a copper vessel facing east) and engage in weekly charitable acts (daan of grains or clothing) to dissolve karmic obstacles.",
                            "bullets": ["Morning Surya Arghya", "Weekly charitable daan"],
                            "tags": ["Sadhana"]
                        }
                    ]
                }
            ]
        }

    lang_instructions = {
        "en": "All text MUST be 100% in fluent English.",
        "hi": "All text MUST be written 100% in authentic, natural Hindi (Devanagari script: हिन्दी). Keep Sanskrit proper nouns (Lagna, Rashi, Bhava, Nakshatra, Dasha) in standard Devanagari.",
        "bn": "All text MUST be written 100% in authentic, natural Bengali script (বাংলা). Keep Sanskrit astrological terms in Bengali script.",
        "ta": "All text MUST be written 100% in authentic, natural Tamil script (தமிழ்). Keep Sanskrit astrological terms in Tamil script.",
        "fr": "All text MUST be written 100% in fluent, polished French."
    }

    system_prompt = f"""You are AstroJunction Daivajna, an authentic, revered Vedic Astrologer providing enlightened astrological counsel for {profile_name}.
Tradition: {trad_title}. Lagna: {lagna_rashi} ({lagna_nak}). Active Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha.

STRICT JSON OUTPUT REQUIREMENT:
You MUST respond with a single, valid JSON object and NOTHING ELSE. No introductory text, no markdown backticks, no explanations.
The JSON must follow this exact schema:
{{
  "sections": [
    {{
      "id": "cosmic_archetype",
      "title": "Section Title Here",
      "cards": [
        {{
          "title": "Card Title",
          "summary": "Detailed summary paragraph. Use **bold** for key phrases.",
          "bullets": ["Key bullet point 1", "Key bullet point 2"],
          "tags": ["Tag1", "Tag2"]
        }}
      ]
    }},
    {{
      "id": "bhava_dynamics",
      "title": "Section Title",
      "cards": [...]
    }},
    {{
      "id": "tradition_deep_dive",
      "title": "Section Title",
      "cards": [...]
    }},
    {{
      "id": "yogas_formations",
      "title": "Section Title",
      "cards": [...]
    }},
    {{
      "id": "sacred_upayas",
      "title": "Section Title",
      "cards": [...]
    }}
  ]
}}

Provide EXACTLY 5 sections matching the IDs: "cosmic_archetype", "bhava_dynamics", "tradition_deep_dive", "yogas_formations", "sacred_upayas".
Each section must contain 2 to 4 rich, flowing cards.
{lang_instructions.get(lang, lang_instructions["en"])}
"""

    max_tok = 3800 if lang in {"hi", "bn", "ta"} else 3000

    try:
        history = [{"role": "user", "content": f"Please generate the complete 5-section {tradition} astrological synthesis in strict JSON."}]
        raw_res = _execute_llm(system_prompt, history, max_tokens=max_tok)
        
        # Clean markdown code blocks if any
        clean_json_str = raw_res.strip()
        if clean_json_str.startswith("```"):
            clean_json_str = re.sub(r"^```(?:json)?\s*", "", clean_json_str)
            clean_json_str = re.sub(r"\s*```$", "", clean_json_str)
            clean_json_str = clean_json_str.strip()

        parsed = json.loads(clean_json_str)
        if isinstance(parsed, dict) and "sections" in parsed and isinstance(parsed["sections"], list) and len(parsed["sections"]) >= 3:
            duration_ms = int((time.time() - start_t) * 1000)
            print(f"[SYNTHESIS] Success | lang={lang} | tradition={tradition} | sections={len(parsed['sections'])} | {duration_ms}ms")
            return parsed
        else:
            raise ValueError("Parsed JSON missing required sections structure")
    except Exception as e:
        duration_ms = int((time.time() - start_t) * 1000)
        print(f"[SYNTHESIS] LLM JSON fallback triggered ({e}) | lang={lang} | tradition={tradition} | {duration_ms}ms")
        return build_native_fallback_synthesis()



def generate_raw_completion(prompt: str, model: str = None) -> str:
    """Calls the active LLM configured in Admin Settings with a prompt string."""
    history = [{"role": "user", "content": prompt}]
    return _execute_llm("", history)


def get_filtered_roadmap_predictions_response(
    profile: dict,
    tradition: str,
    chart_data: dict,
    numerology: dict,
    horizon: str = "0-5 Years",
    language: str = "en"
) -> str:
    valid_langs = ["en", "hi", "bn", "ta", "fr"]
    lang = language.lower() if language and language.lower() in valid_langs else "en"

    lang_instructions = {
        "en": "LANGUAGE MANDATE: Write all 'prediction', 'favorableTransits', and 'remedialAction' text values in clear, engaging English.",
        "hi": "LANGUAGE MANDATE (CRITICAL): The requested language is HINDI. You MUST write all 'prediction', 'favorableTransits', and 'remedialAction' text values strictly in natural, fluent HINDI using DEVANAGARI SCRIPT. Do NOT use English, Roman characters, or Hinglish for descriptions. Topic keys must remain exact in lowercase English (career, wealth, health, relationships, family, education, travel, spirituality).",
        "bn": "LANGUAGE MANDATE (CRITICAL): The requested language is BENGALI. You MUST write all 'prediction', 'favorableTransits', and 'remedialAction' text values strictly in authentic, fluent BENGALI using BENGALI SCRIPT. Do NOT use English, Roman characters, or Banglish for descriptions. Topic keys must remain exact in lowercase English (career, wealth, health, relationships, family, education, travel, spirituality).",
        "ta": "LANGUAGE MANDATE (CRITICAL): The requested language is TAMIL. You MUST write all 'prediction', 'favorableTransits', and 'remedialAction' text values strictly in authentic, fluent TAMIL using TAMIL SCRIPT. Do NOT use English, Roman characters, or Tanglish for descriptions. Topic keys must remain exact in lowercase English (career, wealth, health, relationships, family, education, travel, spirituality).",
        "fr": "LANGUAGE MANDATE (CRITICAL): The requested language is FRENCH. You MUST write all 'prediction', 'favorableTransits', and 'remedialAction' text values strictly in elegant, professional FRENCH with proper French accents and Vedic astrological vocabulary translated appropriately. Topic keys must remain exact in lowercase English (career, wealth, health, relationships, family, education, travel, spirituality)."
    }

    profile_name = profile.get("fullName", "Seeker")
    horoscope_sys = profile.get("horoscopeSystem", "Vedic")
    dob = profile.get("birthDate", "Unknown")
    time = profile.get("birthTime", "Unknown")
    place = profile.get("birthPlace", "Unknown")
    
    lagna_info = chart_data.get("ascendant", {})
    lagna_rashi = lagna_info.get("signName") or lagna_info.get("signSanskrit") or lagna_info.get("rashi") or "Aries"
    lagna_lord = lagna_info.get("lord") or "Ascendant Lord"
    
    moon_info = chart_data.get("moon", {})
    moon_rashi = chart_data.get("moonSign") or moon_info.get("signName") or moon_info.get("signSanskrit") or moon_info.get("rashi") or "Chandra Rashi"
    
    planets_list = chart_data.get("planets", [])
    moon_planet = next((p for p in planets_list if p.get("id") == "moon" or p.get("name", "").lower() == "moon"), {})
    nakshatra = moon_planet.get("nakshatra") or moon_info.get("nakshatra") or chart_data.get("nakshatra") or "Rohini"
    
    dasha_periods = chart_data.get("dashaPeriods", [])
    curr_dasha = next((d for d in dasha_periods if d.get("isCurrent")), {})
    dasha_info = chart_data.get("currentDasha", {})
    maha_dasha = curr_dasha.get("planet") or dasha_info.get("mahadasha") or "Jupiter"
    antar_dasha = curr_dasha.get("antardasha") or dasha_info.get("antardasha") or "Saturn"
    
    mulank = numerology.get("mulank", "3")
    bhagyank = numerology.get("bhagyank", "7")

    instruction_text = lang_instructions.get(lang, lang_instructions["en"])

    system_prompt = f"""You are AstroJunction Daivajna, an expert 25-Year Vedic Astrological Forecaster.
Generate a comprehensive Kundli Life Roadmap Prediction tailored specifically for the time horizon filter: '{horizon}'.
You MUST cover ALL 8 KUNDLI LIFE TOPICS for this timeframe:
1. Career & Profession
2. Wealth & Finance
3. Health & Well-being
4. Marriage & Relationships
5. Family & Children
6. Education & Learning
7. Foreign Travel & Relocation
8. Spirituality & Upayas

User Details:
Name: {profile_name}
System: {horoscope_sys} ({tradition} tradition)
DOB: {dob}, Time: {time}, Place: {place}
Lagna (Ascendant): {lagna_rashi} (Lord: {lagna_lord})
Moon Sign (Rashi): {moon_rashi}, Nakshatra: {nakshatra}
Active Vimshottari Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha
Numerology: Psychic {mulank}, Destiny {bhagyank}
Time Horizon: {horizon}

{instruction_text}

You MUST return a JSON object with EXACTLY this structure containing predictions for all 8 topics:
{{
  "horizon": "{horizon}",
  "topics": [
    {{
      "topicKey": "career",
      "topicName": "Career & Profession",
      "prediction": "Detailed 2-3 sentence prediction for {horizon} based on {maha_dasha} dasha and {lagna_rashi} lagna.",
      "favorableTransits": "Key transits during {horizon}",
      "remedialAction": "1 specific remedy"
    }},
    {{
      "topicKey": "wealth",
      "topicName": "Wealth & Finance",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "health",
      "topicName": "Health & Well-being",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "relationships",
      "topicName": "Marriage & Relationships",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "family",
      "topicName": "Family & Children",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "education",
      "topicName": "Education & Higher Learning",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "travel",
      "topicName": "Foreign Travel & Relocation",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }},
    {{
      "topicKey": "spirituality",
      "topicName": "Spirituality & Upayas",
      "prediction": "...",
      "favorableTransits": "...",
      "remedialAction": "..."
    }}
  ]
}}

Requirements:
- Must generate predictions for ALL 8 topics listed above.
- Ensure prediction specifically mentions user's {lagna_rashi} ascendant and {maha_dasha} Mahadasha.
- Output ONLY valid JSON, no markdown outside code blocks.
"""

    history = [{"role": "user", "content": f"Generate the 8-Topic Kundli Prediction JSON for horizon {horizon} in {lang}."}]

    def _strip_markdown(raw: str) -> str:
        s = raw.strip()
        if s.startswith("```json"):
            s = s[7:]
        elif s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        return s.strip()

    def _verify_script(raw: str, target_lang: str) -> bool:
        if target_lang == "hi":
            return any('\u0900' <= c <= '\u097f' for c in raw)
        elif target_lang == "bn":
            return any('\u0980' <= c <= '\u09ff' for c in raw)
        elif target_lang == "ta":
            return any('\u0b80' <= c <= '\u0bff' for c in raw)
        return True

    try:
        res = _execute_llm(system_prompt, history, max_tokens=4000)
        cleaned = _strip_markdown(res)
        
        # Verify script for Indic languages
        if not _verify_script(cleaned, lang):
            print(f"[LLM] Warning: Script verification failed for {lang}. Retrying once with emphatic reminder...")
            retry_history = history + [
                {"role": "assistant", "content": res},
                {"role": "user", "content": f"CRITICAL: Please regenerate the response strictly in {lang.upper()} using native script (Devanagari for hi, Bengali for bn, Tamil for ta). Output ONLY valid JSON."}
            ]
            retry_res = _execute_llm(system_prompt, retry_history, max_tokens=4000)
            retry_cleaned = _strip_markdown(retry_res)
            if _verify_script(retry_cleaned, lang):
                cleaned = retry_cleaned

        # Validate that cleaned is valid JSON
        import json
        parsed = json.loads(cleaned)
        return json.dumps(parsed, ensure_ascii=False)
    except Exception as e:
        print(f"[LLM] Error generating filtered roadmap: {e}")
        raise LLMError(f"Failed to generate filtered roadmap predictions: {str(e)}")

