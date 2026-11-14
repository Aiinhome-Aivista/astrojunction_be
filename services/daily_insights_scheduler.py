import os
import json
import threading
import time
from datetime import datetime, date, timedelta
import calendar
from database.db_connection import get_db_connection

ALL_ZODIAC_SIGNS = [
    "aries", "taurus", "gemini", "cancer",
    "leo", "virgo", "libra", "scorpio",
    "sagittarius", "capricorn", "aquarius", "pisces"
]

ALL_CATEGORIES = [
    "health", "wealth", "relationship", "love_line",
    "education", "professional", "travel"
]

CATEGORY_TRANSIT_ASPECTS = {
    "aries": {
        "health": "Mars Ascendant Ingress • High Vitality Flow",
        "wealth": "Venus 2nd House Trine • Asset Consolidation",
        "relationship": "Jupiterian Harmonious Aspect • Warm Understanding",
        "love_line": "Venus-Mars Trine • Passionate Chemistry",
        "education": "Mercury Dexterity Alignment • Academic Tenacity",
        "professional": "Sun 10th House Transit • Dynamic Leadership",
        "travel": "Moon-Jupiter Conjunction • Favorable Excursion"
    },
    "taurus": {
        "health": "Venus Sensory Equilibrium • Gentle Restoration",
        "wealth": "Taurus Midheaven Ingress • Tangible Asset Growth",
        "relationship": "Moon Exaltation Harmony • Deep Domestic Peace",
        "love_line": "Venusian Romance Flux • Heartfelt Affection",
        "education": "Mercury-Saturn Sextile • Methodical Focus",
        "professional": "Saturnian Steadfast Aspect • Executive Reliability",
        "travel": "Jupiter Transit • Relaxed Retreat Flow"
    },
    "gemini": {
        "health": "Mercurial Nervous System Balance • Breath Flow",
        "wealth": "Commerce Transit Alignment • Liquid Capital Gains",
        "relationship": "Air Trine Synthesis • Engaging Conversations",
        "love_line": "Venus Air Conjunction • Sparkling Chemistry",
        "education": "Mercury-Uranus Sextile • Intellectual Synthesis",
        "professional": "Solar 10th House Transit • Multitasking Prowess",
        "travel": "Fast Messenger Aspect • Dynamic Commutes"
    },
    "cancer": {
        "health": "Lunar Hydration Equilibrium • Emotional Calming",
        "wealth": "2nd House Solar Ingress • Family Prosperity",
        "relationship": "Moon-Venus Sextile • Compassionate Bonding",
        "love_line": "Jupiter Trine Neptune • Soulmate Resonance",
        "education": "Memory Retention Flux • Intuitive Learning",
        "professional": "Mars Ingress • Tenacious Initiative",
        "travel": "Moon Water Aspect • Calming Coastal Journey"
    },
    "leo": {
        "health": "Solar Prana Radiation • Vibrant Stamina",
        "wealth": "Mercury 2nd House Aspect • Lucrative Investments",
        "relationship": "Sun-Jupiter Trine • Generous Heart Connections",
        "love_line": "Venus Radiance Ingress • Golden Romance",
        "education": "Solar Clarity Alignment • Conceptual Mastery",
        "professional": "10th House Zenith Spark • Executive Authority",
        "travel": "Sun-Mars Trine • Bold Adventures"
    },
    "virgo": {
        "health": "Digestive Equilibrium • Mind-Body Rejuvenation",
        "wealth": "Venus-Mercury Sextile • Pragmatic Wealth Growth",
        "relationship": "Moon Earth Aspect • Reliable Compassion",
        "love_line": "Venusian Grounding • Devoted Affection",
        "education": "Mercury Exaltation Flow • Analytic Precision",
        "professional": "Saturnian Precision Trine • Flawless Execution",
        "travel": "Logistical Alignment • Seamless Organization"
    },
    "libra": {
        "health": "Venus Equilibrium • Artistic Rest & Renewal",
        "wealth": "Jupiter 2nd House Aspect • Fair Financial Returns",
        "relationship": "Venusian Diplomacy Ingress • Social Grace",
        "love_line": "Venus Harmony Resonance • Poetic Intimacy",
        "education": "Air Element Synthesis • Balanced Intellect",
        "professional": "Sun-Venus Midheaven Transit • Collaborative Wins",
        "travel": "Pleasure Travel Ingress • Cultural Explorations"
    },
    "scorpio": {
        "health": "Mars-Ketu Regeneration • Pranic Rebirth",
        "wealth": "Plutonic Depth Aspect • Hidden Value Discovery",
        "relationship": "Water Trine Alignment • Unbreakable Loyalty",
        "love_line": "Mars-Venus Magnetic Trine • Transformative Passion",
        "education": "Deep Investigation Aspect • Research Breakthrough",
        "professional": "Solar 10th House Focus • Strategic Influence",
        "travel": "Transformational Transit • Spiritual Pilgrimage"
    },
    "sagittarius": {
        "health": "Jupiterian Vital Energy • Outdoor Vitality",
        "wealth": "Jupiter Wealth Trine • Expansive Dividends",
        "relationship": "Fire Trine Synthesis • Uplifting Fellowship",
        "love_line": "Sun-Jupiter Conjunction • Spirited Romance",
        "education": "9th House Wisdom Ingress • Philosophical Insight",
        "professional": "Midheaven Fire Alignment • Visionary Ventures",
        "travel": "Jupiter 9th Lord Transit • Long-Distance Voyage"
    },
    "capricorn": {
        "health": "Saturnian Musculoskeletal Strength • Steady Vitality",
        "wealth": "Saturn 2nd Lord Aspect • Enduring Capital Growth",
        "relationship": "Earth Element Grounding • Dutiful Devotion",
        "love_line": "Venus-Saturn Trine • Timeless Commitment",
        "education": "Disciplined Study Alignment • Rigorous Mastery",
        "professional": "Saturnian Zenith Trine • Career Milestone",
        "travel": "Purpose-Driven Commute • Productive Transit"
    },
    "aquarius": {
        "health": "Circulatory Equilibrium • Light Aerobic Fitness",
        "wealth": "Jupiterian Innovation Trine • Tech Gains",
        "relationship": "Air Collective Flow • Meaningful Fellowship",
        "love_line": "Venus Electrifying Sextile • Intellectual Sparks",
        "education": "Rahu-Saturn Genius • Scientific Epiphany",
        "professional": "Disruptive Ideation • Technical Leadership",
        "travel": "Group Transit Ingress • Innovative Exploration"
    },
    "pisces": {
        "health": "Lymphatic Equilibrium • Sound Therapy Rest",
        "wealth": "Creative Royalty Flow • Overseas Fortune",
        "relationship": "Jupiterian Compassion • Loving Harmony",
        "love_line": "Venus Exaltation Resonance • Pure Soulmate Love",
        "education": "Intuitive Creative Absorption • Arts & Psyche",
        "professional": "Empathetic Facilitation • Creative Solutions",
        "travel": "Water Pilgrimage Aspect • Soulful Restoration"
    }
}


