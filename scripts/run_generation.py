"""
Batch Runner Module for AstroJunction Horoscope Generation
Provides CLI: python run_generation.py --period daily|weekly|monthly|all [--date YYYY-MM-DD] [--force]
Features:
- Cache check (skips if all 8 rows already exist unless --force)
- Reuses snapshot calculation once across all 12 signs
- Thread pool execution (max 4 concurrent) with rate-limit exponential backoff
- Upsert into MySQL `horoscopes` table
- Error logging to failed.json and summary report
"""

import os
import sys
import argparse
import json
import time
import calendar
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from scripts.ephemeris import get_snapshot, get_period_snapshots, get_month_ingresses, ZODIAC_SIGNS
from scripts.generate import generate_for_sign, generate_cosmic_pulse_for_sign, CATEGORIES
from database.db_connection import get_db_connection

SYSTEMS = ["tropical", "sidereal"]


def calculate_period_dates(period: str, target_date: date) -> tuple:
    """Returns (period_start, period_end) in IST."""
    if period == "daily":
        return target_date, target_date
    elif period == "weekly":
        # Monday start
        start = target_date - timedelta(days=target_date.weekday())
        end = start + timedelta(days=6)
        return start, end
    elif period == "monthly":
        # 1st of the month
        start = target_date.replace(day=1)
        last_day = calendar.monthrange(target_date.year, target_date.month)[1]
        end = target_date.replace(day=last_day)
        return start, end
    elif period == "yearly":
        # Jan 1 to Dec 31
        start = target_date.replace(month=1, day=1)
        end = target_date.replace(month=12, day=31)
        return start, end
    else:
        return target_date, target_date


def populate_month_ingresses(year: int, month: int) -> int:
    """
    Computes and upserts planetary ingresses and stations into `month_ingresses`
    for both tropical and sidereal systems (pure ephemeris, zero LLM calls).
    """
    try:
        tropical_events = get_month_ingresses(year, month, "tropical")
        sidereal_events = get_month_ingresses(year, month, "sidereal")
        all_events = tropical_events + sidereal_events

        if not all_events:
            print(f"[Month Ingresses]: No events found for {year}-{month:02d}.")
            return 0

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            upsert_query = """
                INSERT INTO `month_ingresses` (
                    `year`, `month`, `system`, `planet`, `from_sign`, `to_sign`,
                    `event_date`, `event_time`, `event_type`, `details`
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON DUPLICATE KEY UPDATE
                    `from_sign` = VALUES(`from_sign`),
                    `to_sign` = VALUES(`to_sign`),
                    `event_time` = VALUES(`event_time`),
                    `details` = VALUES(`details`);
            """
            for ev in all_events:
                cursor.execute(upsert_query, (
                    ev["year"],
                    ev["month"],
                    ev["system"],
                    ev["planet"],
                    ev.get("from_sign"),
                    ev["to_sign"],
                    ev["event_date"],
                    ev.get("event_time"),
                    ev["event_type"],
                    json.dumps(ev.get("details", {}))
                ))
            conn.commit()
            cursor.close()
            print(f"🪐 Populated month_ingresses table with {len(all_events)} events ({len(tropical_events)} tropical, {len(sidereal_events)} sidereal) for {year}-{month:02d}.")
            return len(all_events)
        finally:
            conn.close()
    except Exception as e:
        print(f"[Month Ingresses Error]: {e}")
        return 0


