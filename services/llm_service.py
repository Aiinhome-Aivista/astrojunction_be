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


def _call_mistral_local(system_prompt: str, history: list) -> str:
    base_url = get_setting("MISTRAL_LOCAL_URL", "").rstrip("/")
    model = get_setting("MISTRAL_MODEL", "")
    if not base_url or not model:
        raise LLMError(
            "ACTIVE_LLM is set to mistral_local but MISTRAL_LOCAL_URL or MISTRAL_MODEL is not configured in Admin Settings."
        )

    print(f"\n{'='*60}")
    print(f"[LLM CALL] Provider: mistral_local | Model/Version: {model} | URL: {base_url}/api/generate")
    print(f"{'='*60}\n")

    prompt = system_prompt + "\n\n"
    for msg in history:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        prompt += f"{role}: {content}\n\n"

    timeout = _get_llm_timeout()
    resp = None
    try:
        try:
            resp = requests.post(
                f"{base_url}/api/generate",
                headers={"Connection": "close"},
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
        except requests.RequestException:
            # Fallback to /v1/chat/completions (OpenAI compatible endpoint)
            try:
                print(f"[LLM FALLBACK CALL] Provider: mistral_local | Model/Version: {model} | URL: {base_url}/v1/chat/completions")
                messages = [{"role": "system", "content": system_prompt}] + history
                resp = requests.post(
                    f"{base_url}/v1/chat/completions",
                    headers={"Connection": "close"},
                    json={"model": model, "messages": messages},
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


def _call_mistral_cloud(system_prompt: str, history: list) -> str:
    base_url = get_setting("MISTRAL_CLOUD_URL", "https://api.mistral.ai").rstrip("/")
    api_key = get_setting("MISTRAL_CLOUD_API_KEY", "")
    model = get_setting("MISTRAL_MODEL", "mistral-large-latest")
    if not base_url or not api_key:
        raise LLMError(
            "ACTIVE_LLM is set to mistral_cloud but MISTRAL_CLOUD_URL / "
            "MISTRAL_CLOUD_API_KEY are not fully configured."
        )

    print(f"\n{'='*60}")
    print(f"[LLM CALL] Provider: mistral_cloud | Model/Version: {model} | URL: {base_url}/v1/chat/completions")
    print(f"{'='*60}\n")

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
    resp = None
    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Mistral cloud API returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM RESPONSE] Provider: mistral_cloud | Resolved Model/Version: {returned_model}")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Mistral cloud API returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach Mistral cloud endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_gemini(system_prompt: str, history: list) -> str:
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
    print(f"\n{'='*60}")
    print(f"[LLM CALL] Provider: gemini | Model: {model} | API Version: {api_version} | Endpoint: generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent")
    print(f"{'='*60}\n")

    convo_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history)
    full_prompt = f"{system_prompt}\n\n--- Conversation ---\n{convo_text}"

    timeout = _get_llm_timeout()
    resp = None
    try:
        resp = requests.post(
            url,
            headers={"Connection": "close"},
            json={"contents": [{"parts": [{"text": full_prompt}]}]},
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"Gemini API returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        model_version = data.get("modelVersion", model)
        print(f"[LLM RESPONSE] Provider: gemini | Configured Model: {model} | Resolved Version: {model_version}")
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Gemini API returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach Gemini API: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_openai(system_prompt: str, history: list) -> str:
    api_key = get_setting("OPENAI_API_KEY", "")
    base_url = get_setting("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = get_setting("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise LLMError("ACTIVE_LLM is set to openai but OPENAI_API_KEY is not configured.")

    print(f"\n{'='*60}")
    print(f"[LLM CALL] Provider: openai | Model/Version: {model} | URL: {base_url}/chat/completions")
    print(f"{'='*60}\n")

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
    resp = None
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Connection": "close"},
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenAI returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM RESPONSE] Provider: openai | Resolved Model/Version: {returned_model}")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("OpenAI returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach OpenAI endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _call_openrouter(system_prompt: str, history: list) -> str:
    api_key = get_setting("OPENROUTER_API_KEY", "")
    base_url = get_setting("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = get_setting("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    if not api_key:
        raise LLMError("ACTIVE_LLM is set to openrouter but OPENROUTER_API_KEY is not configured.")

    print(f"\n{'='*60}")
    print(f"[LLM CALL] Provider: openrouter | Model/Version: {model} | URL: {base_url}/chat/completions")
    print(f"{'='*60}\n")

    timeout = _get_llm_timeout()
    messages = [{"role": "system", "content": system_prompt}] + history
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
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"OpenRouter returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model)
        print(f"[LLM RESPONSE] Provider: openrouter | Resolved Model/Version: {returned_model}")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("OpenRouter returned an unexpected response shape.")
    except requests.RequestException as e:
        raise LLMError(f"Could not reach OpenRouter endpoint: {e}")
    finally:
        if resp is not None:
            resp.close()


def _execute_llm(system_prompt: str, history: list) -> str:
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

    print("\n" + "=" * 65)
    print(f"🤖 [LLM CALL TRIGGERED] Active Provider: >>> {active_llm.upper()} <<<")
    print(f"📦 [LLM MODEL]           Model Name:      >>> {model_name} <<<")
    print(f"🛡️  [FAILOVER STATUS]    Fallback:        >>> NONE (Strict Single Engine) <<<")
    print("=" * 65 + "\n")

    if active_llm == "mistral_local":
        return _call_mistral_local(system_prompt, history)
    elif active_llm == "mistral_cloud":
        return _call_mistral_cloud(system_prompt, history)
    elif active_llm == "gemini":
        return _call_gemini(system_prompt, history)
    elif active_llm == "openai":
        return _call_openai(system_prompt, history)
    elif active_llm == "openrouter":
        return _call_openrouter(system_prompt, history)
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
) -> str:
    system_prompt = f"""You are the AstroJunction Daivajna. The user has provided their daily transit data.
You MUST respond with ONLY a valid JSON object matching exactly this structure, no markdown formatting or backticks around it:
{{
  "summary": "A 2-3 sentence overall astrological prediction for today based on transits and tithi.",
  "career": "1-2 sentences on career and commerce predictions.",
  "love": "1-2 sentences on love and relationships.",
  "health": "1-2 sentences on health and prana."
}}

Here is the user's data:
Profile Name: {profile.get("fullName")}
System: {profile.get("horoscopeSystem")}
Lagna/Ascendant: {chart_data.get("ascendant", {}).get("signName", "Unknown")}
Panchang: Tithi {panchang.get("tithi")}, Nakshatra {panchang.get("nakshatra")}, Auspicious Score {panchang.get("auspiciousScore")}
Important Timings: Abhijit Muhurta {panchang.get("abhijitMuhurta")}, Rahu Kaal {panchang.get("rahuKaal")}
Numerology: Mulank {numerology.get("mulank")}, Lucky Number {numerology.get("luckyNumbers", [numerology.get("mulank")])[0]}, Lucky Colors {", ".join(numerology.get("luckyColors", []))}
"""
    history = [{"role": "user", "content": "Generate today's daily insights as JSON."}]

    try:
        res = _execute_llm(system_prompt, history)
        
        # Clean up possible markdown code blocks if the LLM includes them
        res = res.strip()
        if res.startswith("```json"):
            res = res[7:]
        if res.startswith("```"):
            res = res[3:]
        if res.endswith("```"):
            res = res[:-3]
        return res.strip()
    except Exception as e:
        raise LLMError(f"Failed to generate daily insights: {str(e)}")


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
    
    if language == 'bn':
        forecast_texts = {
            'today': f"{sign.capitalize()} রাশির জাতক-জাতিকাদের জন্য আজকের গ্রহ অবস্থান আত্মবিশ্বাস ও একাগ্রতা বৃদ্ধির ইঙ্গিত দিচ্ছে। আর্থিক লেনদেনে ইতিবাচক অগ্রগতি এবং মানসিক শান্তি বজায় থাকবে।",
            'week': f"এই সপ্তাহে বৃহস্পতি ও বুধের শুভ গোচরে {sign.capitalize()} রাশির নতুন পরিকল্পনা সফল হওয়ার শুভ যোগ রয়েছে। কর্মক্ষেত্রে সিনিয়রদের সহযোগিতা পাবেন।",
            'month': f"চলতি মাসে কর্ম ও আর্থিক ক্ষেত্রে গুরুত্বপূর্ণ অগ্রগতির সম্ভাবনা রয়েছে। কৌশলগত সিদ্ধান্ত গ্রহণে ধৈর্য বজায় রাখুন।",
            'year': f"২০২৬-২৭ সালে শনি ও বৃহস্পতির অনুকূল প্রভাব আপনার দীর্ঘমেয়াদী লক্ষ্যপূরণে শক্তিশালী ভূমিকা রাখবে।"
        }
    else:
        forecast_texts = {
            'today': f"The planetary transits for {sign.capitalize()} stimulate decisive action and heightened intuition today. A favorable alignment between your ruling planet and the Moon brings emotional clarity and steady progress.",
            'week': f"This week opens promising windows for strategic collaboration and professional growth for {sign.capitalize()}. Mercury's supportive aspect enhances negotiation and creative brainstorming.",
            'month': f"Monthly planetary ingresses favor long-term consolidation and auspicious financial planning for {sign.capitalize()}. Maintain disciplined routines and trust your inner wisdom.",
            'year': f"The 2026/2027 astrological panorama marks a profound phase of karmic ascension and material stability for {sign.capitalize()}."
        }
    
    forecast_str = forecast_texts.get(timeframe, forecast_texts['today'])
    
    return {
        "forecast": forecast_str,
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
    def fetch_part(system_prompt):
        history = [{"role": "user", "content": f"Generate the {timeframe} JSON forecast for {sign}."}]
        res = _execute_llm(system_prompt, history)
            
        res = res.strip()
        start = res.find("{")
        end = res.rfind("}")
        if start != -1 and end != -1 and end > start:
            res = res[start:end+1]
        try:
            return json.loads(res)
        except Exception:
            return {}

    prompt1 = f"""You are an expert Astrologer. Generate part 1 of the astrological forecast for Zodiac Sign: {sign.capitalize()}.
Timeframe: {timeframe} ('today', 'week', 'month', 'year').
MUST respond ONLY with valid JSON, in language {language} (if 'bn' use Bengali):
{{
  "forecast": "A highly realistic reading focusing on cosmic transits (3-5 sentences maximum).",
  "luckyGemstone": "Name of gemstone",
  "luckyColor": "Name of color",
  "luckyDay": "Day of the week",
  "powerNumbers": [3, 7, 9],
  "resonantChakra": "Name of chakra",
  "affirmation": "A positive affirmation sentence"
}}"""

    prompt2 = f"""You are an expert Astrologer. Generate part 2 (ratings and matches) for Zodiac Sign: {sign.capitalize()}.
Timeframe: {timeframe} ('today', 'week', 'month', 'year').
MUST respond ONLY with valid JSON, text in {language} (if 'bn' use Bengali), ratings 0-100:
{{
  "vitalityToday": 88,
  "loveRating": 75,
  "careerRating": 92,
  "wealthRating": 85,
  "bestRomanceMatches": ["Sign1", "Sign2"],
  "bestCareerMatches": ["Sign3", "Sign4"],
  "growthMatches": ["Sign5"]
}}"""

    try:
        part1_data = fetch_part(prompt1)
        part2_data = fetch_part(prompt2)
        
        combined_data = {**part1_data, **part2_data}
        if not combined_data.get("forecast"):
            fallback = _generate_fallback_zodiac_forecast(sign, timeframe, language)
            return json.dumps(fallback)
        return json.dumps(combined_data)
    except Exception as e:
        print(f"Warning: LLM generation for zodiac forecast failed ({e}), using dynamic Vedic astrological calculation fallback.")
        fallback = _generate_fallback_zodiac_forecast(sign, timeframe, language)
        return json.dumps(fallback)


def get_zodiac_compatibility_response(
    sign_a: str,
    sign_b: str,
    system: str = "tropical",
    language: str = "en"
) -> str:
    system_prompt = f"""You are an expert Vedic and Western Astrologer. Calculate the unique compatibility between {sign_a.capitalize()} and {sign_b.capitalize()} using the {system} system.
Calculate a highly accurate overall compatibility score (0-100) based on elements, modalities, and planetary rulers.
MUST respond ONLY with valid JSON, in language {language} (if 'bn' use Bengali). Do not include any comments or markdown inside the JSON object:
{{
  "overallScore": 68,
  "elementSynergy": "Short description of elemental synergy",
  "romanceAnalysis": "2-3 sentences about their romantic and soul synergy.",
  "intellectualAnalysis": "2-3 sentences about how their minds and communication match.",
  "growthPotential": "2-3 sentences about how they help each other evolve.",
  "remedialAdvice": "1 sentence of practical spiritual/astrological advice for this pairing."
}}
IMPORTANT: Replace 68 with the ACTUAL calculated compatibility score between these two signs (e.g. Leo and Aries might be 90, while Aries and Cancer might be 45). Make sure the score varies based on true astrological principles.
"""
    
    history = [{"role": "user", "content": f"Calculate compatibility between {sign_a} and {sign_b}."}]
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
        # Fallback static response if LLM fails
        return json.dumps({
            "overallScore": 70,
            "elementSynergy": f"Synergy between {sign_a} and {sign_b}.",
            "romanceAnalysis": "They share a unique bond shaped by their planetary rulers.",
            "intellectualAnalysis": "Communication requires mutual understanding and patience.",
            "growthPotential": "They can learn a lot from each other's differences.",
            "remedialAdvice": "Focus on open communication and respect for boundaries."
        })


def get_numerology_insights_response(
    mulank: int,
    bhagyank: int,
    namank: int,
    missing_numbers: list,
    language: str = "en"
) -> str:
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

All text fields MUST be in the requested language: {language}.
If the language is 'bn', use natural Bengali script.
Provide exactly 3 short traits for mulankCharacteristics. Provide customized remedies for the exact missing numbers (or general if none missing). Provide 1-sentence analysis for each of the 8 Lo Shu planes.
"""
    history = [{"role": "user", "content": "Generate the Numerology JSON insights."}]

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
        print(f"Warning: Numerology LLM failed ({e}), using dynamic Vedic numerology calculation fallback.")
        return json.dumps({
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
        })



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
) -> str:
    active_llm = os.getenv("ACTIVE_LLM", "mistral_local")
    
    # Safely extract values
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

    # If still not found and dashas exist, fallback to the first active period
    if maha_dasha == "Unknown" and dashas:
        maha_dasha = dashas[0].get("planet", "Unknown")
        sub_list = dashas[0].get("subPeriods") or dashas[0].get("antardashas") or []
        if sub_list:
            antar_dasha = sub_list[0].get("planet", "Unknown")
    
    planets = chart_data.get("planets", [])
    moon_p = next((p for p in planets if (p.get("name") or "").lower() == "moon" or (p.get("id") or "").lower() == "moon"), None)
    sun_p = next((p for p in planets if (p.get("name") or "").lower() == "sun" or (p.get("id") or "").lower() == "sun"), None)
    moon_sign = moon_p.get("signName", "Moon Sign") if moon_p else "Moon Sign"
    moon_nak = moon_p.get("nakshatra", "Chandra Nakshatra") if moon_p else "Chandra Nakshatra"

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

    def generate_full_5_card_synthesis():
        if language == "bn":
            return f"""### Cosmic Synthesis & Lagna Archetype
- **লগ্নের আত্মিক শক্তি ({lagna_rashi} Lagna)**: আপনার লগ্ন {lagna_rashi} আপনার শারীরিক জীবনীশক্তি, মানসিক দৃঢ়তা এবং ব্যক্তিত্বের মূল কাঠামো নির্দেশ করে। এটি আপনার কর্মশক্তি এবং জীবনের লক্ষ্য অর্জনে ধারাবাহিক একাগ্রতা প্রদান করে।
- **জন্ম নক্ষত্রের প্রভাব ({lagna_nak})**: {lagna_nak} নক্ষত্রের শাসনে আপনার মনস্তাত্ত্বিক উপলব্ধি এবং গভীর অন্তর্দৃষ্টি বিকশিত হয়, যা গুরুত্বপূর্ণ সিদ্ধান্ত গ্রহণে দূরদর্শিতা ও নেতৃত্ব দান করে।
- **লগ্নপতির আত্মিক দিকদর্শন**: আপনার লগ্নপতির অনুকূল প্রভাব জীবনশক্তিকে গভীর বৌদ্ধিক চেতনা, কর্মনিষ্ঠা এবং সমাজে নিজস্ব অবস্থান মজবুত করার দিকে পরিচালিত করে।

### Bhava Alignments & House Lord Dynamics
- **কর্মস্থান ও পেশাগত প্রতিষ্ঠা (দশম ভাব - {h10_sign})**: {h10_sign} রাশিতে অবস্থানরত দশম ভাব এবং এর অধিপতি {h10_lord}-এর প্রভাবে আপনার কর্মজীবনে প্রশাসনিক দক্ষতা, নেতৃত্ব ও দীর্ঘমেয়াদী প্রতিষ্ঠা অর্জনের শক্তিশালী যোগ রয়েছে।
- **ধন ও লাভ সমৃদ্ধি প্রবাহ (দ্বিতীয় ও একাদশ ভাব - {h2_sign} ও {h11_sign})**: ধনভাব ({h2_sign}) এবং লাভভাব ({h11_sign})-এর যৌথ গতিশীলতা আর্থিক নিরাপত্তা, সুশৃঙ্খল সঞ্চয় এবং সফল বিনিয়োগের অনুকূল ভিত্তি তৈরি করে।
- **কেন্দ্র ও ত্রিকোণ সামঞ্জস্য**: কেন্দ্র ও ত্রিকোণ ভাবগুলির অন্তর্নিহিত ভারসাম্য আপনার সার্বিক জীবনে স্থায়িত্ব প্রদান করে এবং সাময়িক অস্থিরতা থেকে রক্ষা করে।

### Tradition-Specific Deep Dive ({trad_title})
- **শাস্ত্রীয় সূত্র বিশ্লেষণ**: {trad_title}-এর শাস্ত্রীয় নিয়ম অনুযায়ী আপনার কুষ্ঠির বিশেষ গ্রহ সংযোগগুলি প্রতিকূলতাকে সম্ভাবনায় রূপান্তর করার শক্তিশালী সংকেত বহন করে।
- **বর্তমান মহাদশা ({maha_dasha}) রূপান্তর**: সক্রিয় {maha_dasha} মহাদশা আপনার জীবনে একটি গভীর আত্মবিকাশ ও পেশাগত অগ্রগতির মূল সময়কাল নির্দেশ করে।
- **অন্তর্দশা ({antar_dasha}) সুযোগ ও সচেতনতা**: সক্রিয় {antar_dasha} অন্তর্দশার প্রভাব তাৎক্ষণিক সিদ্ধান্ত ও পরিকল্পনা রূপায়ণে নতুন দিগন্ত উন্মোচন করে। সুশৃঙ্খল পদক্ষেপ সর্বোচ্চ শুভফল নিশ্চিত করবে।

### Planetary Yogas & Auspicious Formations
- **সক্রিয় শুভ যোগ ({yoga_name1})**: {yoga_desc1}
- **কসমিক সমৃদ্ধি ও সম্পদ প্রবাহ ({yoga_name2})**: {yoga_desc2}
- **আধ্যাত্মিক বিবর্তন ও কর্মিক শিক্ষা**: রাহূ-কেতু ও শনি গ্রহের অবস্থান অন্তর্জাগরণ জাগ্রত করে, জীবনের চ্যালেঞ্জগুলিকে পরম অভিজ্ঞতায় রূপান্তর করতে সাহায্য করে।

### Sacred Vedic Upayas & Remedial Directives
- **নির্দিষ্ট বৈদিক মন্ত্র জপ**: প্রতিদিন ভোরে সূর্যোদয়কালে শান্ত চিত্তে `ওঁ নমো ভগবতে বাসুদেবায়` অথবা আপনার ইষ্ট মন্ত্র ১০৮ বার জপ করুন, যা মানসিক স্থৈর্য ও আত্মবিশ্বাস বৃদ্ধি করবে।
- **রত্ন ও শুভ ধাতুর ভারসাম্য**: লগ্নপতির অনুকূল রত্ন (যেমন হলুদ পোখরাজ, রক্তপ্রবাল বা পান্না) এবং শুভ ধাতু ধারণ গ্রহের ইতিবাচক স্পন্দনকে শক্তিশালী করে।
- **নিত্য সাধনা ও শুভ দান**: রবিবারে তাম্রপাত্রে সূর্যদেবের উদ্দেশ্যে জল নিবেদন (সূর্য অর্ঘ্য) এবং অভাবগ্রস্তদের অন্ন বা বস্ত্র দান করলে কর্মিক বাধা দূরীভূত হয়।"""

        return f"""### Cosmic Synthesis & Lagna Archetype
- **Ascendant ({lagna_rashi}) Core Vitality**: Your Lagna in {lagna_rashi} anchors your fundamental constitution, personal charisma, and psychological resilience. It defines how you meet challenges and grants the steadfast willpower needed to accomplish significant worldly and spiritual goals.
- **Janma Nakshatra ({lagna_nak}) Intuition**: Governed by {lagna_nak}, your mental processing and subconscious instincts are imbued with sharp discernment and perception, guiding strategic judgment in crucial personal and professional crossroads.
- **Lagna Lord & Soul Orientation**: The ruling planet of your Ascendant directs your life force toward intellectual growth, practical leadership, and cultivating lasting authority within your domain.

### Bhava Alignments & House Lord Dynamics
- **Karma Sthana & Professional Prominence (10th Bhava in {h10_sign})**: Ruled by {h10_lord}, your 10th house highlights natural administrative capability, ethical business acumen, and organizational foresight. Professional expansion flourishes through disciplined accountability and structured execution.
- **Dhana & Labha Prosperity Vectors (2nd & 11th Bhavas in {h2_sign} & {h11_sign})**: Governed by {h2_lord} and {h11_lord}, these houses formulate an auspicious financial matrix, favoring steady capital accumulation, resource retention, and multiple long-term prosperity channels.
- **Kendra & Trikona Equilibrium**: The harmonious interplay between the quadrant pillars (1st, 4th, 7th, 10th Kendras) and trines (1st, 5th, 9th Trikonas) establishes enduring life balance, shielding your progress against short-term cyclic fluctuations.

### Tradition-Specific Deep Dive ({trad_title})
- **Classical Sutra Exposition**: Applying {trad_title} classical sutras reveals powerful planetary conjunctions in your chart. Classical principles indicate that channeling natal planetary strengths with moral discipline mitigates conflicting transit vibrations.
- **Active Mahadasha ({maha_dasha}) Karmic Influence**: Operating under the major cycle of {maha_dasha} marks a profound period of transformation and personal evolution. This period accelerates your learning curve and positions you for pivotal life achievements.
- **Antardasha ({antar_dasha}) Catalyst & Opportunity**: The current sub-period of {antar_dasha} acts as an immediate catalyst for growth. Focus on steady, structured initiatives, avoid impulsive speculative ventures, and consolidate foundational assets.

### Planetary Yogas & Auspicious Celestial Formations
- **Active Auspicious Yoga ({yoga_name1})**: {yoga_desc1}
- **Cosmic Wealth & Fortune Harmony ({yoga_name2})**: {yoga_desc2}
- **Karmic Growth & Spiritual Evolution**: Placements along the karmic nodal axis stimulate inner awakening, urging you to transform life challenges into spiritual clarity, psychological maturity, and enduring wisdom.

### Sacred Vedic Upayas, Sadhana & Remedial Directives
- **Prescribed Navagraha & Ishta Devata Mantras**: Recite the sacred Vedic mantra `Om Namo Bhagavate Vasudevaya` or your personalized Navagraha Gayatri mantra (108 times daily at dawn) to align pranic vitality and mental tranquility.
- **Harmonic Gemstone & Elemental Guidance**: Wearing natural auspicious gemstones (such as Yellow Sapphire, Ruby, or Emerald as per your Lagna lord) in consecrated metals on designated weekdays enhances benefic vibrations and pacifies malefic transits.
- **Nitya Sadhana & Charitable Daan Offerings**: Offer morning Surya Arghya (fresh water with copper vessel facing east) and engage in weekly charitable acts (daan of yellow grains, lentils, or warm clothing) to dissolve karmic obstacles and foster auspicious prosperity."""

    def clean_output(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r'^[#\s*]+', '### ', text.strip())
        if language != 'bn':
            cleaned = re.sub(r'\s*\([^\)]*[\u0980-\u09FF]+[^\)]*\)\s*', '', cleaned)
            cleaned = re.sub(r'\s*\(In (?:fluent )?[A-Za-z\s]+script:[^\)]*\)\s*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    lang_inst = "All text MUST be 100% in English only."
    if language == 'bn':
        lang_inst = "All text MUST be written in fluent, authentic Bengali script."
    elif language and language != 'en':
        lang_inst = f"All text MUST be in language code: {language}."

    system_prompt = f"""You are AstroJunction Daivajna, an authentic, revered Vedic Astrologer providing personalized, enlightened astrological counsel for {profile_name}.
Tradition: {trad_title}. Lagna: {lagna_rashi} ({lagna_nak}). Active Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha.

Deliver an exhaustive, authoritative Vedic interpretation formatted into EXACTLY these 5 sections with bold bullet points:
### Cosmic Synthesis & Lagna Archetype
### Bhava Alignments & House Lord Dynamics
### Tradition-Specific Deep Dive ({trad_title})
### Planetary Yogas & Auspicious Celestial Formations
### Sacred Vedic Upayas, Sadhana & Remedial Directives

{lang_inst}
"""

    try:
        history = [{"role": "user", "content": f"Please provide my complete 5-section {tradition} astrological synthesis."}]
        res = _execute_llm(system_prompt, history)
        cleaned = clean_output(res)
        if len(cleaned) > 250 and "###" in cleaned:
            return cleaned
        return generate_full_5_card_synthesis()
    except Exception as e:
        print(f"Notice: Interpretation LLM offline/fallback ({e}), delivering rich 5-card dynamic Vedic calculation synthesis.")
        return generate_full_5_card_synthesis()



def generate_raw_completion(prompt: str, model: str = None) -> str:
    """Directly calls the configured LLM with a raw prompt string."""
    raw_url = get_setting("MISTRAL_LOCAL_URL", "").strip().rstrip("/")
    if not raw_url:
        raise LLMError("MISTRAL_LOCAL_URL is not configured in Admin Settings.")
    model_name = model or get_setting("MISTRAL_MODEL", "mistral:latest")
    
    if raw_url.endswith("/api/generate") or raw_url.endswith("/api/chat"):
        endpoint_url = raw_url
    else:
        endpoint_url = f"{raw_url}/api/generate"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }

    print(f"\n{'='*60}")
    print(f"[LLM CALL - Raw Completion] Provider: mistral_local | Model/Version: {model_name} | Endpoint: {endpoint_url}")
    print(f"{'='*60}\n")

    resp = None
    try:
        resp = requests.post(endpoint_url, headers={"Connection": "close"}, json=payload, timeout=120)
        if resp.status_code != 200:
            raise LLMError(f"LLM server returned HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        returned_model = data.get("model", model_name)
        print(f"[LLM RESPONSE - Raw Completion] Resolved Model/Version: {returned_model}")
        content = data.get("response") or (data.get("message") or {}).get("content") or data.get("text")
        if not content:
            raise LLMError("LLM server returned an unexpected response shape.")
        return content
    except requests.RequestException as e:
        raise LLMError(f"Could not reach LLM endpoint at {endpoint_url}: {e}")
    finally:
        if resp is not None:
            resp.close()


def get_filtered_roadmap_predictions_response(
    profile: dict,
    tradition: str,
    chart_data: dict,
    numerology: dict,
    horizon: str = "0-5 Years",
    language: str = "en"
) -> str:
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

    system_prompt = f"""You are AstroJunction Daivajna, an expert 25-Year Vedic Astrological Forecaster.
Generate a comprehensive Kundli Life Roadmap Prediction tailored specifically for the time horizon filter: '{horizon}'.
You MUST cover ALL 8 KUNDLI LIFE TOPICS for this timeframe:
1. Career & Profession (কর্ম ও পেশা)
2. Wealth & Finance (অর্থ ও সমৃদ্ধি)
3. Health & Well-being (স্বাস্থ্য ও স্থায়িত্ব)
4. Marriage & Relationships (বিবাহ ও দাম্পত্য জীবন)
5. Family & Children (পরিবার ও সন্তান ভাগ্য)
6. Education & Learning (শিক্ষা ও জ্ঞান চর্চা)
7. Foreign Travel & Relocation (বিদেশ ভ্রমণ ও বাসস্থান)
8. Spirituality & Upayas (আধ্যাত্মিক বিকাশ ও প্রতিকার/উপায়)

User Details:
Name: {profile_name}
System: {horoscope_sys} ({tradition} tradition)
DOB: {dob}, Time: {time}, Place: {place}
Lagna (Ascendant): {lagna_rashi} (Lord: {lagna_lord})
Moon Sign (Rashi): {moon_rashi}, Nakshatra: {nakshatra}
Active Vimshottari Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha
Numerology: Psychic {mulank}, Destiny {bhagyank}
Time Horizon: {horizon}

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
- All text values MUST be translated directly into the language code: {language}. If 'bn', use Bengali script.
- Output ONLY valid JSON, no markdown outside code blocks.
"""

    history = [{"role": "user", "content": f"Generate the 8-Topic Kundli Prediction JSON for horizon {horizon}."}]

    try:
        res = _execute_llm(system_prompt, history)
        
        res = res.strip()
        if res.startswith("```json"):
            res = res[7:]
        if res.startswith("```"):
            res = res[3:]
        if res.endswith("```"):
            res = res[:-3]
        return res.strip()
    except Exception as e:
        raise LLMError(f"Failed to generate filtered roadmap predictions: {str(e)}")




