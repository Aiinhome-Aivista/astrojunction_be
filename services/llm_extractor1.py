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
    """Generates astrological facts using the active LLM configured in Admin Settings."""
    from services.llm_service import _execute_llm
    prompt = f"Generate exhaustive Jyotish facts as a JSON object for the following TOPIC:\n\nTOPIC: {topic}"
    try:
        output = _execute_llm(DIRECT_LLM_PROMPT, [{"role": "user", "content": prompt}])
        if output.startswith("```"):
            output = re.sub(r"^```(?:json)?\n?", "", output)
            output = re.sub(r"\n?```$", "", output)
            output = output.strip()
        return json.loads(output)
    except Exception as e:
        print(f"[LLMExtractor] Error fetching data for topic '{topic}': {e}")
        return {"facts": []}


def get_ai_response(system_prompt, messages, timeout=None, max_tokens=750):
    """Executes AI response using the active LLM configured in Admin Settings."""
    from services.llm_service import _execute_llm
    return _execute_llm(system_prompt, messages, max_tokens=max_tokens)
    