def check_cache_exists(sign: str, system: str, period: str, period_start: date, category: str = "all") -> bool:
    """Checks whether required categories already exist in database cache."""
    try:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if category == "cosmic_pulse":
                cursor.execute("""
                    SELECT COUNT(*) FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s
                    AND `category` = 'cosmic_pulse' AND `tip_for_the_day` IS NOT NULL AND TRIM(`tip_for_the_day`) != '';
                """, (sign, system, period, period_start))
                row = cursor.fetchone()
                count = row[0] if row else 0
                cursor.close()
                return count >= 1
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM `horoscopes`
                    WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s;
                """, (sign, system, period, period_start))
                row = cursor.fetchone()
                count = row[0] if row else 0
                cursor.close()
                return count >= len(CATEGORIES)
        finally:
            conn.close()
    except Exception as e:
        print(f"[Cache Check Warning]: {e}")
        return False


def upsert_horoscope_items(
    sign: str,
    system: str,
    period: str,
    period_start: date,
    period_end: date,
    items: list,
    snapshot: dict,
    model_name: str = "claude-3-5-sonnet"
):
    """Upserts the generated items into MySQL table `horoscopes`."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        snapshot_json = json.dumps(snapshot)

        upsert_query = """
            INSERT INTO `horoscopes` (
                `sign`, `system`, `period`, `category`, `period_start`, `period_end`,
                `text`, `score`, `lucky_time`, `remedy`, `affirmation`, `tip_for_the_day`, `planetary_snapshot`, `model`
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                `period_end` = VALUES(`period_end`),
                `text` = VALUES(`text`),
                `score` = VALUES(`score`),
                `lucky_time` = VALUES(`lucky_time`),
                `remedy` = VALUES(`remedy`),
                `affirmation` = VALUES(`affirmation`),
                `tip_for_the_day` = VALUES(`tip_for_the_day`),
                `planetary_snapshot` = VALUES(`planetary_snapshot`),
                `model` = VALUES(`model`),
                `updated_at` = CURRENT_TIMESTAMP;
        """

        for item in items:
            cursor.execute(upsert_query, (
                sign, system, period, item["category"], period_start, period_end,
                item["text"], item["score"], item["lucky_time"], item["remedy"], item["affirmation"],
                item.get("tip_for_the_day"), snapshot_json, model_name
            ))

        conn.commit()
        cursor.close()
    finally:
        conn.close()


def process_sign_generation(
    sign: str,
    system: str,
    period: str,
    period_start: date,
    period_end: date,
    snapshot: dict,
    category: str = "all",
    force: bool = False,
    dry_run: bool = False
) -> dict:
    """Worker task for a single sign + system + period combination."""
    if dry_run:
        print(f"🔎 [DRY-RUN] [{sign.upper():<11}] [{system:<8}]: Period {period} ({period_start} to {period_end}) verified. (No LLM / DB write)")
        return {
            "sign": sign,
            "system": system,
            "period": period,
            "status": "dry_run",
            "count": 8 if category == "all" else 1
        }

    if not force and check_cache_exists(sign, system, period, period_start, category=category):
        return {
            "sign": sign,
            "system": system,
            "period": period,
            "status": "skipped",
            "message": f"Cached ({category})"
        }

    # Unpack primary snapshot for database storage
    primary_snap = snapshot.get("primary_snapshot", snapshot) if isinstance(snapshot, dict) else snapshot

    # Exponential backoff retry loop
    max_retries = 3
    delay = 2
    for attempt in range(max_retries):
        try:
            if category == "cosmic_pulse":
                # Fetch existing categories from DB if available to provide rich context to cosmic_pulse
                cached_cats = []
                try:
                    conn = get_db_connection()
                    try:
                        cur = conn.cursor(dictionary=True)
                        cur.execute("""
                            SELECT `category`, `text`, `score` FROM `horoscopes`
                            WHERE `sign` = %s AND `system` = %s AND `period` = %s AND `period_start` = %s;
                        """, (sign, system, period, period_start))
                        cached_cats = cur.fetchall()
                        cur.close()
                    finally:
                        conn.close()
                except Exception as db_err:
                    print(f"[Warning fetching cached cats for {sign}]: {db_err}")

                item = generate_cosmic_pulse_for_sign(
                    sign, system, period, period_start, snapshot, cached_categories=cached_cats
                )
                upsert_horoscope_items(sign, system, period, period_start, period_end, [item], primary_snap)
                return {
                    "sign": sign,
                    "system": system,
                    "period": period,
                    "status": "generated",
                    "count": 1,
                    "tip": item.get("tip_for_the_day")
                }
            else:
                items = generate_for_sign(sign, system, period, period_start, snapshot)
                upsert_horoscope_items(sign, system, period, period_start, period_end, items, primary_snap)
                return {
                    "sign": sign,
                    "system": system,
                    "period": period,
                    "status": "generated",
                    "count": len(items)
                }
        except Exception as e:
            if "rate" in str(e).lower() and attempt < max_retries - 1:
                print(f"[Rate limit hit for {sign} ({system}), retrying in {delay}s...]")
                time.sleep(delay)
                delay *= 2
            elif attempt == max_retries - 1:
                return {
                    "sign": sign,
                    "system": system,
                    "period": period,
                    "status": "failed",
                    "error": str(e)
                }


