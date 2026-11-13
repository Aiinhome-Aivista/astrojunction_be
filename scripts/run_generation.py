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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AstroJunction Batch Horoscope Generator")
    parser.add_argument("--period", choices=["daily", "weekly", "monthly", "yearly", "all"], default="daily")
    parser.add_argument("--year", type=int, default=None, help="Target year for yearly horoscope (e.g. 2026)")
    parser.add_argument("--category", choices=["all", "cosmic_pulse"], default="all", help="Category to generate ('all' or 'cosmic_pulse')")
    parser.add_argument("--sign", choices=ZODIAC_SIGNS, default=None, help="Specific zodiac sign to run")
    parser.add_argument("--system", choices=SYSTEMS, default=None, help="Specific astrological system to run (tropical or sidereal)")
    parser.add_argument("--date", type=str, help="Target date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Force regenerate even if cached")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without writing to database or calling LLM")

    args = parser.parse_args()
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

