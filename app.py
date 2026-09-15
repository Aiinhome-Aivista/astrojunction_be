# AstroJunction Backend API Server
from flask import Flask, request, jsonify
from flask_cors import CORS

from database.db_connection import get_db_connection
from controllers import auth_controller
from controllers import profile_controller
from controllers import numerology_controller
from controllers import match_making
from controllers import counselling_controller
from controllers import daily_insights_controller
from controllers import global_zodiac_controller
from controllers import birth_chart_controller
from controllers import roadmap_controller
from controllers import calendar_controller
from controllers import blogs_controller
from controllers import landing_chat_controller
from controllers import admin_controller
from utils.security import require_auth, decode_token
from controllers import knowledge_graph_controller
from controllers import llm_generation_controller
from controllers import full_report_controller
from controllers import AI_response
import jwt as pyjwt

app = Flask(__name__)
CORS(app)

# ==========================================
# 🌍 LANDING PAGE APIs (Publicly Accessible)
# ==========================================

# 1. Ask Jyotish Chatbot (Landing Page)
@app.route("/api/public-chat", methods=["POST"])
def public_chat():
    return landing_chat_controller.public_chat()

# 2. Global Zodiac Forecasts (Landing Page)
@app.route("/zodiac/global-forecast", methods=["POST"])
def zodiac_forecast():
    return global_zodiac_controller.zodiac_forecast()

@app.route("/api/zodiac/all", methods=["GET"])
def get_all_zodiacs():
    return global_zodiac_controller.get_all_zodiacs()

@app.route("/zodiac/compatibility", methods=["POST"])
def zodiac_compatibility():
    return global_zodiac_controller.zodiac_compatibility()

# 3. Panjika Calendar APIs (Landing Page)
@app.route("/calendar/convert", methods=["POST"])
def convert_calendar():
    return calendar_controller.convert_date()

@app.route("/calendar/month", methods=["POST"])
def get_calendar_month():
    return calendar_controller.get_panjika_month()

@app.route("/calendar/full-panjika", methods=["POST"])
def get_full_panjika():
    return calendar_controller.get_full_panjika()


# ==========================================
# DAILY HOROSCOPE & PANCHANG
# ==========================================



@app.route("/daily-insights/panchang", methods=["POST"])
def calculate_ephemeris_panchang():
    return daily_insights_controller.calculate_ephemeris_panchang()

@app.route("/daily-insights/horoscope", methods=["POST"])
def daily_horoscope():
    return daily_insights_controller.daily_horoscope()

# ==========================================
# BIRTH CHART AND TRADITIONS
# ==========================================

@app.route("/birth-chart/generate", methods=["POST"])
def calculate_ephemeris_chart():
    return birth_chart_controller.calculate_ephemeris_chart()

@app.route("/birth-chart/ai-interpretation", methods=["POST"])
def post_interpret():
    return birth_chart_controller.post_interpret()

@app.route("/ai/roadmap", methods=["GET"])
@app.route("/api/roadmap", methods=["GET"])
def get_user_roadmap():
    return roadmap_controller.get_user_roadmap()

@app.route("/ai/roadmap/download-pdf", methods=["POST"])
@app.route("/api/roadmap/download-pdf", methods=["POST"])
def download_roadmap_pdf():
    return roadmap_controller.download_roadmap_pdf()

@app.route("/api/roadmap/filtered-predictions", methods=["POST"])
def post_filtered_roadmap_predictions():
    return roadmap_controller.post_filtered_roadmap_predictions()

# ==========================================
# 🌟 UNIFIED MASTER REPORT DATA API
# ==========================================
@app.route("/api/reports/full-report-data", methods=["POST"])
def get_full_report_data():
    return full_report_controller.get_full_report_data()





@app.route("/")
def home():
    return "Server is running!"


@app.route("/health")
def health():
    return jsonify({
        "status": "success",
        "data": {
            "message": "AstroJunction API is healthy",
        },
    })


