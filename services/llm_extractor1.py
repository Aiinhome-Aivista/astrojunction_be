import json
import re
import os
import requests
from dotenv import load_dotenv
from services.settings_service import get_setting

load_dotenv()


DIRECT_LLM_PROMPT = """
You are a strict Jyotish Knowledge Graph Extractor. 
You MUST return ONLY a valid JSON object with a single key "facts". 
The "facts" key must contain an array of objects. Do not use 'data' or any other keys.

Each object MUST strictly follow this EXACT nested JSON structure without exception:
{
  "knowledge_source": "LLM",
  "confidence": 0.99,
  "source_entity": {
    "name": "Name of the entity (e.g. Mars, Sun, Ashwini)",
    "type": "PLANET, SIGN, or NAKSHATRA"
  },
  "target_entity": {
    "name": "Name of the entity (e.g. Aries, Cancer, Moon)",
    "type": "PLANET, SIGN, or NAKSHATRA"
  },
  "relationship": {
    "label": "OWN_SIGN, EXALTED_IN, DEBILITATED_IN, FRIEND, ENEMY, or NEUTRAL",
    "condition": "",
    "result": ""
  },
  "pdf_evidence": ""
}

Example 1 (Lordship):
Source: Mars (PLANET), Target: Aries (SIGN), Relationship: OWN_SIGN

Example 2 (Exaltation):
Source: Sun (PLANET), Target: Aries (SIGN), Relationship: EXALTED_IN

Example 3 (Friendship):
Source: Sun (PLANET), Target: Moon (PLANET), Relationship: FRIEND

Do NOT output plain text. DO NOT use custom keys like 'planet' or 'sign'. YOU MUST USE 'source_entity' and 'target_entity'.
"""

def generate_facts_from_topic(topic):
    """শুধুমাত্র LLM-এর নিজস্ব জ্ঞান থেকে ডাটা আনার ফাংশন"""
    llm_url = get_setting("MISTRAL_LOCAL_URL", "").rstrip("/")
    model_name = get_setting("MISTRAL_MODEL", "mistral:latest")
    
    if not llm_url:
        print("[LLMExtractor] MISTRAL_LOCAL_URL is not configured in Admin Settings.")
        return {"facts": []}

    api_endpoint = f"{llm_url}/v1/chat/completions"
    if "api/" not in api_endpoint and "v1/" not in api_endpoint:
        api_endpoint = f"{llm_url}/api/chat"

    print(f"\n{'='*60}")
    print(f"[LLM CALL - Extractor] Provider: mistral_local | Model/Version: {model_name} | Endpoint: {api_endpoint} | Topic: {topic}")
    print(f"{'='*60}\n")

    prompt = f"Generate exhaustive Jyotish facts as a JSON object for the following TOPIC:\n\nTOPIC: {topic}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": DIRECT_LLM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "stream": False
    }

    response = None
    try:
        response = requests.post(
            api_endpoint,
            json=payload,
            headers={"Content-Type": "application/json", "Connection": "close"}
        )
        response.raise_for_status()
        
        response_data = response.json()
        returned_model = response_data.get("model", model_name)
        print(f"[LLM RESPONSE - Extractor] Resolved Model/Version: {returned_model}")
        if "choices" in response_data:
            output = response_data["choices"][0]["message"]["content"].strip()
        elif "message" in response_data:
            output = response_data["message"]["content"].strip()
        else:
            output = str(response_data)

        if output.startswith("```"):
            output = re.sub(r"^```(?:json)?\n?", "", output)
            output = re.sub(r"\n?```$", "", output)
            output = output.strip()
            print(repr(output))
        return json.loads(output)
    except Exception as e:
        print(f"Error fetching data for topic '{topic}': {e}")
        return {"facts": []}
    finally:
        if response is not None:
            response.close()


def get_ai_response(system_prompt, messages, timeout=None, max_tokens=750):
    if timeout is None:
        try:
            timeout = int(get_setting("LLM_TIMEOUT", "30"))
        except Exception:
            timeout = 30
    llm_url = get_setting("MISTRAL_LOCAL_URL", "").rstrip("/")
    model_name = get_setting("MISTRAL_MODEL", "mistral:latest")

    if not llm_url:
        raise ValueError("MISTRAL_LOCAL_URL is not configured in Admin Settings.")

    # OpenAI-compatible endpoint
    api_endpoint = f"{llm_url}/v1/chat/completions"

    print(f"\n{'='*60}")
    print(f"[LLM CALL - Extractor AI Response] Provider: mistral_local | Model/Version: {model_name} | Endpoint: {api_endpoint}")
    print(f"{'='*60}\n")

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            *messages
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": False
    }

    response = None
    try:
        response = requests.post(
            api_endpoint,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Connection": "close"
            },
            timeout=timeout
        )

        response.raise_for_status()

        response_data = response.json()
        returned_model = response_data.get("model", model_name)
        print(f"[LLM RESPONSE - Extractor AI Response] Resolved Model/Version: {returned_model}")

        # OpenAI-compatible response
        if "choices" in response_data:
            return response_data["choices"][0]["message"]["content"].strip()

        # Ollama response
        elif "message" in response_data:
            return response_data["message"]["content"].strip()

        else:
            raise ValueError(
                f"Unexpected LLM response: {response_data}"
            )

    except Exception as e:
        print(f"LLM Error: {e}")
        raise
    finally:
        if response is not None:
            response.close()
    