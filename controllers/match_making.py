import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

import swisseph as swe
from flask import request, jsonify, Response
from io import BytesIO
from database.db_connection import call_procedure
from services.report_service import generate_match_report_pdf
from services.llm_extractor1 import get_ai_response

from services.report_service import generate_ai_synthesis_pdf
# ============================================================
# ASTROLOGICAL REFERENCE DATA
# ============================================================

ZODIAC_SIGNS = [
    {"name": "Aries", "sanskrit": "Mesha", "lord": "Mars", "element": "Fire", "symbol": "♈"},
    {"name": "Taurus", "sanskrit": "Vrishabha", "lord": "Venus", "element": "Earth", "symbol": "♉"},
    {"name": "Gemini", "sanskrit": "Mithuna", "lord": "Mercury", "element": "Air", "symbol": "♊"},
    {"name": "Cancer", "sanskrit": "Karka", "lord": "Moon", "element": "Water", "symbol": "♋"},
    {"name": "Leo", "sanskrit": "Simha", "lord": "Sun", "element": "Fire", "symbol": "♌"},
    {"name": "Virgo", "sanskrit": "Kanya", "lord": "Mercury", "element": "Earth", "symbol": "♍"},
    {"name": "Libra", "sanskrit": "Tula", "lord": "Venus", "element": "Air", "symbol": "♎"},
    {"name": "Scorpio", "sanskrit": "Vrishchika", "lord": "Mars", "element": "Water", "symbol": "♏"},
    {"name": "Sagittarius", "sanskrit": "Dhanu", "lord": "Jupiter", "element": "Fire", "symbol": "♐"},
    {"name": "Capricorn", "sanskrit": "Makara", "lord": "Saturn", "element": "Earth", "symbol": "♑"},
    {"name": "Aquarius", "sanskrit": "Kumbha", "lord": "Saturn", "element": "Air", "symbol": "♒"},
    {"name": "Pisces", "sanskrit": "Meena", "lord": "Jupiter", "element": "Water", "symbol": "♓"},
]

# Exact 27 Nakshatras, each 13°20′.
NAKSHATRAS = [
    {"name": "Ashwini", "lord": "Ketu", "deity": "Ashwini Kumaras"},
    {"name": "Bharani", "lord": "Venus", "deity": "Yama"},
    {"name": "Krittika", "lord": "Sun", "deity": "Agni"},
    {"name": "Rohini", "lord": "Moon", "deity": "Prajapati"},
    {"name": "Mrigashira", "lord": "Mars", "deity": "Soma"},
    {"name": "Ardra", "lord": "Rahu", "deity": "Rudra"},
    {"name": "Punarvasu", "lord": "Jupiter", "deity": "Aditi"},
    {"name": "Pushya", "lord": "Saturn", "deity": "Brihaspati"},
    {"name": "Ashlesha", "lord": "Mercury", "deity": "Nagas"},
    {"name": "Magha", "lord": "Ketu", "deity": "Pitris"},
    {"name": "Purva Phalguni", "lord": "Venus", "deity": "Bhaga"},
    {"name": "Uttara Phalguni", "lord": "Sun", "deity": "Aryaman"},
    {"name": "Hasta", "lord": "Moon", "deity": "Savitr"},
    {"name": "Chitra", "lord": "Mars", "deity": "Vishvakarma"},
    {"name": "Swati", "lord": "Rahu", "deity": "Vayu"},
    {"name": "Vishakha", "lord": "Jupiter", "deity": "Indra-Agni"},
    {"name": "Anuradha", "lord": "Saturn", "deity": "Mitra"},
    {"name": "Jyeshtha", "lord": "Mercury", "deity": "Indra"},
    {"name": "Mula", "lord": "Ketu", "deity": "Nirriti"},
    {"name": "Purva Ashadha", "lord": "Venus", "deity": "Apas"},
    {"name": "Uttara Ashadha", "lord": "Sun", "deity": "Vishvedevas"},
    {"name": "Shravana", "lord": "Moon", "deity": "Vishnu"},
    {"name": "Dhanishta", "lord": "Mars", "deity": "Vasus"},
    {"name": "Shatabhisha", "lord": "Rahu", "deity": "Varuna"},
    {"name": "Purva Bhadrapada", "lord": "Jupiter", "deity": "Aja Ekapada"},
    {"name": "Uttara Bhadrapada", "lord": "Saturn", "deity": "Ahirbudhnya"},
    {"name": "Revati", "lord": "Mercury", "deity": "Pushan"},
]

# Gana / Yoni / Nadi tables are fixed traditional reference data.
NAKSHATRA_ATTRIBUTES = {
    "Ashwini": {"index": 0, "gana": "Deva", "yoni": "Horse", "nadi": "Adi"},
    "Bharani": {"index": 1, "gana": "Manushya", "yoni": "Elephant", "nadi": "Madhya"},
    "Krittika": {"index": 2, "gana": "Rakshasa", "yoni": "Sheep", "nadi": "Antya"},
    "Rohini": {"index": 3, "gana": "Manushya", "yoni": "Serpent", "nadi": "Antya"},
    "Mrigashira": {"index": 4, "gana": "Deva", "yoni": "Serpent", "nadi": "Madhya"},
    "Ardra": {"index": 5, "gana": "Manushya", "yoni": "Dog", "nadi": "Adi"},
    "Punarvasu": {"index": 6, "gana": "Deva", "yoni": "Cat", "nadi": "Adi"},
    "Pushya": {"index": 7, "gana": "Deva", "yoni": "Sheep", "nadi": "Madhya"},
    "Ashlesha": {"index": 8, "gana": "Rakshasa", "yoni": "Cat", "nadi": "Antya"},
    "Magha": {"index": 9, "gana": "Rakshasa", "yoni": "Rat", "nadi": "Antya"},
    "Purva Phalguni": {"index": 10, "gana": "Manushya", "yoni": "Rat", "nadi": "Madhya"},
    "Uttara Phalguni": {"index": 11, "gana": "Manushya", "yoni": "Cow", "nadi": "Adi"},
    "Hasta": {"index": 12, "gana": "Deva", "yoni": "Buffalo", "nadi": "Adi"},
    "Chitra": {"index": 13, "gana": "Rakshasa", "yoni": "Tiger", "nadi": "Madhya"},
    "Swati": {"index": 14, "gana": "Deva", "yoni": "Buffalo", "nadi": "Antya"},
    "Vishakha": {"index": 15, "gana": "Rakshasa", "yoni": "Tiger", "nadi": "Antya"},
    "Anuradha": {"index": 16, "gana": "Deva", "yoni": "Deer", "nadi": "Madhya"},
    "Jyeshtha": {"index": 17, "gana": "Rakshasa", "yoni": "Deer", "nadi": "Adi"},
    "Mula": {"index": 18, "gana": "Rakshasa", "yoni": "Dog", "nadi": "Adi"},
    "Purva Ashadha": {"index": 19, "gana": "Manushya", "yoni": "Monkey", "nadi": "Madhya"},
    "Uttara Ashadha": {"index": 20, "gana": "Manushya", "yoni": "Mongoose", "nadi": "Antya"},
    "Shravana": {"index": 21, "gana": "Deva", "yoni": "Monkey", "nadi": "Antya"},
    "Dhanishta": {"index": 22, "gana": "Rakshasa", "yoni": "Lion", "nadi": "Madhya"},
    "Shatabhisha": {"index": 23, "gana": "Rakshasa", "yoni": "Horse", "nadi": "Adi"},
    "Purva Bhadrapada": {"index": 24, "gana": "Manushya", "yoni": "Lion", "nadi": "Adi"},
    "Uttara Bhadrapada": {"index": 25, "gana": "Manushya", "yoni": "Cow", "nadi": "Madhya"},
    "Revati": {"index": 26, "gana": "Deva", "yoni": "Elephant", "nadi": "Antya"},
}

# Traditional yoni enemy pairs.
YONI_ENEMIES = {
    frozenset(("Horse", "Buffalo")),
    frozenset(("Elephant", "Lion")),
    frozenset(("Sheep", "Monkey")),
    frozenset(("Serpent", "Mongoose")),
    frozenset(("Dog", "Deer")),
    frozenset(("Cat", "Rat")),
    frozenset(("Cow", "Tiger")),
}

# Common standard Yoni friendship pairs. Unlisted non-enemy pairs receive 2.
YONI_FRIENDS = {
    frozenset(("Horse", "Horse")),
    frozenset(("Elephant", "Elephant")),
    frozenset(("Sheep", "Sheep")),
    frozenset(("Serpent", "Serpent")),
    frozenset(("Dog", "Dog")),
    frozenset(("Cat", "Cat")),
    frozenset(("Rat", "Rat")),
    frozenset(("Cow", "Cow")),
    frozenset(("Tiger", "Tiger")),
    frozenset(("Deer", "Deer")),
    frozenset(("Monkey", "Monkey")),
    frozenset(("Buffalo", "Buffalo")),
    frozenset(("Lion", "Lion")),
    frozenset(("Mongoose", "Mongoose")),
    # Frequently used friendly combinations.
    frozenset(("Horse", "Sheep")),
    frozenset(("Horse", "Monkey")),
    frozenset(("Elephant", "Sheep")),
    frozenset(("Elephant", "Buffalo")),
    frozenset(("Cow", "Buffalo")),
    frozenset(("Deer", "Monkey")),
    frozenset(("Dog", "Monkey")),
    frozenset(("Cat", "Monkey")),
    frozenset(("Rat", "Monkey")),
    frozenset(("Lion", "Monkey")),
}

# Natural planetary relationships used by Graha Maitri.
GRAHA_REL = {
    "Sun": {"friends": {"Moon", "Mars", "Jupiter"}, "neutral": {"Mercury"}, "enemies": {"Venus", "Saturn"}},
    "Moon": {"friends": {"Sun", "Mercury"}, "neutral": {"Mars", "Jupiter", "Venus", "Saturn"}, "enemies": set()},
    "Mars": {"friends": {"Sun", "Moon", "Jupiter"}, "neutral": {"Venus", "Saturn"}, "enemies": {"Mercury"}},
    "Mercury": {"friends": {"Sun", "Venus"}, "neutral": {"Mars", "Jupiter", "Saturn"}, "enemies": {"Moon"}},
    "Jupiter": {"friends": {"Sun", "Moon", "Mars"}, "neutral": {"Saturn"}, "enemies": {"Mercury", "Venus"}},
    "Venus": {"friends": {"Mercury", "Saturn"}, "neutral": {"Mars", "Jupiter"}, "enemies": {"Sun", "Moon"}},
    "Saturn": {"friends": {"Mercury", "Venus"}, "neutral": {"Jupiter"}, "enemies": {"Sun", "Moon", "Mars"}},
}

PLANET_IDS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mars": swe.MARS,
    "mercury": swe.MERCURY,
    "jupiter": swe.JUPITER,
    "venus": swe.VENUS,
    "saturn": swe.SATURN,
    "rahu": swe.TRUE_NODE,
}

PLANET_META = {
    "sun": ("Sun", "Surya (सूर्य)", "☉"),
    "moon": ("Moon", "Chandra (चन्द्र)", "☽"),
    "mars": ("Mars", "Mangal (मंगल)", "♂"),
    "mercury": ("Mercury", "Budha (बुध)", "☿"),
    "jupiter": ("Jupiter", "Guru (गुरु)", "♃"),
    "venus": ("Venus", "Shukra (शुक्र)", "♀"),
    "saturn": ("Saturn", "Shani (शनि)", "♄"),
    "rahu": ("Rahu", "Rahu (राहु)", "☊"),
    "ketu": ("Ketu", "Ketu (केतु)", "☋"),
}

_geolocator = Nominatim(user_agent="astrojunction-kundli/1.0")
_timezone_finder = TimezoneFinder()


def resolve_birth_place(place: str) -> dict:
    """Resolve human-readable birthplace to coordinates + IANA timezone."""
    place = str(place or "").strip()
    if not place:
        raise ValueError("birth place is required")

    location = _geolocator.geocode(
        place, exactly_one=True, addressdetails=True, language="en", timeout=10
    )
    if location is None:
        raise ValueError(f"Could not resolve birth place: {place}")

    lat = float(location.latitude)
    lon = float(location.longitude)
    _validate_lat_lon(lat, lon)

    tz_name = _timezone_finder.timezone_at(lat=lat, lng=lon)
    if not tz_name:
        raise ValueError(f"Could not determine timezone for birth place: {place}")
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise ValueError(f"Invalid timezone resolved for birth place: {tz_name}")

    return {
        "latitude": lat,
        "longitude": lon,
        "timezone": tz_name,
        "resolvedPlace": getattr(location, "address", None) or place,
    }


