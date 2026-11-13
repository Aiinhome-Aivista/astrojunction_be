import os
import json
import threading
import time
from datetime import datetime, date, timedelta, timezone
from database.db_connection import get_db_connection
from services.email_service import send_daily_zodiac_insight_email

IST = timezone(timedelta(hours=5, minutes=30))

def get_now_ist() -> datetime:
    """Returns current datetime in Indian Standard Time (IST, UTC+5:30)."""
    return datetime.now(IST)

def get_today_ist() -> date:
    """Returns current date in Indian Standard Time (IST, UTC+5:30)."""
    return get_now_ist().date()

ALL_ZODIAC_SIGNS = [
    "aries", "taurus", "gemini", "cancer",
    "leo", "virgo", "libra", "scorpio",
    "sagittarius", "capricorn", "aquarius", "pisces"
]

ALL_CATEGORIES = [
    "health", "wealth", "relationship", "love_line",
    "education", "professional", "travel"
]

CATEGORY_ALIASES = {
    "career": "professional",
    "profession": "professional",
    "love": "love_line",
    "love_life": "love_line",
    "romance": "love_line"
}

def normalize_category_key(cat: str) -> str:
    """Normalizes category aliases to canonical names."""
    c = (cat or "").strip().lower()
    return CATEGORY_ALIASES.get(c, c)


def get_missing_signs(target_date: date = None, system: str = "tropical") -> list:
    """
    Returns a list of signs (from all 12) that do not have their complete daily rows
    in the horoscopes table for target_date and system.
    """
    if target_date is None:
        target_date = get_today_ist()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT `sign`, COUNT(DISTINCT `category`) as cat_count
                FROM `horoscopes`
                WHERE `period` = 'daily' AND `period_start` = %s AND `system` = %s
                GROUP BY `sign`;
            """, (target_date, system))
            rows = cursor.fetchall()
            cursor.close()

            found_signs = {r["sign"].lower(): r["cat_count"] for r in rows if r.get("cat_count", 0) >= 7}
            missing = [s for s in ALL_ZODIAC_SIGNS if s not in found_signs]
            return missing
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Email Scheduler] Error checking missing signs: {e}")
        return list(ALL_ZODIAC_SIGNS)


def verify_subscriber_sign_ready(
    sign: str,
    system: str,
    preferred_categories: list,
    target_date: date
) -> tuple:
    """
    Checks that subscriber's sign has today's rows in horoscopes table
    covering every category they selected plus cosmic_pulse.
    Returns (is_ready: bool, missing_categories: list[str]).
    """
    norm_sign = (sign or "aries").strip().lower()
    norm_system = (system or "tropical").strip().lower()

    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    needed = set()
    if preferred_categories:
        for c in preferred_categories:
            nc = normalize_category_key(c)
            if nc:
                needed.add(nc)
    else:
        needed = set(ALL_CATEGORIES)

    needed.add("cosmic_pulse")

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT `category`
                FROM `horoscopes`
                WHERE `sign` = %s AND `system` = %s AND `period` = 'daily' AND `period_start` = %s;
            """, (norm_sign, norm_system, target_date))
            rows = cursor.fetchall()
            cursor.close()

            existing_cats = {r["category"].lower() for r in rows}
            missing_cats = [c for c in needed if c not in existing_cats]
            return (len(missing_cats) == 0, sorted(list(missing_cats)))
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Email Scheduler] Error checking subscriber ready ({norm_sign}): {e}")
        return (False, sorted(list(needed)))


