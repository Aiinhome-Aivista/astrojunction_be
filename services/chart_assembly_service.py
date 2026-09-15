"""
chart_assembly_service.py
Assembles a fully-resolved VedicChart from raw ephemeris data.
Zodiac sign reference data is loaded from the `zodiac_signs` DB table (with fallback).
Returns planet positions, houses, ascendant, KP sub-lords — all mapped to
the exact same TypeScript PlanetPosition / HouseData shape the frontend expects.
"""

from datetime import datetime

# ─── DB-backed reference data loader ─────────────────────────────────────────

_ZODIAC_CACHE = None  # module-level cache (populated once per server lifetime)

# Fallback if DB is unavailable
_ZODIAC_FALLBACK = [
    {"name": "Aries",       "sanskrit": "Mesha",        "lord": "Mars",    "element": "Fire",  "symbol": "♈"},
    {"name": "Taurus",      "sanskrit": "Vrishabha",   "lord": "Venus",   "element": "Earth", "symbol": "♉"},
    {"name": "Gemini",      "sanskrit": "Mithuna",    "lord": "Mercury", "element": "Air",   "symbol": "♊"},
    {"name": "Cancer",      "sanskrit": "Karka",       "lord": "Moon",    "element": "Water", "symbol": "♋"},
    {"name": "Leo",         "sanskrit": "Simha",       "lord": "Sun",     "element": "Fire",  "symbol": "♌"},
    {"name": "Virgo",       "sanskrit": "Kanya",      "lord": "Mercury", "element": "Earth", "symbol": "♍"},
    {"name": "Libra",       "sanskrit": "Tula",        "lord": "Venus",   "element": "Air",   "symbol": "♎"},
    {"name": "Scorpio",     "sanskrit": "Vrishchika",  "lord": "Mars",   "element": "Water", "symbol": "♏"},
    {"name": "Sagittarius", "sanskrit": "Dhanu",        "lord": "Jupiter", "element": "Fire",  "symbol": "♐"},
    {"name": "Capricorn",   "sanskrit": "Makara",       "lord": "Saturn",  "element": "Earth", "symbol": "♑"},
    {"name": "Aquarius",    "sanskrit": "Kumbha",     "lord": "Saturn",  "element": "Air",   "symbol": "♒"},
    {"name": "Pisces",      "sanskrit": "Meena",        "lord": "Jupiter", "element": "Water", "symbol": "♓"},
]

# Ordered by sidereal sign index (Aries=0 to Pisces=11)
_SIGN_ID_ORDER = [
    "aries","taurus","gemini","cancer","leo","virgo",
    "libra","scorpio","sagittarius","capricorn","aquarius","pisces"
]

def _get_zodiac_signs():
    """Load zodiac_signs from DB (cached). Falls back to hardcoded list."""
    global _ZODIAC_CACHE
    if _ZODIAC_CACHE is not None:
        return _ZODIAC_CACHE
    try:
        from database.db_connection import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, sanskrit, symbol, element, ruling_planet "
            "FROM zodiac_signs ORDER BY FIELD(id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            _SIGN_ID_ORDER
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        if len(rows) == 12:
            _ZODIAC_CACHE = [
                {
                    "name":     r["name"],
                    "sanskrit": r["sanskrit"],
                    "lord":     r["ruling_planet"],
                    "element":  r["element"],
                    "symbol":   r["symbol"],
                }
                for r in rows
            ]
            print("[chart_assembly] Zodiac signs loaded from DB ✓")
            return _ZODIAC_CACHE
    except Exception as e:
        print(f"[chart_assembly] DB zodiac load failed, using fallback: {e}")
    _ZODIAC_CACHE = _ZODIAC_FALLBACK
    return _ZODIAC_CACHE

NAKSHATRAS = [
    {"name": "Ashwini",          "lord": "Ketu"},    {"name": "Bharani",          "lord": "Venus"},
    {"name": "Krittika",         "lord": "Sun"},     {"name": "Rohini",           "lord": "Moon"},
    {"name": "Mrigashira",       "lord": "Mars"},    {"name": "Ardra",            "lord": "Rahu"},
    {"name": "Punarvasu",        "lord": "Jupiter"}, {"name": "Pushya",           "lord": "Saturn"},
    {"name": "Ashlesha",         "lord": "Mercury"}, {"name": "Magha",            "lord": "Ketu"},
    {"name": "Purva Phalguni",   "lord": "Venus"},   {"name": "Uttara Phalguni",  "lord": "Sun"},
    {"name": "Hasta",            "lord": "Moon"},    {"name": "Chitra",           "lord": "Mars"},
    {"name": "Swati",            "lord": "Rahu"},    {"name": "Vishakha",         "lord": "Jupiter"},
    {"name": "Anuradha",         "lord": "Saturn"},  {"name": "Jyeshtha",         "lord": "Mercury"},
    {"name": "Mula",             "lord": "Ketu"},    {"name": "Purva Ashadha",    "lord": "Venus"},
    {"name": "Uttara Ashadha",   "lord": "Sun"},     {"name": "Shravana",         "lord": "Moon"},
    {"name": "Dhanishta",        "lord": "Mars"},    {"name": "Shatabhisha",      "lord": "Rahu"},
    {"name": "Purva Bhadrapada", "lord": "Jupiter"}, {"name": "Uttara Bhadrapada","lord": "Saturn"},
    {"name": "Revati",           "lord": "Mercury"},
]