def compute_color_tier(score: int) -> dict:
    """
    Computes the standard 5-tier color indicators based on percentage score:
    - Green (80–100%): Excellent / Highly Favourable
    - Light Green (60–79%): Good / Favourable
    - Yellow (40–59%): Average / Moderate
    - Orange (20–39%): Challenging
    - Red (0–19%): Unfavourable
    """
    s = max(0, min(100, int(score)))
    if s >= 80:
        return {
            "colorName": "green",
            "colorLabel": "Excellent / Highly Favourable",
            "barColor": "#22c55e",
            "badgeClass": "bg-green-500/10 dark:bg-green-500/15 text-green-700 dark:text-green-400 border border-green-600/25 dark:border-green-500/30",
            "dotClass": "bg-green-500",
            "textClass": "text-green-700 dark:text-green-400"
        }
    elif s >= 60:
        return {
            "colorName": "emerald",
            "colorLabel": "Good / Favourable",
            "barColor": "#10b981",
            "badgeClass": "bg-emerald-500/10 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-600/25 dark:border-emerald-500/30",
            "dotClass": "bg-emerald-500",
            "textClass": "text-emerald-700 dark:text-emerald-400"
        }
    elif s >= 40:
        return {
            "colorName": "yellow",
            "colorLabel": "Average / Moderate",
            "barColor": "#eab308",
            "badgeClass": "bg-amber-500/10 dark:bg-yellow-500/15 text-amber-700 dark:text-yellow-400 border border-amber-600/25 dark:border-yellow-500/30",
            "dotClass": "bg-yellow-500",
            "textClass": "text-amber-700 dark:text-yellow-400"
        }
    elif s >= 20:
        return {
            "colorName": "orange",
            "colorLabel": "Challenging",
            "barColor": "#f97316",
            "badgeClass": "bg-orange-500/10 dark:bg-orange-500/15 text-orange-700 dark:text-orange-400 border border-orange-600/25 dark:border-orange-500/30",
            "dotClass": "bg-orange-500",
            "textClass": "text-orange-700 dark:text-orange-400"
        }
    else:
        return {
            "colorName": "red",
            "colorLabel": "Unfavourable",
            "barColor": "#ef4444",
            "badgeClass": "bg-rose-500/10 dark:bg-rose-500/15 text-rose-700 dark:text-rose-400 border border-rose-600/25 dark:border-rose-500/30",
            "dotClass": "bg-rose-500",
            "textClass": "text-rose-700 dark:text-rose-400"
        }