# ---------------- Auth ----------------

@app.route("/auth/register", methods=["POST"])
@app.route("/api/auth/register", methods=["POST"])
def register():
    return auth_controller.register()


@app.route("/auth/login", methods=["POST"])
@app.route("/api/auth/login", methods=["POST"])
def login():
    return auth_controller.login()


@app.route("/auth/google", methods=["POST"])
@app.route("/api/auth/google", methods=["POST"])
def google_auth():
    return auth_controller.google_auth()


@app.route("/auth/current-user", methods=["GET"])
@app.route("/api/auth/current-user", methods=["GET"])
@require_auth
def me():
    return auth_controller.me(request.user_id)


# ---------------- Profiles (require login) ----------------

@app.route("/user/profiles", methods=["GET"])
@require_auth
def get_profiles():
    return profile_controller.list_profiles(request.user_id)


@app.route("/user/profiles", methods=["POST"])
@require_auth
def post_profile():
    return profile_controller.create_profile(request.user_id)


@app.route("/user/profiles/<profile_id>", methods=["PUT"])
@require_auth
def put_profile(profile_id):
    return profile_controller.update_profile(request.user_id, profile_id)


@app.route("/user/profiles/<profile_id>", methods=["DELETE"])
@require_auth
def delete_profile(profile_id):
    return profile_controller.delete_profile(request.user_id, profile_id)


# ---------------- Numerology reports (require login) ----------------

@app.route("/numerology/reports", methods=["POST"])
@require_auth
def post_numerology():
    return numerology_controller.save_numerology(request.user_id)


@app.route("/numerology/reports/<profile_id>", methods=["GET"])
@require_auth
def get_numerology(profile_id):
    return numerology_controller.get_numerology(request.user_id, profile_id)



@app.route("/numerology/ai-insights", methods=["POST"])
def post_numerology_insights():
    return numerology_controller.get_dynamic_insights()

@app.route("/numerology/calculate", methods=["POST"])
def calculate_numerology_route():
    return numerology_controller.calculate_numerology_endpoint()



# ---------------- Matchmaking / Kundli Milan reports (require login) ----------------


@app.route("/matchmaking/reports", methods=["POST"])
@app.route("/api/matchmaking/reports", methods=["POST"])
@require_auth
def post_match_report1():
    # ডাইনামিক কুন্ডলী মিলন এবং রিপোর্ট সেভ করার জন্য কল হবে
    return match_making.create_match_report(request.user_id)


@app.route("/matchmaking/reports", methods=["GET"])
@app.route("/api/matchmaking/reports", methods=["GET"])
@require_auth
def get_match_reports1():
    # ইউজারের আগের সেভ করা সমস্ত রিপোর্ট দেখার জন্য
    return match_making.list_match_reports(request.user_id)


@app.route("/matchmaking/reports/<report_id>", methods=["GET"])
@app.route("/api/matchmaking/reports/<report_id>", methods=["GET"])
@require_auth
def get_match_report1(report_id):
    # নির্দিষ্ট কোনো একটি রিপোর্টের বিস্তারিত জানার জন্য
    return match_making.get_match_report(request.user_id, report_id)


@app.route("/matchmaking/reports/<report_id>/pdf", methods=["GET"])
@app.route("/api/matchmaking/reports/<report_id>/pdf", methods=["GET"])
def get_match_report_pdf1(report_id):
    # PDF ডাউনলোড করার জন্য (এখানে টোকেন URL প্যারামিটারে আসে)
    token = request.args.get("token", "")
    if not token:
        return jsonify({"status": "error", "message": "Missing token", "error_code": "AUTH_REQUIRED"}), 401
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        return jsonify({"status": "error", "message": "Invalid or expired token", "error_code": "TOKEN_INVALID"}), 401

    return match_making.download_match_report_pdf(payload["sub"], report_id)