def run_batch_generation(
    period_mode: str = "daily",
    target_date: date = None,
    category: str = "all",
    force: bool = False,
    filter_sign: str = None,
    filter_system: str = None,
    dry_run: bool = False,
    target_year: int = None
):
    """Main batch orchestration routine."""
    if target_year is not None:
        target_date = date(target_year, 1, 1)
    elif target_date is None:
        target_date = date.today()

    if period_mode == "yearly":
        target_date = target_date.replace(month=1, day=1)

    periods_to_run = []
    if period_mode == "all":
        periods_to_run.append("daily")
        if target_date.weekday() == 0 or force:  # Monday
            periods_to_run.append("weekly")
        if target_date.day == 1 or force:  # 1st of month
            periods_to_run.append("monthly")
        if target_year is not None:
            periods_to_run.append("yearly")
    else:
        periods_to_run.append(period_mode)

    signs_to_run = [filter_sign.lower().strip()] if filter_sign else ZODIAC_SIGNS
    systems_to_run = [filter_system.lower().strip()] if filter_system else SYSTEMS

    print(f"\n{'='*70}")
    print(f"🚀 AstroJunction Batch Horoscope Generation {'[DRY-RUN MODE]' if dry_run else ''}")
    print(f"📅 Target Date: {target_date} | Periods: {periods_to_run} | Category: {category} | Force: {force}")
    if filter_sign or filter_system:
        print(f"🎯 Filter: Sign={filter_sign or 'ALL'} | System={filter_system or 'ALL'}")
    print(f"{'='*70}\n")

    summary = {
        "generated": 0,
        "skipped": 0,
        "failed": 0,
        "failures": []
    }

    # Pre-calculate snapshots once and reuse across signs
    snapshot_cache = {}
    for p in periods_to_run:
        p_start, p_end = calculate_period_dates(p, target_date)
        print(f"🔭 Calculating Swiss Ephemeris snapshot for period '{p}' ({p_start} to {p_end})...")
        snap_bundle = get_period_snapshots(p, p_start)
        snapshot_cache[p] = (p_start, p_end, snap_bundle)

    # Populate month_ingresses table if running monthly
    if "monthly" in periods_to_run and not dry_run:
        m_start, _, _ = snapshot_cache["monthly"]
        populate_month_ingresses(m_start.year, m_start.month)

    tasks = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for p in periods_to_run:
            p_start, p_end, snapshot = snapshot_cache[p]
            for sign in signs_to_run:
                for system in systems_to_run:
                    tasks.append(
                        executor.submit(
                            process_sign_generation,
                            sign, system, p, p_start, p_end, snapshot, category, force, dry_run
                        )
                    )

        for future in as_completed(tasks):
            res = future.result()
            sign = res["sign"]
            system = res["system"]
            p = res["period"]
            status = res["status"]

            if status == "generated":
                summary["generated"] += 1
                tip_display = f" | Tip: {res.get('tip')}" if res.get('tip') else ""
                print(f"✅ [{sign.upper():<11}] [{system:<8}] [{p:<7}]: Stored {res.get('count', 0)} category(s) in DB{tip_display}")
            elif status == "dry_run":
                summary["generated"] += 1
            elif status == "skipped":
                summary["skipped"] += 1
                print(f"⚡ [{sign.upper():<11}] [{system:<8}] [{p:<7}]: Skipped (Cached)")
            else:
                summary["failed"] += 1
                summary["failures"].append(res)
                print(f"❌ [{sign.upper():<11}] [{system:<8}] [{p:<7}]: Failed - {res.get('error')}")

    # For weekly batch runs without filter, verify 192 rows and retry missing combinations up to 2 times
    if "weekly" in periods_to_run and not filter_sign and not filter_system and category == "all" and not dry_run:
        p_start, p_end, snapshot = snapshot_cache["weekly"]
        expected_total = len(ZODIAC_SIGNS) * len(SYSTEMS) * len(CATEGORIES)  # 192
        for retry_round in range(1, 3):
            try:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM `horoscopes` WHERE `period` = 'weekly' AND `period_start` = %s;", (p_start,))
                    current_count = cur.fetchone()[0]
                    cur.execute("""
                        SELECT `sign`, `system`, COUNT(*) as cnt 
                        FROM `horoscopes` 
                        WHERE `period` = 'weekly' AND `period_start` = %s 
                        GROUP BY `sign`, `system`;
                    """, (p_start,))
                    counts_by_pair = {(r[0], r[1]): r[2] for r in cur.fetchall()}
                    cur.close()
                finally:
                    conn.close()

                if current_count >= expected_total:
                    print(f"✨ Weekly verification passed: All {expected_total} rows present for week starting {p_start}.")
                    break
                else:
                    print(f"\n⚠️  Weekly verification found {current_count}/{expected_total} rows. Retry round {retry_round}/2...")
                    missing_pairs = []
                    for s in ZODIAC_SIGNS:
                        for sys_name in SYSTEMS:
                            if counts_by_pair.get((s, sys_name), 0) < len(CATEGORIES):
                                missing_pairs.append((s, sys_name))

                    print(f"🔄 Retrying {len(missing_pairs)} missing sign/system combinations: {missing_pairs}")
                    retry_tasks = []
                    with ThreadPoolExecutor(max_workers=4) as retry_exec:
                        for s, sys_name in missing_pairs:
                            retry_tasks.append(
                                retry_exec.submit(
                                    process_sign_generation,
                                    s, sys_name, "weekly", p_start, p_end, snapshot, "all", True
                                )
                            )
                        for rf in as_completed(retry_tasks):
                            rres = rf.result()
                            if rres["status"] == "generated":
                                summary["generated"] += 1
                                print(f"✅ [RETRY SUCCESS] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: Stored {rres.get('count', 0)} categories.")
                            else:
                                print(f"❌ [RETRY FAILED] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: {rres.get('error')}")
            except Exception as v_err:
                print(f"[Verification error]: {v_err}")
                break

    # For monthly batch runs without filter, verify 192 rows and retry missing combinations up to 2 times
    if "monthly" in periods_to_run and not filter_sign and not filter_system and category == "all" and not dry_run:
        p_start, p_end, snapshot = snapshot_cache["monthly"]
        expected_total = len(ZODIAC_SIGNS) * len(SYSTEMS) * len(CATEGORIES)  # 192
        for retry_round in range(1, 3):
            try:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM `horoscopes` WHERE `period` = 'monthly' AND `period_start` = %s;", (p_start,))
                    current_count = cur.fetchone()[0]
                    cur.execute("""
                        SELECT `sign`, `system`, COUNT(*) as cnt 
                        FROM `horoscopes` 
                        WHERE `period` = 'monthly' AND `period_start` = %s 
                        GROUP BY `sign`, `system`;
                    """, (p_start,))
                    counts_by_pair = {(r[0], r[1]): r[2] for r in cur.fetchall()}
                    cur.close()
                finally:
                    conn.close()

                if current_count >= expected_total:
                    print(f"✨ Monthly verification passed: All {expected_total} rows present for month starting {p_start}.")
                    break
                else:
                    print(f"\n⚠️  Monthly verification found {current_count}/{expected_total} rows. Retry round {retry_round}/2...")
                    missing_pairs = []
                    for s in ZODIAC_SIGNS:
                        for sys_name in SYSTEMS:
                            if counts_by_pair.get((s, sys_name), 0) < len(CATEGORIES):
                                missing_pairs.append((s, sys_name))

                    print(f"🔄 Retrying {len(missing_pairs)} missing sign/system combinations: {missing_pairs}")
                    retry_tasks = []
                    with ThreadPoolExecutor(max_workers=4) as retry_exec:
                        for s, sys_name in missing_pairs:
                            retry_tasks.append(
                                retry_exec.submit(
                                    process_sign_generation,
                                    s, sys_name, "monthly", p_start, p_end, snapshot, "all", True
                                )
                            )
                        for rf in as_completed(retry_tasks):
                            rres = rf.result()
                            if rres["status"] == "generated":
                                summary["generated"] += 1
                                print(f"✅ [RETRY SUCCESS] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: Stored {rres.get('count', 0)} categories.")
                            else:
                                print(f"❌ [RETRY FAILED] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: {rres.get('error')}")
            except Exception as v_err:
                print(f"[Monthly verification error]: {v_err}")
                break

    # For yearly batch runs without filter, verify 192 rows and retry missing combinations up to 2 times
    if "yearly" in periods_to_run and not filter_sign and not filter_system and category == "all" and not dry_run:
        p_start, p_end, snapshot = snapshot_cache["yearly"]
        expected_total = len(ZODIAC_SIGNS) * len(SYSTEMS) * len(CATEGORIES)  # 192
        for retry_round in range(1, 3):
            try:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM `horoscopes` WHERE `period` = 'yearly' AND `period_start` = %s;", (p_start,))
                    current_count = cur.fetchone()[0]
                    cur.execute("""
                        SELECT `sign`, `system`, COUNT(*) as cnt 
                        FROM `horoscopes` 
                        WHERE `period` = 'yearly' AND `period_start` = %s 
                        GROUP BY `sign`, `system`;
                    """, (p_start,))
                    counts_by_pair = {(r[0], r[1]): r[2] for r in cur.fetchall()}
                    cur.close()
                finally:
                    conn.close()

                if current_count >= expected_total:
                    print(f"✨ Yearly verification passed: All {expected_total} rows present for year starting {p_start}.")
                    break
                else:
                    print(f"\n⚠️  Yearly verification found {current_count}/{expected_total} rows. Retry round {retry_round}/2...")
                    missing_pairs = []
                    for s in ZODIAC_SIGNS:
                        for sys_name in SYSTEMS:
                            if counts_by_pair.get((s, sys_name), 0) < len(CATEGORIES):
                                missing_pairs.append((s, sys_name))

                    print(f"🔄 Retrying {len(missing_pairs)} missing sign/system combinations: {missing_pairs}")
                    retry_tasks = []
                    with ThreadPoolExecutor(max_workers=4) as retry_exec:
                        for s, sys_name in missing_pairs:
                            retry_tasks.append(
                                retry_exec.submit(
                                    process_sign_generation,
                                    s, sys_name, "yearly", p_start, p_end, snapshot, "all", True
                                )
                            )
                        for rf in as_completed(retry_tasks):
                            rres = rf.result()
                            if rres["status"] == "generated":
                                summary["generated"] += 1
                                print(f"✅ [RETRY SUCCESS] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: Stored {rres.get('count', 0)} categories.")
                            else:
                                print(f"❌ [RETRY FAILED] [{rres['sign'].upper():<11}] [{rres['system']:<8}]: {rres.get('error')}")
            except Exception as v_err:
                print(f"[Yearly verification error]: {v_err}")
                break

    # Write failures to failed.json if any
    failed_path = os.path.join(backend_dir, "failed.json")
    if summary["failures"] and not dry_run:
        with open(failed_path, "w", encoding="utf-8") as f:
            json.dump(summary["failures"], f, indent=2)
        print(f"\n⚠️  {len(summary['failures'])} failures logged to: {failed_path}")
    elif os.path.exists(failed_path) and not dry_run:
        os.remove(failed_path)

    # Token and cost calculation estimate
    gen_count = summary["generated"]
    if "yearly" in periods_to_run:
        est_prompt_tokens = gen_count * 2500
        est_comp_tokens = gen_count * 5200
    else:
        est_prompt_tokens = gen_count * 1500
        est_comp_tokens = gen_count * 2600
    est_cost = (est_prompt_tokens / 1_000_000 * 0.04) + (est_comp_tokens / 1_000_000 * 0.10)

    print(f"\n{'='*70}")
    if dry_run:
        summary_msg = "[DRY-RUN SUCCESS]"
    else:
        summary_msg = f"Generated: {summary['generated']} | Skipped (Cached): {summary['skipped']} | Failed: {summary['failed']}"
    print(f"📊 SUMMARY: {summary_msg}")
    if gen_count > 0 and not dry_run:
        print(f"🪙 Estimated Token Usage: ~{est_prompt_tokens:,} prompt tokens, ~{est_comp_tokens:,} completion tokens")
        print(f"💵 Estimated Cost: ~${est_cost:.4f} USD (Ministral-3B @ $0.04/M input, $0.10/M output)")
    print(f"{'='*70}\n")
    return summary