def get_sign_daily_insights_from_db(sign: str, target_date: str = None) -> dict:
    """
    Retrieves the daily insights for a given zodiac sign directly from the horoscopes table.
    """
    if not target_date:
        target_date = str(date.today())

    norm_sign = (sign or "aries").strip().lower()

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`
                FROM `horoscopes`
                WHERE LOWER(`sign`) = %s AND `period` = 'daily' AND `period_start` = %s AND `system` = 'tropical';
            """
            cursor.execute(query, (norm_sign, target_date))
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return None

            cats = {}
            forecast_text = ""
            vitality_score = 85
            affirmation_text = ""

            for r in rows:
                c_name = r["category"]
                cats[c_name] = {
                    "score": r["score"],
                    "description": r["text"],
                    "text": r["text"],
                    "insight": r["text"],
                    "lucky_time": r["lucky_time"],
                    "remedy": r["remedy"],
                    "affirmation": r["affirmation"],
                    "tip_for_the_day": r["tip_for_the_day"]
                }
                if c_name == "cosmic_pulse":
                    forecast_text = r["text"]
                    vitality_score = r["score"]
                    affirmation_text = r["affirmation"]

            return {
                "sign": norm_sign,
                "forecastDate": target_date,
                "forecast": forecast_text,
                "categoryInsights": cats,
                "vitalityToday": vitality_score,
                "loveRating": cats.get("love_line", {}).get("score", 80),
                "careerRating": cats.get("professional", {}).get("score", 85),
                "wealthRating": cats.get("wealth", {}).get("score", 80),
                "affirmation": affirmation_text or "I flow with cosmic currents and welcome blessings.",
                "resonantChakra": "Solar Plexus (Manipura)",
                "luckyGemstone": "Ruby",
                "luckyColor": "Gold",
                "luckyDay": "Sunday",
                "powerNumbers": [3, 7, 9],
                "bestRomanceMatches": ["Leo", "Sagittarius"],
                "bestCareerMatches": ["Capricorn", "Taurus"],
                "growthMatches": ["Aquarius"]
            }
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Insights DB Error] Failed to fetch for {norm_sign}: {e}")
        return None


def generate_and_save_sign_daily_insights(sign: str, target_date: str = None, language: str = "en") -> dict:
    """
    Generates dynamic daily insights for a sign (using LLM or fallback), computes the percentage scores,
    colour indicators, and saves them into the database table daily_zodiac_insights.
    """
    if not target_date:
        target_date = str(date.today())

    norm_sign = (sign or "aries").strip().lower()

    # 1. First check if horoscopes table has clean generated items for this sign and date
    raw_data = None
    try:
        conn_check = get_db_connection()
        cursor_check = conn_check.cursor(dictionary=True)
        cursor_check.execute("""
            SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`
            FROM `horoscopes`
            WHERE `sign` = %s AND `period_start` = %s AND `period` = 'daily'
            ORDER BY `id` ASC;
        """, (norm_sign, target_date))
        h_rows = cursor_check.fetchall()
        cursor_check.close()
        conn_check.close()

        if h_rows and len(h_rows) >= 7:
            cat_map = {}
            pulse_text = ""
            pulse_score = 85
            aff = ""
            for r in h_rows:
                c = r["category"]
                if c == "cosmic_pulse":
                    pulse_text = r["text"]
                    pulse_score = r["score"]
                    aff = r["affirmation"]
                else:
                    cat_map[c] = {
                        "score": r["score"],
                        "insight": r["text"],
                        "lucky_time": r["lucky_time"],
                        "remedy": r["remedy"],
                        "affirmation": r["affirmation"]
                    }
            
            raw_data = {
                "forecast": pulse_text or f"Auspicious celestial alignments bring positive growth for {norm_sign.capitalize()} today.",
                "vitalityToday": pulse_score,
                "wealthRating": cat_map.get("wealth", {}).get("score", 85),
                "careerRating": cat_map.get("professional", {}).get("score", 85),
                "loveRating": cat_map.get("love_line", {}).get("score", 85),
                "affirmation": aff or f"I embrace today with calm confidence and inner harmony.",
                "categoryInsights": cat_map
            }
    except Exception as ex:
        print(f"[Daily Insights Sync Notice] Could not read from horoscopes ({ex})")

    if not raw_data:
        # Import LLM generator
        from services.llm_service import get_zodiac_forecast_response, _generate_fallback_zodiac_forecast

        try:
            forecast_json_str = get_zodiac_forecast_response(norm_sign, "today", language)
            raw_data = json.loads(forecast_json_str)
        except Exception as e:
            print(f"[Daily Insights Gen Warning] LLM generation failed for {norm_sign} ({e}), using fallback.")
            raw_data = _generate_fallback_zodiac_forecast(norm_sign, "today", language)

    if not raw_data:
        from services.llm_service import _generate_fallback_zodiac_forecast
        raw_data = _generate_fallback_zodiac_forecast(norm_sign, "today", language)

    # Process and enrich each category with color indicators & transit aspects
    category_insights = raw_data.get("categoryInsights") or {}
    enriched_categories = {}

    sign_aspects = CATEGORY_TRANSIT_ASPECTS.get(norm_sign, {})

    for cat_id in ALL_CATEGORIES:
        cat_data = category_insights.get(cat_id) or {}
        score = cat_data.get("score") if isinstance(cat_data, dict) else 75
        insight = cat_data.get("insight") if isinstance(cat_data, dict) else (str(cat_data) if cat_data else "")
        transit_aspect = cat_data.get("transitAspect") if isinstance(cat_data, dict) else None

        if not transit_aspect:
            transit_aspect = sign_aspects.get(cat_id, "Harmonious Planetary Transit")

        # Color indicator tier computation
        tier = compute_color_tier(score)

        enriched_categories[cat_id] = {
            "score": score,
            "insight": insight,
            "transitAspect": transit_aspect,
            "colorName": tier["colorName"],
            "colorLabel": tier["colorLabel"],
            "barColor": tier["barColor"],
            "badgeClass": tier["badgeClass"],
            "dotClass": tier["dotClass"],
            "textClass": tier["textClass"]
        }

    raw_data["categoryInsights"] = enriched_categories

    # Extract fields for database
    forecast_text = raw_data.get("forecast") or f"Auspicious celestial alignments bring positive growth for {norm_sign.capitalize()} today."
    vitality_today = int(raw_data.get("vitalityToday") or 85)
    love_rating = int(raw_data.get("loveRating") or 80)
    career_rating = int(raw_data.get("careerRating") or 85)
    wealth_rating = int(raw_data.get("wealthRating") or 80)
    affirmation = raw_data.get("affirmation")
    resonant_chakra = str(raw_data.get("resonantChakra") or "")[:250] if raw_data.get("resonantChakra") else None
    lucky_gemstone = str(raw_data.get("luckyGemstone") or "")[:250] if raw_data.get("luckyGemstone") else None
    lucky_color = str(raw_data.get("luckyColor") or "")[:250] if raw_data.get("luckyColor") else None
    lucky_day = str(raw_data.get("luckyDay") or "")[:250] if raw_data.get("luckyDay") else None
    power_numbers_raw = raw_data.get("powerNumbers")
    power_numbers_str = ",".join(str(n) for n in power_numbers_raw) if isinstance(power_numbers_raw, list) else str(power_numbers_raw or "3,7,9")
    power_numbers_str = power_numbers_str[:250]

    best_romance_json = json.dumps(raw_data.get("bestRomanceMatches") or [])
    best_career_json = json.dumps(raw_data.get("bestCareerMatches") or [])
    growth_json = json.dumps(raw_data.get("growthMatches") or [])
    category_insights_json = json.dumps(enriched_categories)

    return {
        "sign": norm_sign,
        "forecastDate": target_date,
        "forecast": forecast_text,
        "categoryInsights": enriched_categories,
        "vitalityToday": vitality_today,
        "loveRating": love_rating,
        "careerRating": career_rating,
        "wealthRating": wealth_rating,
        "affirmation": affirmation,
        "resonantChakra": resonant_chakra,
        "luckyGemstone": lucky_gemstone,
        "luckyColor": lucky_color,
        "luckyDay": lucky_day,
        "powerNumbers": power_numbers_raw or [3, 7, 9],
        "bestRomanceMatches": raw_data.get("bestRomanceMatches") or [],
        "bestCareerMatches": raw_data.get("bestCareerMatches") or [],
        "growthMatches": raw_data.get("growthMatches") or []
    }


def fetch_and_store_daily_insights_for_all_signs(target_date: str = None, force: bool = False) -> dict:
    """
    Scheduler job:
    1. Triggers Swiss Ephemeris (pyswisseph) + Mistral batch generation for all 12 signs x 2 systems x 8 categories
       into the `horoscopes` table.
    2. Syncs the category percentage scores and color indicators into `daily_zodiac_insights`.
    """
    if not target_date:
        target_date = str(date.today())

    print(f"[Daily Insights Scheduler] Starting daily insights job for all 12 signs on {target_date} (force={force})...")
    
    # Step 1: Run Swiss Ephemeris + Mistral batch generation for horoscopes table
    try:
        from scripts.run_generation import run_batch_generation
        target_dt = datetime.strptime(target_date, "%Y-%m-%d").date() if isinstance(target_date, str) else target_date
        print(f"[Daily Insights Scheduler] Running batch horoscope generation (pyswisseph + Mistral) for {target_dt}...")
        run_batch_generation(period_mode="daily", target_date=target_dt, force=force)
    except Exception as b_err:
        print(f"[Daily Insights Scheduler Warning] Batch generation encountered error: {b_err}")

    results = {}

    for sign in ALL_ZODIAC_SIGNS:
        try:
            if not force:
                existing = get_sign_daily_insights_from_db(sign, target_date)
                if existing:
                    results[sign] = "existing"
                    continue

            generate_and_save_sign_daily_insights(sign, target_date)
            results[sign] = "generated"
        except Exception as e:
            print(f"[Daily Insights Scheduler] Error for {sign}: {e}")
            results[sign] = f"error: {str(e)}"

    print(f"[Daily Insights Scheduler] Job finished for all 12 signs: {results}")
    return results


def acquire_weekly_job_lock(monday: date, force: bool = False) -> bool:
    """
    Tries to acquire a lock for the weekly generation job in scheduler_runs table.
    Returns True if the lock was acquired, False if already running or completed.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT `status`, `started_at` FROM `scheduler_runs` WHERE `job_name` = 'weekly' AND `run_date` = %s;", (monday,))
            row = cursor.fetchone()
            if row:
                status, started_at = row[0], row[1]
                if status == "completed" and not force:
                    cursor.close()
                    return False
                if status == "running" and not force:
                    # If started within the last 30 minutes, assume another worker is actively generating
                    if started_at and (datetime.now() - started_at).total_seconds() < 1800:
                        cursor.close()
                        return False
                # Update to running
                cursor.execute("""
                    UPDATE `scheduler_runs` 
                    SET `status` = 'running', `started_at` = CURRENT_TIMESTAMP, `details` = 'Weekly batch in progress'
                    WHERE `job_name` = 'weekly' AND `run_date` = %s;
                """, (monday,))
            else:
                cursor.execute("""
                    INSERT INTO `scheduler_runs` (`job_name`, `run_date`, `status`, `started_at`, `details`)
                    VALUES ('weekly', %s, 'running', CURRENT_TIMESTAMP, 'Weekly batch started');
                """, (monday,))
            conn.commit()
            cursor.close()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[Scheduler Lock Error]: {e}")
        return True  # Fallback to allow generation if lock table has an issue