@app.route("/matchmaking/generate-pdf", methods=["POST"])
@app.route("/api/matchmaking/generate-pdf", methods=["POST"])
def generate_direct_match_pdf():
    # ফ্রন্টএন্ড থেকে সরাসরি ডেটা পাঠিয়ে ব্যাকএন্ড থেকে PDF জেনারেট করে ডাউনলোড করার এন্ডপয়েন্ট
    return match_making.generate_direct_pdf()


@app.route("/matchmaking/calculate", methods=["POST"])
@app.route("/api/matchmaking/calculate", methods=["POST"])
def calculate_matchmaking_route():
    # ফ্রন্টএন্ড থেকে সরাসরি Swiss Ephemeris ম্যাচ মেকিং গণনার এন্ডপয়েন্ট
    return match_making.calculate_match_endpoint()



# ---------------- AI Counsellor sessions & messages (require login) ----------------

@app.route("/ai-counsellor/sessions", methods=["GET"])
@require_auth
def get_sessions():
    return counselling_controller.list_sessions(request.user_id)


@app.route("/ai-counsellor/sessions", methods=["POST"])
@require_auth
def post_session():
    return counselling_controller.create_session(request.user_id)


@app.route("/ai-counsellor/sessions/<session_id>", methods=["PUT"])
@require_auth
def put_session(session_id):
    return counselling_controller.rename_session(request.user_id, session_id)