PLANET_META = {
    "sun":     {"name": "Sun",     "sanskritName": "Surya (सूर्य)",    "symbol": "☉", "gemstone": "gemstone.sun",     "element": "element.fire"},
    "moon":    {"name": "Moon",    "sanskritName": "Chandra (चन्द्र)", "symbol": "☽", "gemstone": "gemstone.moon",    "element": "element.water"},
    "mars":    {"name": "Mars",    "sanskritName": "Mangal (मंगल)",    "symbol": "♂", "gemstone": "gemstone.mars",    "element": "element.fire"},
    "mercury": {"name": "Mercury", "sanskritName": "Budha (बुध)",      "symbol": "☿", "gemstone": "gemstone.mercury", "element": "element.earth"},
    "jupiter": {"name": "Jupiter", "sanskritName": "Guru (गुरु)",      "symbol": "♃", "gemstone": "gemstone.jupiter", "element": "element.ether"},
    "venus":   {"name": "Venus",   "sanskritName": "Shukra (शुक्र)",   "symbol": "♀", "gemstone": "gemstone.venus",   "element": "element.water"},
    "saturn":  {"name": "Saturn",  "sanskritName": "Shani (शनि)",      "symbol": "♄", "gemstone": "gemstone.saturn",  "element": "element.air"},
    "rahu":    {"name": "Rahu",    "sanskritName": "Rahu (राहु)",      "symbol": "☊", "gemstone": "gemstone.rahu",    "element": "element.shadow"},
    "ketu":    {"name": "Ketu",    "sanskritName": "Ketu (केतु)",      "symbol": "☋", "gemstone": "gemstone.ketu",    "element": "element.shadow"},
}

PLANET_ORDER = ["sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu"]

DIGNITY_RULES = {
    "sun":     {"exalted": 0, "own": [4], "debilitated": 6},
    "moon":    {"exalted": 1, "own": [3], "debilitated": 7},
    "mars":    {"exalted": 9, "own": [0, 7], "debilitated": 3},
    "mercury": {"exalted": 5, "own": [2, 5], "debilitated": 11},
    "jupiter": {"exalted": 3, "own": [8, 11], "debilitated": 9},
    "venus":   {"exalted": 11, "own": [1, 6], "debilitated": 5},
    "saturn":  {"exalted": 6, "own": [9, 10], "debilitated": 0},
}

HOUSE_SIGNIFICANCES = [
    {"name": "Tanur Bhava",  "sanskrit": "तनु भाव (Lagna)",     "significance": "Self, Personality, Physical Body, Vitality, Life Path & Head"},
    {"name": "Dhana Bhava",  "sanskrit": "धन भाव",              "significance": "Wealth, Speech, Family lineage, Food habits, Face & Right Eye"},
    {"name": "Sahaja Bhava", "sanskrit": "सहज भाव",             "significance": "Siblings, Courage, Communication, Short Journeys, Skill with Hands"},
    {"name": "Sukha Bhava",  "sanskrit": "सुख भाव (Matru)",     "significance": "Mother, Home, Land, Vehicles, Inner Peace, Heart & Education"},
    {"name": "Putra Bhava",  "sanskrit": "पुत्र भाव",           "significance": "Children, Intellect, Creativity, Speculation, Mantras & Past Karma"},
    {"name": "Shatru Bhava", "sanskrit": "शत्रु भाव (Roga/Rina)","significance": "Enemies, Debts, Diseases, Daily Work, Service & Obstacles"},
    {"name": "Jaya Bhava",   "sanskrit": "जाया भाव (Kalatra)",  "significance": "Spouse, Marriage, Business Partnerships, Public Relations, Contracts"},
    {"name": "Mrityu Bhava", "sanskrit": "मृत्यु भाव (Randhra)","significance": "Longevity, Sudden Transformation, Occult, Inheritance, Hidden Truths"},
    {"name": "Dharma Bhava", "sanskrit": "धर्म भाव (Bhagya)",  "significance": "Father, Guru, Higher Wisdom, Luck, Long Pilgrimages, Righteousness"},
    {"name": "Karma Bhava",  "sanskrit": "कर्म भाव",            "significance": "Career, Profession, Fame, Social Status, Authority & Achievements"},
    {"name": "Labha Bhava",  "sanskrit": "लाभ भाव (Aya)",       "significance": "Gains, Income, Elder Siblings, Desires Fulfillment, Large Networks"},
    {"name": "Vyaya Bhava",  "sanskrit": "व्यय भाव (Moksha)",   "significance": "Expenditure, Foreign Lands, Hospitalization, Isolation, Bed Pleasures & Liberation"},
]