def release_weekly_job_lock(monday: date, status: str = "completed", details: str = ""):
    """Updates job status and details in scheduler_runs upon completion or failure."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE `scheduler_runs`
                SET `status` = %s, `completed_at` = CURRENT_TIMESTAMP, `details` = %s
                WHERE `job_name` = 'weekly' AND `run_date` = %s;
            """, (status, details, monday))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[Scheduler Release Lock Error]: {e}")


def ensure_weekly_insights_ready(target_date: date = None, force: bool = False):
    """
    Checks if current week's rows exist in horoscopes table (12 signs x 2 systems x 8 categories = 192 rows).
    If missing (< 192 rows) or force=True, acquires DB lock and generates missing weekly horoscopes
    with period_start = Monday and period_end = Sunday.
    """
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    # Monday start in IST
    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM `horoscopes`
                WHERE `period` = 'weekly' AND `period_start` = %s;
            """, (monday,))
            row = cursor.fetchone()
            count = row[0] if row else 0
            cursor.close()
        finally:
            conn.close()

        if count < 192 or force:
            print(f"[Daily Insights Scheduler] Weekly horoscopes for week {monday} to {sunday} (Found: {count}/192 rows). Attempting lock...")
            if acquire_weekly_job_lock(monday, force=force):
                print(f"[Daily Insights Scheduler] Lock acquired. Triggering weekly generation (force={force})...")
                try:
                    from scripts.run_generation import run_batch_generation
                    summary = run_batch_generation(period_mode="weekly", target_date=monday, force=force)
                    release_weekly_job_lock(
                        monday,
                        status="completed",
                        details=f"Generated: {summary.get('generated', 0)}, Skipped: {summary.get('skipped', 0)}, Failed: {summary.get('failed', 0)}"
                    )
                except Exception as gen_err:
                    release_weekly_job_lock(monday, status="failed", details=str(gen_err)[:250])
                    raise gen_err
            else:
                print(f"[Daily Insights Scheduler] Weekly generation for week {monday} is already completed or locked by another worker.")
        else:
            print(f"[Daily Insights Scheduler] Weekly horoscopes for week {monday} to {sunday} are complete ({count}/192 rows).")
    except Exception as e:
        print(f"[Daily Insights Scheduler] Error checking/generating weekly insights: {e}")


def acquire_monthly_job_lock(first_day: date, force: bool = False) -> bool:
    """
    Tries to acquire a lock for the monthly generation job in scheduler_runs table.
    Returns True if the lock was acquired, False if already running or completed.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT `status`, `started_at` FROM `scheduler_runs` WHERE `job_name` = 'monthly' AND `run_date` = %s;", (first_day,))
            row = cursor.fetchone()
            if row:
                status, started_at = row[0], row[1]
                if status == "completed" and not force:
                    cursor.close()
                    return False
                if status == "running" and not force:
                    # If started within the last 45 minutes, assume another worker is actively generating
                    if started_at and (datetime.now() - started_at).total_seconds() < 2700:
                        cursor.close()
                        return False
                cursor.execute("""
                    UPDATE `scheduler_runs` 
                    SET `status` = 'running', `started_at` = CURRENT_TIMESTAMP, `details` = 'Monthly batch in progress'
                    WHERE `job_name` = 'monthly' AND `run_date` = %s;
                """, (first_day,))
            else:
                cursor.execute("""
                    INSERT INTO `scheduler_runs` (`job_name`, `run_date`, `status`, `started_at`, `details`)
                    VALUES ('monthly', %s, 'running', CURRENT_TIMESTAMP, 'Monthly batch started');
                """, (first_day,))
            conn.commit()
            cursor.close()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[Monthly Scheduler Lock Error]: {e}")
        return True


