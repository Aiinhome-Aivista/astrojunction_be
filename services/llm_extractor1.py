import json
import re
import os
import requests
from dotenv import load_dotenv

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
    llm_url = os.getenv("MISTRAL_LOCAL_URL", "http://122.163.121.176:3041")
    model_name = os.getenv("MISTRAL_MODEL", "mistral:latest")
    
    api_endpoint = f"{llm_url.rstrip('/')}/v1/chat/completions"
    if "api/" not in api_endpoint and "v1/" not in api_endpoint:
        api_endpoint = f"{llm_url.rstrip('/')}/api/chat"

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

    try:
        response = requests.post(api_endpoint, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        
        response_data = response.json()
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


def get_ai_response(system_prompt, messages, timeout=20, max_tokens=750):
    llm_url = os.getenv(
        "MISTRAL_LOCAL_URL",
        "http://122.163.121.176:3041"
    )

    model_name = os.getenv(
        "MISTRAL_MODEL",
        "mistral:latest"
    )

    llm_url = llm_url.rstrip("/")

    # OpenAI-compatible endpoint
    api_endpoint = f"{llm_url}/v1/chat/completions"

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

    try:
        response = requests.post(
            api_endpoint,
            json=payload,
            headers={
                "Content-Type": "application/json"
            },
            timeout=timeout
        )

        response.raise_for_status()

        response_data = response.json()

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
    