def run_translation_tests():
    """
    Automated Test Suite for Landing Horoscope Translation.
    Validates:
    1. lang=en never calls Mistral; unsupported lang returns 400.
    2. Same request twice: the second is served from cache (Mistral call count stays 1).
    3. 10 simultaneous requests for the same missing key trigger exactly 1 Mistral call.
    4. Validator rejects wrong paragraph count, markdown, untranslated English, and falls back to English with translated=false.
    5. Score, lucky_time numbers, and category keys are identical across languages.
    6. If the English row changes, the old cached translation is not reused.
    """
    import threading
    from services.landing_translation import (
        translate_items,
        _TRANSLATION_CACHE,
        _FAILURE_CACHE,
        _validate_translation,
        _get_sha1,
        get_translation_stats,
    )
    from controllers.horoscope_controller import VALID_LANGUAGES

    print("\n" + "=" * 70)
    print("🧪 RUNNING HOROSCOPE TRANSLATION TEST SUITE")
    print("=" * 70)

    # Test 1: lang=en never calls Mistral; unsupported lang validation
    print("\n[Test 1] Testing language validation...")
    assert "en" in VALID_LANGUAGES and "hi" in VALID_LANGUAGES and "bn" in VALID_LANGUAGES
    assert "ta" in VALID_LANGUAGES and "fr" in VALID_LANGUAGES
    assert "es" not in VALID_LANGUAGES and "de" not in VALID_LANGUAGES

    mock_items = [
        {
            "category": "cosmic_pulse",
            "text": "The Moon enters your sign today, bringing emotional clarity.\n\nTake time for mindful meditation.",
            "score": 88,
            "lucky_time": "09:00 AM - 11:30 AM",
            "remedy": "Offer water to the rising Sun.",
            "affirmation": "I embrace peace and abundance.",
            "tip_for_the_day": "Stay grounded and trust your intuition.",
        },
        {
            "category": "wealth",
            "text": "Financial investments show promising growth.\n\nAvoid speculative trading in the afternoon.",
            "score": 75,
            "lucky_time": "02:15 PM to 04:00 PM",
            "remedy": "Chant the Lakshmi Beej Mantra.",
            "affirmation": "Wealth flows easily into my life.",
            "tip_for_the_day": "Review your monthly budget carefully.",
        }
    ]
    meta = {"sign": "taurus", "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}

    # Call to lang=en
    stats_before = get_translation_stats()
    en_res = translate_items(mock_items, "en", meta)
    stats_after = get_translation_stats()
    assert en_res[0]["text"] == mock_items[0]["text"], "English text was modified"
    assert en_res[0]["score"] == 88, "Score changed"
    assert stats_after["total_calls"] == stats_before["total_calls"], "Mistral was called for English"
    print("  ✓ lang=en returned rows unchanged without calling Mistral.")

    # Test 2: Cache hit test - same request twice triggers exactly 1 Mistral call
    print("\n[Test 2] Testing caching & idempotency...")
    test_sign = "virgo_test"
    test_meta = {"sign": test_sign, "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}
    
    call_count = 0
    import services.landing_translation as lt
    orig_execute = lt._execute_mistral_chunk
    
    def fake_execute(chunk, lang, m):
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        res = {}
        for it in chunk:
            c = it["category"]
            res[c] = {
                "text": "चंद्रमा आज आपकी राशि में प्रवेश कर रहा है, जिससे भावनात्मक स्पष्टता आएगी।\n\nसचेत ध्यान के लिए समय निकालें।",
                "remedy": "उगते सूर्य को जल अर्पित करें।",
                "affirmation": "मैं शांति और समृद्धि को स्वीकार करता हूं।",
                "lucky_time": "सुबह 09:00 AM - 11:30 AM",
                "tip_for_the_day": "धैर्य रखें और अपनी अंतरात्मा पर भरोसा करें।",
            }
        return res

    lt._execute_mistral_chunk = fake_execute
    try:
        # First call -> triggers fake_execute
        res1 = lt.translate_items(mock_items[:1], "hi", test_meta)
        assert call_count == 1, f"Expected 1 call, got {call_count}"
        assert res1[0]["translated"] is True
        assert "चंद्रमा" in res1[0]["text"]

        # Second call with same parameters -> must hit cache!
        res2 = lt.translate_items(mock_items[:1], "hi", test_meta)
        assert call_count == 1, f"Expected call count to remain 1, got {call_count}"
        assert res2[0]["text"] == res1[0]["text"]
        print("  ✓ Second request served from memory cache (call count stayed 1).")
    finally:
        lt._execute_mistral_chunk = orig_execute

    # Test 3: 10 simultaneous requests trigger exactly 1 Mistral call
    print("\n[Test 3] Testing 10 simultaneous parallel requests de-duplication...")
    concurrent_calls = 0
    def slow_fake_execute(chunk, lang, m):
        nonlocal concurrent_calls
        concurrent_calls += 1
        time.sleep(0.15)
        res = {}
        for it in chunk:
            c = it["category"]
            res[c] = {
                "text": "চাঁদ আজ আপনার রাশিতে প্রবেশ করছে, যা মানসিক স্পষ্টতা এনে দেবে।\n\nমননশীল ধ্যানের জন্য সময় দিন।",
                "remedy": "উদীয়মান সূর্যকে জল অর্পণ করুন।",
                "affirmation": "আমি শান্তি ও প্রাচুর্য গ্রহণ করি।",
                "lucky_time": "সকাল 09:00 AM - 11:30 AM",
                "tip_for_the_day": "ধৈর্য ধরুন এবং আপনার অন্তর্দৃষ্টিতে বিশ্বাস রাখুন।",
            }
        return res

    orig_execute = lt._execute_mistral_chunk
    lt._execute_mistral_chunk = slow_fake_execute
    try:
        simul_meta = {"sign": "libra_simul", "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}
        results = [None] * 10
        threads = []
        def worker(idx):
            results[idx] = lt.translate_items(mock_items[:1], "bn", simul_meta)

        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert concurrent_calls == 1, f"Expected exactly 1 Mistral call for 10 concurrent requests, got {concurrent_calls}"
        for r in results:
            assert r[0]["translated"] is True
            assert "চাঁদ" in r[0]["text"]
        print("  ✓ 10 simultaneous requests triggered exactly 1 Mistral call.")
    finally:
        lt._execute_mistral_chunk = orig_execute

    # Test 4: Validator rejects wrong paragraph count, markdown, untranslated English and truncated JSON
    print("\n[Test 4] Testing validation rules...")
    # 4a: Wrong paragraph count
    bad_para = {"text": "Only one paragraph without break."}
    v_res, err = _validate_translation(bad_para, mock_items[0], "hi")
    assert not v_res and "Paragraph count mismatch" in err, f"Failed: {err}"
    print("  ✓ Rejected paragraph count mismatch.")

    # 4b: Markdown in text
    bad_md = {"text": "**bold title**\n\n- bullet point item"}
    v_res, err = _validate_translation(bad_md, mock_items[0], "hi")
    assert not v_res and "Markdown" in err, f"Failed: {err}"
    print("  ✓ Rejected markdown formatting.")

    # 4c: Untranslated English in Hindi
    bad_script = {"text": "This is completely in English language without any Devanagari.\n\nAnother paragraph in English."}
    v_res, err = _validate_translation(bad_script, mock_items[0], "hi")
    assert not v_res and ("script" in err.lower() or "english" in err.lower()), f"Failed: {err}"
    print("  ✓ Rejected untranslated English in Hindi script check.")

    # 4d: Truncated JSON / failure fallback
    def failing_execute(chunk, lang, m):
        return None # Simulated truncated JSON or API failure

    lt._execute_mistral_chunk = failing_execute
    try:
        fail_meta = {"sign": "scorpio_fail", "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}
        fail_res = lt.translate_items(mock_items[:1], "hi", fail_meta)
        assert fail_res[0]["translated"] is False, "Expected translated=False on failure"
        assert fail_res[0]["text"] == mock_items[0]["text"], "Expected fallback to English text"
        print("  ✓ Truncated/failed translation fell back to English with translated=false.")
    finally:
        lt._execute_mistral_chunk = orig_execute

    # Test 5: Score, lucky_time numbers, and category keys identical across languages
    print("\n[Test 5] Testing score, numbers, and category keys fidelity...")
    valid_trans = {
        "text": "चंद्रमा आज आपकी राशि में प्रवेश कर रहा है।\n\nसचेत ध्यान के लिए समय निकालें।",
        "score": 999, # LLM attempts to tamper with score
        "lucky_time": "शुभ समय 09:00 AM - 11:30 AM",
        "category": "hacked_category"
    }
    def mock_good_execute(chunk, lang, m):
        return {"cosmic_pulse": valid_trans}

    lt._execute_mistral_chunk = mock_good_execute
    try:
        safe_meta = {"sign": "leo_safe", "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}
        safe_res = lt.translate_items(mock_items[:1], "hi", safe_meta)
        assert safe_res[0]["score"] == 88, f"Score was tampered: {safe_res[0]['score']} != 88"
        assert safe_res[0]["category"] == "cosmic_pulse", "Category key was altered"
        assert "09:00 AM - 11:30 AM" in safe_res[0]["lucky_time"], "Lucky time numbers altered"
        print("  ✓ Score (88), category key ('cosmic_pulse'), and time numbers preserved exactly.")
    finally:
        lt._execute_mistral_chunk = orig_execute

    # Test 6: If English row changes, old cached translation is not reused
    print("\n[Test 6] Testing cache invalidation when English text changes...")
    def dynamic_execute(chunk, lang, m):
        res = {}
        for it in chunk:
            res[it["category"]] = {
                "text": f"अनुवाद: {it['text'][:30]}...",
                "lucky_time": it.get("lucky_time", "")
            }
        return res

    lt._execute_mistral_chunk = dynamic_execute
    try:
        inv_meta = {"sign": "pisces_inv", "system": "tropical", "period": "daily", "period_start": "2026-11-14", "period_end": "2026-11-14"}
        item_v1 = [dict(mock_items[0], text="Version 1 original text.\n\nSecond paragraph.")]
        res_v1 = lt.translate_items(item_v1, "hi", inv_meta)

        # Modify English text in row
        item_v2 = [dict(mock_items[0], text="Version 2 updated text from database.\n\nSecond paragraph.")]
        res_v2 = lt.translate_items(item_v2, "hi", inv_meta)

        assert res_v1[0]["text"] != res_v2[0]["text"], "Old translation was reused despite English text change!"
        assert "Version 2" in res_v2[0]["text"], "New translation did not reflect updated English text"
        print("  ✓ English row modification correctly bypassed stale cache (SHA1 check passed).")
    finally:
        lt._execute_mistral_chunk = orig_execute

    print("\n" + "=" * 70)
    print("✅ ALL 6 TRANSLATION UNIT TESTS PASSED SUCCESSFULLY!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstroJunction Batch Horoscope Generator")
    parser.add_argument("--test-translation", action="store_true", help="Run translation unit test suite")
    parser.add_argument("--period", choices=["daily", "weekly", "monthly", "yearly", "all"], default="daily")
    parser.add_argument("--year", type=int, default=None, help="Target year for yearly horoscope (e.g. 2026)")
    parser.add_argument("--category", choices=["all", "cosmic_pulse"], default="all", help="Category to generate ('all' or 'cosmic_pulse')")
    parser.add_argument("--sign", choices=ZODIAC_SIGNS, default=None, help="Specific zodiac sign to run")
    parser.add_argument("--system", choices=SYSTEMS, default=None, help="Specific astrological system to run (tropical or sidereal)")
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Force regenerate even if cached")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without writing to database or calling LLM")

    args = parser.parse_args()

    if args.test_translation:
        run_translation_tests()
        sys.exit(0)

    target_dt = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else (date(args.year, 1, 1) if args.year else date.today())
    run_batch_generation(
        args.period,
        target_dt,
        args.category,
        args.force,
        filter_sign=args.sign,
        filter_system=args.system,
        dry_run=args.dry_run,
        target_year=args.year
    )