def get_subscriber_horoscope_data(sign: str, system: str, target_date: date) -> dict:
    """
    Fetches today's clean 1-paragraph horoscope items from the horoscopes table for email.
    """
    norm_sign = (sign or "aries").strip().lower()
    norm_system = (system or "tropical").strip().lower()

    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT `category`, `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`
                FROM `horoscopes`
                WHERE `sign` = %s AND `system` = %s AND `period` = 'daily' AND `period_start` = %s;
            """, (norm_sign, norm_system, target_date))
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return None

            cat_map = {}
            pulse_text = ""
            vitality = 85
            affirmation = ""
            tip_for_the_day = None

            for r in rows:
                c = r["category"]
                if c == "cosmic_pulse":
                    pulse_text = r["text"]
                    vitality = r["score"]
                    affirmation = r["affirmation"]
                    tip_for_the_day = r.get("tip_for_the_day")
                else:
                    cat_map[c] = {
                        "score": r["score"],
                        "insight": r["text"],
                        "transitAspect": f"Harmonious {norm_system.title()} Transit",
                        "lucky_time": r["lucky_time"],
                        "remedy": r["remedy"],
                        "affirmation": r["affirmation"]
                    }

            return {
                "forecast": pulse_text or f"Auspicious celestial alignments bring positive growth for {norm_sign.capitalize()} today.",
                "tip_for_the_day": tip_for_the_day,
                "vitalityToday": vitality,
                "affirmation": affirmation or "I step forward with clarity and courage, trusting my inner wisdom.",
                "resonantChakra": "Solar Plexus (Manipura)",
                "categoryInsights": cat_map
            }
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Email Scheduler] Error fetching email data for {norm_sign}: {e}")
        return None


def get_active_subscribers():
    """
    Fetches all active subscribers from the daily_update_subscriptions table.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT id, email, zodiac_sign, preferred_categories, last_sent_date, is_active
                FROM daily_update_subscriptions
                WHERE is_active = 1
                ORDER BY id ASC;
            """
            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()
            return rows
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Email Scheduler] Error fetching subscribers: {e}")
        return []


def mark_subscriber_sent(subscriber_id: int, sent_date: str):
    """
    Updates the last_sent_date for a subscriber to prevent duplicate emails on the same day.
    """
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            query = """
                UPDATE daily_update_subscriptions
                SET last_sent_date = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """
            cursor.execute(query, (sent_date, subscriber_id))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception as e:
        print(f"[Daily Email Scheduler] Error marking subscriber {subscriber_id} as sent: {e}")


def get_daily_email_scheduler_config() -> dict:
    """
    Reads the daily email scheduler settings dynamically from .env:
    - DAILY_EMAIL_SCHEDULER_START_HOUR: Beginning of morning dispatch window in IST (default: 6)
    - DAILY_EMAIL_CUTOFF_HOUR: Cutoff hour after which sending stops in IST (default: 10)
    - DAILY_EMAIL_CHECK_INTERVAL_SECONDS: Polling interval in seconds (default: 600 = 10 min)
    """
    try:
        start_hour = int(os.getenv("DAILY_EMAIL_SCHEDULER_START_HOUR", "6"))
    except Exception:
        start_hour = 6

    try:
        cutoff_hour = int(os.getenv("DAILY_EMAIL_CUTOFF_HOUR", "10"))
    except Exception:
        cutoff_hour = 10

    try:
        check_interval = int(os.getenv("DAILY_EMAIL_CHECK_INTERVAL_SECONDS", "600"))
        if check_interval < 10:
            check_interval = 10
    except Exception:
        check_interval = 600

    return {
        "start_hour": start_hour,
        "cutoff_hour": cutoff_hour,
        "check_interval": check_interval
    }


def send_daily_emails_to_all_subscribers(
    target_date: date = None,
    force: bool = False,
    current_time_ist: datetime = None
) -> dict:
    """
    Main Daily Email Scheduler Job:
    1. Enforces the morning dispatch window (06:00 IST - 10:00 IST).
       After the cutoff, stops sending and logs 'skipped, data not ready' with the count.
    2. Logs missing signs once per cycle via get_missing_signs(today).
    3. For each subscriber:
       - Checks last_sent_date (never sends twice in the same day).
       - Checks subscriber's sign has today's rows in horoscopes covering every selected category plus cosmic_pulse.
       - If missing, skips ONLY that subscriber without updating last_sent_date.
       - If ready, sends personalized email and marks last_sent_date.
    """
    if current_time_ist is None:
        current_time_ist = get_now_ist()

    if target_date is None:
        target_date = current_time_ist.date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    target_date_str = str(target_date)
    config = get_daily_email_scheduler_config()
    start_hour = config["start_hour"]
    cutoff_hour = config["cutoff_hour"]
    current_hour = current_time_ist.hour

    print(f"\n{'='*70}")
    print(f"📬 [DAILY EMAIL SCHEDULER] Dispatch poll for {target_date_str} at {current_time_ist.strftime('%H:%M:%S')} IST (Window: {start_hour}:00 - {cutoff_hour}:00 IST, force={force})...")

    # Retry window check: Poll starting at 06:00 IST, stop sending after 10:00 IST (cutoff)
    if not force:
        if current_hour < start_hour:
            print(f"⏰ [DAILY EMAIL SCHEDULER] Current IST hour ({current_hour}:00) is before morning window ({start_hour}:00 IST). Waiting...")
            print(f"{'='*70}\n")
            return {
                "status": "before_window",
                "message": f"Before start window {start_hour}:00 IST.",
                "date": target_date_str,
                "dispatched": 0,
                "skipped": 0,
                "errors": 0
            }

        if current_hour >= cutoff_hour:
            # Cutoff reached: Do not send stale or yesterday's content; just log "skipped, data not ready" with count
            subscribers = get_active_subscribers()
            unsent_count = sum(1 for s in subscribers if str(s.get("last_sent_date")) != target_date_str)
            print(f"🛑 [DAILY EMAIL SCHEDULER] Cutoff hour reached ({cutoff_hour}:00 IST). Stopped sending.")
            print(f"   skipped, data not ready: {unsent_count}")
            print(f"{'='*70}\n")
            return {
                "status": "cutoff_passed",
                "message": f"Cutoff hour {cutoff_hour}:00 IST reached. Stopped sending.",
                "date": target_date_str,
                "skipped_data_not_ready": unsent_count,
                "dispatched": 0,
                "skipped": unsent_count,
                "errors": 0
            }

    subscribers = get_active_subscribers()
    if not subscribers:
        print(f"ℹ️  [DAILY EMAIL SCHEDULER] No active subscribers found in daily_update_subscriptions.")
        print(f"{'='*70}\n")
        return {
            "status": "success",
            "date": target_date_str,
            "total_subscribers": 0,
            "dispatched": 0,
            "skipped": 0,
            "errors": 0,
            "details": []
        }

    # Helper get_missing_signs(today): Log once per polling cycle
    missing_signs = get_missing_signs(target_date, system="tropical")
    if missing_signs:
        print(f"⚠️  [DAILY EMAIL SCHEDULER] Missing signs in horoscopes table today ({target_date_str}): {', '.join(missing_signs)}")
    else:
        print(f"✅ [DAILY EMAIL SCHEDULER] All 12 signs ready in horoscopes table for {target_date_str}.")

    dispatched = 0
    skipped = 0
    errors = 0
    details = []

    for sub in subscribers:
        sub_id = sub["id"]
        email = sub["email"]
        sign = (sub.get("zodiac_sign") or "Aries").strip().lower()
        system = (sub.get("system") or sub.get("zodiac_system") or "tropical").strip().lower()
        last_sent = str(sub.get("last_sent_date")) if sub.get("last_sent_date") else None

        # Check if already sent today (Never send a subscriber the same day twice)
        if last_sent == target_date_str and not force:
            skipped += 1
            details.append({"email": email, "sign": sign, "status": "skipped_already_sent"})
            continue

        # Parse preferred categories
        pref_raw = sub.get("preferred_categories")
        pref_cats = []
        if isinstance(pref_raw, str):
            try:
                pref_cats = json.loads(pref_raw)
            except Exception:
                pref_cats = [c.strip() for c in pref_raw.split(",") if c.strip()]
        elif isinstance(pref_raw, list):
            pref_cats = pref_raw

        # Before sending to subscriber, check that THEIR sign has today's rows in horoscopes table
        # covering every category they selected plus cosmic_pulse.
        is_ready, missing_cats = verify_subscriber_sign_ready(sign, system, pref_cats, target_date)
        if not is_ready:
            print(f"  ⏭️  Skipping subscriber {email} ({sign.title()} / {system}): missing categories today: {', '.join(missing_cats)}")
            skipped += 1
            details.append({
                "email": email,
                "sign": sign,
                "system": system,
                "status": f"skipped_missing_categories: {', '.join(missing_cats)}"
            })
            continue

        try:
            # Fetch today's clean data directly from horoscopes table
            daily_data = get_subscriber_horoscope_data(sign, system, target_date)
            if not daily_data:
                print(f"  ⏭️  Skipping subscriber {email} ({sign.title()}): horoscope data could not be formatted.")
                skipped += 1
                details.append({"email": email, "sign": sign, "status": "skipped_data_not_ready"})
                continue

            # Dispatch personalized daily email
            send_daily_zodiac_insight_email(
                email=email,
                zodiac_sign=sign,
                daily_data=daily_data,
                preferred_categories=pref_cats
            )

            # Mark subscriber sent in database
            mark_subscriber_sent(sub_id, target_date_str)

            dispatched += 1
            details.append({
                "email": email,
                "sign": sign,
                "system": system,
                "categories": pref_cats or "all",
                "status": "dispatched"
            })
            print(f"  ✓ Dispatched daily horoscope email for {sign.title()} to {email}")

            # 150ms rate limit throttle
            time.sleep(0.15)

        except Exception as err:
            errors += 1
            print(f"  ❌ Failed to send daily email to {email}: {err}")
            details.append({"email": email, "sign": sign, "status": f"error: {str(err)}"})

    print(f"🏁 [DAILY EMAIL SCHEDULER] Completed: {dispatched} dispatched, {skipped} skipped, {errors} errors.")
    print(f"{'='*70}\n")

    return {
        "status": "success",
        "date": target_date_str,
        "total_subscribers": len(subscribers),
        "dispatched": dispatched,
        "skipped": skipped,
        "errors": errors,
        "details": details
    }


_email_scheduler_started = False
_email_scheduler_lock = threading.Lock()


def _email_scheduler_worker():
    """
    Background worker:
    Runs one-time verification on server startup: checks if within morning window (06:00 - 10:00 IST),
    dispatches daily emails to unsent subscribers if applicable, and terminates.
    """
    config = get_daily_email_scheduler_config()
    print(f"[Daily Email Scheduler] Background thread initialized (Window: {config['start_hour']:02d}:00 - {config['cutoff_hour']:02d}:00 IST).")
    time.sleep(6)

    try:
        now_ist = get_now_ist()
        today_date = now_ist.date()
        if config["start_hour"] <= now_ist.hour < config["cutoff_hour"]:
            send_daily_emails_to_all_subscribers(force=False, current_time_ist=now_ist)
        elif now_ist.hour >= config["cutoff_hour"]:
            print(f"[Daily Email Scheduler] Cutoff hour ({config['cutoff_hour']}:00 IST) has passed for {today_date}. Email dispatch window closed for today.")
        else:
            print(f"[Daily Email Scheduler] Current IST time ({now_ist.strftime('%H:%M:%S')}) is before morning window ({config['start_hour']:02d}:00 IST).")
    except Exception as e:
        print(f"[Daily Email Scheduler] Worker execution error: {e}")

    # Single-run mode: defaults to True so email scheduler runs only one time per server start
    run_once = os.getenv("DAILY_EMAIL_RUN_ONCE", "true").lower() in ("true", "1", "yes")
    if run_once:
        print("[Daily Email Scheduler] One-time execution completed successfully. Scheduler thread stopped.")
        return

    last_cutoff_logged_date = None
    while True:
        config = get_daily_email_scheduler_config()
        sleep_seconds = config["check_interval"]
        try:
            now_ist = get_now_ist()
            today_date = now_ist.date()
            # Send daily emails during 06:00 IST - 10:00 IST morning window
            if config["start_hour"] <= now_ist.hour < config["cutoff_hour"]:
                send_daily_emails_to_all_subscribers(force=False, current_time_ist=now_ist)
            elif now_ist.hour >= config["cutoff_hour"]:
                if last_cutoff_logged_date != today_date:
                    print(f"[Daily Email Scheduler] Cutoff hour reached ({config['cutoff_hour']}:00 IST) for {today_date}. Email dispatch window closed for today.")
                    last_cutoff_logged_date = today_date
            time.sleep(sleep_seconds)
        except Exception as e:
            print(f"[Daily Email Scheduler] Worker loop error: {e}")
            time.sleep(sleep_seconds)


def start_daily_email_scheduler():
    """
    Starts the separate background daily email scheduler thread.
    """
    global _email_scheduler_started
    with _email_scheduler_lock:
        if not _email_scheduler_started:
            _email_scheduler_started = True
            t = threading.Thread(
                target=_email_scheduler_worker,
                daemon=True,
                name="DailyEmailSchedulerThread"
            )
            t.start()
            print("[Daily Email Scheduler] Started separate background thread successfully.")


