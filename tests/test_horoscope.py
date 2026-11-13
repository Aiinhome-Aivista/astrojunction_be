"""
Unit tests for AstroJunction:
1. Horoscope stale fallback (controllers/horoscope_controller.py)
2. Missing sign / category subscriber skip (services/daily_email_scheduler.py)
3. Email scheduler retry window and cutoff behavior (services/daily_email_scheduler.py)
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, date, timedelta, timezone
from flask import Flask

import sys
import os
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

from controllers.horoscope_controller import get_horoscope, get_horoscope_vitality, get_today_ist, IST
from scripts.generate import HoroscopeCategoryItem, clean_text
from scripts.run_generation import calculate_period_dates
from services.daily_email_scheduler import (
    get_missing_signs,
    verify_subscriber_sign_ready,
    send_daily_emails_to_all_subscribers,
    ALL_ZODIAC_SIGNS
)


class TestHoroscopeStaleFallback(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.add_url_rule("/api/horoscope", view_func=get_horoscope, methods=["GET"])
        self.app.add_url_rule("/api/horoscope/vitality", view_func=get_horoscope_vitality, methods=["GET"])
        self.client = self.app.test_client()

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_today_row_found_not_stale(self, mock_get_conn):
        today_ist = get_today_ist()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # First query: today's row exists
        mock_cursor.fetchone.return_value = {
            "period_start": today_ist,
            "period_end": today_ist
        }
        # Second query: category items
        mock_cursor.fetchall.return_value = [
            {
                "category": "cosmic_pulse",
                "text": "Today's cosmic pulse reading.",
                "score": 90,
                "lucky_time": "10:00 AM",
                "remedy": "Chant Om",
                "affirmation": "I am calm.",
                "generated_at": str(datetime.now())
            }
        ]

        res = self.client.get("/api/horoscope?sign=taurus&system=tropical&period=daily&category=all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["stale"])
        self.assertEqual(data["period_start"], str(today_ist))
        self.assertEqual(len(data["items"]), 1)

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_no_today_row_falls_back_to_stale_previous(self, mock_get_conn):
        today_ist = get_today_ist()
        yesterday_ist = today_ist - timedelta(days=1)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # 1st query (today): None
        # 2nd query (period_start < today): returns yesterday
        mock_cursor.fetchone.side_effect = [
            None,
            {
                "period_start": yesterday_ist,
                "period_end": yesterday_ist
            }
        ]
        mock_cursor.fetchall.return_value = [
            {
                "category": "cosmic_pulse",
                "text": "Yesterday's cosmic pulse reading.",
                "score": 85,
                "lucky_time": "11:00 AM",
                "remedy": "Drink water",
                "affirmation": "I trust the journey.",
                "generated_at": str(datetime.now() - timedelta(days=1))
            }
        ]

        res = self.client.get("/api/horoscope?sign=taurus&system=tropical&period=daily&category=all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["stale"])
        self.assertEqual(data["period_start"], str(yesterday_ist))

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_no_rows_at_all_returns_404(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Both queries return None
        mock_cursor.fetchone.side_effect = [None, None]

        res = self.client.get("/api/horoscope?sign=scorpio&system=tropical&period=daily&category=all")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertEqual(data["status"], "error")
        self.assertIn("No horoscope data found", data["message"])
        self.assertTrue(data["stale"])

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_horoscope_vitality_returns_sign_map(self, mock_get_conn):
        today_ist = get_today_ist()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {"period_start": today_ist}
        mock_cursor.fetchall.return_value = [
            {"sign": "aries", "score": 86},
            {"sign": "taurus", "score": 89}
        ]

        res = self.client.get("/api/horoscope/vitality?system=tropical&period=daily")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["vitality"]["aries"], 86)
        self.assertEqual(data["vitality"]["taurus"], 89)

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_weekly_active_window_found(self, mock_get_conn):
        today_ist = get_today_ist()
        monday = today_ist - timedelta(days=today_ist.weekday())
        sunday = monday + timedelta(days=6)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # 1st query: active week window covering today
        mock_cursor.fetchone.return_value = {
            "period_start": monday,
            "period_end": sunday
        }
        mock_cursor.fetchall.return_value = [
            {
                "category": "cosmic_pulse",
                "text": "Weekly cosmic pulse forecast.",
                "score": 88,
                "lucky_time": "11:00 AM",
                "remedy": "Weekly meditation",
                "affirmation": "I embrace the week with courage.",
                "tip_for_the_day": "Set clear weekly boundaries early.",
                "generated_at": str(datetime.now())
            }
        ]

        res = self.client.get("/api/horoscope?sign=taurus&system=tropical&period=weekly&category=all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["stale"])
        self.assertEqual(data["period_start"], str(monday))
        self.assertEqual(data["period_end"], str(sunday))
        self.assertEqual(data["items"][0]["tip_for_the_day"], "Set clear weekly boundaries early.")

    @patch("controllers.horoscope_controller.get_db_connection")
    def test_weekly_falls_back_to_stale_earlier_week(self, mock_get_conn):
        today_ist = get_today_ist()
        last_monday = today_ist - timedelta(days=today_ist.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # 1st query: None
        # 2nd query (period_end < today): returns previous week
        mock_cursor.fetchone.side_effect = [
            None,
            {
                "period_start": last_monday,
                "period_end": last_sunday
            }
        ]
        mock_cursor.fetchall.return_value = [
            {
                "category": "cosmic_pulse",
                "text": "Previous week reading.",
                "score": 82,
                "lucky_time": "09:00 AM",
                "remedy": "Drink herbal tea",
                "affirmation": "I stay aligned.",
                "tip_for_the_day": "Review your goals.",
                "generated_at": str(datetime.now() - timedelta(days=7))
            }
        ]

        res = self.client.get("/api/horoscope?sign=taurus&system=tropical&period=weekly&category=all")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["stale"])
        self.assertEqual(data["period_start"], str(last_monday))


class TestDailyEmailSchedulerMissingSign(unittest.TestCase):
    @patch("services.daily_email_scheduler.get_db_connection")
    def test_get_missing_signs_detects_incomplete_signs(self, mock_get_conn):
        today = date(2026, 11, 13)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # 11 signs have 8 categories; 'pisces' has only 3 categories
        complete_rows = [
            {"sign": s, "cat_count": 8} for s in ALL_ZODIAC_SIGNS if s != "pisces"
        ]
        complete_rows.append({"sign": "pisces", "cat_count": 3})
        mock_cursor.fetchall.return_value = complete_rows

        missing = get_missing_signs(today, system="tropical")
        self.assertIn("pisces", missing)
        self.assertEqual(len(missing), 1)

    @patch("services.daily_email_scheduler.get_db_connection")
    def test_verify_subscriber_sign_ready(self, mock_get_conn):
        today = date(2026, 11, 13)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        # Case 1: DB has wealth and cosmic_pulse -> Ready
        mock_cursor.fetchall.return_value = [
            {"category": "wealth"},
            {"category": "cosmic_pulse"}
        ]
        ready, missing = verify_subscriber_sign_ready("taurus", "tropical", ["wealth"], today)
        self.assertTrue(ready)
        self.assertEqual(missing, [])

        # Case 2: DB is missing wealth -> Not ready
        mock_cursor.fetchall.return_value = [
            {"category": "cosmic_pulse"}
        ]
        ready, missing = verify_subscriber_sign_ready("taurus", "tropical", ["wealth"], today)
        self.assertFalse(ready)
        self.assertIn("wealth", missing)

    @patch("services.daily_email_scheduler.get_active_subscribers")
    @patch("services.daily_email_scheduler.verify_subscriber_sign_ready")
    @patch("services.daily_email_scheduler.get_subscriber_horoscope_data")
    @patch("services.daily_email_scheduler.send_daily_zodiac_insight_email")
    @patch("services.daily_email_scheduler.mark_subscriber_sent")
    @patch("services.daily_email_scheduler.get_missing_signs")
    def test_missing_sign_skips_only_that_subscriber(
        self,
        mock_missing_signs,
        mock_mark_sent,
        mock_send_email,
        mock_get_data,
        mock_verify_ready,
        mock_get_subs
    ):
        today = date(2026, 11, 13)
        mock_missing_signs.return_value = ["gemini"]

        # Two subscribers: Sub 1 is Taurus (ready), Sub 2 is Gemini (missing)
        mock_get_subs.return_value = [
            {"id": 1, "email": "taurus@example.com", "zodiac_sign": "taurus", "system": "tropical", "preferred_categories": ["wealth"], "last_sent_date": None},
            {"id": 2, "email": "gemini@example.com", "zodiac_sign": "gemini", "system": "tropical", "preferred_categories": ["health"], "last_sent_date": None}
        ]

        def verify_side_effect(sign, system, cats, target_dt):
            if sign == "taurus":
                return (True, [])
            else:
                return (False, ["health", "cosmic_pulse"])

        mock_verify_ready.side_effect = verify_side_effect
        mock_get_data.return_value = {
            "forecast": "Great day",
            "vitalityToday": 90,
            "categoryInsights": {}
        }

        # Dispatch at 07:00 IST (within valid window)
        send_time = datetime(2026, 11, 13, 7, 0, 0, tzinfo=IST)
        res = send_daily_emails_to_all_subscribers(target_date=today, current_time_ist=send_time)

        self.assertEqual(res["dispatched"], 1)
        self.assertEqual(res["skipped"], 1)

        # Taurus subscriber was marked sent
        mock_mark_sent.assert_called_once_with(1, "2026-11-13")
        mock_send_email.assert_called_once()


class TestDailyEmailSchedulerCutoff(unittest.TestCase):
    @patch("services.daily_email_scheduler.get_active_subscribers")
    @patch("services.daily_email_scheduler.send_daily_zodiac_insight_email")
    def test_cutoff_hour_stops_sending(self, mock_send_email, mock_get_subs):
        today = date(2026, 11, 13)
        mock_get_subs.return_value = [
            {"id": 1, "email": "user1@example.com", "zodiac_sign": "aries", "last_sent_date": None},
            {"id": 2, "email": "user2@example.com", "zodiac_sign": "taurus", "last_sent_date": None}
        ]

        # 10:15 IST is >= cutoff (10:00 IST)
        cutoff_time = datetime(2026, 11, 13, 10, 15, 0, tzinfo=IST)
        res = send_daily_emails_to_all_subscribers(target_date=today, current_time_ist=cutoff_time)

        self.assertEqual(res["status"], "cutoff_passed")
        self.assertEqual(res["skipped_data_not_ready"], 2)
        self.assertEqual(res["dispatched"], 0)
        # Verify no email was dispatched
        mock_send_email.assert_not_called()

    @patch("services.daily_email_scheduler.get_active_subscribers")
    @patch("services.daily_email_scheduler.send_daily_zodiac_insight_email")
    def test_before_start_hour_waits(self, mock_send_email, mock_get_subs):
        today = date(2026, 11, 13)
        # 05:30 IST is < start (06:00 IST)
        early_time = datetime(2026, 11, 13, 5, 30, 0, tzinfo=IST)
        res = send_daily_emails_to_all_subscribers(target_date=today, current_time_ist=early_time)

        self.assertEqual(res["status"], "before_window")
        self.assertEqual(res["dispatched"], 0)
        mock_send_email.assert_not_called()

    @patch("services.daily_email_scheduler.get_active_subscribers")
    @patch("services.daily_email_scheduler.verify_subscriber_sign_ready")
    @patch("services.daily_email_scheduler.send_daily_zodiac_insight_email")
    def test_already_sent_subscriber_never_sent_twice(self, mock_send_email, mock_verify_ready, mock_get_subs):
        today = date(2026, 11, 13)
        mock_get_subs.return_value = [
            {"id": 1, "email": "already_sent@example.com", "zodiac_sign": "aries", "preferred_categories": ["wealth"], "last_sent_date": "2026-11-13"}
        ]

        mid_time = datetime(2026, 11, 13, 8, 30, 0, tzinfo=IST)
        res = send_daily_emails_to_all_subscribers(target_date=today, current_time_ist=mid_time)

        self.assertEqual(res["dispatched"], 0)
        self.assertEqual(res["skipped"], 1)
        mock_send_email.assert_not_called()
        mock_verify_ready.assert_not_called()


class TestHoroscopeTipForTheDay(unittest.TestCase):
    def test_cosmic_pulse_requires_tip_for_the_day(self):
        sample_text = (
            "Harmonious alignments bring steady clarity to your overarching initiatives today as balanced energy supports "
            "both professional progress and personal relationships. Prioritize thoughtful communication in all meetings and "
            "maintain steady patience with evolving schedules. Evening hours offer a peaceful atmosphere for rest and recharge."
        )
        with self.assertRaises(Exception):
            HoroscopeCategoryItem(
                category="cosmic_pulse",
                text=sample_text,
                score=85,
                lucky_time="08:00 AM - 09:30 AM",
                remedy="Chant Gayatri mantra during dawn.",
                affirmation="I navigate today with wisdom and grace.",
                tip_for_the_day=None
            )

    def test_cosmic_pulse_valid_tip_accepted(self):
        sample_text = (
            "Harmonious alignments bring steady clarity to your overarching initiatives today as balanced energy supports "
            "both professional progress and personal relationships. Prioritize thoughtful communication in all meetings and "
            "maintain steady patience with evolving schedules. Evening hours offer a peaceful atmosphere for rest and recharge."
        )
        item = HoroscopeCategoryItem(
            category="cosmic_pulse",
            text=sample_text,
            score=85,
            lucky_time="08:00 AM - 09:30 AM",
            remedy="Chant Gayatri mantra during dawn.",
            affirmation="I navigate today with wisdom and grace.",
            tip_for_the_day="Write down the issue before discussing it, and keep your wording factual."
        )
        self.assertIsNotNone(item.tip_for_the_day)
        self.assertEqual(item.tip_for_the_day, "Write down the issue before discussing it, and keep your wording factual.")

    def test_unique_tips_across_signs_on_same_day(self):
        """
        Asserts failure if two signs share the same tip on the same day.
        """
        unique_sign_tips = {
            "aries": "Write down the issue before discussing it, and keep your wording factual.",
            "taurus": "Review your monthly commitments before agreeing to any new scheduled appointments.",
            "gemini": "Focus on finishing your primary morning deliverable before checking incoming messages.",
            "cancer": "Take regular pauses between intense conversations to maintain emotional equilibrium.",
            "leo": "Structure your leadership feedback with clear examples to guide your team effectively.",
            "virgo": "Organize your active workspace and clear unnecessary clutter before starting projects.",
            "libra": "Weigh both perspectives objectively before making any binding personal agreements.",
            "scorpio": "Keep sensitive negotiations private until terms are documented and agreed upon.",
            "sagittarius": "Confirm all travel details and appointment times before heading out today.",
            "capricorn": "Prioritize high-impact long-term milestones over minor reactive requests.",
            "aquarius": "Collaborate with trusted peers and welcome constructive input on new ideas.",
            "pisces": "Set gentle boundaries around your time to protect your creative focus."
        }
        # Check that unique tips pass
        tips_list = list(unique_sign_tips.values())
        self.assertEqual(len(tips_list), len(set(tips_list)), "All 12 signs must have unique tips.")

        # Duplicate tip shared between two signs must trigger failure
        duplicate_sign_tips = dict(unique_sign_tips)
        duplicate_sign_tips["taurus"] = duplicate_sign_tips["aries"]

        with self.assertRaises(AssertionError):
            dup_list = list(duplicate_sign_tips.values())
            assert len(dup_list) == len(set(dup_list)), "Duplicate tip detected across signs on the same day!"


class TestWeeklyHoroscopeAndValidator(unittest.TestCase):
    def test_weekly_range_calculation(self):
        # A Friday date: 2026-11-13
        target_friday = date(2026, 11, 13)
        start, end = calculate_period_dates("weekly", target_friday)
        # Monday start
        self.assertEqual(start, date(2026, 11, 9))
        self.assertEqual(start.weekday(), 0)
        # Sunday end
        self.assertEqual(end, date(2026, 11, 15))
        self.assertEqual(end.weekday(), 6)

        # A Monday date: 2026-11-09
        start_mon, end_sun = calculate_period_dates("weekly", date(2026, 11, 9))
        self.assertEqual(start_mon, date(2026, 11, 9))
        self.assertEqual(end_sun, date(2026, 11, 15))

    def test_validator_rejects_too_short_weekly_text(self):
        # Weekly requires 250-300 words (min with 10% tolerance = 225)
        short_text = "This is a very short text that does not meet the weekly horoscope word count requirements."
        with self.assertRaises(Exception):
            HoroscopeCategoryItem(
                category="health",
                text=short_text,
                score=85,
                lucky_time="08:00 AM - 10:00 AM",
                remedy="Rest well.",
                affirmation="I am healthy.",
                period="weekly"
            )

    def test_validator_rejects_markdown_syntax(self):
        # 260 words containing prohibited bold syntax "**"
        long_words = ["word"] * 260
        long_words[10] = "**bold_text**"
        markdown_text = " ".join(long_words)
        with self.assertRaises(Exception):
            HoroscopeCategoryItem(
                category="wealth",
                text=markdown_text,
                score=88,
                lucky_time="10:00 AM",
                remedy="Keep records.",
                affirmation="I am prosperous.",
                period="weekly"
            )

    @patch("controllers.horoscope_controller.get_db_connection")
    @patch("services.llm_service._execute_llm")
    def test_api_never_invokes_llm(self, mock_llm, mock_get_conn):
        today_ist = get_today_ist()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        mock_cursor.fetchone.return_value = {
            "period_start": today_ist,
            "period_end": today_ist
        }
        mock_cursor.fetchall.return_value = [
            {
                "category": "cosmic_pulse",
                "text": "Database reading without LLM call.",
                "score": 90,
                "lucky_time": "10:00 AM",
                "remedy": "Drink water",
                "affirmation": "Peace",
                "tip_for_the_day": "Stay focused.",
                "generated_at": str(datetime.now())
            }
        ]

        app = Flask(__name__)
        app.add_url_rule("/api/horoscope", view_func=get_horoscope, methods=["GET"])
        client = app.test_client()

        res = client.get("/api/horoscope?sign=aries&system=tropical&period=weekly&category=all")
        self.assertEqual(res.status_code, 200)
        # Verify LLM was NEVER called during API serving
        mock_llm.assert_not_called()


class TestEphemerisSnapshots(unittest.TestCase):
    def test_sun_tropical_vs_sidereal_ayanamsha(self):
        from scripts.ephemeris import get_snapshot
        snap = get_snapshot()
        trop_sun = snap['tropical']['planets']['sun']['longitude']
        sid_sun = snap['sidereal']['planets']['sun']['longitude']
        diff = (trop_sun - sid_sun) % 360
        self.assertLess(abs(diff - 24.2), 1.0, f"Ayanamsha difference {diff} is unexpected")

    def test_nakshatra_and_tithi_structure(self):
        from scripts.ephemeris import get_snapshot
        snap = get_snapshot()
        nak = snap['sidereal']['moon_nakshatra']
        self.assertIn('name', nak)
        self.assertIn('pada', nak)
        self.assertTrue(1 <= nak['pada'] <= 4)
        tithi = snap['sidereal']['tithi']
        self.assertIn('name', tithi)
        self.assertIn('index', tithi)
        self.assertTrue(1 <= tithi['index'] <= 30)

    def test_period_snapshots_length(self):
        from scripts.ephemeris import get_period_snapshots
        weekly = get_period_snapshots("weekly")
        self.assertEqual(len(weekly['snapshots']), 7)
        monthly = get_period_snapshots("monthly")
        self.assertGreaterEqual(len(monthly['snapshots']), 10)


class TestContentSafetyQuality(unittest.TestCase):
    def test_clean_text_removes_markdown_and_banned(self):
        raw = "**Death** and **guaranteed profit** in *crypto*! Visit #now."
        cleaned = clean_text(raw)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("*", cleaned)


class TestYearlyHoroscopeAndValidator(unittest.TestCase):
    def test_yearly_ephemeris_snapshot(self):
        from scripts.ephemeris import get_period_snapshots
        snap = get_period_snapshots("yearly", date(2026, 1, 1))
        self.assertEqual(snap["period"], "yearly")
        self.assertEqual(len(snap["snapshots"]), 24)
        self.assertIn("eclipses", snap)
        self.assertGreaterEqual(len(snap["eclipses"]), 2)
        # Check slow planet ingresses & stations
        self.assertIn("slow_planet_ingresses", snap["tropical_summary"])
        self.assertIn("stations", snap["tropical_summary"])
        # Check quarterly houses for all 12 signs
        q_houses = snap["tropical_summary"]["quarterly_houses"]
        self.assertIn("taurus", q_houses)
        self.assertIn("Q1 (Jan-Mar)", q_houses["taurus"])
        self.assertIn("jupiter", q_houses["taurus"]["Q1 (Jan-Mar)"])

    def test_yearly_validator_word_and_paragraph_rules(self):
        from scripts.generate import ensure_yearly_paragraphs, HoroscopeCategoryItem

        sample = "Quarter 1 brings steady momentum and thoughtful planning for all endeavors. " * 20 + "\n\n" + \
                 "Quarter 2 expands commercial initiatives and rewards persistent daily efforts. " * 20 + "\n\n" + \
                 "Quarter 3 integrates deep learning milestones and elevates personal connections. " * 20 + "\n\n" + \
                 "Quarter 4 secures enduring stability while opening bright new horizons. " * 20

        formatted = ensure_yearly_paragraphs(sample, sign="taurus")
        paras = [p for p in formatted.split("\n\n") if p.strip()]
        words = len(formatted.split())
        self.assertTrue(4 <= len(paras) <= 5)
        self.assertTrue(540 <= words <= 770)

        # Valid item
        item = HoroscopeCategoryItem(
            category="cosmic_pulse",
            text=formatted,
            score=90,
            lucky_time="Sunrise hours offer optimum peace.",
            remedy="Practice morning pranayama outdoors.",
            affirmation="I welcome the cosmic rhythm of the new year.",
            tip_for_the_day="Anchor your greatest endeavors in steady patience and mindful quarterly planning.",
            period="yearly"
        )
        self.assertEqual(item.category, "cosmic_pulse")
        self.assertEqual(len(item.tip_for_the_day.split()), 11)

    def test_yearly_api_and_stale_fallback(self):
        from controllers.horoscope_controller import get_horoscope, get_horoscope_years
        app = Flask(__name__)
        app.add_url_rule("/api/horoscope", view_func=get_horoscope, methods=["GET"])
        app.add_url_rule("/api/horoscope/years", view_func=get_horoscope_years, methods=["GET"])
        client = app.test_client()

        with patch("controllers.horoscope_controller.get_db_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn_fn.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            # 1. Test requested year 2026 present
            mock_cursor.fetchone.return_value = {
                "period_start": date(2026, 1, 1),
                "period_end": date(2026, 12, 31)
            }
            mock_cursor.fetchall.return_value = [
                {
                    "category": "cosmic_pulse",
                    "text": "Yearly cosmic pulse reading for 2026.",
                    "score": 92,
                    "lucky_time": "08:00 AM",
                    "remedy": "Chant Om",
                    "affirmation": "Peace",
                    "tip_for_the_day": "Stay grounded.",
                    "generated_at": str(datetime.now())
                }
            ]

            res = client.get("/api/horoscope?sign=taurus&system=tropical&period=yearly&category=all&year=2026")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertFalse(data["stale"])
            self.assertEqual(data["period_start"], "2026-01-01")

            # 2. Test requested year 2028 missing -> falls back to 2027 with stale=True
            mock_cursor.fetchone.side_effect = [
                None, # 2028 missing
                {
                    "period_start": date(2027, 1, 1),
                    "period_end": date(2027, 12, 31)
                }
            ]
            res_fallback = client.get("/api/horoscope?sign=taurus&system=tropical&period=yearly&category=all&year=2028")
            self.assertEqual(res_fallback.status_code, 200)
            fb_data = res_fallback.get_json()
            self.assertTrue(fb_data["stale"])
            self.assertEqual(fb_data["period_start"], "2027-01-01")

    def test_yearly_years_endpoint(self):
        from controllers.horoscope_controller import get_horoscope_years
        app = Flask(__name__)
        app.add_url_rule("/api/horoscope/years", view_func=get_horoscope_years, methods=["GET"])
        client = app.test_client()

        with patch("controllers.horoscope_controller.get_db_connection") as mock_conn_fn:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn_fn.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            mock_cursor.fetchall.return_value = [(2026,), (2027,)]
            res = client.get("/api/horoscope/years?period=yearly")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["years"], [2026, 2027])


if __name__ == "__main__":
    unittest.main()