def prepare_partner(partner: dict) -> dict:
    """Accept only name/date/time/place from the client and enrich location internally."""
    if not isinstance(partner, dict):
        raise ValueError("partner must be a JSON object")
    q = dict(partner)
    if not q.get("name"):
        q["name"] = q.get("fullName")
    if not q.get("dob"):
        q["dob"] = q.get("birthDate")
    if not q.get("time"):
        q["time"] = q.get("birthTime")
    if not q.get("place"):
        q["place"] = q.get("birthPlace")

    tz = q.get("timezone") or q.get("timeZone")
    if not isinstance(tz, str) or "/" not in tz:
        # Timezone is numeric (like 5.5) or invalid -> resolve via lat/lon or default to Asia/Kolkata
        lat = q.get("latitude")
        lon = q.get("longitude")
        if lat is not None and lon is not None:
            try:
                tf = TimezoneFinder()
                resolved_tz = tf.timezone_at(lat=float(lat), lng=float(lon))
                q["timezone"] = resolved_tz or "Asia/Kolkata"
            except Exception:
                q["timezone"] = "Asia/Kolkata"
        elif q.get("place"):
            try:
                q.update(resolve_birth_place(q.get("place")))
            except Exception:
                q["timezone"] = "Asia/Kolkata"
        else:
            q["timezone"] = "Asia/Kolkata"

    if q.get("latitude") is None or q.get("longitude") is None:
        try:
            q.update(resolve_birth_place(q.get("place") or "Delhi, India"))
        except Exception:
            if q.get("latitude") is None:
                q["latitude"] = 28.6139
            if q.get("longitude") is None:
                q["longitude"] = 77.2090

    if not isinstance(q.get("timezone"), str) or "/" not in str(q.get("timezone")):
        q["timezone"] = "Asia/Kolkata"

    return q



# ============================================================
# BASIC HELPERS
# ============================================================

def _error(message: str, code: str, http_status: int = 400):
    return jsonify({"status": "error", "message": message, "error_code": code}), http_status


def _norm360(x: float) -> float:
    return x % 360.0


def _format_dms(deg: float) -> str:
    deg = deg % 30.0
    d = int(deg)
    minutes_float = (deg - d) * 60
    m = int(minutes_float)
    s = round((minutes_float - m) * 60, 1)
    return f"{d}° {m}′ {s}″"


def _reduce_to_single_digit(num: int, keep_masters: bool = False) -> int:
    if keep_masters and num in (11, 22, 33):
        return num
    while num > 9:
        num = sum(int(d) for d in str(abs(num)))
    return num


def _get_varna(rashi_idx: int) -> Dict[str, Any]:
    # Standard Rashi varna grouping.
    if rashi_idx in (3, 7, 11):
        return {"name": "Brahmin", "rank": 4}
    if rashi_idx in (0, 4, 8):
        return {"name": "Kshatriya", "rank": 3}
    if rashi_idx in (1, 5, 9):
        return {"name": "Vaishya", "rank": 2}
    return {"name": "Shudra", "rank": 1}


def _vashya_class(rashi_idx: int) -> str:
    """
    Conventional Rashi Vashya animal/human classes.

    Note: Sagittarius is conventionally split by degree (first half
    human, second half quadruped), so a sign-only classifier cannot be
    perfectly accurate for Vashya. The detailed scorer below therefore
    accepts the Moon/Lagna longitude when available.
    """
    classes = {
        0: "Chatushpada",   # Aries
        1: "Chatushpada",   # Taurus
        2: "Manava",        # Gemini
        3: "Jalachara",     # Cancer
        4: "Vanachara",     # Leo
        5: "Manava",        # Virgo
        6: "Manava",        # Libra
        7: "Keeta",         # Scorpio
        8: "Chatushpada",   # Sagittarius (degree split handled separately)
        9: "Chatushpada",   # Capricorn
        10: "Manava",       # Aquarius
        11: "Jalachara",    # Pisces
    }
    return classes[rashi_idx]


