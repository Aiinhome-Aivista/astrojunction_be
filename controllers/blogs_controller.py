from flask import request, jsonify
from database.db_connection import get_db_connection
import json

def list_blogs():
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_blog_ops', ('get_all', 0, '', '', '', '', '', '', '', '[]', 0))
        
        blogs = []
        for result in cursor.stored_results():
            blogs = result.fetchall()
            
        # Parse tags from JSON string to list if necessary
        for blog in blogs:
            if blog.get('tags'):
                try:
                    blog['tags'] = json.loads(blog['tags'])
                except (TypeError, json.JSONDecodeError):
                    pass
            else:
                blog['tags'] = []
                
        return jsonify({"status": "success", "data": blogs}), 200
    except Exception as e:
        print(f"Error fetching blogs: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch blogs"}), 500
    finally:
        cursor.close()
        conn.close()

def get_blog(blog_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_blog_ops', ('get_one', blog_id, '', '', '', '', '', '', '', '[]', 0))
        
        blog = None
        for result in cursor.stored_results():
            blog = result.fetchone()
            
        if not blog:
            return jsonify({"status": "error", "message": "Blog not found"}), 404
            
        if blog.get('tags'):
            try:
                blog['tags'] = json.loads(blog['tags'])
            except (TypeError, json.JSONDecodeError):
                pass
        else:
            blog['tags'] = []
            
        return jsonify({"status": "success", "data": blog}), 200
    except Exception as e:
        print(f"Error fetching blog: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch blog"}), 500
    finally:
        cursor.close()
        conn.close()

def create_blog():
    data = request.json
    if not data or not data.get('title') or not data.get('content'):
        return jsonify({"status": "error", "message": "Title and content are required"}), 400
        
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        
        tags_json = json.dumps(data.get('tags', []))
        
        args = (
            'create',
            0,
            data.get('title'),
            data.get('content'),
            data.get('preview'),
            data.get('image_url'),
            data.get('category'),
            data.get('sub_category'),
            data.get('status', 'Draft'),
            tags_json,
            1 if data.get('pinned') else 0
        )
        
        cursor.callproc('sp_blog_ops', args)
        conn.commit()
        
        new_blog = None
        for result in cursor.stored_results():
            new_blog = result.fetchone()
            
        if new_blog and new_blog.get('tags'):
            try:
                new_blog['tags'] = json.loads(new_blog['tags'])
            except:
                pass
                
        return jsonify({"status": "success", "data": new_blog}), 201
    except Exception as e:
        conn.rollback()
        print(f"Error creating blog: {e}")
        return jsonify({"status": "error", "message": "Failed to create blog"}), 500
    finally:
        cursor.close()
        conn.close()

def update_blog(blog_id):
    data = request.json
    if not data or not data.get('title') or not data.get('content'):
        return jsonify({"status": "error", "message": "Title and content are required"}), 400
        
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        
        tags_json = json.dumps(data.get('tags', []))
        
        args = (
            'update',
            blog_id,
            data.get('title'),
            data.get('content'),
            data.get('preview'),
            data.get('image_url'),
            data.get('category'),
            data.get('sub_category'),
            data.get('status', 'Draft'),
            tags_json,
            1 if data.get('pinned') else 0
        )
        
        cursor.callproc('sp_blog_ops', args)
        conn.commit()
        
        updated_blog = None
        for result in cursor.stored_results():
            updated_blog = result.fetchone()
            
        if not updated_blog:
            return jsonify({"status": "error", "message": "Blog not found"}), 404
            
        if updated_blog.get('tags'):
            try:
                updated_blog['tags'] = json.loads(updated_blog['tags'])
            except:
                pass
                
        return jsonify({"status": "success", "data": updated_blog}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error updating blog: {e}")
        return jsonify({"status": "error", "message": "Failed to update blog"}), 500
    finally:
        cursor.close()
        conn.close()

def delete_blog(blog_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_blog_ops', ('delete', blog_id, '', '', '', '', '', '', '', '[]', 0))
        conn.commit()
        
        deleted_count = 0
        for result in cursor.stored_results():
            row = result.fetchone()
            if row:
                deleted_count = row.get('deleted_count', 0)
                
        if deleted_count == 0:
            return jsonify({"status": "error", "message": "Blog not found or already deleted"}), 404
            
        return jsonify({"status": "success", "message": "Blog deleted successfully"}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error deleting blog: {e}")
        return jsonify({"status": "error", "message": "Failed to delete blog"}), 500
    finally:
        cursor.close()
        conn.close()


# ------------------------------------------------------------
# Categories & Subcategories
# ------------------------------------------------------------

def get_categories():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('get_cats', 0, '', 0))
        categories = []
        for result in cursor.stored_results():
            categories = result.fetchall()
        return jsonify({"status": "success", "data": categories}), 200
    except Exception as e:
        print(f"Error fetching categories: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch categories"}), 500
    finally:
        if conn: conn.close()

def create_category():
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({"status": "error", "message": "Category name is required"}), 400
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('create_cat', 0, name, 0))
        conn.commit()
        new_category = None
        for result in cursor.stored_results():
            new_category = result.fetchone()
        return jsonify({"status": "success", "data": new_category}), 201
    except Exception as e:
        conn.rollback()
        print(f"Error creating category: {e}")
        return jsonify({"status": "error", "message": "Failed to create category"}), 500
    finally:
        if conn: conn.close()

def delete_category(category_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('delete', category_id, '', 0))
        conn.commit()
        return jsonify({"status": "success", "message": "Category deleted successfully"}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error deleting category: {e}")
        return jsonify({"status": "error", "message": "Failed to delete category"}), 500
    finally:
        if conn: conn.close()

def get_subcategories():
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('get_subcats', 0, '', 0))
        subcategories = []
        for result in cursor.stored_results():
            subcategories = result.fetchall()
        return jsonify({"status": "success", "data": subcategories}), 200
    except Exception as e:
        print(f"Error fetching subcategories: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch subcategories"}), 500
    finally:
        if conn: conn.close()

def create_subcategory():
    data = request.json
    name = data.get('name')
    category_id = data.get('category_id')
    if not name or not category_id:
        return jsonify({"status": "error", "message": "Name and category_id are required"}), 400
    
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('create_subcat', 0, name, category_id))
        conn.commit()
        new_sub = None
        for result in cursor.stored_results():
            new_sub = result.fetchone()
        return jsonify({"status": "success", "data": new_sub}), 201
    except Exception as e:
        conn.rollback()
        print(f"Error creating subcategory: {e}")
        return jsonify({"status": "error", "message": "Failed to create subcategory"}), 500
    finally:
        if conn: conn.close()

def delete_subcategory(subcategory_id):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_category_ops', ('delete', subcategory_id, '', 0))
        conn.commit()
        return jsonify({"status": "success", "message": "Subcategory deleted successfully"}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error deleting subcategory: {e}")
        return jsonify({"status": "error", "message": "Failed to delete subcategory"}), 500
    finally:
        if conn: conn.close()
