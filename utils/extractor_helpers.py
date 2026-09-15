import re
import os

ALLOWED_NODE_TYPES = {"PLANET", "SIGN", "HOUSE", "YOGA", "DOSHA", "NAKSHATRA", "GRAHA", "OTHER"}
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "0.70"))
ALLOW_PURE_LLM_FACTS = os.getenv("ALLOW_PURE_LLM_FACTS", "false").lower() == "true"

def normalize_node_type(node_type):
    if not node_type:
        return "OTHER"
    node_type = str(node_type).upper().strip()
    return node_type if node_type in ALLOWED_NODE_TYPES else "OTHER"


def create_node_id(node_type, title):
    node_type = node_type.split("(")[0].strip()
    title = title.split("(")[0].strip()

    safe_type = re.sub(r"[^a-zA-Z0-9_]", "_", node_type.lower())
    safe_title = re.sub(r"[^a-zA-Z0-9_]", "_", title.lower())

    return f"{safe_type}_{safe_title}"

def validate_fact(fact):
    if not isinstance(fact, dict):
        return False

    src = fact.get("source_entity")
    tgt = fact.get("target_entity")
    rel = fact.get("relationship")

 
    if not all([src, tgt, rel]) or not all([src.get("name"), tgt.get("name"), rel.get("label")]):
        return False

    confidence = fact.get("confidence", 0.99)
    try:
       
        if float(confidence) < 0.50:
            return False
    except ValueError:
        pass # যদি টেক্সট দেয়, তবুও স্কিপ করবে না

    knowledge_source = str(fact.get("knowledge_source", "LLM")).upper()
    
    
    
    return True