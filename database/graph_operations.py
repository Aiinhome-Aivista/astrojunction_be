import json
from utils.extractor_helpers import validate_fact, normalize_node_type, create_node_id

def upsert_node(cursor, node_type, title, title_native=None, description=None, properties=None):
    node_type = normalize_node_type(node_type)
    title = str(title).strip()
    
    if not title:
        return None

    node_id = create_node_id(node_type, title)
    
    if properties is None:
        properties = {}
    properties_json = json.dumps(properties)

    sql = """
        INSERT INTO nodes (id, type, title, title_native, description, properties)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            type = VALUES(type),
            title = VALUES(title),
            title_native = VALUES(title_native),
            description = VALUES(description),
            properties = VALUES(properties),
            updated_at = CURRENT_TIMESTAMP
    """
    cursor.execute(sql, (node_id, node_type, title, title_native, description, properties_json))
    return node_id


def create_relationship(cursor, source_id, target_id, label):
    if not source_id or not target_id or not label:
        return None
    label = str(label).strip().upper()

    cursor.execute(
        "SELECT id FROM relationships WHERE source_id = %s AND target_id = %s AND label = %s LIMIT 1",
        (source_id, target_id, label)
    )
    row = cursor.fetchone()
    
    
    if row:
        return row['id']

    
    insert_sql = """
        INSERT INTO relationships (source_id, target_id, label) VALUES (%s, %s, %s)
    """
    cursor.execute(insert_sql, (source_id, target_id, label))
    return cursor.lastrowid



def save_evidence(cursor, relationship_id, book_name, knowledge_source, evidence):
    sql = """
        INSERT INTO relationship_sources (relationship_id, book_name, knowledge_source, evidence)
        VALUES (%s, %s, %s, %s)
    """
    cursor.execute(sql, (relationship_id, book_name, knowledge_source, evidence))


def save_fact(cursor, fact, book_name):
    if not validate_fact(fact):
        print(fact)
        return False

    src = fact["source_entity"]
    tgt = fact["target_entity"]
    rel = fact["relationship"]

    source_desc = rel.get("condition", "") or rel.get("result", "")
    target_desc = rel.get("result", "")
    
    src_properties = src.get("properties", {})
    tgt_properties = tgt.get("properties", {})

    source_id = upsert_node(cursor, src.get("type"), src["name"], src.get("native_name"), source_desc, src_properties)
    target_id = upsert_node(cursor, tgt.get("type"), tgt["name"], tgt.get("native_name"), target_desc, tgt_properties)

    
    relationship_id = create_relationship(cursor, source_id, target_id, rel["label"])
    
    if relationship_id:
       
        knowledge_source = fact.get("knowledge_source", "UNKNOWN")
        evidence = fact.get("pdf_evidence", "")
        
        save_evidence(cursor, relationship_id, book_name, knowledge_source, evidence)
        return True
        
    return False