# KP Sub-Lord sequence (Vimshottari order)
KP_SEQ = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
KP_LORD_IDX = {v: i for i, v in enumerate(KP_SEQ)}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _dignity(planet_id: str, sign_idx: int) -> str:
    rules = DIGNITY_RULES.get(planet_id)
    if not rules:
        return "Neutral"
    if sign_idx == rules.get("exalted"):
        return "Exalted"
    if sign_idx in rules.get("own", []):
        return "Own"
    if sign_idx == rules.get("debilitated"):
        return "Debilitated"
    return "Neutral"


def _kp_sub_lord(total_degree: float, nak_idx: int) -> str:
    nak_lord = NAKSHATRAS[nak_idx]["lord"]
    nak_span = 360.0 / 27.0
    pos_in_nak = total_degree % nak_span
    sub_lord_offset = int((pos_in_nak / nak_span) * 9) % 9
    start_idx = KP_LORD_IDX.get(nak_lord, 0)
    return KP_SEQ[(start_idx + sub_lord_offset) % 9]


# ─── Main Assembler ───────────────────────────────────────────────────────────

def assemble_full_chart(ephemeris_data: dict, profile: dict) -> dict:
    """
    Takes raw ephemeris_data from calculate_chart_data() and profile dict.
    Returns a fully assembled chart matching the frontend TypeScript interface.
    Zodiac sign data is loaded from the DB (cached after first load).
    """
    ZODIAC_SIGNS = _get_zodiac_signs()  # DB-backed, cached
    asc_deg = ephemeris_data.get("ascendant", 0.0)
    lagna_sign_idx = int(asc_deg / 30) % 12
    lagna_nak_idx = int(asc_deg / 13.3333) % 27

    raw_planets = ephemeris_data.get("planets", {})
    raw_karakas = ephemeris_data.get("karakas", {})  # e.g. {"sun": "AK (Atmakaraka)", ...}

    # ── Planet Positions ─────────────────────────────────────────────────────
    assembled_planets = []
    for p_id in PLANET_ORDER:
        if p_id not in raw_planets:
            continue
        p_raw = raw_planets[p_id]
        tot_deg = float(p_raw.get("longitude", 0.0))
        is_retro = bool(p_raw.get("isRetrograde", False))

        sign_idx = int(tot_deg / 30) % 12
        deg_in_sign = round(tot_deg % 30, 2)
        nak_idx = int(tot_deg / 13.3333) % 27
        pada = int((tot_deg % 13.3333) / 3.3333) + 1
        house = ((sign_idx - lagna_sign_idx + 12) % 12) + 1

        meta = PLANET_META.get(p_id, {})
        nak = NAKSHATRAS[nak_idx]
        sign = ZODIAC_SIGNS[sign_idx]

        assembled_planets.append({
            "id":            p_id,
            "name":          meta.get("name", p_id.capitalize()),
            "sanskritName":  meta.get("sanskritName", ""),
            "symbol":        meta.get("symbol", ""),
            "signIndex":     sign_idx,
            "signName":      sign["name"],
            "signSanskrit":  sign["sanskrit"],
            "degree":        deg_in_sign,
            "totalDegree":   round(tot_deg, 2),
            "house":         house,
            "isRetrograde":  is_retro,
            "nakshatra":     nak["name"],
            "nakshatraLord": nak["lord"],
            "pada":          pada,
            "dignity":       _dignity(p_id, sign_idx),
            "gemstone":      meta.get("gemstone", ""),
            "element":       meta.get("element", ""),
            "karaka":        raw_karakas.get(p_id),          # Jaimini karaka (optional)
            "kpSubLord":     _kp_sub_lord(tot_deg, nak_idx), # KP Sub-Lord
        })

    # ── Houses ───────────────────────────────────────────────────────────────
    assembled_houses = []
    for i in range(12):
        house_num = i + 1
        sign_idx = (lagna_sign_idx + i) % 12
        sign = ZODIAC_SIGNS[sign_idx]
        sig = HOUSE_SIGNIFICANCES[i]

        # KP Cusps from Placidus
        kp_cusp_deg = 0.0
        kp_houses = ephemeris_data.get("kpSystem", {}).get("houses", [])
        if i < len(kp_houses):
            kp_cusp_deg = kp_houses[i]
        kp_cusp_nak_idx = int(kp_cusp_deg / 13.3333) % 27
        kp_star_lord = NAKSHATRAS[kp_cusp_nak_idx]["lord"]
        kp_sub_lord = _kp_sub_lord(kp_cusp_deg, kp_cusp_nak_idx)

        occupying = [p for p in assembled_planets if p["house"] == house_num]

        assembled_houses.append({
            "houseNumber":  house_num,
            "signIndex":    sign_idx,
            "signName":     sign["name"],
            "signSanskrit": sign["sanskrit"],
            "signLord":     sign["lord"],
            "sanskritName": sig["sanskrit"],
            "significance": sig["significance"],
            "kpStarLord":   kp_star_lord,
            "kpSubLord":    kp_sub_lord,
            "planets":      occupying,
        })

    # ── Ascendant ─────────────────────────────────────────────────────────────
    asc_sign = ZODIAC_SIGNS[lagna_sign_idx]
    ascendant = {
        "signIndex":   lagna_sign_idx,
        "degree":      round(asc_deg % 30, 2),
        "signName":    asc_sign["name"],
        "signSanskrit": asc_sign["sanskrit"],
        "nakshatra":   NAKSHATRAS[lagna_nak_idx]["name"],
    }

    # ── Dashas: enrich with isCurrent & subPeriods for timeline & LLM ─────────
    raw_dashas = ephemeris_data.get("dashas", [])
    today_str = datetime.now().strftime("%Y-%m-%d")
    enriched_dashas = []

    for d in raw_dashas:
        start_str = str(d.get("startDate", ""))[:10]
        end_str   = str(d.get("endDate", ""))[:10]
        is_current_md = bool(start_str and end_str and start_str <= today_str <= end_str)

        try:
            start_yr = int(start_str[:4])
        except (ValueError, IndexError):
            start_yr = 2000
        try:
            end_yr = int(end_str[:4])
        except (ValueError, IndexError):
            end_yr = 2020

        raw_subs = d.get("antardashas") or d.get("subPeriods") or []
        sub_periods = []
        for sub in raw_subs:
            s_start = str(sub.get("startDate", ""))[:10]
            s_end   = str(sub.get("endDate", ""))[:10]
            is_current_ad = bool(is_current_md and s_start and s_end and s_start <= today_str <= s_end)
            try:
                sub_s_yr = int(s_start[:4])
            except (ValueError, IndexError):
                sub_s_yr = start_yr
            try:
                sub_e_yr = int(s_end[:4])
            except (ValueError, IndexError):
                sub_e_yr = end_yr

            sub_periods.append({
                "planet":    sub.get("planet", ""),
                "sanskrit":  sub.get("sanskrit", ""),
                "startDate": s_start,
                "endDate":   s_end,
                "startYear": sub_s_yr,
                "endYear":   sub_e_yr,
                "isCurrent": is_current_ad,
                "pratyantardashas": sub.get("pratyantardashas", []),
            })

        enriched_dashas.append({
            "planet":      d.get("planet", ""),
            "sanskrit":    d.get("sanskrit", ""),
            "startDate":   start_str,
            "endDate":     end_str,
            "startYear":   start_yr,
            "endYear":     end_yr,
            "isCurrent":   is_current_md,
            "subPeriods":  sub_periods,
            "antardashas": sub_periods,
        })

    return {
        "system":      profile.get("horoscopeSystem", "vedic"),
        "systemTitle": "Vedic Sidereal (Lahiri Ayanamsha)" if profile.get("horoscopeSystem") != "western" else "Western Tropical",
        "ayanamsha":   ephemeris_data.get("ayanamsha", 0.0),
        "ascendant":   ascendant,
        "planets":     assembled_planets,
        "houses":      assembled_houses,
        "dashas":      enriched_dashas,
        "yogas":       ephemeris_data.get("yogas", []),
        "doshas":      ephemeris_data.get("doshas", []),
        "divisionalCharts": ephemeris_data.get("divisionalCharts", {}),
        "aspects":     ephemeris_data.get("aspects", []),
        "gemstones":   ephemeris_data.get("gemstones", []),
        "kpSystem":    ephemeris_data.get("kpSystem", {}),
    }
