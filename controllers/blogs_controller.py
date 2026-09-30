from flask import request, jsonify
from database.db_connection import get_db_connection
import json
import re
import unicodedata
import time

def generate_slug(text: str) -> str:
    """Generate a URL-friendly slug from text."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("utf-8")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text)

def _get_unique_slug(cursor, title: str, blog_id: int = 0) -> str:
    base_slug = generate_slug(title) or f"blog-{blog_id or int(time.time())}"
    slug = base_slug
    counter = 1
    while True:
        cursor.execute("SELECT id FROM blogs WHERE slug = %s AND id != %s", (slug, blog_id))
        if not cursor.fetchone():
            break
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug

def ensure_slug_schema():
    """Ensure slug column exists in blogs table and populate any missing slugs."""
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW COLUMNS FROM blogs LIKE %s", ("slug",))
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE blogs ADD COLUMN slug VARCHAR(255) UNIQUE AFTER title")
            conn.commit()

        cursor.execute("SELECT id, title, slug FROM blogs WHERE slug IS NULL OR slug = ''")
        rows = cursor.fetchall()
        for row in rows:
            slug = _get_unique_slug(cursor, row["title"], row["id"])
            cursor.execute("UPDATE blogs SET slug = %s WHERE id = %s", (slug, row["id"]))
        conn.commit()
    except Exception as e:
        print(f"Slug schema check error: {e}")
    finally:
        cursor.close()
        conn.close()

# Auto-verify on controller load
ensure_slug_schema()

def list_blogs():
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    
    try:
        cursor = conn.cursor(dictionary=True)
        status_filter = request.args.get('status', '')
        
        if status_filter.lower() == 'all':
            cursor.execute("SELECT * FROM blogs ORDER BY pinned DESC, created_at DESC")
        elif status_filter:
            cursor.execute("SELECT * FROM blogs WHERE status = %s ORDER BY pinned DESC, created_at DESC", (status_filter,))
        else:
            cursor.execute("SELECT * FROM blogs WHERE status = 'Published' ORDER BY pinned DESC, created_at DESC")
        
        blogs = cursor.fetchall()
            
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
            
        if new_blog:
            new_id = new_blog.get('id')
            slug = _get_unique_slug(cursor, data.get('title'), new_id)
            cursor.execute("UPDATE blogs SET slug = %s WHERE id = %s", (slug, new_id))
            conn.commit()
            new_blog['slug'] = slug
            if new_blog.get('tags'):
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
            
        slug = _get_unique_slug(cursor, data.get('title'), blog_id)
        cursor.execute("UPDATE blogs SET slug = %s WHERE id = %s", (slug, blog_id))
        conn.commit()
        updated_blog['slug'] = slug

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


def get_blog_by_slug(slug):
    """Fetch a single published blog by its slug (for public BlogPage)."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM blogs WHERE slug = %s AND status = 'Published' LIMIT 1",
            (slug,)
        )
        blog = cursor.fetchone()
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
        print(f"Error fetching blog by slug: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch blog"}), 500
    finally:
        cursor.close()
        conn.close()


def increment_blog_share(blog_id):
    """Increment share count for a blog."""
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "UPDATE blogs SET shares_count = COALESCE(shares_count, 0) + 1 WHERE id = %s",
            (blog_id,)
        )
        conn.commit()
        cursor.execute("SELECT id, shares_count FROM blogs WHERE id = %s", (blog_id,))
        row = cursor.fetchone()
        return jsonify({"status": "success", "data": row}), 200
    except Exception as e:
        conn.rollback()
        print(f"Error incrementing share: {e}")
        return jsonify({"status": "error", "message": "Failed to increment share"}), 500
    finally:
        cursor.close()
        conn.close()


def upload_blog_image():
    """Handle secure image upload for blog posts."""
    import os, time
    from werkzeug.utils import secure_filename
    
    # Read upload path dynamically from .env or default to upload/blogs_image
    env_folder = os.getenv("BLOG_UPLOAD_DIR", "upload/blogs_image").strip().replace('\\', '/')
    base_dir = os.path.dirname(os.path.dirname(__file__))
    upload_folder = os.path.join(base_dir, *env_folder.split('/'))
    allowed_exts = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "No file selected"}), 400
        
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_exts:
        return jsonify({"error": "File type not allowed"}), 400
        
    name = secure_filename(file.filename.rsplit('.', 1)[0])
    filename = f"{name}_{int(time.time())}.{ext}"
    os.makedirs(upload_folder, exist_ok=True)
    file.save(os.path.join(upload_folder, filename))
    
    # Return normalized web path (e.g. /upload/blogs_image/xyz.png)
    web_path = f"/{env_folder}/{filename}"
    return jsonify({"url": web_path}), 200


def serve_uploaded_file(filename):
    """Serve uploaded blog images and files."""
    import os
    from flask import send_from_directory
    
    root_dir = os.path.dirname(os.path.dirname(__file__))
    # Check in upload directory
    upload_dir = os.path.join(root_dir, 'upload')
    if os.path.exists(os.path.join(upload_dir, filename)):
        return send_from_directory(upload_dir, filename)
    # Check in static/uploads directory fallback
    static_upload_dir = os.path.join(root_dir, 'static', 'uploads')
    if os.path.exists(os.path.join(static_upload_dir, filename)):
        return send_from_directory(static_upload_dir, filename)
        
    return send_from_directory(upload_dir, filename)