from flask import jsonify, request

from database.db_connection import call_procedure
import json    



def get_stats():
    """
    Returns Knowledge Graph statistics from MySQL.
    """

    try:
        rows = call_procedure(
            "sp_get_stats",
            []
        )

        if not rows:
            stats = {
                "nodes": 0,
                "relationships": 0,
                "active_profiles": 0
            }
        else:
            stats = rows[0]

            # Keep frontend-compatible response
            stats["active_profiles"] = 1

        return jsonify({
            "status": "success",
            "data": stats
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500




def get_nodes():
    """
    Returns nodes from MySQL.

    Supported query parameters:

        /nodes
        /nodes?type=PLANET
        /nodes?type=YOGA
        /nodes?search=jupiter
        /nodes?type=PLANET&search=sun
    """

    try:

        node_type = request.args.get("type", "ALL")
        search = request.args.get("search", "")

        rows = call_procedure(
            "sp_get_nodes",
            [
                node_type,
                search
            ]
        )

        nodes = []

      

        for node in rows:

            node_id = node["id"]

            if node.get("properties"):
                if isinstance(node["properties"], str):
                    node["properties"] = json.loads(node["properties"])
            else:
                node["properties"] = {}

         
            relationship_rows = call_procedure(
                "sp_get_node_relationships",
                [node_id]
            )

            relationships = []

            for relationship in relationship_rows:

                relationships.append({
                    "label": relationship["label"],
                    "target": relationship["target_id"]
                })

            # Add relationship information
            node["relationships"] = relationships

            # Calculate connection count
            node["connections"] = len(relationships)

           
          

            nodes.append(node)

        return jsonify({
            "status": "success",
            "data": {
                "nodes": nodes,
                "total": len(nodes)
            }
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def get_node(node_id):
    """
    Returns one node and its relationships.
    """

    try:

       

        rows = call_procedure(
            "sp_get_node",
            [node_id]
        )

        if not rows:

            return jsonify({
                "status": "error",
                "message": "Node not found"
            }), 404

        node = rows[0]

        if node.get("properties"):
            if isinstance(node["properties"], str):
                node["properties"] = json.loads(node["properties"])
        else:
            node["properties"] = {}

        relationship_rows = call_procedure(
            "sp_get_node_relationships",
            [node_id]
        )

        relationships = []

        for relationship in relationship_rows:

            relationships.append({
                "label": relationship["label"],
                "target": relationship["target_id"]
            })

        node["relationships"] = relationships

        # Connection count
        node["connections"] = len(relationships)

      
        

        return jsonify({
            "status": "success",
            "data": node
        }), 200

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500