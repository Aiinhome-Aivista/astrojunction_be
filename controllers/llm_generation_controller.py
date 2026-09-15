import threading
from flask import jsonify, request
from database.db_connection import get_db_connection
from database.graph_operations import save_fact


from services.llm_extractor1 import generate_facts_from_topic

DEFAULT_TOPICS = [
    "Planets and their Own Signs (Lordships)",
    "Planets and their Exaltation (Ucha) and Debilitation (Neecha) signs",
    "Permanent Friendship, Enmity, and Neutral relationships between the 9 planets",
    "The 27 Nakshatras and their ruling planets"
]

def run_direct_llm_job(topics):
    print("\nStarting Direct LLM Knowledge Extraction...")
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)

    total_saved = 0
    book_name = "LLM_Internal_Knowledge"  


    try:
        for idx, topic in enumerate(topics, start=1):
            print(f"\n[{idx}/{len(topics)}] Asking LLM about: {topic}")
            
            result = generate_facts_from_topic(topic)
            
            print("\n----- LLM RAW OUTPUT -----")
            print(result)
            print("--------------------------\n")
            
            
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], dict) and "facts" in result[0]:
                    facts = result[0]["facts"]
                else:
                    facts = result 
            elif isinstance(result, dict):
                facts = result.get("facts") or result.get("data") or []
            else:
                facts = []

            print(f"Found {len(facts)} facts. Saving to DB...")

            for fact in facts:
                if not isinstance(fact, dict):
                    print("  - Skipped: Fact is not a valid dictionary.")
                    continue
                
                if "source_entity" not in fact and "planet" in fact and "sign" in fact:
                    sign_val = fact["sign"][0] if isinstance(fact["sign"], list) else fact["sign"]
                    fact["source_entity"] = {"name": fact["planet"], "type": "PLANET"}
                    fact["target_entity"] = {"name": sign_val, "type": "SIGN"}
                    fact["relationship"] = {"label": "OWN_SIGN"}

                elif "source_entity" not in fact and "nakshatra" in fact and "ruling_planet" in fact:
                    fact["source_entity"] = {"name": fact["ruling_planet"], "type": "PLANET"}
                    fact["target_entity"] = {"name": fact["nakshatra"], "type": "NAKSHATRA"}
                    fact["relationship"] = {"label": "NAKSHATRA_LORD"}

                elif "source_entity" not in fact and "planets" in fact and isinstance(fact.get("planets"), list) and len(fact["planets"]) >= 2:
                    p1 = fact["planets"][0].split('/')[0].strip() # Sun/Surya থাকলে শুধু Sun নেবে
                    p2 = fact["planets"][1].split('/')[0].strip()
                    
                    cond = fact.get("condition", "").upper()
                    if "FRIEND" in cond:
                        rel = "FRIEND"
                    elif "ENEMY" in cond:
                        rel = "ENEMY"
                    else:
                        rel = "NEUTRAL"
                        
                    fact["source_entity"] = {"name": p1, "type": "PLANET"}
                    fact["target_entity"] = {"name": p2, "type": "PLANET"}
                    fact["relationship"] = {"label": rel}

            
                elif "source_entity" not in fact and "condition" in fact:
                    cond_text = fact["condition"]
                    rel_label = fact.get("relationship", "UNKNOWN")
                    if "exalted in" in cond_text.lower() or "debilitated in" in cond_text.lower():
                        parts = cond_text.split(" in ")
                        if len(parts) == 2:
                            planet_name = parts[0].replace(" is exalted", "").replace(" is debilitated", "").strip()
                            sign_name = parts[1].replace(" sign.", "").strip()
                            fact["source_entity"] = {"name": planet_name, "type": "PLANET"}
                            fact["target_entity"] = {"name": sign_name, "type": "SIGN"}
                            fact["relationship"] = {"label": rel_label}
          
                print("\n-> Checking Fact:", fact)
                
                try:
                   
                    if save_fact(cursor, fact, book_name):
                        total_saved += 1
                        print("  ✓ SUCCESS: Fact saved to DB!")
                    else:
                        print("  ✗ FAILED: Validation skipped this fact.")
                except Exception as e:
                    print(f"  ✗ DB ERROR: {e}")
            
            
            connection.commit()

        print(f"\n==============================================")
        print(f"Success! Saved {total_saved} pure LLM facts to database.")
        print(f"==============================================\n")
        
    except Exception as e:
        connection.rollback()
        print(f"Error in LLM background job: {e}")
    finally:
        cursor.close()
        connection.close()


def start_llm_generation():
    """
    API endpoint function
    """
  
    req_data = request.get_json(silent=True) or {}
    topics_to_process = req_data.get("topics", DEFAULT_TOPICS)

    generation_thread = threading.Thread(target=run_direct_llm_job, args=(topics_to_process,))
    generation_thread.start()

    return jsonify({
        "status": "success",
        "message": f"LLM direct generation started for {len(topics_to_process)} topics in the background.",
        "topics": topics_to_process
    }), 202
    