@app.route("/ai-counsellor/sessions/<session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id):
    return counselling_controller.delete_session(request.user_id, session_id)


@app.route("/ai-counsellor/sessions/<session_id>/messages", methods=["GET"])
@require_auth
def get_session_messages(session_id):
    return counselling_controller.get_messages(request.user_id, session_id)


@app.route("/ai-counsellor/sessions/<session_id>/messages", methods=["POST"])
@require_auth
def post_session_message(session_id):
    return counselling_controller.send_message(request.user_id, session_id)


# ---------------- Blogs (Admin only, but for now we'll just require auth or leave public depending on rules) ----------------
# We will leave GET public so users can view blogs, and POST/PUT/DELETE protected. 
# However, the user said "admin & k-graph ta admin er jonno hobe user ke etar asscess dewa hobe na", 
# which suggests the admin panel is only for admins. The routes can just be standard for now.

@app.route("/api/blogs", methods=["GET"])
def get_blogs():
    return blogs_controller.list_blogs()

@app.route("/api/blogs/<blog_id>", methods=["GET"])
def get_blog(blog_id):
    return blogs_controller.get_blog(blog_id)

@app.route("/api/blogs", methods=["POST"])
# @require_auth # Uncomment to protect when auth is fully implemented in frontend
def post_blog():
    return blogs_controller.create_blog()

@app.route("/api/blogs/<blog_id>", methods=["PUT"])
# @require_auth
def put_blog(blog_id):
    return blogs_controller.update_blog(blog_id)

@app.route("/api/blogs/<blog_id>", methods=["DELETE"])
# @require_auth
def delete_blog(blog_id):
    return blogs_controller.delete_blog(blog_id)

@app.route("/api/categories", methods=["GET"])
def get_categories():
    return blogs_controller.get_categories()

@app.route("/api/categories", methods=["POST"])
def post_category():
    return blogs_controller.create_category()

@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    return blogs_controller.delete_category(category_id)

@app.route("/api/subcategories", methods=["GET"])
def get_subcategories():
    return blogs_controller.get_subcategories()

@app.route("/api/subcategories", methods=["POST"])
def post_subcategory():
    return blogs_controller.create_subcategory()

@app.route("/api/subcategories/<int:subcategory_id>", methods=["DELETE"])
def delete_subcategory(subcategory_id):
    return blogs_controller.delete_subcategory(subcategory_id)

@app.route("/api/admin/dashboard-stats", methods=["GET"])
# @require_auth # Protect this when auth is ready
def get_dashboard_stats():
    return admin_controller.get_dashboard_stats()

@app.route("/api/admin/users", methods=["GET"])
# @require_auth
def get_all_users():
    return admin_controller.get_all_users()

@app.route("/api/admin/users/<user_id>/role", methods=["PUT"])
# @require_auth
def update_user_role(user_id):
    data = request.json
    return admin_controller.update_user_role(user_id, data.get('role'))

@app.route("/api/admin/users/<user_id>/status", methods=["PUT"])
# @require_auth
def update_user_status(user_id):
    data = request.json
    return admin_controller.update_user_status(user_id, data.get('is_active'))

@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
# @require_auth
def delete_user(user_id):
    return admin_controller.delete_user(user_id)

@app.route("/api/admin/logs/ai", methods=["GET"])
# @require_auth
def get_ai_logs():
    return admin_controller.get_ai_logs()

@app.route("/api/admin/logs/system", methods=["GET"])
# @require_auth
def get_system_logs():
    return admin_controller.get_system_logs()

@app.route("/api/admin/revenue/stats", methods=["GET"])
# @require_auth
def get_revenue_stats():
    return admin_controller.get_revenue_stats()

@app.route("/api/admin/revenue/transactions", methods=["GET"])
# @require_auth
def get_all_transactions():
    return admin_controller.get_all_transactions()

@app.errorhandler(Exception)
def handle_exception(e):
    """Global error handler to catch exceptions and log them."""
    import traceback
    error_msg = f"{str(e)}\n{traceback.format_exc()}"
    print(f"[ERROR] Global Exception: {error_msg}")
    try:
        admin_controller.log_system_error('error', error_msg, 'flask_app')
    except Exception as log_err:
        print(f"Failed to log system error: {log_err}")
    return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# ---------------- Knowledge Graph ----------------

@app.route("/api/knowledge-graph/stats", methods=["GET"])
def get_kg_stats():
    return knowledge_graph_controller.get_stats()

@app.route("/api/knowledge-graph/nodes", methods=["GET"])
def get_kg_nodes():
    return knowledge_graph_controller.get_nodes()

@app.route("/api/knowledge-graph/nodes/<node_id>", methods=["GET"])
def get_kg_node(node_id):
    return knowledge_graph_controller.get_node(node_id)

@app.route("/api/knowledge/generate-from-llm", methods=["POST"])
def generate_pure_llm_facts():
    """
    Endpoint to directly generate knowledge from LLM without PDFs.
    """
    return llm_generation_controller.start_llm_generation()    

  

@app.route("/api/matchmaking/synthesis", methods=["POST"])
@require_auth
def post_match_synthesis():
    return match_making.generate_ai_synthesis(request.user_id)


@app.route("/api/matchmaking/ai-synthesis/<synthesis_id>/pdf", methods=["GET"])
def download_ai_synthesis_pdf1(synthesis_id):
    return match_making.download_ai_synthesis_pdf(synthesis_id)


@app.route("/api/matchmaking/ai-synthesis/generate-pdf", methods=["POST"])
def generate_direct_ai_synthesis_pdf1():
    return match_making.generate_direct_ai_synthesis_pdf()


@app.route("/api/ai/response_generate", methods=["POST"])
@require_auth
def direct_response_generate1():
    return AI_response.direct_response_generate()


@app.route("/api/ai/history", methods=["GET"])
@require_auth
def get_ai_history():
    return AI_response.get_chat_history()


@app.route("/api/ai/history/<user_id>", methods=["GET"])
def get_ai_history_by_user(user_id):
    return AI_response.get_chat_history(target_user_id=user_id)


@app.route("/api/ai/history", methods=["DELETE"])
@require_auth
def clear_ai_history():
    return AI_response.clear_chat_history()



if __name__ == "__main__":
    # Fail fast if MySQL isn't reachable, rather than starting silently broken.
    conn = get_db_connection()
    conn.close()
    app.run(host="0.0.0.0", port=5001, debug=True)