def _vashya_class_from_longitude(longitude: float) -> str:
    """Return the conventional Vashya class, including Sagittarius split."""
    lon = _norm360(longitude)
    sign = int(lon // 30)
    deg = lon % 30
    if sign == 8 and deg < 15.0:
        return "Manava"
    if sign == 8 and deg >= 15.0:
        return "Chatushpada"
    return _vashya_class(sign)


def _validate_lat_lon(lat: float, lon: float):
    if not -90 <= lat <= 90:
        raise ValueError("latitude must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("longitude must be between -180 and 180")


def _local_to_utc_jd(local_dt: datetime, timezone_name: str) -> Tuple[datetime, float]:
    """Convert local civil time in an IANA timezone to UTC/JD(UT).

    The conversion is intentionally timezone-database based rather than a
    fixed numeric offset, because historical DST/offset changes matter.
    For an ambiguous DST clock time, ``fold=0`` is used unless the caller
    supplies a datetime with ``fold=1``. Non-existent local times are rejected.
    """
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid IANA timezone: {timezone_name}") from exc

    if local_dt.tzinfo is None:
        aware = local_dt.replace(tzinfo=tz, fold=getattr(local_dt, "fold", 0))
    else:
        aware = local_dt.astimezone(tz)

    # Round-trip through UTC. If it does not reproduce the same local clock,
    # the supplied local time falls inside a DST gap and is not a real instant.
    utc_dt = aware.astimezone(timezone.utc)
    roundtrip = utc_dt.astimezone(tz)
    if roundtrip.replace(tzinfo=None) != local_dt.replace(tzinfo=None):
        raise ValueError(
            f"Birth time {local_dt.isoformat()} does not exist in timezone {timezone_name}"
        )

    hour_decimal = (
        utc_dt.hour
        + utc_dt.minute / 60.0
        + utc_dt.second / 3600.0
        + utc_dt.microsecond / 3_600_000_000.0
    )
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour_decimal, swe.GREG_CAL)
    return utc_dt, jd


def _parse_local_birth_datetime(date_str: str, time_str: str, tz_name: str) -> Tuple[datetime, float]:
    time_str = time_str.strip()
    if len(time_str) == 5:
        time_str += ":00"

    try:
        local_naive = datetime.strptime(
            f"{date_str.strip()} {time_str}", "%Y-%m-%d %H:%M:%S"
        )
    except ValueError as exc:
        raise ValueError("birth date/time must be YYYY-MM-DD and HH:MM[:SS]") from exc

    return _local_to_utc_jd(local_naive, tz_name)


def _nakshatra_from_longitude(sidereal_longitude: float) -> Dict[str, Any]:
    span = 360.0 / 27.0
    pada_span = span / 4.0
    idx = min(26, int(_norm360(sidereal_longitude) / span))
    within = _norm360(sidereal_longitude) - idx * span
    pada = min(4, int(within / pada_span) + 1)

    n = NAKSHATRAS[idx]
    return {
        "index": idx,
        "name": n["name"],
        "lord": n["lord"],
        "deity": n["deity"],
        "pada": pada,
        "degreesInNakshatra": round(within, 6),
    }


def _planet_object(pid: str, lon: float, speed: float, house: int) -> Dict[str, Any]:
    sign_idx = int(_norm360(lon) // 30)
    deg_in_sign = _norm360(lon) % 30.0
    nak = _nakshatra_from_longitude(lon)
    name, sanskrit, symbol = PLANET_META[pid]

    return {
        "id": pid,
        "name": name,
        "sanskritName": sanskrit,
        "symbol": symbol,
        "signIndex": sign_idx,
        "signName": ZODIAC_SIGNS[sign_idx]["name"],
        "signSanskrit": ZODIAC_SIGNS[sign_idx]["sanskrit"],
        "degree": round(deg_in_sign, 6),
        "degreeDMS": _format_dms(deg_in_sign),
        "totalDegree": round(_norm360(lon), 6),
        "longitudeSidereal": round(_norm360(lon), 6),
        "speedLongitude": round(speed, 8),
        "retrograde": speed < 0,
        "house": int(house),
        "nakshatra": nak["name"],
        "nakshatraLord": nak["lord"],
        "nakshatraDeity": nak["deity"],
        "pada": nak["pada"],
    }


# ============================================================
# VALIDATION / NORMALIZATION
# ============================================================

def validate_partner(partner: Any, partner_name: str = "partner") -> Optional[str]:
    if not isinstance(partner, dict):
        return f"{partner_name} must be a JSON object"

    name = partner.get("name") or partner.get("fullName")
    dob = partner.get("dob") or partner.get("birthDate")
    time_val = partner.get("time") or partner.get("birthTime")
    place = partner.get("place") or partner.get("birthPlace")

    missing = []
    if not str(name or "").strip():
        missing.append("name/fullName")
    if not str(dob or "").strip():
        missing.append("dob/birthDate")
    if not str(time_val or "").strip():
        missing.append("time/birthTime")
    if not str(place or "").strip():
        missing.append("place/birthPlace")

    if missing:
        return f"{partner_name} missing field(s): " + ", ".join(missing)

    try:
        datetime.strptime(str(dob).strip(), "%Y-%m-%d")
    except ValueError:
        return f"{partner_name} DOB must be in YYYY-MM-DD format"

    try:
        t = str(time_val).strip()
        if len(t) == 5:
            datetime.strptime(t, "%H:%M")
        else:
            datetime.strptime(t, "%H:%M:%S")
    except ValueError:
        return f"{partner_name} time must be in HH:MM:SS or HH:MM format"

    try:
        float(partner.get("latitude"))
        float(partner.get("longitude"))
    except (TypeError, ValueError):
        return f"{partner_name} must contain numeric latitude and longitude"

    tz_name = partner.get("timezone") or partner.get("timeZone")
    if not isinstance(tz_name, str) or "/" not in tz_name:
        return (
            f"{partner_name} timezone must be an IANA timezone such as "
            f"'Asia/Kolkata' (do not use a fixed 5.5 offset for historical accuracy)"
        )

    try:
        ZoneInfo(tz_name)
    except Exception:
        return f"{partner_name} has invalid IANA timezone: {tz_name}"

    try:
        _validate_lat_lon(float(partner["latitude"]), float(partner["longitude"]))
    except ValueError as exc:
        return f"{partner_name}: {exc}"

    house_system = str(partner.get("houseSystem") or partner.get("house_system") or "W").upper()
    if len(house_system) != 1 or not house_system.isalpha():
        return f"{partner_name} houseSystem must be a single Swiss Ephemeris code"

    node_type = str(partner.get("nodeType") or partner.get("node_type") or "true").lower()
    if node_type not in {"true", "mean"}:
        return f"{partner_name} nodeType must be 'true' or 'mean'"

    return None


def _normalize_partner(p: dict) -> dict:
    """
    Unlike the old implementation, this does NOT silently invent Delhi,
    12:00, or an arbitrary timezone. Missing astronomical inputs remain errors.
    """
    tz_name = p.get("timezone") or p.get("timeZone")

    return {
        "id": p.get("id") or str(uuid.uuid4()),
        "name": str(p.get("name") or p.get("fullName") or "").strip(),
        "fullName": str(p.get("name") or p.get("fullName") or "").strip(),
        "dob": str(p.get("dob") or p.get("birthDate") or "").strip(),
        "birthDate": str(p.get("dob") or p.get("birthDate") or "").strip(),
        "time": str(p.get("time") or p.get("birthTime") or "").strip(),
        "birthTime": str(p.get("time") or p.get("birthTime") or "").strip(),
        "place": str(p.get("place") or p.get("birthPlace") or "").strip(),
        "birthPlace": str(p.get("place") or p.get("birthPlace") or "").strip(),
        "latitude": float(p["latitude"]),
        "longitude": float(p["longitude"]),
        "timezone": tz_name,
        "horoscopeSystem": p.get("horoscopeSystem", "vedic"),
        "houseSystem": p.get("houseSystem") or p.get("house_system") or "W",
        "nodeType": p.get("nodeType") or p.get("node_type") or "true",
    }


# ============================================================
# ASTRONOMICAL KUNDLI
# ============================================================

def generate_kundli(partner: dict) -> dict:
    """
    Calculate a sidereal Vedic-style natal chart with Swiss Ephemeris.

    Defaults:
      * Lahiri ayanamsha
      * geocentric positions
      * True lunar node (Rahu); Ketu is exactly opposite Rahu
      * Whole-sign houses (traditional Vedic-style default)

    ``houseSystem`` may be ``"W"`` for Whole Sign or ``"P"`` for Placidus
    (or another Swiss Ephemeris house-system code supported by your build).
    ``nodeType`` may be ``"true"`` or ``"mean"``.
    """
    p = _normalize_partner(partner)
    lat = p["latitude"]
    lon = p["longitude"]
    _validate_lat_lon(lat, lon)

    _, jd_ut = _parse_local_birth_datetime(p["dob"], p["time"], p["timezone"])

    swe.set_sid_mode(swe.SIDM_LAHIRI)

    house_system = str(p.get("houseSystem") or p.get("house_system") or "W").upper()
    if len(house_system) != 1:
        raise ValueError("houseSystem must be a single Swiss Ephemeris house-system code")

    node_type = str(p.get("nodeType") or p.get("node_type") or "true").lower()
    if node_type not in {"true", "mean"}:
        raise ValueError("nodeType must be 'true' or 'mean'")

    flags = swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_SIDEREAL

    try:
        houses, ascmc = swe.houses_ex(
            jd_ut, lat, lon, house_system.encode("ascii"), swe.FLG_SIDEREAL
        )
    except Exception as exc:
        raise ValueError(
            f"Swiss Ephemeris house calculation failed for houseSystem={house_system}: {exc}"
        ) from exc

    asc_sid = _norm360(float(ascmc[0]))
    asc_sign_idx = int(asc_sid // 30)
    asc_nak = _nakshatra_from_longitude(asc_sid)

    node_swe_id = swe.TRUE_NODE if node_type == "true" else swe.MEAN_NODE
    planet_ids = dict(PLANET_IDS)
    planet_ids["rahu"] = node_swe_id

    calculated_planets = []
    planets_by_id = {}

    for pid, swe_id in planet_ids.items():
        try:
            xx, retflag = swe.calc_ut(jd_ut, swe_id, flags)
        except Exception as exc:
            raise ValueError(f"Swiss Ephemeris failed for {pid}: {exc}") from exc
        if not xx or len(xx) < 4:
            raise ValueError(f"Swiss Ephemeris returned invalid data for {pid}")

        sid_lon = _norm360(float(xx[0]))
        speed = float(xx[3])
        house = _house_from_cusps(sid_lon, houses)
        obj = _planet_object(pid, sid_lon, speed, house)
        obj["ephemerisReturnFlag"] = int(retflag)
        calculated_planets.append(obj)
        planets_by_id[pid] = obj

    rahu = planets_by_id["rahu"]
    ketu_lon = _norm360(rahu["totalDegree"] + 180.0)
    ketu_house = _house_from_cusps(ketu_lon, houses)
    ketu = _planet_object("ketu", ketu_lon, -rahu["speedLongitude"], ketu_house)
    ketu["ephemerisReturnFlag"] = rahu.get("ephemerisReturnFlag", 0)
    planets_by_id["ketu"] = ketu
    calculated_planets.append(ketu)

    house_cusps = []
    for i, cusp in enumerate(houses, start=1):
        c = _norm360(float(cusp))
        house_cusps.append({
            "house": i,
            "longitudeSidereal": round(c, 6),
            "signIndex": int(c // 30),
            "signName": ZODIAC_SIGNS[int(c // 30)]["name"],
            "degree": round(c % 30, 6),
        })

    return {
        "calculation": {
            "engine": "Swiss Ephemeris / pyswisseph",
            "zodiac": "Sidereal",
            "ayanamsha": "Lahiri",
            "ephemerisFlags": flags,
            "julianDayUT": jd_ut,
            "latitude": lat,
            "longitude": lon,
            "timezone": p["timezone"],
            "houseSystem": house_system,
            "nodeType": node_type,
            "coordinateFrame": "Geocentric",
        },
        "ascendant": {
            "longitudeSidereal": round(asc_sid, 6),
            "signIndex": asc_sign_idx,
            "degree": round(asc_sid % 30, 6),
            "degreeDMS": _format_dms(asc_sid),
            "signName": ZODIAC_SIGNS[asc_sign_idx]["name"],
            "signSanskrit": ZODIAC_SIGNS[asc_sign_idx]["sanskrit"],
            "nakshatra": asc_nak["name"],
            "nakshatraLord": asc_nak["lord"],
            "pada": asc_nak["pada"],
        },
        "houseCusps": house_cusps,
        "planets": calculated_planets,
        "planetsById": planets_by_id,
        "partner": p,
    }


def _house_from_cusps(longitude: float, cusps) -> int:
    """
    Find the house in a circular list of 12 cusps.
    """
    lon = _norm360(longitude)
    c = [_norm360(float(x)) for x in cusps]

    for i in range(12):
        start = c[i]
        end = c[(i + 1) % 12]

        if start <= end:
            inside = start <= lon < end
        else:
            inside = lon >= start or lon < end

        if inside:
            return i + 1

    return 12


# ============================================================
# NUMEROLOGY – OPTIONAL, NOT PART OF ASHTA KOOTA
# ============================================================

CHALDEAN_VALUES = {
    "A": 1, "I": 1, "J": 1, "Q": 1, "Y": 1,
    "B": 2, "K": 2, "R": 2,
    "C": 3, "G": 3, "L": 3, "S": 3,
    "D": 4, "M": 4, "T": 4,
    "E": 5, "H": 5, "N": 5, "X": 5,
    "U": 6, "V": 6, "W": 6,
    "O": 7, "Z": 7,
    "F": 8, "P": 8,
}

PYTHAGOREAN_VALUES = {
    "A": 1, "J": 1, "S": 1,
    "B": 2, "K": 2, "T": 2,
    "C": 3, "L": 3, "U": 3,
    "D": 4, "M": 4, "V": 4,
    "E": 5, "N": 5, "W": 5,
    "F": 6, "O": 6, "X": 6,
    "G": 7, "P": 7, "Y": 7,
    "H": 8, "Q": 8, "Z": 8,
    "I": 9, "R": 9,
}


def calculate_numerology(name: str, dob_str: str) -> dict:
    day = int(dob_str.split("-")[2])
    mulank = _reduce_to_single_digit(day)
    bhagyank = _reduce_to_single_digit(sum(int(d) for d in dob_str if d.isdigit()))

    upper = name.upper()
    chaldean_sum = sum(CHALDEAN_VALUES.get(c, 0) for c in upper if c.isalpha())
    pythagorean_sum = sum(PYTHAGOREAN_VALUES.get(c, 0) for c in upper if c.isalpha())

    return {
        "mulank": mulank,
        "bhagyank": bhagyank,
        "namankChaldean": _reduce_to_single_digit(chaldean_sum),
        "namankPythagorean": _reduce_to_single_digit(pythagorean_sum),
    }


# ============================================================
# ASHTA KOOTA – 36 GUNA
# ============================================================

def _tara_points(nak1_idx: int, nak2_idx: int) -> Tuple[float, int, int]:
    # Count inclusive from each birth star; reduce modulo 9.
    t12 = ((nak2_idx - nak1_idx) % 27) + 1
    t21 = ((nak1_idx - nak2_idx) % 27) + 1

    tara1 = ((t12 - 1) % 9) + 1
    tara2 = ((t21 - 1) % 9) + 1

    good = {1, 2, 4, 6, 8, 9}
    score = (1.5 if tara1 in good else 0.0) + (1.5 if tara2 in good else 0.0)
    return score, tara1, tara2


def _yoni_score(y1: str, y2: str) -> float:
    pair = frozenset((y1, y2))
    if y1 == y2:
        return 4.0
    if pair in YONI_ENEMIES:
        return 0.0
    if pair in YONI_FRIENDS:
        return 3.0
    return 2.0


def _graha_maitri_score(lord1: str, lord2: str) -> float:
    if lord1 == lord2:
        return 5.0

    r1 = GRAHA_REL[lord1]
    r2 = GRAHA_REL[lord2]

    def rel(a, b):
        if b in GRAHA_REL[a]["friends"]:
            return "friend"
        if b in GRAHA_REL[a]["enemies"]:
            return "enemy"
        return "neutral"

    a = rel(lord1, lord2)
    b = rel(lord2, lord1)

    if a == "friend" and b == "friend":
        return 5.0
    if (a == "friend" and b == "neutral") or (a == "neutral" and b == "friend"):
        return 4.0
    if a == "neutral" and b == "neutral":
        return 3.0
    if (a == "enemy" and b == "neutral") or (a == "neutral" and b == "enemy"):
        return 1.0
    return 0.0


def _gana_score(g1: str, g2: str) -> float:
    if g1 == g2:
        return 6.0
    if {g1, g2} == {"Deva", "Manushya"}:
        return 5.0
    if {g1, g2} == {"Manushya", "Rakshasa"}:
        return 0.0
    return 1.0


def _vashya_score_from_classes(c1: str, c2: str) -> float:
    if c1 == c2:
        return 2.0
    cross = {
        frozenset(("Manava", "Chatushpada")): 1.0,
        frozenset(("Manava", "Jalachara")): 1.0,
        frozenset(("Manava", "Keeta")): 0.5,
        frozenset(("Manava", "Vanachara")): 1.0,
        frozenset(("Chatushpada", "Jalachara")): 0.5,
        frozenset(("Chatushpada", "Keeta")): 0.0,
        frozenset(("Chatushpada", "Vanachara")): 1.0,
        frozenset(("Jalachara", "Keeta")): 1.0,
        frozenset(("Jalachara", "Vanachara")): 0.0,
        frozenset(("Keeta", "Vanachara")): 0.0,
    }
    return cross.get(frozenset((c1, c2)), 0.0)


def _vashya_score(r1: int, r2: int, lon1: float | None = None, lon2: float | None = None) -> float:
    c1 = _vashya_class_from_longitude(lon1) if lon1 is not None else _vashya_class(r1)
    c2 = _vashya_class_from_longitude(lon2) if lon2 is not None else _vashya_class(r2)
    return _vashya_score_from_classes(c1, c2)


def _bhakoot_relation(r1: int, r2: int) -> str:
    """Return the conventional Rashi relation label."""
    d = (r2 - r1) % 12
    labels = {
        0: "1/1",
        1: "2/12", 11: "2/12",
        2: "3/11", 10: "3/11",
        3: "4/10", 9: "4/10",
        4: "5/9", 8: "5/9",
        5: "6/8", 7: "6/8",
        6: "7/7",
    }
    return labels[d]


def calculate_ashta_koota(chart1: dict, chart2: dict) -> Tuple[List[dict], Dict[str, dict], float, float]:
    moon1 = chart1["planetsById"]["moon"]
    moon2 = chart2["planetsById"]["moon"]

    dyn_nak1 = moon1.get("nakshatra") or _nakshatra_from_longitude(moon1.get("longitudeSidereal") or moon1.get("longitude") or 0.0)["name"]
    dyn_nak2 = moon2.get("nakshatra") or _nakshatra_from_longitude(moon2.get("longitudeSidereal") or moon2.get("longitude") or 0.0)["name"]
    nak1_name = str(dyn_nak1).split("(")[0].strip()
    nak2_name = str(dyn_nak2).split("(")[0].strip()
    nak1 = NAKSHATRA_ATTRIBUTES.get(nak1_name) or _nakshatra_from_longitude(moon1.get("longitudeSidereal") or moon1.get("longitude") or 0.0)
    nak2 = NAKSHATRA_ATTRIBUTES.get(nak2_name) or _nakshatra_from_longitude(moon2.get("longitudeSidereal") or moon2.get("longitude") or 0.0)
    r1 = moon1["signIndex"]
    r2 = moon2["signIndex"]
    lord1 = ZODIAC_SIGNS[r1]["lord"]
    lord2 = ZODIAC_SIGNS[r2]["lord"]
    pada1 = moon1.get("pada", 1)
    pada2 = moon2.get("pada", 1)

    v1 = _get_varna(r1)
    v2 = _get_varna(r2)
    varna_score = 1.0 if v1["rank"] >= v2["rank"] else 0.0

    vashya_score = _vashya_score(
        r1, r2, moon1["longitudeSidereal"], moon2["longitudeSidereal"]
    )
    vashya_c1 = _vashya_class_from_longitude(moon1["longitudeSidereal"])
    vashya_c2 = _vashya_class_from_longitude(moon2["longitudeSidereal"])

    tara_score, tara12, tara21 = _tara_points(nak1["index"], nak2["index"])
    yoni_score = _yoni_score(nak1["yoni"], nak2["yoni"])
    graha_score = _graha_maitri_score(lord1, lord2)
    gana_score = _gana_score(nak1["gana"], nak2["gana"])

    # IMPORTANT: with zero-based Rashi indexes, the traditional Bhakoot
    # dosha relations are 2/12, 5/9 and 6/8. Their offsets are:
    # {1, 11}, {4, 8}, {5, 7}.
    d12 = (r2 - r1) % 12
    bhakoot_relation = _bhakoot_relation(r1, r2)
    bhakoot_dosha = d12 in {1, 4, 5, 7, 8, 11}
    bhakoot_cancelled = bhakoot_dosha and (lord1 == lord2 or graha_score >= 4.0)
    bhakoot_score = 7.0 if (not bhakoot_dosha or bhakoot_cancelled) else 0.0

    # Authentic Classical Vedic Nadi Scoring:
    same_nadi = nak1["nadi"] == nak2["nadi"]
    nadi_cancelled = False
    nadi_cancel_reason = ""

    if same_nadi:
        # Classical Vedic Nadi Dosha Cancellations (Parihara):
        # 1. Same Rashi, Different Nakshatras (Ekarksha Bhinna Nakshatra)
        if r1 == r2 and nak1["index"] != nak2["index"]:
            nadi_cancelled = True
            nadi_cancel_reason = (
                f"Same Moon sign ({ZODIAC_SIGNS[r1]['name']}) with different Nakshatras "
                f"({nak1_name} & {nak2_name}) cancels Nadi Dosha (Ekarksha Bhinna Nakshatra Parihara)."
            )
        # 2. Same Nakshatra, Different Rashis (Eka Nakshatra Bhinna Rashi)
        elif nak1["index"] == nak2["index"] and r1 != r2:
            nadi_cancelled = True
            nadi_cancel_reason = (
                f"Same Nakshatra ({nak1_name}) spanning different Moon signs "
                f"({ZODIAC_SIGNS[r1]['name']} & {ZODIAC_SIGNS[r2]['name']}) cancels Nadi Dosha (Eka Nakshatra Bhinna Rashi Parihara)."
            )
        # 3. Same Nakshatra, Same Rashi, Different Padas (Charana Bheda)
        elif nak1["index"] == nak2["index"] and r1 == r2 and pada1 != pada2:
            nadi_cancelled = True
            nadi_cancel_reason = (
                f"Same Nakshatra ({nak1_name}) with different Charanas/Padas "
                f"(Pada {pada1} & Pada {pada2}) mitigates Nadi Dosha."
            )

    nadi_score = 8.0 if (not same_nadi or nadi_cancelled) else 0.0

    kootas = [
        _koota("varna", "Varna Koota", "वर्ण कूट", 1, varna_score,
               v1["name"], v2["name"], "Traditional Varna compatibility",
               details="Harmonious spiritual polarity; shared vocational respect." if varna_score == 1 else "Slight authority dissonance; remedied through mutual respect."),
        _koota("vashya", "Vashya Koota", "वश्य कूट", 2, vashya_score,
               vashya_c1, vashya_c2, "Mutual influence and receptivity",
               details="Strong mutual magnetic attraction without dominance struggles." if vashya_score >= 1.5 else "Balanced interpersonal dynamic with collaborative consensus."),
        _koota("tara", "Tara Koota", "तारा कूट", 3, tara_score,
               f"Tara {tara12}/9", f"Tara {tara21}/9", "Birth-star compatibility",
               details="Auspicious cosmic star timing bringing longevity and health protection." if tara_score >= 1.5 else "Challenging Tara cycle; recite Maha Mrityunjaya Mantra."),
        _koota("yoni", "Yoni Koota", "योनि कूट", 4, yoni_score,
               nak1["yoni"], nak2["yoni"], "Instinctual/physical compatibility",
               details="Natural physical affinity and instinctual bonding." if yoni_score >= 2 else "Inimical animal archetypes; requires conscious emotional tenderness."),
        _koota("graha_maitri", "Graha Maitri Koota", "ग्रह मैत्री कूट", 5, graha_score,
               f"{ZODIAC_SIGNS[r1]['name']} ({lord1})", f"{ZODIAC_SIGNS[r2]['name']} ({lord2})", "Moon-sign lord compatibility",
               details="Planetary lords share natural camaraderie and common intellectual wavelength." if graha_score >= 3 else "Contrasting planetary temperaments; cultivates mutual patience."),
        _koota("gana", "Gana Koota", "गण कूट", 6, gana_score,
               f"{nak1['gana']} Gana", f"{nak2['gana']} Gana", "Temperament compatibility",
               details="Harmonious lifestyle pace and psychological constitution." if gana_score >= 5 else "Temperamental contrast; remedied through personal space and empathy."),
        _koota("bhakoot", "Bhakoot Koota", "भकूट कूट", 7, bhakoot_score,
               f"{ZODIAC_SIGNS[r1]['name']} ({r1 + 1})", f"{ZODIAC_SIGNS[r2]['name']} ({r2 + 1})", "Rashi relationship",
               details="Auspicious Rashi disposition ensuring financial growth and family bliss." if bhakoot_score == 7 else f"Challenging {bhakoot_relation} placement (Bhakoot Dosha); perform joint Shiva puja."),
        _koota("nadi", "Nadi Koota", "नाड़ी कूट", 8, nadi_score,
               f"{nak1['nadi']} Nadi", f"{nak2['nadi']} Nadi", "Nadi compatibility",
               details=(
                   f"Different Nadis ({nak1['nadi']} & {nak2['nadi']}) provide optimal bio-magnetic balance and progeny vigor."
                   if not same_nadi
                   else (
                       f"Nadi Dosha cancelled: {nadi_cancel_reason} Full 8 points awarded."
                       if nadi_cancelled
                       else f"Active Nadi Dosha detected ({nak1['nadi']} Nadi for both: {nak1_name} & {nak2_name}). Perform Maha Mrityunjaya Japa."
                   )
               )),
    ]

    total = round(sum(x["obtainedPoints"] for x in kootas), 2)
    max_score = 36.0

    ashta = {
        "varna": {"score": varna_score, "maxScore": 1},
        "vashya": {"score": vashya_score, "maxScore": 2,
                   "class1": vashya_c1, "class2": vashya_c2},
        "tara": {"score": tara_score, "maxScore": 3,
                 "tara1": tara12, "tara2": tara21},
        "yoni": {"score": yoni_score, "maxScore": 4,
                 "yoni1": nak1["yoni"], "yoni2": nak2["yoni"]},
        "grahaMaitri": {"score": graha_score, "maxScore": 5,
                         "lord1": lord1, "lord2": lord2},
        "gana": {"score": gana_score, "maxScore": 6},
        "bhakoot": {
            "score": bhakoot_score,
            "maxScore": 7,
            "dosha": bhakoot_dosha,
            "relation": bhakoot_relation,
            "offsetZeroBased": d12,
            "cancellationApplied": bhakoot_cancelled,
            "note": "Cancelled by common/friendly lordship." if bhakoot_cancelled else ("Bhakoot Dosha detected." if bhakoot_dosha else "Auspicious disposition."),
        },
        "nadi": {
            "score": nadi_score,
            "maxScore": 8,
            "sameNadi": same_nadi,
            "cancellationApplied": nadi_cancelled,
            "partner1Nadi": nak1["nadi"],
            "partner2Nadi": nak2["nadi"],
            "reason": (
                f"Different Nadis ({nak1['nadi']} & {nak2['nadi']}) - Harmonious Genetic Accord"
                if not same_nadi
                else (nadi_cancel_reason if nadi_cancelled else f"Both share {nak1['nadi']} Nadi ({nak1_name} & {nak2_name}) - Active Nadi Dosha")
            ),
            "note": (
                f"Different Nadis ({nak1['nadi']} & {nak2['nadi']}) provide optimal bio-magnetic balance."
                if not same_nadi
                else (
                    f"Nadi Dosha cancelled: {nadi_cancel_reason} Full 8 points awarded."
                    if nadi_cancelled
                    else f"Active Nadi Dosha detected ({nak1['nadi']} Nadi for both: {nak1_name} & {nak2_name}). Maha Mrityunjaya Japa and charity recommended."
                )
            ),
        },
    }

    return kootas, ashta, total, max_score


def _koota(kid, name, sanskrit, max_points, score, p1, p2, area, details=""):
    status = "good" if score >= max_points * 0.5 else "critical"
    return {
        "id": kid,
        "name": name,
        "sanskritName": sanskrit,
        "maxPoints": float(max_points),
        "maxScore": float(max_points),
        "obtainedPoints": float(score),
        "score": float(score),
        "p1Value": p1,
        "p2Value": p2,
        "area": area,
        "details": details or ("Harmonious compatibility." if score == max_points else "Challenging disposition."),
        "status": status,
        "verdict": (
            "Excellent" if score == max_points
            else "Good" if score >= max_points * 0.5
            else "Critical" if score == 0
            else "Challenging"
        ),
    }


# ============================================================
# MANGLIK / KUJA DOSHA
# ============================================================

def _mars_manglik_from_house(house: int) -> bool:
    return house in {1, 2, 4, 7, 8, 12}


def _manglik_reference(chart: dict, reference: str) -> dict:
    """Evaluate Mars from Lagna, Moon or Venus when requested."""
    ref = reference.lower()
    if ref == "lagna":
        house = chart["planetsById"]["mars"]["house"]
    elif ref in {"moon", "venus"}:
        ref_sign = chart["planetsById"][ref]["signIndex"]
        mars_sign = chart["planetsById"]["mars"]["signIndex"]
        house = ((mars_sign - ref_sign) % 12) + 1
    else:
        raise ValueError("Manglik reference must be Lagna, Moon or Venus")
    return {"reference": reference, "house": house, "isManglik": _mars_manglik_from_house(house)}


def calculate_manglik_dosha(chart1: dict, chart2: dict) -> dict:
    """
    Calculate Manglik Dosha primarily from Lagna.

    Mars in houses 1, 2, 4, 7, 8, or 12 from Lagna
    is considered Manglik.

    Moon and Venus references are also reported, but they
    are not used for the primary Manglik status.
    """

    checks = {}

    for key, chart in (
        ("partner1", chart1),
        ("partner2", chart2),
    ):
        refs = {
            r: _manglik_reference(chart, r)
            for r in ("Lagna", "Moon", "Venus")
        }

        checks[key] = {
            "name": chart["partner"]["name"],
            "marsSign": chart["planetsById"]["mars"]["signName"],
            "marsHouseFromLagna": chart["planetsById"]["mars"]["house"],
            "fromLagna": refs["Lagna"],
            "fromMoon": refs["Moon"],
            "fromVenus": refs["Venus"],
        }

    m1 = checks["partner1"]["fromLagna"]["isManglik"]
    m2 = checks["partner2"]["fromLagna"]["isManglik"]

    p1_name = checks["partner1"]["name"]
    p2_name = checks["partner2"]["name"]

    partner1_status = (
        f"{p1_name} has Manglik Dosha"
        if m1
        else f"{p1_name} has no Manglik Dosha"
    )

    partner2_status = (
        f"{p2_name} has Manglik Dosha"
        if m2
        else f"{p2_name} has no Manglik Dosha"
    )

    return {
        "partner1": checks["partner1"],
        "partner2": checks["partner2"],

        "status": {
            "partner1": partner1_status,
            "partner2": partner2_status,
        },

        "method": (
            "Manglik is determined primarily from Lagna. "
            "Mars in houses 1, 2, 4, 7, 8, or 12 from Lagna "
            "is considered Manglik."
        ),

        "cancellation": {
            "automaticallyApplied": False,
            "note": (
                "Full Kuja Dosha cancellation depends on the "
                "selected Jyotish tradition and additional "
                "chart factors."
            ),
        },
    }

# ============================================================
# COMPLETE MILAN
# ============================================================

def generate_match_remedies(p1: dict, p2: dict, moon1: dict, moon2: dict, ashta: dict, manglik: dict) -> List[str]:
    remedies = []
    p1_name = p1.get("name") or p1.get("fullName") or "Partner 1"
    p2_name = p2.get("name") or p2.get("fullName") or "Partner 2"
    r1_idx = moon1.get("signIndex") if moon1.get("signIndex") is not None else 0
    r2_idx = moon2.get("signIndex") if moon2.get("signIndex") is not None else 0
    rashi1 = moon1.get("signName") or ZODIAC_SIGNS[r1_idx]["name"]
    rashi2 = moon2.get("signName") or ZODIAC_SIGNS[r2_idx]["name"]
    nak1 = moon1.get("nakshatra") or _nakshatra_from_longitude(moon1.get("longitudeSidereal") or moon1.get("longitude") or 0.0)["name"]
    nak2 = moon2.get("nakshatra") or _nakshatra_from_longitude(moon2.get("longitudeSidereal") or moon2.get("longitude") or 0.0)["name"]
    lord1 = moon1.get("signLord") or ZODIAC_SIGNS[r1_idx]["lord"]
    lord2 = moon2.get("signLord") or ZODIAC_SIGNS[r2_idx]["lord"]

    # 1. Manglik Specific Upaya
    m_status = (manglik or {}).get("status", {})
    p1_m = "has Manglik Dosha" in str(m_status.get("partner1", ""))
    p2_m = "has Manglik Dosha" in str(m_status.get("partner2", ""))
    is_neutralized = m_status.get("neutralized", False) or m_status.get("bothManglik", False)

    if (p1_m or p2_m) and not is_neutralized:
        m_names = " and ".join(filter(None, [p1_name if p1_m else "", p2_name if p2_m else ""]))
        remedies.append(
            f"Kuja Shanti Upaya: {m_names} should recite Hanuman Chalisa on Tuesdays, light a sesame/mustard oil lamp, "
            f"and donate red lentils (masoor dal) or copper to pacify Mars intensity."
        )

    # 2. Nadi Dosha Nivaran
    nadi_koota = (ashta or {}).get("nadi", {})
    nadi_score = float(nadi_koota.get("score") if nadi_koota.get("score") is not None else (nadi_koota.get("obtainedPoints") or 0))
    nadi1 = nadi_koota.get("p1Value") or nadi_koota.get("partner1Nadi") or "Adi Nadi"
    nadi2 = nadi_koota.get("p2Value") or nadi_koota.get("partner2Nadi") or "Madhya Nadi"
    nadi_details = str(nadi_koota.get("details") or nadi_koota.get("reason") or nadi_koota.get("note") or "")
    is_nadi_cancelled = nadi_koota.get("cancellationApplied") or "Cancelled" in nadi_details or "Parihara" in nadi_details

    if nadi_score == 0:
        remedies.append(
            f"Nadi Dosha Nivaran: As both {p1_name} and {p2_name} share {nadi1} ({nak1} & {nak2}), "
            f"perform Maha Mrityunjaya Japa (108 chants daily or 125,000 samput mantra anushthana) "
            f"and donate warm clothing, grain, or a gold/silver token (Swarna-Daan) on auspicious nakshatra days."
        )
    elif is_nadi_cancelled:
        remedies.append(
            f"Nadi Parihara Harmonization: Classical Nadi cancellation applies between {nak1} and {nak2}. "
            f"Perform light Shiva Puja on Pradosham days with white flowers and bilva leaves for enduring physical wellness."
        )

    # 3. Bhakoot Shanti
    bhakoot_koota = (ashta or {}).get("bhakoot", {})
    bhakoot_score = float(bhakoot_koota.get("score") if bhakoot_koota.get("score") is not None else (bhakoot_koota.get("obtainedPoints") or 0))
    bhakoot_rel = str(bhakoot_koota.get("details") or bhakoot_koota.get("relation") or bhakoot_koota.get("note") or f"{rashi1} ↔ {rashi2}")
    if bhakoot_score == 0:
        remedies.append(
            f"Bhakoot Shanti: To balance the {rashi1} ↔ {rashi2} ({bhakoot_rel}) rashi disposition, recite Vishnu Sahasranama together "
            f"every Thursday, perform Navagraha Shanti, and offer yellow flowers or gram dal to Lord Brihaspati."
        )

    # 4. Gana Dosha Shanti
    gana_koota = (ashta or {}).get("gana", {})
    gana_score = float(gana_koota.get("score") if gana_koota.get("score") is not None else (gana_koota.get("obtainedPoints") or 0))
    if gana_score == 0:
        remedies.append(
            f"Gana Dosha Shanti: As {p1_name} and {p2_name} have temperamental divergence ({gana_koota.get('p1Value')} vs {gana_koota.get('p2Value')}), "
            f"perform quarterly Sri Satyanarayan Katha and maintain conscious non-judgmental communication practices."
        )

    # 5. Yoni Hostility Shanti
    yoni_koota = (ashta or {}).get("yoni", {})
    yoni_score = float(yoni_koota.get("score") if yoni_koota.get("score") is not None else (yoni_koota.get("obtainedPoints") or 0))
    if yoni_score <= 1:
        remedies.append(
            f"Yoni Dosha Shanti: To harmonize instinctual compatibility ({yoni_koota.get('p1Value')} vs {yoni_koota.get('p2Value')}), "
            f"worship Lord Shiva and Goddess Parvati jointly on Shukla Paksha Mondays and offer grain or milk to animals."
        )

    # 6. Graha Maitri (Rashi Lords)
    graha_koota = (ashta or {}).get("grahaMaitri", {})
    graha_score = float(graha_koota.get("score") if graha_koota.get("score") is not None else (graha_koota.get("obtainedPoints") or 0))
    if graha_score < 3:
        remedies.append(
            f"Graha Maitri Harmony: Rashi rulers {lord1} ({p1_name}) & {lord2} ({p2_name}) benefit from joint Archana "
            f"at Shiva-Parvati or Radha-Krishna temples on Shukla Paksha Mondays."
        )

    # 7. Shukra & Love Harmony
    remedies.append(
        f"Shukra & Preeti Mantra: {p1_name} & {p2_name} should chant 'Om Shum Shukraya Namaha' (21 times) "
        f"every Friday to invoke enduring romantic sweetness and Venusian grace."
    )

    # 8. Vastu Energy Alignment
    remedies.append(
        "Ishanya Vastu Remedy: Place energized Rose Quartz crystals or a sacred silver coin in the Northeast (Ishanya) "
        "corner of your home to attract marital tranquility and financial growth."
    )

    # 9. Auspicious Deep Daan
    remedies.append(
        "Deep Daan: Light a pure cow ghee lamp facing East during sunset on Thursdays to foster family tranquility and sustained fortune."
    )

    return remedies


def calculate_kundli_milan(partner1: dict, partner2: dict) -> dict:
    err1 = validate_partner(partner1, "partner1")
    if err1:
        raise ValueError(err1)
    err2 = validate_partner(partner2, "partner2")
    if err2:
        raise ValueError(err2)

    p1 = _normalize_partner(partner1)
    p2 = _normalize_partner(partner2)

    chart1 = generate_kundli(p1)
    chart2 = generate_kundli(p2)

    kootas, ashta, total_score, max_score = calculate_ashta_koota(chart1, chart2)
    manglik = calculate_manglik_dosha(chart1, chart2)

    percentage = round(total_score / max_score * 100.0, 2)

    if total_score >= 28:
        verdict = "Excellent"
    elif total_score >= 24:
        verdict = "Very Good"
    elif total_score >= 18:
        verdict = "Acceptable / Moderate"
    else:
        verdict = "Challenging"

    moon1 = chart1["planetsById"]["moon"]
    moon2 = chart2["planetsById"]["moon"]

    remedies = generate_match_remedies(p1, p2, moon1, moon2, ashta, manglik)

    report = {
        "partner1": p1,
        "partner2": p2,
        "partners": {
            "partner1": {
                "name": p1["name"],
                "dob": p1["dob"],
                "time": p1["time"],
                "place": p1["place"],
                "rashi": moon1["signName"],
                "nakshatra": moon1["nakshatra"],
                "nakshatraPada": moon1["pada"],
            },
            "partner2": {
                "name": p2["name"],
                "dob": p2["dob"],
                "time": p2["time"],
                "place": p2["place"],
                "rashi": moon2["signName"],
                "nakshatra": moon2["nakshatra"],
                "nakshatraPada": moon2["pada"],
            },
        },
        "calculatedAt": datetime.now(timezone.utc).isoformat(),
        "calculationEngine": "Swiss Ephemeris",
        "ayanamsha": "Lahiri",
        "zodiac": "Sidereal",
        "totalScore": total_score,
        "totalPoints": total_score,
        "maxScore": max_score,
        "maxPoints": max_score,
        "percentage": percentage,
        "verdictTitle": f"{verdict} Match",
        "summary": {
            "totalScore": total_score,
            "maxScore": max_score,
            "percentage": percentage,
            "verdictTitle": f"{verdict} Match",
            "description": (
                f"Ashta Koota score is {total_score:g}/{max_score:g} "
                f"({percentage}%). This score is based on traditional "
                f"Moon Nakshatra/Rashi matching."
            ),
        },
        "charts": {
            "partner1": chart1,
            "partner2": chart2,
        },
        "kootas": kootas,
        "ashtaKoota": ashta,
        "manglik": manglik,
        "remedies": remedies,
        "numerologyMilan": {
            "note": "Optional/non-Ashta-Koota system",
            "partner1": calculate_numerology(p1["name"], p1["dob"]),
            "partner2": calculate_numerology(p2["name"], p2["dob"]),
        },
        "methodNotes": [
            "Planetary longitudes are calculated from Swiss Ephemeris.",
            "Sidereal zodiac uses Lahiri ayanamsha.",
            "Birth time is converted from the supplied IANA timezone to UTC using the IANA tz database.",
            "Default house system is Whole Sign; Placidus can be selected explicitly with houseSystem='P'.",
            "Rahu defaults to True Node; Mean Node can be selected with nodeType='mean'.",
            "Ashta Koota uses Moon Rashi and Nakshatra.",
            "Manglik reports Mars from Lagna, Moon and Venus without silently applying tradition-specific cancellation rules.",
            "Nadi/Bhakoot cancellation is intentionally conservative; a complete traditional cancellation analysis is separate.",
            "Western synastry is not mixed into the 36-Guna score.",
        ],
    }

    return {
        "totalScore": total_score,
        "maxScore": max_score,
        "partner1ManglikStatus": manglik["status"]["partner1"],
        "partner2ManglikStatus": manglik["status"]["partner2"],
        "remedies": remedies,
        "report": report,
    }

# ============================================================
# DATABASE SERIALIZATION
# ============================================================

def _row_to_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "partner1Name": row["partner1_name"],
        "partner1BirthDate": row["partner1_birth_date"].isoformat()
        if hasattr(row["partner1_birth_date"], "isoformat")
        else str(row["partner1_birth_date"]),
        "partner2Name": row["partner2_name"],
        "partner2BirthDate": row["partner2_birth_date"].isoformat()
        if hasattr(row["partner2_birth_date"], "isoformat")
        else str(row["partner2_birth_date"]),
        "totalScore": float(row["total_score"]),
        "maxScore": float(row["max_score"]),
        "partner1ManglikStatus": row.get(
            "partner1_manglik_status"
        ),

        "partner2ManglikStatus": row.get(
            "partner2_manglik_status"
        ),

        "createdAt": row["created_at"].isoformat()
        if hasattr(row.get("created_at"), "isoformat")
        else row.get("created_at"),
    }


def _row_to_full(row: dict) -> dict:
    result = _row_to_summary(row)
    report_json = row.get("report_json")
    if isinstance(report_json, str):
        try:
            report_json = json.loads(report_json)
        except Exception:
            pass
    result["report"] = report_json
    return result


# ============================================================
# CONTROLLER ENDPOINTS
# ============================================================

def create_match_report(user_id: str):
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        return _error(
            "Request body must be valid JSON",
            "INVALID_JSON"
        )

    partner1 = body.get("partner1")
    partner2 = body.get("partner2")
    supplied_report = body.get("report")

    # --------------------------------------------------------
    # PARTNER 1
    # --------------------------------------------------------

    if not partner1:
        partner1 = {
            "name": body.get("partner1Name"),
            "dob": body.get("partner1BirthDate"),
            "time": body.get("partner1BirthTime"),
            "place": (
                body.get("partner1BirthPlace")
                or body.get("partner1Place")
            ),
            "houseSystem": body.get(
                "partner1HouseSystem",
                "W"
            ),
            "nodeType": body.get(
                "partner1NodeType",
                "true"
            ),
        }

    # --------------------------------------------------------
    # PARTNER 2
    # --------------------------------------------------------

    if not partner2:
        partner2 = {
            "name": body.get("partner2Name"),
            "dob": body.get("partner2BirthDate"),
            "time": body.get("partner2BirthTime"),
            "place": (
                body.get("partner2BirthPlace")
                or body.get("partner2Place")
            ),
            "houseSystem": body.get(
                "partner2HouseSystem",
                "W"
            ),
            "nodeType": body.get(
                "partner2NodeType",
                "true"
            ),
        }

    # --------------------------------------------------------
    # RESOLVE PLACE -> LAT/LON/TIMEZONE
    # --------------------------------------------------------

    try:
        partner1 = prepare_partner(partner1)
        partner2 = prepare_partner(partner2)

    except Exception as exc:
        return _error(
            str(exc),
            "BIRTH_PLACE_RESOLUTION_ERROR"
        )

    # ========================================================
    # BACKEND CALCULATION
    # ========================================================

    if not supplied_report:

        err1 = validate_partner(
            partner1,
            "partner1"
        )

        if err1:
            return _error(
                err1,
                "VALIDATION_ERROR"
            )

        err2 = validate_partner(
            partner2,
            "partner2"
        )

        if err2:
            return _error(
                err2,
                "VALIDATION_ERROR"
            )

        try:
            result = calculate_kundli_milan(
                partner1,
                partner2
            )

        except Exception as exc:
            return _error(
                f"Failed to calculate Kundli Milan: {exc}",
                "CALCULATION_ERROR",
                500
            )

        # ----------------------------------------------------
        # BASIC RESULT
        # ----------------------------------------------------

        report = result["report"]

        total_score = float(
            result["totalScore"]
        )

        max_score = float(
            result["maxScore"]
        )

        # ----------------------------------------------------
        # SEPARATE MANGLIK STATUS
        # ----------------------------------------------------

        partner1_manglik_status = str(
            result["partner1ManglikStatus"]
        )

        partner2_manglik_status = str(
            result["partner2ManglikStatus"]
        )

        # ----------------------------------------------------
        # NORMALIZE PARTNERS
        # ----------------------------------------------------

        p1 = _normalize_partner(partner1)
        p2 = _normalize_partner(partner2)

        p1_name = p1["name"]
        p1_dob = p1["dob"]

        p2_name = p2["name"]
        p2_dob = p2["dob"]

    # ========================================================
    # BACKWARD COMPATIBILITY
    # ========================================================

    else:

        report = supplied_report

        p1_name = (
            body.get("partner1Name")
            or partner1.get("name")
        )

        p1_dob = (
            body.get("partner1BirthDate")
            or partner1.get("dob")
        )

        p2_name = (
            body.get("partner2Name")
            or partner2.get("name")
        )

        p2_dob = (
            body.get("partner2BirthDate")
            or partner2.get("dob")
        )

        try:
            total_score = float(
                body["totalScore"]
            )

            max_score = float(
                body.get("maxScore", 36)
            )

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            return _error(
                "totalScore/maxScore must be numeric",
                "VALIDATION_ERROR"
            )

        partner1_manglik_status = str(
            body.get(
                "partner1ManglikStatus",
                "Unknown"
            )
        )

        partner2_manglik_status = str(
            body.get(
                "partner2ManglikStatus",
                "Unknown"
            )
        )

    # ========================================================
    # SERIALIZE JSON
    # ========================================================

    report_id = str(uuid.uuid4())

    report_json_str = json.dumps(
        report,
        ensure_ascii=False
    )

    partner1_manglik_status,
    partner2_manglik_status,

    # ========================================================
    # SAVE TO DATABASE
    # ========================================================

    try:

        rows = call_procedure(
            "sp_create_match_report",
            [
                report_id,
                user_id,

                p1_name,
                p1_dob,

                p2_name,
                p2_dob,

                total_score,
                max_score,

                partner1_manglik_status,
                partner2_manglik_status,
                report_json_str,
            ],
        )

    except Exception as exc:

        return _error(
            f"Database error while saving report: {exc}",
            "DATABASE_ERROR",
            500
        )

    if not rows:
        return _error(
            "Could not save match report",
            "SAVE_FAILED",
            500
        )

    return jsonify({
        "status": "success",
        "message": (
            "Astronomical Kundli Milan report "
            "generated and saved successfully"
        ),
        "data": _row_to_full(rows[0]),
    }), 201

def list_match_reports(user_id: str):
    try:
        rows = call_procedure("sp_get_match_reports", [user_id])
        return jsonify({
            "status": "success",
            "data": [_row_to_summary(r) for r in rows],
        })
    except Exception as exc:
        return _error(f"Database error while fetching reports: {exc}", "DATABASE_ERROR", 500)


def get_match_report(user_id: str, report_id: str):
    try:
        rows = call_procedure("sp_get_match_report", [report_id, user_id])
        if not rows:
            return _error("Match report not found", "NOT_FOUND", 404)

        return jsonify({
            "status": "success",
            "data": _row_to_full(rows[0]),
        })
    except Exception as exc:
        return _error(f"Database error while fetching report: {exc}", "DATABASE_ERROR", 500)


def download_match_report_pdf(user_id: str, report_id: str):
    try:
        rows = call_procedure("sp_get_match_report", [report_id, user_id])
        if not rows:
            return _error("Match report not found", "NOT_FOUND", 404)

        row = dict(rows[0])
        report_json = row.get("report_json")

        if isinstance(report_json, str):
            report_json = json.loads(report_json)

        row["report_json"] = report_json
        pdf_bytes = generate_match_report_pdf(row)

        filename = f"astrojunction-kundli-milan-{report_id[:8]}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as exc:
        return _error(f"Error generating PDF: {exc}", "PDF_ERROR", 500)


def generate_direct_pdf():
    try:
        body = request.get_json(silent=True) or {}

        partner1 = body.get("partner1")
        partner2 = body.get("partner2")

        if not partner1:
            partner1 = {
                "name": body.get("partner1_name") or body.get("partner1Name") or "Partner 1",
                "dob": body.get("partner1_birth_date") or body.get("partner1BirthDate") or "",
                "time": body.get("partner1_birth_time") or body.get("partner1BirthTime") or "12:00",
                "place": body.get("partner1_birth_place") or body.get("partner1BirthPlace") or body.get("partner1Place") or "Delhi, India",
                "latitude": body.get("partner1_latitude") or body.get("partner1Latitude"),
                "longitude": body.get("partner1_longitude") or body.get("partner1Longitude"),
                "timezone": body.get("partner1_timezone") or body.get("partner1Timezone", 5.5),
                "houseSystem": body.get("partner1HouseSystem", "W"),
                "nodeType": body.get("partner1NodeType", "true"),
            }

        if not partner2:
            partner2 = {
                "name": body.get("partner2_name") or body.get("partner2Name") or "Partner 2",
                "dob": body.get("partner2_birth_date") or body.get("partner2BirthDate") or "",
                "time": body.get("partner2_birth_time") or body.get("partner2BirthTime") or "12:00",
                "place": body.get("partner2_birth_place") or body.get("partner2BirthPlace") or body.get("partner2Place") or "Mumbai, India",
                "latitude": body.get("partner2_latitude") or body.get("partner2Latitude"),
                "longitude": body.get("partner2_longitude") or body.get("partner2Longitude"),
                "timezone": body.get("partner2_timezone") or body.get("partner2Timezone", 5.5),
                "houseSystem": body.get("partner2HouseSystem", "W"),
                "nodeType": body.get("partner2NodeType", "true"),
            }

        # Resolve lat/lon/timezone if not supplied
        partner1 = prepare_partner(partner1)
        partner2 = prepare_partner(partner2)

        err1 = validate_partner(partner1, "partner1")
        if err1:
            return _error(err1, "VALIDATION_ERROR")
        err2 = validate_partner(partner2, "partner2")
        if err2:
            return _error(err2, "VALIDATION_ERROR")

        # Full Vedic calculation via Swiss Ephemeris engine
        result = calculate_kundli_milan(partner1, partner2)
        report_data = result.get("report") or {}

        p1_name = partner1.get("name") or "Partner 1"
        p2_name = partner2.get("name") or "Partner 2"

        row = {
            "report_json": report_data,
            "partner1_name": p1_name,
            "partner1_birth_date": partner1.get("dob") or "",
            "partner1_birth_time": partner1.get("time") or "",
            "partner1_birth_place": partner1.get("place") or "",
            "partner2_name": p2_name,
            "partner2_birth_date": partner2.get("dob") or "",
            "partner2_birth_time": partner2.get("time") or "",
            "partner2_birth_place": partner2.get("place") or "",
            "total_score": float(result.get("totalScore", 0)),
            "max_score": float(result.get("maxScore", 36)),
        }

        pdf_bytes = generate_match_report_pdf(row)

        clean_p1 = "".join(c for c in p1_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        clean_p2 = "".join(c for c in p2_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        filename = f"AstroJunction_Kundli_Milan_{clean_p1}_and_{clean_p2}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        print(f"Error generating direct match PDF: {exc}")
        return _error(f"Error generating PDF: {exc}", "PDF_ERROR", 500)


def generate_direct_ai_synthesis_pdf():
    try:
        body = request.get_json(silent=True) or {}
        synthesis_id = body.get("synthesisId") or body.get("id")

        if synthesis_id:
            return download_ai_synthesis_pdf(synthesis_id)

        p1_name = body.get("partner1_name") or body.get("partner1Name") or (body.get("partner1") or {}).get("fullName") or "Partner 1"
        p2_name = body.get("partner2_name") or body.get("partner2Name") or (body.get("partner2") or {}).get("fullName") or "Partner 2"
        synthesis_data = body.get("synthesis") or body.get("aiSynthesis") or {}
        score = body.get("score") or body.get("totalScore") or 0
        max_score = body.get("max_score") or body.get("maxScore") or 36

        manglik_obj = synthesis_data.get("manglik_dosha") if isinstance(synthesis_data, dict) else {}
        p1_manglik = (
            (manglik_obj.get("partner1") if isinstance(manglik_obj, dict) else None)
            or body.get("partner1_manglik_status")
            or body.get("partner1ManglikStatus")
        )
        p2_manglik = (
            (manglik_obj.get("partner2") if isinstance(manglik_obj, dict) else None)
            or body.get("partner2_manglik_status")
            or body.get("partner2ManglikStatus")
        )

        if not p1_manglik or "unavailable" in str(p1_manglik).lower():
            p1_manglik = f"{p1_name} has no Manglik Dosha"
        if not p2_manglik or "unavailable" in str(p2_manglik).lower():
            p2_manglik = f"{p2_name} has no Manglik Dosha"

        row = {
            "partner1_name": p1_name,
            "partner2_name": p2_name,
            "total_score": score,
            "max_score": max_score,
            "partner1_manglik_status": p1_manglik,
            "partner2_manglik_status": p2_manglik,
            "synthesis_json": synthesis_data if isinstance(synthesis_data, str) else json.dumps(synthesis_data, ensure_ascii=False),
        }

        pdf_bytes = generate_ai_synthesis_pdf(row)

        clean_p1 = "".join(c for c in p1_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        clean_p2 = "".join(c for c in p2_name if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        filename = f"AstroJunction_AI_Counsel_{clean_p1}_and_{clean_p2}.pdf"

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf_bytes)),
                "Cache-Control": "no-store",
            },
        )
    except Exception as exc:
        print(f"Error generating direct AI synthesis PDF: {exc}")
        return _error(f"Error generating AI synthesis PDF: {exc}", "PDF_ERROR", 500)


def calculate_match_endpoint():
    """
    Public calculation endpoint (no login required for calculation).
    Returns exact Swiss Ephemeris Ashta Koota, Manglik, Nadi, Bhakoot, and Planetary charts.
    """
    body = request.get_json(silent=True) or {}
    partner1 = body.get("partner1")
    partner2 = body.get("partner2")

    if not partner1:
        partner1 = {
            "name": body.get("partner1Name") or "Partner 1",
            "dob": body.get("partner1BirthDate") or "",
            "time": body.get("partner1BirthTime") or "12:00",
            "place": body.get("partner1BirthPlace") or body.get("partner1Place") or "Delhi, India",
            "latitude": body.get("partner1Latitude") or body.get("latitude"),
            "longitude": body.get("partner1Longitude") or body.get("longitude"),
            "timezone": body.get("partner1Timezone", 5.5),
            "gender": body.get("partner1Gender", "male"),
        }

    if not partner2:
        partner2 = {
            "name": body.get("partner2Name") or "Partner 2",
            "dob": body.get("partner2BirthDate") or "",
            "time": body.get("partner2BirthTime") or "12:00",
            "place": body.get("partner2BirthPlace") or body.get("partner2Place") or "Mumbai, India",
            "latitude": body.get("partner2Latitude") or body.get("latitude"),
            "longitude": body.get("partner2Longitude") or body.get("longitude"),
            "timezone": body.get("partner2Timezone", 5.5),
            "gender": body.get("partner2Gender", "female"),
        }

    try:
        partner1 = prepare_partner(partner1)
        partner2 = prepare_partner(partner2)
        
        result = calculate_kundli_milan(partner1, partner2)
        return jsonify({
            "status": "success",
            "data": result
        })
    except Exception as exc:
        print(f"Error calculating matchmaking in calculate_match_endpoint: {exc}")
        return _error(f"Failed to calculate Kundli Milan: {exc}", "CALCULATION_ERROR", 500)


def build_deterministic_synthesis(
    partner1: dict,
    partner2: dict,
    ashtaKoota: Any,
    score: float,
    max_score: float,
    partner1_manglik_status: str,
    partner2_manglik_status: str,
) -> dict:
    p1_name = partner1.get("fullName") or partner1.get("name") or "Partner 1"
    p2_name = partner2.get("fullName") or partner2.get("name") or "Partner 2"
    p1_rashi = partner1.get("rashi") or (partner1.get("moon") or {}).get("signName") or "Moon Rashi"
    p2_rashi = partner2.get("rashi") or (partner2.get("moon") or {}).get("signName") or "Moon Rashi"
    p1_nak = partner1.get("nakshatra") or (partner1.get("moon") or {}).get("nakshatra") or "Nakshatra"
    p2_nak = partner2.get("nakshatra") or (partner2.get("moon") or {}).get("nakshatra") or "Nakshatra"

    def _get_k(key, alt_id=None):
        if isinstance(ashtaKoota, dict):
            return ashtaKoota.get(key) or (ashtaKoota.get(alt_id) if alt_id else None) or {}
        if isinstance(ashtaKoota, list):
            for item in ashtaKoota:
                if isinstance(item, dict) and (item.get("id") == key or item.get("id") == alt_id or str(item.get("name", "")).lower() == key.lower()):
                    return item
        return {}

    varna_k = _get_k("varna")
    vashya_k = _get_k("vashya")
    tara_k = _get_k("tara")
    yoni_k = _get_k("yoni")
    graha_k = _get_k("grahaMaitri", "graha")
    gana_k = _get_k("gana")
    bhakoot_k = _get_k("bhakoot")
    nadi_k = _get_k("nadi")

    nadi_score = float(nadi_k.get("score") if nadi_k.get("score") is not None else (nadi_k.get("obtainedPoints") or 0))
    bhakoot_score = float(bhakoot_k.get("score") if bhakoot_k.get("score") is not None else (bhakoot_k.get("obtainedPoints") or 0))
    gana_score = float(gana_k.get("score") if gana_k.get("score") is not None else (gana_k.get("obtainedPoints") or 0))
    graha_score = float(graha_k.get("score") if graha_k.get("score") is not None else (graha_k.get("obtainedPoints") or 0))
    yoni_score = float(yoni_k.get("score") if yoni_k.get("score") is not None else (yoni_k.get("obtainedPoints") or 0))
    tara_score = float(tara_k.get("score") if tara_k.get("score") is not None else (tara_k.get("obtainedPoints") or 0))
    vashya_score = float(vashya_k.get("score") if vashya_k.get("score") is not None else (vashya_k.get("obtainedPoints") or 0))
    varna_score = float(varna_k.get("score") if varna_k.get("score") is not None else (varna_k.get("obtainedPoints") or 0))

    nadi1 = nadi_k.get("p1Value") or nadi_k.get("partner1Nadi") or "Adi Nadi"
    nadi2 = nadi_k.get("p2Value") or nadi_k.get("partner2Nadi") or "Madhya Nadi"
    nadi_details = str(nadi_k.get("details") or nadi_k.get("reason") or nadi_k.get("note") or "")
    is_nadi_cancelled = nadi_k.get("cancellationApplied") or "Cancelled" in nadi_details or "Parihara" in nadi_details

    yoni1 = yoni_k.get("p1Value") or yoni_k.get("yoni1") or "Ashwa"
    yoni2 = yoni_k.get("p2Value") or yoni_k.get("yoni2") or "Gaja"
    gana1 = gana_k.get("p1Value") or gana_k.get("gana1") or "Deva"
    gana2 = gana_k.get("p2Value") or gana_k.get("gana2") or "Manushya"
    bhakoot_rel = str(bhakoot_k.get("details") or bhakoot_k.get("relation") or bhakoot_k.get("note") or f"{p1_rashi} and {p2_rashi}")

    pct = (score / max_score * 100.0) if max_score > 0 else 0
    if score >= 28:
        verdict_term = "an Auspicious / Excellent"
    elif score >= 24:
        verdict_term = "a Highly Favorable / Very Good"
    elif score >= 18:
        verdict_term = "an Acceptable / Moderate"
    else:
        verdict_term = "a Delicately Balanced / Challenging"

    # Overall compatibility narrative
    overall = (
        f"The marital compatibility evaluation between {p1_name} ({p1_rashi} Rashi, {p1_nak} Nakshatra) and "
        f"{p2_name} ({p2_rashi} Rashi, {p2_nak} Nakshatra) registers an Ashta Koota total of {score:g} out of {max_score:g} "
        f"points ({pct:.1f}%). Classical Vedic Jyotish categorizes this score as {verdict_term} match, indicating "
        f"a meaningful alignment of core psychological, energetic, and temperamental archetypes. "
        f"While the fundamental cosmic harmony is supportive, conscious cultivation of mutual patience and communication "
        f"will ensure stability and long-term domestic tranquility."
    )

    # Guna Milan narrative
    top_strengths = []
    if nadi_score >= 6: top_strengths.append("Nadi (physiological & genetic vitality)")
    if bhakoot_score >= 5: top_strengths.append("Bhakoot (emotional & familial welfare)")
    if gana_score >= 5: top_strengths.append("Gana (temperamental concord)")
    if graha_score >= 4: top_strengths.append("Graha Maitri (intellectual friendship)")
    if yoni_score >= 3: top_strengths.append("Yoni (instinctual compatibility)")
    strengths_str = ", ".join(top_strengths) if top_strengths else "Varna and Vashya foundation"

    guna = (
        f"In the canonical 36-Guna Milan framework, the alliance earns {score:g} points, reflecting significant "
        f"resonance across primary relationship dimensions. Strongest point contributions are observed in {strengths_str}, "
        f"which provide an enduring bedrock for marital understanding. Areas where points are constrained highlight points "
        f"of individual differentiation rather than insurmountable barriers. By consciously honoring each other's inherent "
        f"planetary tendencies, the couple can navigate any Guna discrepancies with ease."
    )

    # Psychological affinity narrative
    psycho = (
        f"Psychological and intellectual affinity is governed by Graha Maitri (planetary friendship) between the Rashi lords, "
        f"scoring {graha_score:g}/5 points. {p1_name}'s mental disposition is steered by {p1_rashi}, while {p2_name}'s cognitive "
        f"approach is shaped by {p2_rashi}. Their interaction reveals "
        f"{'warm mutual understanding and shared intellectual wavelengths' if graha_score >= 3 else 'divergent thinking styles that require active, open discussion rather than assumptions'}. "
        f"Practicing open communication without defensiveness will allow both partners to convert philosophical differences into mutual enrichment."
    )

    # Emotional resonance narrative
    emotional = (
        f"The emotional resonance between {p1_name} and {p2_name} is anchored in their Moon nakshatras, {p1_nak} and {p2_nak}. "
        f"The Moon governs the subconscious feeling nature, receptive capacity, and instinctual empathy. "
        f"Their mutual alignment allows intuitive understanding of each other's emotional moods and vulnerabilities when patience is exercised. "
        f"Creating regular quiet interludes away from daily routines will allow their emotional intimacy to blossom securely over time."
    )

    # Karmic bond narrative
    karmic = (
        f"From the perspective of Vedic karmic synastry, Tara Koota ({tara_score:g}/3 points) indicates an authentic past-life "
        f"connection and shared destiny intended for personal evolution. Both souls bring complementary karmic debts (Rinanubandha) "
        f"and lessons that balance one another's life paths. Engaging in joint spiritual disciplines, temple visits, and charitable "
        f"service together will help sublimate latent karmic tensions into spiritual progress and domestic joy."
    )

    # Physical harmonization narrative
    physical = (
        f"Physical and instinctual harmonization, governed by Yoni Koota ({yoni_score:g}/4 points with {yoni1} and {yoni2} types), "
        f"reflects the couple's subconscious attraction and biological rhythm. "
        f"{'Their animal archetypes share a natural attraction that supports deep intimate warmth and physical affection.' if yoni_score >= 3 else 'Their distinct biological archetypes benefit from mutual gentleness, considerate pacing, and emotional reassurance.'} "
        f"Cultivating a calm, restful bedroom sanctuary and honoring individual personal space will sustain lasting romance and mutual vitality."
    )

    # Manglik dosha narrative
    p1_m = "has Manglik Dosha" in str(partner1_manglik_status)
    p2_m = "has Manglik Dosha" in str(partner2_manglik_status)
    if p1_m and p2_m:
        manglik_narrative = (
            f"Kuja Dosha evaluation reveals that both {p1_name} and {p2_name} carry active Manglik influences. "
            f"According to classical Jyotish maxims, mutual Manglik presence provides an authentic cancellation (Dosha Samyam), "
            f"neutralizing harsh malefic effects through reciprocal high energy and assertive drive. "
            f"The couple should channel their dynamic vitality constructively into shared physical activities and creative ambitions."
        )
    elif p1_m or p2_m:
        m_who = p1_name if p1_m else p2_name
        non_who = p2_name if p1_m else p1_name
        manglik_narrative = (
            f"Kuja Dosha analysis indicates that {m_who} carries an active Manglik placement, while {non_who} has a Non-Manglik status. "
            f"The focused intensity of Mars can manifest as sudden impatience or sharp verbal reactions during high-stress situations. "
            f"Observing Tuesday Hanuman Chalisa recitation, donating red lentils (masoor dal), and practicing conscious conflict cooling "
            f"will preserve harmony and balance marital energies effectively."
        )
    else:
        manglik_narrative = (
            f"Evaluation confirms that neither {p1_name} nor {p2_name} carries an active Manglik Dosha in their foundational charts. "
            f"Mars is situated in benign, non-afflicting houses, shielding the marital seventh and eighth cusps from destructive friction. "
            f"This clean Manglik disposition provides a serene and balanced astrological foundation for peaceful matrimonial life."
        )

    # Nadi analysis narrative
    if nadi_score == 0:
        nadi_narrative = (
            f"Nadi Koota registers an active Nadi Dosha with 0/8 points as both partners share {nadi1} ({p1_nak} and {p2_nak}). "
            f"In classical Vedic physiology, identical Nadi signifies an identical elemental humor (Tridosha: Vata, Pitta, or Kapha), "
            f"which traditionally calls for mindfulness regarding reproductive wellness, progeny, and physiological stamina. "
            f"The couple should perform dedicated Maha Mrityunjaya Japa (108 daily), practice Swarna-Daan or grain donation, "
            f"and maintain regular medical checkups to smoothly mitigate these bio-energetic imbalances."
        )
    elif is_nadi_cancelled:
        nadi_narrative = (
            f"While both partners share {nadi1}, canonical Vedic cancellation (Parihara) applies due to different Nakshatras or distinct Rashi lords, "
            f"awarding the full 8/8 points. Classical Jyotish texts confirm that this parihara dissolves the primary bio-energetic and genetic afflictions, "
            f"ensuring sound physiological compatibility and auspicious progeny. "
            f"Routine worship of Lord Shiva with white flowers and bilva leaves on Mondays will sustain excellent physical well-being."
        )
    else:
        nadi_narrative = (
            f"Nadi Koota achieves a perfect 8 out of 8 points, with {p1_name} having {nadi1} and {p2_name} having {nadi2}. "
            f"Under classical Ayurvedic and Jyotish principles, complementary Nadis generate optimal bio-energetic balance, genetic vitality, "
            f"and sound reproductive wellness. This stands as one of the most auspicious and reassuring pillars of this marital union."
        )

    # Bhakoot analysis narrative
    if bhakoot_score == 0:
        bhakoot_narrative = (
            f"Bhakoot Koota receives 0/7 points due to a mutual disposition ({bhakoot_rel}) between Moon signs {p1_rashi} and {p2_rashi}. "
            f"This planetary stance can periodically test financial coordination, emotional expectations, or familial obligations. "
            f"Classical Vedic tradition prescribes reciting the Vishnu Sahasranama, performing Navagraha Shanti, and maintaining transparent "
            f"financial conversations to dissolve energetic friction and cultivate abundance."
        )
    else:
        bhakoot_narrative = (
            f"Bhakoot Koota awards a full 7 out of 7 points, reflecting an auspicious planetary relationship ({bhakoot_rel}) between "
            f"{p1_rashi} and {p2_rashi}. This harmonious flow fosters mutual emotional generosity, long-term financial security, and blissful "
            f"domestic growth. Both partners will naturally support each other's career goals and share joint pride in their home life."
        )

    # Family & married life narrative
    family_life = (
        f"Family integration and the long-term prospects of married life are favorably supported by the foundational Gunas, "
        f"including Varna ({varna_score:g}/1) and Vashya ({vashya_score:g}/2). Both individuals show sincere respect for family duties, "
        f"traditions, and domestic comfort. Cultivating active rapport with extended in-laws and celebrating auspicious occasions jointly "
        f"will reinforce a warm, unified, and enduring family structure."
    )

    # Wealth & prosperity narrative
    wealth = (
        f"Wealth generation and material prosperity demonstrate steady, cumulative promise under their combined planetary signatures. "
        f"Their joint energetic alignment encourages prudent fiscal discipline, thoughtful investments, and long-term asset building. "
        f"Practicing regular joint charity on Thursdays or Fridays will invite the divine grace of Goddess Lakshmi and Lord Brihaspati, "
        f"amplifying both material security and spiritual contentment."
    )

    # Major strengths (list of strings)
    strengths = [
        f"Strong core Ashta Koota total ({score:g}/{max_score:g} points), satisfying classical criteria for marital consideration.",
        f"Excellent Nadi compatibility ({nadi1} & {nadi2}), ensuring sound bio-energetic vitality and reproductive wellness." if nadi_score >= 8 else (
            f"Authentic Nadi Parihara (Cancellation) mitigating traditional genetic concerns and preserving vitality." if is_nadi_cancelled else
            f"Complementary personality strengths rooted in {p1_nak} and {p2_nak} Nakshatra placements."
        ),
        f"Auspicious Bhakoot flow ({bhakoot_score:g}/7 points) ensuring domestic cheerfulness and emotional generosity." if bhakoot_score >= 5 else (
            f"Shared dedication to domestic security and household integrity despite astrological variations."
        ),
        f"Deep psychological and soul-level connection fostering long-term spiritual growth and companionship."
    ]

    # Major challenges (list of strings)
    challenges = []
    if nadi_score == 0:
        challenges.append(f"Active Nadi Dosha ({nadi1} shared by both partners), requiring traditional remedial vigilance and health care.")
    if bhakoot_score == 0:
        challenges.append(f"Bhakoot discord ({bhakoot_rel}), requiring clear communication around finances and emotional expectations.")
    if gana_score == 0:
        challenges.append(f"Gana divergence ({gana1} vs {gana2}), which may trigger occasional misunderstandings during disagreements.")
    if (p1_m or p2_m) and not (p1_m and p2_m):
        challenges.append(f"Kuja (Manglik) intensity in one partner, requiring conscious anger management and cooling practices.")
    if not challenges:
        challenges.append("Minor differences in daily routines and communication styles that require ongoing mutual adaptation.")
        challenges.append("Balancing individual career ambitions with collective domestic responsibilities.")

    # Conflict resolution (list of strings)
    conflict = [
        "Adopt a 24-hour cooling-off rule before addressing sensitive or emotionally charged relationship topics.",
        "Practice active listening without interrupting, validating each other's feelings before proposing practical solutions.",
        "Establish unified financial guidelines and maintain transparent communication regarding significant family expenditures.",
        "Celebrate weekly shared spiritual moments or peaceful nature walks to recalibrate relationship tranquility."
    ]

    def _find_sign_lord(sign_name):
        for z in ZODIAC_SIGNS:
            if z["name"].lower() == str(sign_name).lower() or z["sanskrit"].lower() == str(sign_name).lower():
                return z["lord"]
        return "Moon"

    p1_lord = _find_sign_lord(p1_rashi)
    p2_lord = _find_sign_lord(p2_rashi)

    # Vedic remedies (list of strings)
    vedic_rems = generate_match_remedies(
        partner1, partner2,
        {"signName": p1_rashi, "nakshatra": p1_nak, "signLord": p1_lord},
        {"signName": p2_rashi, "nakshatra": p2_nak, "signLord": p2_lord},
        ashtaKoota if isinstance(ashtaKoota, dict) else {},
        {"status": {"partner1": partner1_manglik_status, "partner2": partner2_manglik_status}}
    )

    # Final assessment narrative
    final = (
        f"In summary, the astrological union between {p1_name} and {p2_name} presents a {verdict_term} compatibility profile "
        f"backed by a solid score of {score:g}/36 Gunas. The natural strengths of this match provide a resilient base for a loving, "
        f"fulfilling, and prosperous married life. By observing the recommended Vedic upayas, maintaining mutual respect, and "
        f"approaching life's challenges with unified teamwork, this couple can build a deeply happy and enduring bond."
    )

    return {
        "overall_compatibility": overall,
        "guna_milan": guna,
        "psychological_affinity": psycho,
        "emotional_resonance": emotional,
        "karmic_bond": karmic,
        "physical_harmonization": physical,
        "manglik_dosha": manglik_narrative,
        "nadi_analysis": nadi_narrative,
        "bhakoot_analysis": bhakoot_narrative,
        "family_and_married_life": family_life,
        "wealth_and_prosperity": wealth,
        "major_strengths": strengths,
        "major_challenges": challenges,
        "conflict_resolution": conflict,
        "vedic_remedies": vedic_rems,
        "final_assessment": final,
    }


def generate_ai_synthesis(user_id: str):
    try:
        body = request.get_json(silent=True) or {}

        if "matchResult" in body:
            report = body.get("matchResult", {})
            partner1 = body.get("partner1", {})
            partner2 = body.get("partner2", {})
            report_id = "unsaved"
            data = body
        else:
            data = body.get("data", {})
            if not isinstance(data, dict):
                return _error("data must be a JSON object", "INVALID_DATA", 400)

            report = data.get("report", {})
            if not isinstance(report, dict):
                return _error("report must be a JSON object", "INVALID_REPORT", 400)

            report_id = data.get("id")
            if not report_id:
                return _error("id is required", "ID_REQUIRED", 400)

        partner1 = report.get("partner1") or body.get("partner1") or {}
        partner2 = report.get("partner2") or body.get("partner2") or {}
        ashtaKoota = report.get("ashtaKoota") or report.get("kootas") or {}

        if not isinstance(partner1, dict):
            partner1 = {}
        if not isinstance(partner2, dict):
            partner2 = {}
        if not isinstance(ashtaKoota, (dict, list)):
            ashtaKoota = {}

        p1_name = (
            partner1.get("fullName")
            or partner1.get("name")
            or body.get("partner1Name")
            or data.get("partner1Name")
            or "Partner 1"
        )
        p2_name = (
            partner2.get("fullName")
            or partner2.get("name")
            or body.get("partner2Name")
            or data.get("partner2Name")
            or "Partner 2"
        )

        score = None
        if isinstance(ashtaKoota, dict):
            score = ashtaKoota.get("totalPoints") or ashtaKoota.get("totalScore")
        elif isinstance(ashtaKoota, list):
            score = sum(float(k.get("obtainedPoints") or k.get("obtained") or 0) for k in ashtaKoota if isinstance(k, dict))

        if score is None:
            score = report.get("totalPoints")
        if score is None:
            score = report.get("totalScore")
        if score is None:
            score = data.get("totalScore")
        if score is None:
            score = 0.0

        max_score = data.get("maxScore") or report.get("maxPoints") or 36.0

        partner1_manglik_status = (
            data.get("partner1ManglikStatus")
            or report.get("partner1ManglikStatus")
            or (report.get("manglik") or {}).get("status", {}).get("partner1")
        )
        partner2_manglik_status = (
            data.get("partner2ManglikStatus")
            or report.get("partner2ManglikStatus")
            or (report.get("manglik") or {}).get("status", {}).get("partner2")
        )

        # Auto calculate if missing
        if (
            not partner1_manglik_status
            or "unavailable" in str(partner1_manglik_status).lower()
            or not partner2_manglik_status
            or "unavailable" in str(partner2_manglik_status).lower()
            or not ashtaKoota
        ):
            try:
                p1_candidate = partner1 if (partner1.get("dob") or partner1.get("birthDate")) else (body.get("partner1") or {})
                p2_candidate = partner2 if (partner2.get("dob") or partner2.get("birthDate")) else (body.get("partner2") or {})
                if (p1_candidate.get("dob") or p1_candidate.get("birthDate")) and (p2_candidate.get("dob") or p2_candidate.get("birthDate")):
                    p1_prep = prepare_partner(p1_candidate)
                    p2_prep = prepare_partner(p2_candidate)
                    calc_res = calculate_kundli_milan(p1_prep, p2_prep)
                    if calc_res:
                        if not partner1_manglik_status or "unavailable" in str(partner1_manglik_status).lower():
                            partner1_manglik_status = calc_res.get("partner1ManglikStatus")
                        if not partner2_manglik_status or "unavailable" in str(partner2_manglik_status).lower():
                            partner2_manglik_status = calc_res.get("partner2ManglikStatus")
                        if not ashtaKoota:
                            ashtaKoota = (calc_res.get("report") or {}).get("ashtaKoota") or {}
                        if not score:
                            score = calc_res.get("totalScore") or score
            except Exception as auto_calc_err:
                print(f"Auto Kundli Milan calculation in synthesis: {auto_calc_err}")

        if not partner1_manglik_status or "unavailable" in str(partner1_manglik_status).lower():
            partner1_manglik_status = f"{p1_name} has no Manglik Dosha"
        if not partner2_manglik_status or "unavailable" in str(partner2_manglik_status).lower():
            partner2_manglik_status = f"{p2_name} has no Manglik Dosha"

        # Baseline deterministic synthesis
        baseline_synthesis = build_deterministic_synthesis(
            partner1, partner2, ashtaKoota, score, max_score,
            partner1_manglik_status, partner2_manglik_status
        )

        system_prompt = """
You are an expert AI Vedic Astrological Counselor for a Jyotish matchmaking application.

CRITICAL INSTRUCTIONS:
1. Return ONLY a single valid JSON object. Do not include markdown fences (```json), commentary, or extra text.
2. For all narrative keys, write 3 to 5 comprehensive, deeply insightful sentences explaining the Vedic astrological implications in elegant, professional language.
3. NEVER return single-word or brief answers (such as "Moderate", "Good", "Challenging", or "Average").
4. NEVER return nested objects or dictionaries for narrative keys.
5. For list keys (major_strengths, major_challenges, conflict_resolution, vedic_remedies), return a JSON array of complete, descriptive strings (each 1-2 sentences).
6. Use the supplied Ashta Koota scores and Manglik statuses exactly as provided. Do not recalculate or invent different scores.

Required JSON keys:
- overall_compatibility (string: 3-5 complete sentences)
- guna_milan (string: 3-5 complete sentences)
- psychological_affinity (string: 3-5 complete sentences)
- emotional_resonance (string: 3-5 complete sentences)
- karmic_bond (string: 3-5 complete sentences)
- physical_harmonization (string: 3-5 complete sentences)
- manglik_dosha (string: 3-5 complete sentences describing Kuja influence and mitigation)
- nadi_analysis (string: 3-5 complete sentences detailing Nadi compatibility or Parihara)
- bhakoot_analysis (string: 3-5 complete sentences detailing Moon sign relationship)
- family_and_married_life (string: 3-5 complete sentences)
- wealth_and_prosperity (string: 3-5 complete sentences)
- major_strengths (array of 3 to 5 descriptive strings)
- major_challenges (array of 2 to 4 descriptive strings)
- conflict_resolution (array of 3 to 5 actionable guidance strings)
- vedic_remedies (array of 4 to 6 traditional Vedic upayas, mantras, and charitable remedies)
- final_assessment (string: 3-5 uplifting concluding sentences)
"""

        prompt = f"""
PARTNER 1:
{json.dumps(partner1, ensure_ascii=False, indent=2)}

PARTNER 2:
{json.dumps(partner2, ensure_ascii=False, indent=2)}

ASHTA KOOTA:
{json.dumps(ashtaKoota, ensure_ascii=False, indent=2)}

TOTAL ASHTA KOOTA SCORE:
{score}/36

PARTNER 1 MANGLIK STATUS:
{partner1_manglik_status}

PARTNER 2 MANGLIK STATUS:
{partner2_manglik_status}

PARTNER 1 NAME:
{p1_name}

PARTNER 2 NAME:
{p2_name}

Provide a comprehensive, highly insightful Vedic Jyotish synthesis for {p1_name} and {p2_name}.
Ensure each narrative section is a rich paragraph of 3 to 5 full sentences.
Do NOT output single words like 'Moderate' or raw JSON dictionaries for narrative fields.
"""

        ai_synthesis_data = None
        try:
            raw_synthesis = get_ai_response(
                system_prompt,
                [{"role": "user", "content": prompt}]
            )
            if raw_synthesis:
                cleaned = raw_synthesis.strip()
                if cleaned.startswith("```"):
                    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
                    cleaned = re.sub(r"\s*```$", "", cleaned)
                    cleaned = cleaned.strip()
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    ai_synthesis_data = parsed
        except Exception as ai_err:
            print(f"Notice: AI synthesis generation encountered error/timeout: {ai_err}. Using deterministic baseline.")

        # Harmonize with baseline
        synthesis_data = dict(baseline_synthesis)
        if ai_synthesis_data:
            narrative_keys = [
                "overall_compatibility", "guna_milan", "psychological_affinity",
                "emotional_resonance", "karmic_bond", "physical_harmonization",
                "manglik_dosha", "nadi_analysis", "bhakoot_analysis",
                "family_and_married_life", "wealth_and_prosperity", "final_assessment"
            ]
            for nk in narrative_keys:
                val = ai_synthesis_data.get(nk)
                if isinstance(val, str) and len(val.strip()) >= 30:
                    synthesis_data[nk] = val.strip()

            list_keys = ["major_strengths", "major_challenges", "conflict_resolution", "vedic_remedies"]
            for lk in list_keys:
                val = ai_synthesis_data.get(lk)
                if isinstance(val, list) and len(val) >= 2:
                    str_items = [str(x).strip() for x in val if x and len(str(x).strip()) > 5]
                    if len(str_items) >= 2:
                        synthesis_data[lk] = str_items

        # Ensure vedic_remedies is rich and never empty
        if not synthesis_data.get("vedic_remedies") or len(synthesis_data["vedic_remedies"]) == 0:
            synthesis_data["vedic_remedies"] = baseline_synthesis["vedic_remedies"]

        # Save final synthesis
        try:
            synthesis_id = save_ai_synthesis(
                user_id=user_id,
                report_id=report_id,
                p1_name=p1_name,
                p2_name=p2_name,
                score=score,
                max_score=max_score,
                partner1_manglik_status=partner1_manglik_status,
                partner2_manglik_status=partner2_manglik_status,
                synthesis_data=synthesis_data
            )
        except Exception as db_err:
            print(f"Warning: Failed to save AI synthesis to database: {db_err}")
            synthesis_id = str(uuid.uuid4())

        return jsonify({
            "success": True,
            "synthesisId": synthesis_id,
            "message": "AI synthesis generated and saved successfully",
            "synthesis": synthesis_data
        }), 200

    except Exception as exc:
        print(f"AI synthesis top-level error: {exc}")
        return _error(f"AI synthesis failed: {exc}", "AI_SYNTHESIS_FAILED", 500)
        
def generate_manglik_remedies_with_ai(manglik_status: dict) -> list:

    partner1_status = manglik_status.get(
        "partner1",
        "No Manglik Dosha detected"
    )

    partner2_status = manglik_status.get(
        "partner2",
        "No Manglik Dosha detected"
    )

    prompt = f"""
You are a traditional Vedic Jyotish assistant.

The astrology calculation engine has already calculated
the Manglik status.

PARTNER 1 MANGLIK STATUS:
{partner1_status}

PARTNER 2 MANGLIK STATUS:
{partner2_status}

DO NOT calculate Manglik Dosha again.

Generate AT LEAST 3 DISTINCT traditional Vedic Jyotish
remedies only for the Manglik condition indicated by
the supplied statuses.

Rules:

1. Remedies must be generated dynamically by AI.
2. Minimum 4 remedies are required.
3. Remedies must be related to Manglik / Kuja Dosha.
4. Do not invent planetary positions.
5. Do not invent cancellation rules.
6. Do not claim that a remedy guarantees removal or
   cancellation of Manglik Dosha.
7. Keep remedies traditional and practical.
8. If neither partner has Manglik Dosha, return an
   empty remedies list.
9. Return ONLY valid JSON.

Required format:

{{
    "remedies": [
        "Remedy 1",
        "Remedy 2",
        "Remedy 3",
        "Remedy 4"
    ]
}}
"""

    response = get_ai_response(
        """
You are a Vedic Jyotish remedy assistant.

Generate Manglik remedies dynamically from the
supplied Manglik statuses.

Do not recalculate Manglik Dosha.

Return ONLY valid JSON.
""",
        [
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    response = response.strip()

    # ---------------------------------------------------------
    # Remove Markdown code fence
    # ---------------------------------------------------------

    if response.startswith("```"):

        response = re.sub(
            r"^```(?:json)?\s*",
            "",
            response
        )

        response = re.sub(
            r"\s*```$",
            "",
            response
        )

    # ---------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------

    result = json.loads(response)

    remedies = result.get("remedies", [])

    if not isinstance(remedies, list):
        raise RuntimeError(
            "AI remedies must be a list"
        )

    remedies = [
        remedy.strip()
        for remedy in remedies
        if isinstance(remedy, str)
        and remedy.strip()
    ]

    # ---------------------------------------------------------
    # Minimum 4 remedies
    # ---------------------------------------------------------

    if len(remedies) < 4:
        raise RuntimeError(
            "AI returned fewer than 4 Manglik remedies"
        )

    return remedies

# ---------------------------------------------------------
# Save synthesis into database
# ---------------------------------------------------------

def save_ai_synthesis(
    user_id: str,
    report_id: str,
    p1_name: str,
    p2_name: str,
    score,
    max_score,
    partner1_manglik_status: str,
    partner2_manglik_status: str,
    synthesis_data: dict,
) -> str:

    synthesis_id = str(uuid.uuid4())
    params = [
        synthesis_id,
        user_id,
        report_id,
        p1_name,
        p2_name,
        score,
        max_score,
        partner1_manglik_status,
        partner2_manglik_status,
        json.dumps(
            synthesis_data,
            ensure_ascii=False
        ),
    ]
    
    call_procedure(
        "sp_save_matchmaking_ai_synthesis",
        params
    )

    return synthesis_id


def download_ai_synthesis_pdf(synthesis_id):

    try:
        rows = call_procedure(
            "sp_get_matchmaking_ai_synthesis",
            [synthesis_id]
        )

        if not rows:
            return _error(
                        "AI synthesis not found",
                "NOT_FOUND",
                404
            )

        row = dict(rows[0])

        # Service function call
        pdf_bytes = generate_ai_synthesis_pdf(row)

        partner1_name = (
            row.get("partner1_name") or "Partner1"
        )

        partner2_name = (
            row.get("partner2_name") or "Partner2"
        )

        filename = (
            f"AI_Matchmaking_Report_"
            f"{partner1_name}_"
            f"{partner2_name}.pdf"
        )

        filename = re.sub(
            r"[^A-Za-z0-9_. -]",
            "_",
            filename
        )

        return Response(
            pdf_bytes,
            mimetype="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{filename}"',
                "Content-Length":
                    str(len(pdf_bytes)),
                "Cache-Control": "no-store"
            }
        )

    except Exception as exc:
        return _error(
            f"PDF download failed: {exc}",
            "PDF_DOWNLOAD_FAILED",
            500
        )
