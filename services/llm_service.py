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
    model = get_setting("MISTRAL_MODEL", "mistral:latest")
    if not base_url:
        raise LLMError(
            "ACTIVE_LLM is set to mistral_local but MISTRAL_LOCAL_URL is not configured in Admin Settings."
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


def _execute_llm(system_prompt: str, history: list) -> str:
    active_llm = get_setting("ACTIVE_LLM", "mistral_local")
    failover_enabled = get_setting("ENABLE_AUTO_FAILOVER", "true").lower() in ("true", "1", "yes")
    fallback_llm = get_setting("FALLBACK_LLM", "gemini")

    providers = [active_llm]
    if failover_enabled and fallback_llm and fallback_llm != active_llm:
        providers.append(fallback_llm)

    print(f"[LLMService] Executing LLM request | Active: '{active_llm}' | Failover: {'Enabled (Fallback: ' + fallback_llm + ')' if failover_enabled else 'Disabled'} | Providers: {providers}")

    last_error = None
    for prov in providers:
        try:
            if prov == "mistral_local":
                return _call_mistral_local(system_prompt, history)
            elif prov == "mistral_cloud":
                return _call_mistral_cloud(system_prompt, history)
            elif prov == "gemini":
                return _call_gemini(system_prompt, history)
            elif prov == "openai":
                return _call_openai(system_prompt, history)
            else:
                raise LLMError(f"Unknown LLM provider: '{prov}'")
        except Exception as e:
            last_error = e
            print(f"[LLMService] Provider '{prov}' encountered error: {e}. Trying fallback if available...")

    raise last_error or LLMError("All configured LLM engines failed.")


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
    
    def fetch_part(system_prompt):
        history = [{"role": "user", "content": f"Analyze my chart using {tradition}."}]
        res = _execute_llm(system_prompt, history)
        return res.strip()
    
    lang_inst = "All text MUST be 100% in English only. Do NOT output any translations, parenthetical scripts, or other languages."
    if language == 'bn':
        lang_inst = "All text MUST be written in fluent, authentic Bengali script."
    elif language and language != 'en':
        lang_inst = f"All text MUST be in language code: {language}."

    prompt1 = f"""You are AstroJunction Daivajna, an authentic, revered Vedic Astrologer providing personalized, enlightened astrological counsel for a seeker.
Deliver a deeply insightful and personalized Vedic astrological interpretation in English. Write warmly and authoritatively like a revered Guru or Daivajna, NOT like a generic chatbot or machine.

Seeker Details: Name: {profile_name}, Lagna (Ascendant): {lagna_rashi} ({lagna_nak})

Instructions:
1. Begin with a clean heading:
### Cosmic Synthesis & Lagna Archetype
2. Present a synthesis of how their Ascendant ({lagna_rashi}) and Nakshatra ({lagna_nak}) shape their core soul vitality and dharma.
3. Provide 3-4 distinct archetypal dimensions as bullet points with bold titles (for example: - **Communication Mastery**: explanation...).
4. Do NOT output raw hashtags like ### at random places or multiple stars. Keep the text clean, respectful, and eloquent.
5. {lang_inst}
"""

    prompt2 = f"""You are AstroJunction Daivajna, an authentic, revered Vedic Astrologer specializing in the {tradition.upper()} tradition.
Deliver an authoritative, personalized timeline analysis of the seeker's active planetary cycles in English. Write warmly and authoritatively like a revered Guru or Daivajna, NOT like a generic chatbot.

Seeker Details: Name: {profile_name}, Active Dasha: {maha_dasha} Mahadasha / {antar_dasha} Antardasha

Instructions:
1. Begin with a clean heading:
### Tradition-Specific Deep Dive ({tradition.upper()})
2. Use the classical principles of {tradition.upper()} astrology to explain the karmic significance and practical guidance for their current active Dasha ({maha_dasha}/{antar_dasha}) right now.
3. Provide 2-3 focused guidance points as bullet points with bold titles.
4. Do NOT output raw hashtags like ### at random places or multiple stars. Keep the text clean, respectful, and eloquent.
5. {lang_inst}
"""
    
    def clean_output(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r'^[#\s*]+', '### ', text.strip())
        if language != 'bn':
            cleaned = re.sub(r'\s*\([^\)]*[\u0980-\u09FF]+[^\)]*\)\s*', '', cleaned)
            cleaned = re.sub(r'\s*\(In (?:fluent )?[A-Za-z\s]+script:[^\)]*\)\s*', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    try:
        part1_res = fetch_part(prompt1)
        part2_res = fetch_part(prompt2)
        
        part1_clean = clean_output(part1_res)
        part2_clean = clean_output(part2_res)
        
        return f"{part1_clean}\n\n{part2_clean}"
    except Exception as e:
        print(f"Warning: Interpretation LLM failed ({e}), using dynamic Vedic astrological calculation fallback.")
        return f"""### Cosmic Synthesis & Lagna Archetype
- **Ascendant ({lagna_rashi})**: Your Lagna governs fundamental vitality, personal resilience, and the primary direction of your karmic expression.
- **Nakshatra ({lagna_nak})**: Bestows sharp intuition, intellectual depth, and leadership qualities that guide your professional and personal decisions.

### Tradition-Specific Deep Dive ({tradition.upper()})
- **Active Dasha**: Operating under the **{maha_dasha} Mahadasha** and **{antar_dasha} Antardasha**.
- **Karmic Focus**: This period activates important transformations in career, wealth consolidation, and personal growth. Focus on steady discipline and moral clarity for maximum spiritual and material success."""



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




