from flask import request, jsonify, make_response
from datetime import datetime, date, timedelta, timezone
from database.db_connection import get_db_connection

IST = timezone(timedelta(hours=5, minutes=30))

def get_today_ist() -> date:
    """Returns current date in Indian Standard Time (IST, UTC+5:30)."""
    return datetime.now(IST).date()

VALID_SIGNS = [
    "aries", "taurus", "gemini", "cancer",
    "leo", "virgo", "libra", "scorpio",
    "sagittarius", "capricorn", "aquarius", "pisces"
]
VALID_SYSTEMS = ["tropical", "sidereal"]
VALID_PERIODS = ["daily", "weekly", "monthly", "yearly"]
VALID_LANGUAGES = ["en", "hi", "bn", "ta", "fr"]
VALID_CATEGORIES = [
    "all", "cosmic_pulse", "health", "wealth", "relationship",
    "love_line", "education", "professional", "travel",
    "career", "love_life"
]


def get_horoscope():
    """
    GET /api/horoscope?sign=taurus&category=wealth&period=daily&system=tropical
    Returns cached horoscope items for the selected sign, system, period, and category.
    - Queries today's row (period_start = today in IST, not CURDATE() of the DB server timezone).
    - If no row exists for that sign/system/period, falls back to the latest row with
      period_start < today in IST, adding "stale": true and "period_start" to response.
    - If nothing exists at all, returns 404 with a clear message, never an empty 200.
    """
    sign = (request.args.get("sign") or "aries").strip().lower()
    system = (request.args.get("system") or "tropical").strip().lower()
    period = (request.args.get("period") or "daily").strip().lower()
    category = (request.args.get("category") or "all").strip().lower()
    lang = (request.args.get("lang") or "en").strip().lower()

    if category == "career":
        category = "professional"
    elif category == "love_life":
        category = "love_line"

    # Validation
    if lang not in VALID_LANGUAGES:
        return jsonify({
            "status": "error",
            "message": f"Invalid lang '{lang}'. Allowed: {', '.join(VALID_LANGUAGES)}"
        }), 400

    if sign not in VALID_SIGNS:
        return jsonify({
            "status": "error",
            "message": f"Invalid sign '{sign}'. Allowed: {', '.join(VALID_SIGNS)}"
        }), 400

    if system not in VALID_SYSTEMS:
        return jsonify({
            "status": "error",
            "message": f"Invalid system '{system}'. Allowed: {', '.join(VALID_SYSTEMS)}"
        }), 400

    if period not in VALID_PERIODS:
        return jsonify({
            "status": "error",
            "message": f"Invalid period '{period}'. Allowed: {', '.join(VALID_PERIODS)}"
        }), 400

    if category not in VALID_CATEGORIES:
        return jsonify({
            "status": "error",
            "message": f"Invalid category '{category}'. Allowed: {', '.join(VALID_CATEGORIES)}"
        }), 400

    today_ist = get_today_ist()

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            # 1. Query current period row in IST
            if period == "yearly":
                year_arg = request.args.get("year")
                try:
                    req_year = int(year_arg) if year_arg else today_ist.year
                except (ValueError, TypeError):
                    req_year = today_ist.year

                target_jan1 = date(req_year, 1, 1)
                cursor.execute("""
                    SELECT DISTINCT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = 'yearly' AND `period_start` = %s
                    LIMIT 1;
                """, (sign, system, target_jan1))
                date_row = cursor.fetchone()
                is_stale = False

                # Stale fallback: if requested year missing, return latest earlier year
                if not date_row:
                    cursor.execute("""
                        SELECT DISTINCT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = 'yearly' AND `period_start` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (sign, system, target_jan1))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True
                    else:
                        cursor.execute("""
                            SELECT DISTINCT `period_start`, `period_end`
                            FROM `horoscopes`
                            WHERE `sign` = %s AND `system` = %s AND `period` = 'yearly'
                            ORDER BY `period_start` DESC
                            LIMIT 1;
                        """, (sign, system))
                        date_row = cursor.fetchone()
                        if date_row:
                            is_stale = True
            elif period in ("weekly", "monthly"):
                cursor.execute("""
                    SELECT DISTINCT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s
                      AND `period_start` <= %s AND `period_end` >= %s
                    LIMIT 1;
                """, (sign, system, period, today_ist, today_ist))
                date_row = cursor.fetchone()
                is_stale = False

                # If no active window exists, fall back to latest earlier window
                if not date_row:
                    cursor.execute("""
                        SELECT DISTINCT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = %s
                          AND `period_end` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (sign, system, period, today_ist))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True
            else:
                # Daily: period_start = today_ist
                cursor.execute("""
                    SELECT DISTINCT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s
                    LIMIT 1;
                """, (sign, system, period, today_ist))
                date_row = cursor.fetchone()
                is_stale = False

                # Fallback to latest earlier row
                if not date_row:
                    cursor.execute("""
                        SELECT DISTINCT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (sign, system, period, today_ist))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True

            # 3. If nothing exists at all, return 404 with a clear message, never an empty 200
            if not date_row:
                cursor.close()
                return jsonify({
                    "status": "error",
                    "message": f"No horoscope data found for {sign} ({system}, {period}).",
                    "stale": True
                }), 404

            period_start = date_row["period_start"]
            period_end = date_row["period_end"]

            # Double check staleness
            if period == "daily" and period_start != today_ist:
                is_stale = True
            elif period in ("weekly", "monthly") and (period_start > today_ist or period_end < today_ist):
                is_stale = True
            elif period == "yearly":
                year_arg = request.args.get("year")
                try:
                    target_yr = int(year_arg) if year_arg else today_ist.year
                except Exception:
                    target_yr = today_ist.year
                if period_start != date(target_yr, 1, 1):
                    is_stale = True

            # Fetch the category items for this period_start
            if category == "all":
                cursor.execute("""
                    SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `generated_at`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s
                    ORDER BY `id` ASC;
                """, (sign, system, period, period_start))
            else:
                cursor.execute("""
                    SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `generated_at`
                    FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s AND `category` = %s
                    LIMIT 1;
                """, (sign, system, period, period_start, category))

            items = cursor.fetchall()

            ingresses = []
            if period == "monthly":
                cursor.execute("""
                    SELECT `planet`, `from_sign`, `to_sign`, `event_date`, `event_time`, `event_type`, `details`
                    FROM `month_ingresses`
                    WHERE `year` = %s AND `month` = %s AND `system` = %s
                    ORDER BY `event_date` ASC, `event_time` ASC;
                """, (period_start.year, period_start.month, system))
                raw_ingresses = cursor.fetchall()
                for ing in raw_ingresses:
                    ev_item = dict(ing)
                    if isinstance(ev_item.get("event_date"), (date, datetime)):
                        ev_item["event_date"] = str(ev_item["event_date"])
                    if isinstance(ev_item.get("details"), str):
                        try:
                            import json
                            ev_item["details"] = json.loads(ev_item["details"])
                        except Exception:
                            pass
                    ingresses.append(ev_item)

            cursor.close()

            # If no items found for this record, return 404
            if not items:
                return jsonify({
                    "status": "error",
                    "message": f"No category items found for {sign} ({system}, {period}) on {period_start}.",
                    "stale": is_stale
                }), 404

            # Dynamic translation for non-English languages
            all_translated = True
            if lang != "en":
                from services.landing_translation import translate_items
                items = translate_items(
                    items,
                    lang,
                    {
                        "sign": sign,
                        "system": system,
                        "period": period,
                        "period_start": str(period_start),
                        "period_end": str(period_end),
                    }
                )
                all_translated = all(it.get("translated", True) for it in items)

            # Format response
            response_data = {
                "status": "success",
                "sign": sign,
                "system": system,
                "period": period,
                "period_start": str(period_start),
                "period_end": str(period_end),
                "lang": lang,
                "translated": all_translated,
                "items": items,
                "stale": is_stale
            }
            if period == "monthly":
                response_data["ingresses"] = ingresses

            resp = make_response(jsonify(response_data))
            resp.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
            resp.headers["Vary"] = "Accept-Encoding, lang"
            return resp

        finally:
            conn.close()

    except Exception as e:
        print(f"[Horoscope API Error]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def horoscope_health():
    """Health check endpoint: returns the latest generated_at timestamp."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT MAX(`generated_at`) as latest_generated_at, COUNT(*) as total_records FROM `horoscopes`;")
            row = cursor.fetchone()
            cursor.close()
            return jsonify({
                "status": "healthy",
                "latest_generated_at": str(row["latest_generated_at"]) if row else None,
                "total_records": row["total_records"] if row else 0,
                "server_time_utc": str(datetime.utcnow()),
                "timezone": "Asia/Kolkata"
            })
        finally:
            conn.close()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def get_horoscope_vitality():
    """
    GET /api/horoscope/vitality?system=tropical&period=daily
    Returns vitality scores (score from category='cosmic_pulse') for all 12 signs in ONE lightweight call.
    Pure database SELECT, no LLM calls.
    """
    system = (request.args.get("system") or "tropical").strip().lower()
    period = (request.args.get("period") or "daily").strip().lower()

    if system not in VALID_SYSTEMS:
        return jsonify({"status": "error", "message": f"Invalid system '{system}'"}), 400
    if period not in VALID_PERIODS:
        return jsonify({"status": "error", "message": f"Invalid period '{period}'"}), 400

    today_ist = get_today_ist()

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            # Check if active period rows exist for cosmic_pulse in IST
            if period == "yearly":
                year_arg = request.args.get("year")
                try:
                    req_year = int(year_arg) if year_arg else today_ist.year
                except (ValueError, TypeError):
                    req_year = today_ist.year
                target_jan1 = date(req_year, 1, 1)

                cursor.execute("""
                    SELECT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `system` = %s AND `period` = 'yearly' AND `category` = 'cosmic_pulse' AND `period_start` = %s
                    LIMIT 1;
                """, (system, target_jan1))
                date_row = cursor.fetchone()
                is_stale = False

                if not date_row:
                    cursor.execute("""
                        SELECT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `system` = %s AND `period` = 'yearly' AND `category` = 'cosmic_pulse' AND `period_start` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (system, target_jan1))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True
                    else:
                        cursor.execute("""
                            SELECT `period_start`, `period_end`
                            FROM `horoscopes`
                            WHERE `system` = %s AND `period` = 'yearly' AND `category` = 'cosmic_pulse'
                            ORDER BY `period_start` DESC
                            LIMIT 1;
                        """, (system,))
                        date_row = cursor.fetchone()
                        if date_row:
                            is_stale = True
            elif period in ("weekly", "monthly"):
                cursor.execute("""
                    SELECT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `system` = %s AND `period` = %s AND `category` = 'cosmic_pulse'
                      AND `period_start` <= %s AND `period_end` >= %s
                    LIMIT 1;
                """, (system, period, today_ist, today_ist))
                date_row = cursor.fetchone()
                is_stale = False

                if not date_row:
                    cursor.execute("""
                        SELECT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `system` = %s AND `period` = %s AND `category` = 'cosmic_pulse'
                          AND `period_end` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (system, period, today_ist))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True
            else:
                cursor.execute("""
                    SELECT `period_start`, `period_end`
                    FROM `horoscopes`
                    WHERE `system` = %s AND `period` = %s AND `category` = 'cosmic_pulse' AND `period_start` = %s
                    LIMIT 1;
                """, (system, period, today_ist))
                date_row = cursor.fetchone()
                is_stale = False

                if not date_row:
                    # Fall back to latest available period_start < today
                    cursor.execute("""
                        SELECT `period_start`, `period_end`
                        FROM `horoscopes`
                        WHERE `system` = %s AND `period` = %s AND `category` = 'cosmic_pulse' AND `period_start` < %s
                        ORDER BY `period_start` DESC
                        LIMIT 1;
                    """, (system, period, today_ist))
                    date_row = cursor.fetchone()
                    if date_row:
                        is_stale = True

            target_date = date_row["period_start"] if date_row else today_ist

            cursor.execute("""
                SELECT `sign`, `score`
                FROM `horoscopes`
                WHERE `system` = %s AND `period` = %s AND `category` = 'cosmic_pulse' AND `period_start` = %s;
            """, (system, period, target_date))
            rows = cursor.fetchall()
            cursor.close()

            vitality_map = {r["sign"]: r["score"] for r in rows}

            resp = make_response(jsonify({
                "status": "success",
                "system": system,
                "period": period,
                "period_start": str(target_date),
                "stale": is_stale,
                "vitality": vitality_map
            }))
            resp.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
            return resp

        finally:
            conn.close()
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def get_horoscope_years():
    """
    GET /api/horoscope/years?period=yearly
    Returns list of calendar years present in the database (e.g. [2026, 2027]).
    Fast MySQL SELECT only, zero LLM calls.
    """
    period = (request.args.get("period") or "yearly").strip().lower()
    if period not in VALID_PERIODS:
        return jsonify({"status": "error", "message": f"Invalid period '{period}'"}), 400

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT YEAR(`period_start`) as yr, COUNT(*) as cnt
                FROM `horoscopes`
                WHERE `period` = %s
                GROUP BY YEAR(`period_start`)
                HAVING cnt >= 192
                ORDER BY yr ASC;
            """, (period,))
            rows = cursor.fetchall()
            years = [int(r[0]) for r in rows if r[0]]

            if not years:
                cursor.execute("""
                    SELECT DISTINCT YEAR(`period_start`) as yr
                    FROM `horoscopes`
                    WHERE `period` = %s
                    ORDER BY yr ASC;
                """, (period,))
                years = [int(r[0]) for r in cursor.fetchall() if r[0]]

            if not years:
                years = [2026, 2027]

            cursor.close()

            resp = make_response(jsonify({
                "status": "success",
                "period": period,
                "years": years
            }))
            resp.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=86400"
            return resp
        finally:
            conn.close()
    except Exception as e:
        print(f"[Horoscope Years Error]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