def release_monthly_job_lock(first_day: date, status: str = "completed", details: str = ""):
    """Updates job status and details in scheduler_runs upon completion or failure."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE `scheduler_runs`
                SET `status` = %s, `completed_at` = CURRENT_TIMESTAMP, `details` = %s
                WHERE `job_name` = 'monthly' AND `run_date` = %s;
            """, (status, details, first_day))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[Monthly Scheduler Release Lock Error]: {e}")


def ensure_monthly_insights_ready(target_date: date = None, force: bool = False):
    """
    Checks if current month's rows exist in horoscopes table (12 signs x 2 systems x 8 categories = 192 rows)
    AND month_ingresses table has entries.
    If missing (< 192 rows or ingresses empty) or force=True, acquires DB lock and generates missing monthly horoscopes.
    """
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    first_day = target_date.replace(day=1)

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM `horoscopes`
                WHERE `period` = 'monthly' AND `period_start` = %s;
            """, (first_day,))
            row = cursor.fetchone()
            horo_count = row[0] if row else 0

            cursor.execute("""
                SELECT COUNT(*) FROM `month_ingresses`
                WHERE `year` = %s AND `month` = %s;
            """, (first_day.year, first_day.month))
            ing_row = cursor.fetchone()
            ing_count = ing_row[0] if ing_row else 0
            cursor.close()
        finally:
            conn.close()

        if horo_count < 192 or ing_count == 0 or force:
            print(f"[Daily Insights Scheduler] Monthly horoscopes for {first_day.strftime('%B %Y')} (Found: {horo_count}/192 rows, {ing_count} ingresses). Attempting lock...")
            if acquire_monthly_job_lock(first_day, force=force):
                print(f"[Daily Insights Scheduler] Lock acquired. Triggering monthly generation (force={force})...")
                try:
                    from scripts.run_generation import run_batch_generation
                    summary = run_batch_generation(period_mode="monthly", target_date=first_day, force=force)
                    release_monthly_job_lock(
                        first_day,
                        status="completed",
                        details=f"Generated: {summary.get('generated', 0)}, Skipped: {summary.get('skipped', 0)}, Failed: {summary.get('failed', 0)}"
                    )
                except Exception as gen_err:
                    release_monthly_job_lock(first_day, status="failed", details=str(gen_err)[:250])
                    raise gen_err
            else:
                print(f"[Daily Insights Scheduler] Monthly generation for {first_day} is already completed or locked by another worker.")
        else:
            print(f"[Daily Insights Scheduler] Monthly horoscopes for {first_day.strftime('%B %Y')} are complete ({horo_count}/192 rows, {ing_count} ingresses).")
    except Exception as e:
        print(f"[Daily Insights Scheduler] Error checking/generating monthly insights: {e}")


def acquire_yearly_job_lock(jan1: date, force: bool = False) -> bool:
    """
    Attempts to acquire an execution lock in `scheduler_runs` table for the yearly job.
    Uses unique constraint on (job_name, run_date).
    Returns True if lock acquired and job should execute; False if already completed or active.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT `status`, `started_at` FROM `scheduler_runs`
                WHERE `job_name` = 'yearly' AND `run_date` = %s;
            """, (jan1,))
            row = cursor.fetchone()
            if row:
                status, started_at = row[0], row[1]
                if status == "completed" and not force:
                    cursor.close()
                    return False
                if status == "running" and not force:
                    # If started within the last 60 minutes, assume another worker is actively generating
                    if started_at and (datetime.now() - started_at).total_seconds() < 3600:
                        cursor.close()
                        return False
                cursor.execute("""
                    UPDATE `scheduler_runs` 
                    SET `status` = 'running', `started_at` = CURRENT_TIMESTAMP, `details` = 'Yearly batch in progress'
                    WHERE `job_name` = 'yearly' AND `run_date` = %s;
                """, (jan1,))
            else:
                cursor.execute("""
                    INSERT INTO `scheduler_runs` (`job_name`, `run_date`, `status`, `started_at`, `details`)
                    VALUES ('yearly', %s, 'running', CURRENT_TIMESTAMP, 'Yearly batch started');
                """, (jan1,))
            conn.commit()
            cursor.close()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"[Yearly Scheduler Lock Error]: {e}")
        return True


def release_yearly_job_lock(jan1: date, status: str = "completed", details: str = ""):
    """Updates job status and details in scheduler_runs upon completion or failure."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE `scheduler_runs`
                SET `status` = %s, `completed_at` = CURRENT_TIMESTAMP, `details` = %s
                WHERE `job_name` = 'yearly' AND `run_date` = %s;
            """, (status, details, jan1))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[Yearly Scheduler Release Lock Error]: {e}")


def ensure_yearly_insights_ready(target_year: int = None, force: bool = False):
    """
    Checks if yearly rows exist in horoscopes table (12 signs x 2 systems x 8 categories = 192 rows)
    for the specified year (defaults to current year in IST).
    If missing (< 192 rows) or force=True, acquires DB lock and generates missing yearly horoscopes.
    """
    current_year = target_year if target_year else date.today().year
    jan1 = date(current_year, 1, 1)

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM `horoscopes`
                WHERE `period` = 'yearly' AND `period_start` = %s;
            """, (jan1,))
            row = cursor.fetchone()
            horo_count = row[0] if row else 0
            cursor.close()
        finally:
            conn.close()

        if horo_count < 192 or force:
            print(f"[Daily Insights Scheduler] Yearly horoscopes for {current_year} (Found: {horo_count}/192 rows). Attempting lock...")
            if acquire_yearly_job_lock(jan1, force=force):
                print(f"[Daily Insights Scheduler] Lock acquired. Triggering yearly generation for {current_year} (force={force})...")
                try:
                    from scripts.run_generation import run_batch_generation
                    summary = run_batch_generation(period_mode="yearly", target_date=jan1, target_year=current_year, force=force)
                    release_yearly_job_lock(
                        jan1,
                        status="completed",
                        details=f"Generated: {summary.get('generated', 0)}, Skipped: {summary.get('skipped', 0)}, Failed: {summary.get('failed', 0)}"
                    )
                except Exception as gen_err:
                    release_yearly_job_lock(jan1, status="failed", details=str(gen_err)[:250])
                    raise gen_err
            else:
                print(f"[Daily Insights Scheduler] Yearly generation for {current_year} is already completed or locked by another worker.")
        else:
            print(f"[Daily Insights Scheduler] Yearly horoscopes for {current_year} are complete ({horo_count}/192 rows).")
    except Exception as e:
        print(f"[Daily Insights Scheduler] Error checking/generating yearly insights: {e}")


