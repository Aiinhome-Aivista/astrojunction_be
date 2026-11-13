from flask import request, jsonify
import json
import re
from services.llm_service import get_zodiac_forecast_response
from database.db_connection import call_procedure

def get_all_zodiacs():
    try:
        results = call_procedure("sp_zodiac_ops", ["get_all", None])
        # The nakshatras are stored as comma separated strings, we need to convert them to lists for the frontend
        for row in results:
            if row.get('nakshatras'):
                row['nakshatras'] = [n.strip() for n in row['nakshatras'].split(',')]
        return jsonify({"status": "success", "data": results})
    except Exception as e:
        print(f"Error in get_all_zodiacs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def zodiac_forecast():
    data = request.json or {}
    sign = (data.get("sign") or "Aries").strip().lower()
    timeframe = (data.get("timeframe") or "today").strip().lower()
    language = data.get("language") or "en"

    # For 'today' daily insights: retrieve directly from the database!
    if timeframe == "today":
        try:
            from services.daily_insights_scheduler import get_sign_daily_insights_from_db, generate_and_save_sign_daily_insights
            db_data = get_sign_daily_insights_from_db(sign)
            if db_data:
                return jsonify({"status": "success", "data": db_data, "source": "database"})

            # If not yet pre-generated in DB for today, generate, save to DB, and return
            saved_data = generate_and_save_sign_daily_insights(sign, language=language)
            if saved_data:
                return jsonify({"status": "success", "data": saved_data, "source": "database_cached"})
        except Exception as e:
            print(f"[Zodiac Forecast DB Retrieval Warning] Error retrieving from DB ({e}), falling back to generator.")

    # For 'week' / 'weekly' insights: retrieve directly from horoscopes database table (pure DB, NO live LLM call)
    if timeframe in ("week", "weekly"):
        try:
            from controllers.horoscope_controller import get_today_ist
            today_ist = get_today_ist()
            from database.db_connection import get_db_connection
            conn = get_db_connection()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute("""
                    SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `period` = 'weekly'
                      AND `period_start` <= %s AND `period_end` >= %s;
                """, (sign, today_ist, today_ist))
                rows = cur.fetchall()
                if not rows:
                    cur.execute("""
                        SELECT `period_start` FROM `horoscopes`
                        WHERE `sign` = %s AND `period` = 'weekly' AND `period_end` < %s
                        ORDER BY `period_start` DESC LIMIT 1;
                    """, (sign, today_ist))
                    earlier = cur.fetchone()
                    if earlier:
                        cur.execute("""
                            SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `period_start`, `period_end`
                            FROM `horoscopes`
                            WHERE `sign` = %s AND `period` = 'weekly' AND `period_start` = %s;
                        """, (sign, earlier["period_start"]))
                        rows = cur.fetchall()
                cur.close()
            finally:
                conn.close()

            if rows:
                cats_map = {r["category"]: r for r in rows}
                cp = cats_map.get("cosmic_pulse", {})
                return jsonify({
                    "status": "success",
                    "data": {
                        "sign": sign,
                        "timeframe": "week",
                        "forecast": cp.get("text", ""),
                        "vitalityToday": cp.get("score", 85),
                        "tip_for_the_day": cp.get("tip_for_the_day"),
                        "periodStart": str(rows[0]["period_start"]),
                        "periodEnd": str(rows[0]["period_end"]),
                        "categoryInsights": cats_map
                    },
                    "source": "database_weekly"
                })
        except Exception as e:
            print(f"[Zodiac Forecast Weekly DB Warning]: {e}")

    # For 'month' / 'monthly' insights: retrieve directly from horoscopes database table (pure DB, NO live LLM call)
    if timeframe in ("month", "monthly"):
        try:
            from controllers.horoscope_controller import get_today_ist
            today_ist = get_today_ist()
            from database.db_connection import get_db_connection
            conn = get_db_connection()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute("""
                    SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `period` = 'monthly'
                      AND `period_start` <= %s AND `period_end` >= %s;
                """, (sign, today_ist, today_ist))
                rows = cur.fetchall()
                if not rows:
                    cur.execute("""
                        SELECT `period_start` FROM `horoscopes`
                        WHERE `sign` = %s AND `period` = 'monthly' AND `period_end` < %s
                        ORDER BY `period_start` DESC LIMIT 1;
                    """, (sign, today_ist))
                    earlier = cur.fetchone()
                    if earlier:
                        cur.execute("""
                            SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `period_start`, `period_end`
                            FROM `horoscopes`
                            WHERE `sign` = %s AND `period` = 'monthly' AND `period_start` = %s;
                        """, (sign, earlier["period_start"]))
                        rows = cur.fetchall()

                ingresses = []
                if rows:
                    p_start = rows[0]["period_start"]
                    cur.execute("""
                        SELECT `planet`, `from_sign`, `to_sign`, `event_date`, `event_time`, `event_type`, `details`
                        FROM `month_ingresses`
                        WHERE `year` = %s AND `month` = %s AND `system` = 'tropical'
                        ORDER BY `event_date` ASC, `event_time` ASC;
                    """, (p_start.year, p_start.month))
                    raw_ing = cur.fetchall()
                    from datetime import date, datetime
                    for ing in raw_ing:
                        ev = dict(ing)
                        if isinstance(ev.get("event_date"), (date, datetime)):
                            ev["event_date"] = str(ev["event_date"])
                        if isinstance(ev.get("details"), str):
                            try:
                                import json
                                ev["details"] = json.loads(ev["details"])
                            except Exception:
                                pass
                        ingresses.append(ev)
                cur.close()
            finally:
                conn.close()

            if rows:
                cats_map = {r["category"]: r for r in rows}
                cp = cats_map.get("cosmic_pulse", {})
                return jsonify({
                    "status": "success",
                    "data": {
                        "sign": sign,
                        "timeframe": "month",
                        "forecast": cp.get("text", ""),
                        "vitalityToday": cp.get("score", 85),
                        "tip_for_the_day": cp.get("tip_for_the_day"),
                        "periodStart": str(rows[0]["period_start"]),
                        "periodEnd": str(rows[0]["period_end"]),
                        "ingresses": ingresses,
                        "categoryInsights": cats_map
                    },
                    "source": "database_monthly"
                })
        except Exception as e:
            print(f"[Zodiac Forecast Monthly DB Warning]: {e}")

    try:
        forecast_json_str = get_zodiac_forecast_response(sign, timeframe, language)
        forecast_data = json.loads(forecast_json_str)
        return jsonify({"status": "success", "data": forecast_data})
    except Exception as e:
        print(f"Error in zodiac_forecast: {e}")
        from services.llm_service import _generate_fallback_zodiac_forecast
        fallback = _generate_fallback_zodiac_forecast(sign, timeframe, language)
        return jsonify({"status": "success", "data": fallback})

def get_daily_category_insight():
    """
    Retrieves the exact daily insight, percentage score, color indicators,
    and transit aspect for a specific zodiac sign and category directly from the database.
    """
    if request.method == "POST":
        data = request.json or {}
        sign = (data.get("sign") or data.get("zodiac_sign") or "Aries").strip().lower()
        category = (data.get("category") or data.get("category_id") or "health").strip().lower()
    else:
        sign = (request.args.get("sign") or "Aries").strip().lower()
        category = (request.args.get("category") or "health").strip().lower()

    try:
        from services.daily_insights_scheduler import get_sign_daily_insights_from_db, generate_and_save_sign_daily_insights
        db_data = get_sign_daily_insights_from_db(sign)
        if not db_data:
            db_data = generate_and_save_sign_daily_insights(sign)

        if not db_data:
            return jsonify({"status": "error", "message": f"Could not retrieve insights for {sign}"}), 404

        categories = db_data.get("categoryInsights") or {}
        cat_details = categories.get(category)
        if not cat_details and category == "all":
            return jsonify({"status": "success", "source": "database", "data": db_data})

        if not cat_details:
            # fallback to first category if requested category key differs
            cat_details = list(categories.values())[0] if categories else {}

        return jsonify({
            "status": "success",
            "source": "database",
            "sign": sign,
            "category": category,
            "data": cat_details,
            "forecast": db_data.get("forecast"),
            "affirmation": db_data.get("affirmation"),
            "resonantChakra": db_data.get("resonantChakra")
        })
    except Exception as e:
        print(f"Error in get_daily_category_insight: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def refresh_daily_insights():
    """
    Triggers the scheduler to fetch/refresh daily insights from LLM
    for all 12 signs and store them in the database.
    """
    force = request.args.get("force", "false").lower() in ("true", "1")
    try:
        from services.daily_insights_scheduler import fetch_and_store_daily_insights_for_all_signs
        results = fetch_and_store_daily_insights_for_all_signs(force=force)
        return jsonify({
            "status": "success",
            "message": "Daily insights scheduler run completed.",
            "results": results
        })
    except Exception as e:
        print(f"Error in refresh_daily_insights: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def zodiac_compatibility():
    data = request.json or {}
    sign_a = data.get("signA", "Aries")
    sign_b = data.get("signB", "Leo")
    system = data.get("system", "tropical")
    language = data.get("language", "en")

    try:
        from services.llm_service import get_zodiac_compatibility_response
        compat_json_str = get_zodiac_compatibility_response(sign_a, sign_b, system, language)
        compat_data = json.loads(compat_json_str)
        return jsonify({"status": "success", "data": compat_data})
    except Exception as e:
        print(f"Error in zodiac_compatibility: {e}")
        return jsonify({"status": "success", "data": {
            "overallScore": 75,
            "elementSynergy": f"Harmonious alignment between {sign_a} and {sign_b}.",
            "romanceAnalysis": "Planetary energies create mutual attraction and shared vision.",
            "intellectualAnalysis": "Dynamic communication fuels positive collaboration.",
            "growthPotential": "Both signs empower each other toward spiritual and personal growth.",
            "remedialAdvice": "Maintain patience and celebrate each other's individuality."
        }})

def subscribe_daily_update():
    """
    Subscribes a user's email to daily cosmic updates for their selected zodiac sign
    and preferred categories into the database table daily_update_subscriptions.
    """
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    zodiac_sign = (data.get("zodiac_sign") or data.get("sign") or "Aries").strip().title()
    preferred_categories = data.get("preferred_categories") or data.get("categories") or []

    # Validate email
    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
    if not email or not re.match(email_regex, email):
        return jsonify({"status": "error", "message": "Please provide a valid email address."}), 400

    if not isinstance(preferred_categories, list):
        preferred_categories = [str(preferred_categories)]

    categories_json = json.dumps(preferred_categories)

    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            insert_query = """
                INSERT INTO daily_update_subscriptions (email, zodiac_sign, preferred_categories, is_active)
                VALUES (%s, %s, %s, 1)
                ON DUPLICATE KEY UPDATE
                  preferred_categories = VALUES(preferred_categories),
                  is_active = 1,
                  updated_at = CURRENT_TIMESTAMP;
            """
            cursor.execute(insert_query, (email, zodiac_sign, categories_json))
            conn.commit()
            cursor.close()
        finally:
            conn.close()

        # Immediately dispatch today's first insight email asynchronously so user receives instant confirmation
        try:
            from services.daily_insights_scheduler import get_sign_daily_insights_from_db, generate_and_save_sign_daily_insights
            from services.email_service import send_daily_zodiac_insight_email
            from datetime import date
            
            sign_key = zodiac_sign.lower().strip()
            today_str = str(date.today())
            daily_data = get_sign_daily_insights_from_db(sign_key, today_str)
            if not daily_data:
                daily_data = generate_and_save_sign_daily_insights(sign_key, today_str)

            if daily_data:
                send_daily_zodiac_insight_email(
                    email=email,
                    zodiac_sign=sign_key,
                    daily_data=daily_data,
                    preferred_categories=preferred_categories
                )
        except Exception as mail_err:
            print(f"[Instant Daily Email Dispatch Warning] {mail_err}")

        return jsonify({
            "status": "success",
            "message": f"Successfully subscribed to daily updates for {zodiac_sign}!",
            "data": {
                "email": email,
                "zodiac_sign": zodiac_sign,
                "preferred_categories": preferred_categories
            }
        })
    except Exception as e:
        print(f"Error in subscribe_daily_update: {e}")
        return jsonify({"status": "error", "message": f"Failed to save subscription: {str(e)}"}), 500

def trigger_daily_email_dispatch():
    """
    Triggers the daily email scheduler to dispatch personalized emails
    with percentage scores and color indicators to all subscribed users.
    """
    force = request.args.get("force", "false").lower() in ("true", "1")
    target_date = request.args.get("date")
    try:
        from services.daily_email_scheduler import send_daily_emails_to_all_subscribers
        results = send_daily_emails_to_all_subscribers(target_date=target_date, force=force)
        return jsonify(results)
    except Exception as e:
        print(f"Error in trigger_daily_email_dispatch: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500