_scheduler_started = False
_scheduler_lock = threading.Lock()


def get_now_ist() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.utcnow() + timedelta(hours=5, minutes=30)


def get_daily_scheduler_config() -> dict:
    """
    Reads the scheduler time and check interval dynamically from environment variables (.env).
    - DAILY_INSIGHTS_SCHEDULER_TIME: 24-hr format HH:MM (e.g. '00:05', '05:00', '06:30', '10:30')
    - DAILY_INSIGHTS_CHECK_INTERVAL_SECONDS: Daemon periodic check frequency in seconds (default: 60)
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    time_str = os.getenv("DAILY_INSIGHTS_SCHEDULER_TIME", "10:30").strip()
    try:
        parts = time_str.split(":")
        target_hour = int(parts[0])
        target_minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        target_hour, target_minute = 10, 30

    try:
        check_interval = int(os.getenv("DAILY_INSIGHTS_CHECK_INTERVAL_SECONDS", "60"))
        if check_interval < 5:
            check_interval = 5
    except Exception:
        check_interval = 60

    return {
        "time_str": f"{target_hour:02d}:{target_minute:02d}",
        "target_hour": target_hour,
        "target_minute": target_minute,
        "check_interval": check_interval
    }


def _scheduler_worker():
    config = get_daily_scheduler_config()
    print(f"[Daily Insights Scheduler] Background thread initialized in IST. Running startup check (Configured daily time: {config['time_str']} IST, check interval: {config['check_interval']}s).")

    # Run initial check after a brief server startup delay (4 seconds)
    time.sleep(4)
    now_startup = get_now_ist()
    today_str = str(now_startup.date())
    try:
        # On server startup, ensure today's insights exist for all 12 signs without overwriting if already generated
        fetch_and_store_daily_insights_for_all_signs(target_date=today_str, force=False)
        # Startup catch-up: if current week's rows are missing (<96), generate only the missing ones
        ensure_weekly_insights_ready(target_date=now_startup.date(), force=False)
        # Startup catch-up: if current month's rows are missing (<192), generate only the missing ones
        ensure_monthly_insights_ready(target_date=now_startup.date(), force=False)
        # Startup catch-up: if current year's rows are missing (<192), generate only the missing ones
        ensure_yearly_insights_ready(target_year=now_startup.year, force=False)
    except Exception as e:
        print(f"[Daily Insights Scheduler] Startup check encountered exception: {e}")

    # Single-run mode: defaults to False so scheduler runs continuously every day
    run_once = os.getenv("DAILY_INSIGHTS_RUN_ONCE", "false").lower() in ("true", "1", "yes")
    if run_once:
        print("[Daily Insights Scheduler] One-time execution completed. Scheduler thread stopped.")
        return

    last_scheduled_date_run = None
    # If today already has full data at startup, record today's date as processed for the scheduled daily batch
    try:
        existing_test = get_sign_daily_insights_from_db("aries", today_str)
        if existing_test:
            last_scheduled_date_run = now_startup.date()
    except Exception:
        pass

    # Continuous loop: runs continuously every day
    while True:
        config = get_daily_scheduler_config()
        sleep_seconds = config["check_interval"]
        try:
            time.sleep(sleep_seconds)
            now = get_now_ist()
            today_date = now.date()
            today_str = str(today_date)
            target_hour = config["target_hour"]
            target_minute = config["target_minute"]

            # Trigger fresh daily LLM fetch when scheduled time is reached or passed on a new day
            is_new_day = (last_scheduled_date_run != today_date)
            has_reached_time = (now.hour > target_hour) or (now.hour == target_hour and now.minute >= target_minute)

            if is_new_day and has_reached_time:
                print(f"[Daily Insights Scheduler] Triggering scheduled daily LLM generation for {today_str} at {now.strftime('%H:%M:%S')} IST (Configured time: {config['time_str']} IST)...")
                fetch_and_store_daily_insights_for_all_signs(target_date=today_str, force=True)
                # If today is Monday (weekday == 0), trigger fresh weekly generation
                if today_date.weekday() == 0:
                    print(f"[Daily Insights Scheduler] Monday detected! Triggering scheduled weekly batch generation for {today_str}...")
                    ensure_weekly_insights_ready(target_date=today_date, force=True)
                # If today is 1st of month, trigger fresh monthly generation
                if today_date.day == 1:
                    print(f"[Daily Insights Scheduler] 1st of month detected! Triggering scheduled monthly batch generation for {today_str}...")
                    ensure_monthly_insights_ready(target_date=today_date, force=True)
                # If today is Jan 1, trigger fresh yearly generation for the new year
                if today_date.month == 1 and today_date.day == 1:
                    print(f"[Daily Insights Scheduler] Jan 1 detected! Triggering scheduled yearly batch generation for {today_date.year}...")
                    ensure_yearly_insights_ready(target_year=today_date.year, force=True)
                last_scheduled_date_run = today_date
            else:
                # Passive check: ONLY if today's rows are incomplete in DB (< 192 rows), then trigger catch-up
                try:
                    conn = get_db_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM `horoscopes` WHERE `period` = 'daily' AND `period_start` = %s;", (today_date,))
                        cnt = cur.fetchone()[0]
                        cur.close()
                    finally:
                        conn.close()

                    if cnt < 192:
                        print(f"[Daily Insights Scheduler] Incomplete daily rows detected ({cnt}/192). Generating missing rows...")
                        fetch_and_store_daily_insights_for_all_signs(target_date=today_str, force=False)
                except Exception as check_err:
                    print(f"[Daily Insights Scheduler] Passive check error: {check_err}")
        except Exception as e:
            print(f"[Daily Insights Scheduler] Loop error: {e}")


def start_daily_insights_scheduler():
    """
    Starts the background scheduler thread if not already running.
    """
    global _scheduler_started
    with _scheduler_lock:
        if not _scheduler_started:
            _scheduler_started = True
            t = threading.Thread(target=_scheduler_worker, daemon=True, name="DailyInsightsScheduler")
            t.start()
            print("[Daily Insights Scheduler] Started background thread successfully.")
