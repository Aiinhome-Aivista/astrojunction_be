"""
Ephemeris Module for AstroJunction
Calculates real-time planetary snapshots for noon IST using Swiss Ephemeris (pyswisseph).
Supports both Tropical (Western) and Sidereal (Lahiri) systems, Moon Nakshatra, Pada, Tithi,
and Major Aspects.
"""

import swisseph as swe
from datetime import datetime, date, timedelta
import json
import calendar

ZODIAC_SIGNS = [
    "aries", "taurus", "gemini", "cancer",
    "leo", "virgo", "libra", "scorpio",
    "sagittarius", "capricorn", "aquarius", "pisces"
]

NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

TITHIS = [
    "Shukla Pratipada", "Shukla Dwitiya", "Shukla Tritiya", "Shukla Chaturthi",
    "Shukla Panchami", "Shukla Shashthi", "Shukla Saptami", "Shukla Ashtami",
    "Shukla Navami", "Shukla Dashami", "Shukla Ekadashi", "Shukla Dvadashi",
    "Shukla Trayodashi", "Shukla Chaturdashi", "Purnima",
    "Krishna Pratipada", "Krishna Dwitiya", "Krishna Tritiya", "Krishna Chaturthi",
    "Krishna Panchami", "Krishna Shashthi", "Krishna Saptami", "Krishna Ashtami",
    "Krishna Navami", "Krishna Dashami", "Krishna Ekadashi", "Krishna Dvadashi",
    "Krishna Trayodashi", "Krishna Chaturdashi", "Amavasya"
]

PLANET_IDS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "rahu": swe.MEAN_NODE
}


def _get_julian_day_noon_ist(target_date: date) -> float:
    """12:00 PM IST is 06:30 AM UTC (hour 6.5)"""
    return swe.julday(target_date.year, target_date.month, target_date.day, 6.5, 1)


def _calc_system_positions(jd_ut: float, is_sidereal: bool = False) -> dict:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if is_sidereal:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        flags |= swe.FLG_SIDEREAL

    planets = {}
    for name, p_id in PLANET_IDS.items():
        res, _ = swe.calc_ut(jd_ut, p_id, flags)
        lon = res[0] % 360.0
        speed = res[3]
        sign_idx = int(lon // 30)
        deg_in_sign = round(lon % 30.0, 2)

        planets[name] = {
            "sign": ZODIAC_SIGNS[sign_idx],
            "sign_index": sign_idx,
            "degree_in_sign": deg_in_sign,
            "longitude": round(lon, 2),
            "is_retrograde": speed < 0
        }

    # Ketu is exactly 180 degrees opposite to Rahu
    rahu_lon = planets["rahu"]["longitude"]
    ketu_lon = (rahu_lon + 180.0) % 360.0
    ketu_sign_idx = int(ketu_lon // 30)
    planets["ketu"] = {
        "sign": ZODIAC_SIGNS[ketu_sign_idx],
        "sign_index": ketu_sign_idx,
        "degree_in_sign": round(ketu_lon % 30.0, 2),
        "longitude": round(ketu_lon, 2),
        "is_retrograde": planets["rahu"]["is_retrograde"]
    }

    return planets


def _calc_aspects(planets: dict, max_orb: float = 6.0) -> list:
    """Computes major aspects (Conjunction 0°, Sextile 60°, Square 90°, Trine 120°, Opposition 180°)"""
    aspect_targets = [
        ("conjunction", 0.0),
        ("sextile", 60.0),
        ("square", 90.0),
        ("trine", 120.0),
        ("opposition", 180.0)
    ]
    p_names = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
    aspects = []

    for i in range(len(p_names)):
        for j in range(i + 1, len(p_names)):
            p1 = p_names[i]
            p2 = p_names[j]
            lon1 = planets[p1]["longitude"]
            lon2 = planets[p2]["longitude"]

            diff = abs(lon1 - lon2)
            shortest_dist = min(diff, 360.0 - diff)

            for aspect_name, target_angle in aspect_targets:
                orb = abs(shortest_dist - target_angle)
                if orb <= max_orb:
                    aspects.append({
                        "planet1": p1,
                        "planet2": p2,
                        "aspect": aspect_name,
                        "angle": round(shortest_dist, 2),
                        "orb": round(orb, 2)
                    })
                    break

    return aspects


def get_snapshot(target_date: date = None) -> dict:
    """
    Computes planetary snapshot for noon IST on the given date in both Tropical and Sidereal systems.
    """
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    jd_ut = _get_julian_day_noon_ist(target_date)

    # 1. Tropical positions
    tropical_planets = _calc_system_positions(jd_ut, is_sidereal=False)
    tropical_aspects = _calc_aspects(tropical_planets)

    # 2. Sidereal positions (Lahiri)
    sidereal_planets = _calc_system_positions(jd_ut, is_sidereal=True)
    sidereal_aspects = _calc_aspects(sidereal_planets)

    # 3. Moon Nakshatra & Pada (Sidereal)
    moon_sid_lon = sidereal_planets["moon"]["longitude"]
    nakshatra_span = 360.0 / 27.0  # 13° 20' = 13.3333333°
    nak_idx = int(moon_sid_lon // nakshatra_span)
    nak_name = NAKSHATRAS[nak_idx % 27]
    deg_in_nak = moon_sid_lon % nakshatra_span
    pada = int(deg_in_nak // (nakshatra_span / 4.0)) + 1

    # 4. Tithi Calculation (Difference between Moon and Sun longitude)
    sun_sid_lon = sidereal_planets["sun"]["longitude"]
    elongation = (moon_sid_lon - sun_sid_lon) % 360.0
    tithi_idx = int(elongation // 12.0)
    tithi_name = TITHIS[tithi_idx % 30]

    # 5. Ayanamsha (Lahiri difference)
    ayanamsa_deg = round(swe.get_ayanamsa_ut(jd_ut), 2)

    return {
        "date": str(target_date),
        "timezone": "Asia/Kolkata (Noon IST)",
        "ayanamsa": ayanamsa_deg,
        "tropical": {
            "planets": tropical_planets,
            "aspects": tropical_aspects
        },
        "sidereal": {
            "planets": sidereal_planets,
            "aspects": sidereal_aspects,
            "moon_nakshatra": {
                "name": nak_name,
                "pada": pada,
                "degree_in_nakshatra": round(deg_in_nak, 2)
            },
            "tithi": {
                "name": tithi_name,
                "index": tithi_idx + 1,
                "elongation_degrees": round(elongation, 2)
            }
        }
    }



def get_year_eclipses(year: int) -> list:
    """
    Computes all solar and lunar eclipses for the given calendar year in IST
    using Swiss Ephemeris (swe.sol_eclipse_when_glob and swe.lun_eclipse_when).
    Returns a sorted list of eclipse events with date, eclipse type, tropical sign, and sidereal sign.
    """
    tjd = swe.julday(year, 1, 1, 0.0)
    end_tjd = swe.julday(year, 12, 31, 23.9)
    eclipses = []

    # 1. Solar eclipses
    cur_tjd = tjd
    while cur_tjd < end_tjd:
        res = swe.sol_eclipse_when_glob(cur_tjd)
        if not res[0]:
            break
        ecl_tjd = res[1][0]
        if ecl_tjd > end_tjd:
            break
        ecl_mask = res[0]
        ecl_type = "Solar Eclipse"
        if ecl_mask & swe.ECL_TOTAL:
            ecl_type = "Total Solar Eclipse"
        elif ecl_mask & swe.ECL_ANNULAR:
            ecl_type = "Annular Solar Eclipse"
        elif ecl_mask & swe.ECL_PARTIAL:
            ecl_type = "Partial Solar Eclipse"

        y, m, d, h = swe.revjul(ecl_tjd)
        date_str = f"{y:04d}-{m:02d}-{int(d):02d}"
        r, _ = swe.calc_ut(ecl_tjd, swe.SUN)
        trop_s = ZODIAC_SIGNS[int((r[0] % 360) // 30)]
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        r_sid, _ = swe.calc_ut(ecl_tjd, swe.SUN, swe.FLG_SIDEREAL)
        sid_s = ZODIAC_SIGNS[int((r_sid[0] % 360) // 30)]
        eclipses.append({
            "date": date_str,
            "type": ecl_type,
            "tropical_sign": trop_s,
            "sidereal_sign": sid_s,
            "tjd": ecl_tjd
        })
        cur_tjd = ecl_tjd + 20.0

    # 2. Lunar eclipses
    cur_tjd = tjd
    while cur_tjd < end_tjd:
        res = swe.lun_eclipse_when(cur_tjd)
        if not res[0]:
            break
        ecl_tjd = res[1][0]
        if ecl_tjd > end_tjd:
            break
        ecl_mask = res[0]
        ecl_type = "Lunar Eclipse"
        if ecl_mask & swe.ECL_TOTAL:
            ecl_type = "Total Lunar Eclipse"
        elif ecl_mask & swe.ECL_PARTIAL:
            ecl_type = "Partial Lunar Eclipse"
        elif ecl_mask & swe.ECL_PENUMBRAL:
            ecl_type = "Penumbral Lunar Eclipse"

        y, m, d, h = swe.revjul(ecl_tjd)
        date_str = f"{y:04d}-{m:02d}-{int(d):02d}"
        r, _ = swe.calc_ut(ecl_tjd, swe.MOON)
        trop_s = ZODIAC_SIGNS[int((r[0] % 360) // 30)]
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        r_sid, _ = swe.calc_ut(ecl_tjd, swe.MOON, swe.FLG_SIDEREAL)
        sid_s = ZODIAC_SIGNS[int((r_sid[0] % 360) // 30)]
        eclipses.append({
            "date": date_str,
            "type": ecl_type,
            "tropical_sign": trop_s,
            "sidereal_sign": sid_s,
            "tjd": ecl_tjd
        })
        cur_tjd = ecl_tjd + 20.0

    eclipses.sort(key=lambda x: x["tjd"])
    for e in eclipses:
        del e["tjd"]
    return eclipses


def get_year_planetary_events(year: int, is_sidereal: bool = False) -> dict:
    """
    Computes sign changes (ingresses) for slow planets (Jupiter, Saturn, Rahu, Ketu),
    compact list of inner planet ingresses (Sun, Mercury, Venus, Mars),
    and retrograde/direct stations of Mercury, Venus, Mars, Jupiter, Saturn across the year.
    Pure pyswisseph, noon IST, zero LLM calls.
    """
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if is_sidereal:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        flags |= swe.FLG_SIDEREAL

    tracked = {
        "sun": swe.SUN,
        "mercury": swe.MERCURY,
        "venus": swe.VENUS,
        "mars": swe.MARS,
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN,
        "rahu": swe.MEAN_NODE,
    }

    start_dt = date(year, 1, 1)
    end_dt = date(year, 12, 31)
    total_days = (end_dt - start_dt).days + 1

    slow_planets = {"jupiter", "saturn", "rahu", "ketu"}
    inner_planets = {"sun", "mercury", "venus", "mars"}
    station_planets = {"mercury", "venus", "mars", "jupiter", "saturn"}

    prev_state = None
    slow_ingresses = []
    inner_ingresses = []
    stations = []

    for d in range(total_days):
        cur_d = start_dt + timedelta(days=d)
        jd = swe.julday(cur_d.year, cur_d.month, cur_d.day, 6.5, 1)  # Noon IST
        state = {}
        for p, pid in tracked.items():
            r, _ = swe.calc_ut(jd, pid, flags)
            lon = r[0] % 360.0
            spd = r[3]
            s_idx = int(lon // 30)
            state[p] = {
                "sign_idx": s_idx,
                "sign": ZODIAC_SIGNS[s_idx],
                "spd": spd,
                "is_retro": spd < 0
            }

        # Ketu is opposite to Rahu
        k_idx = (state["rahu"]["sign_idx"] + 6) % 12
        state["ketu"] = {
            "sign_idx": k_idx,
            "sign": ZODIAC_SIGNS[k_idx],
            "spd": state["rahu"]["spd"],
            "is_retro": state["rahu"]["is_retro"]
        }

        if prev_state:
            for p in list(tracked.keys()) + ["ketu"]:
                if state[p]["sign_idx"] != prev_state[p]["sign_idx"]:
                    ev = {
                        "planet": p,
                        "from_sign": prev_state[p]["sign"],
                        "to_sign": state[p]["sign"],
                        "date": str(cur_d)
                    }
                    if p in slow_planets:
                        slow_ingresses.append(ev)
                    elif p in inner_planets:
                        inner_ingresses.append(
                            f"{p.capitalize()} enters {state[p]['sign'].capitalize()} ({str(cur_d)[5:]})"
                        )

                if p in station_planets:
                    if not prev_state[p]["is_retro"] and state[p]["is_retro"]:
                        stations.append({
                            "planet": p,
                            "event": "Retrograde",
                            "date": str(cur_d)
                        })
                    elif prev_state[p]["is_retro"] and not state[p]["is_retro"]:
                        stations.append({
                            "planet": p,
                            "event": "Direct",
                            "date": str(cur_d)
                        })
        prev_state = state

    return {
        "slow_ingresses": slow_ingresses,
        "inner_ingresses": inner_ingresses,
        "stations": stations
    }


def calc_quarterly_houses(year: int, is_sidereal: bool = False) -> dict:
    """
    Computes which house each slow planet (Jupiter, Saturn, Rahu, Ketu) transits per quarter
    (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec) for all 12 signs, using each sign as house 1.
    """
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if is_sidereal:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        flags |= swe.FLG_SIDEREAL

    q_dates = {
        "Q1 (Jan-Mar)": date(year, 2, 15),
        "Q2 (Apr-Jun)": date(year, 5, 15),
        "Q3 (Jul-Sep)": date(year, 8, 15),
        "Q4 (Oct-Dec)": date(year, 11, 15),
    }
    slow_pids = {
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN,
        "rahu": swe.MEAN_NODE,
    }

    q_planets = {}
    for q, dt in q_dates.items():
        jd = swe.julday(dt.year, dt.month, dt.day, 6.5, 1)
        q_planets[q] = {}
        for p, pid in slow_pids.items():
            r, _ = swe.calc_ut(jd, pid, flags)
            s_idx = int((r[0] % 360) // 30)
            q_planets[q][p] = s_idx
        ketu_idx = (q_planets[q]["rahu"] + 6) % 12
        q_planets[q]["ketu"] = ketu_idx

    houses_per_sign = {}
    for sign_idx, sign in enumerate(ZODIAC_SIGNS):
        houses_per_sign[sign] = {}
        for q in q_dates.keys():
            houses_per_sign[sign][q] = {}
            for p in ["jupiter", "saturn", "rahu", "ketu"]:
                p_s_idx = q_planets[q][p]
                house = ((p_s_idx - sign_idx) % 12) + 1
                houses_per_sign[sign][q][p] = {
                    "house": house,
                    "sign": ZODIAC_SIGNS[p_s_idx]
                }
    return houses_per_sign


def get_period_snapshots(period: str, start_date: date = None) -> dict:
    """
    Returns period snapshots and complete astrological transit summary:
    - daily: 1 snapshot
    - weekly: 7 daily snapshots plus comprehensive weekly summary
    - monthly: every 3rd day across the month plus sign changes and retrograde stations
    - yearly: 24 snapshots (1st and 15th of each month), eclipses, slow planet ingresses,
              inner planet ingresses, retrograde/direct stations, and quarterly house transits
    """
    if start_date is None:
        start_date = date.today()
    elif isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

    if period == "daily":
        sample_days = [0]
        end_date = start_date
    elif period == "weekly":
        sample_days = list(range(7))
        end_date = start_date + timedelta(days=6)
    elif period == "monthly":
        start_date = start_date.replace(day=1)
        _, last_day = calendar.monthrange(start_date.year, start_date.month)
        end_date = start_date.replace(day=last_day)
        total_days = (end_date - start_date).days
        sample_days = sorted(list(set([d for d in range(0, total_days + 1, 3)] + [total_days])))
    elif period == "yearly":
        start_date = start_date.replace(month=1, day=1)
        end_date = start_date.replace(month=12, day=31)
        sample_dates = []
        for m in range(1, 13):
            sample_dates.append(date(start_date.year, m, 1))
            sample_dates.append(date(start_date.year, m, 15))
        sample_days = [(d - start_date).days for d in sample_dates]
    else:
        sample_days = [0]
        end_date = start_date

    snapshots = []
    tropical_sign_changes = []
    tropical_retrograde_stations = []
    tropical_moon_signs = []
    tropical_moon_phases = []
    tropical_slow_aspects = []

    sidereal_sign_changes = []
    sidereal_retrograde_stations = []
    sidereal_moon_signs = []
    sidereal_moon_phases = []
    sidereal_slow_aspects = []

    slow_planets = {"mars", "jupiter", "saturn", "uranus", "neptune", "pluto"}
    seen_trop_aspects = set()
    seen_sid_aspects = set()

    prev_snapshot = None
    for day_offset in sample_days:
        cur_date = start_date + timedelta(days=day_offset)
        snap = get_snapshot(cur_date)
        snapshots.append(snap)

        t_planets = snap["tropical"]["planets"]
        s_planets = snap["sidereal"]["planets"]

        # Track Moon sign per day
        tropical_moon_signs.append({
            "date": str(cur_date),
            "sign": t_planets["moon"]["sign"],
            "degree": t_planets["moon"]["degree_in_sign"]
        })
        sidereal_moon_signs.append({
            "date": str(cur_date),
            "sign": s_planets["moon"]["sign"],
            "degree": s_planets["moon"]["degree_in_sign"],
            "nakshatra": snap["sidereal"]["moon_nakshatra"]["name"]
        })

        # Track slow planet aspects active during this day
        for asp in snap["tropical"]["aspects"]:
            p1, p2 = asp["planet1"], asp["planet2"]
            if (p1 in slow_planets or p2 in slow_planets) and asp["orb"] <= 3.5:
                pair_key = tuple(sorted([p1, p2])) + (asp["aspect"],)
                if pair_key not in seen_trop_aspects:
                    seen_trop_aspects.add(pair_key)
                    tropical_slow_aspects.append({
                        "date": str(cur_date),
                        "planet1": p1,
                        "planet2": p2,
                        "aspect": asp["aspect"],
                        "orb": asp["orb"]
                    })

        for asp in snap["sidereal"]["aspects"]:
            p1, p2 = asp["planet1"], asp["planet2"]
            if (p1 in slow_planets or p2 in slow_planets) and asp["orb"] <= 3.5:
                pair_key = tuple(sorted([p1, p2])) + (asp["aspect"],)
                if pair_key not in seen_sid_aspects:
                    seen_sid_aspects.add(pair_key)
                    sidereal_slow_aspects.append({
                        "date": str(cur_date),
                        "planet1": p1,
                        "planet2": p2,
                        "aspect": asp["aspect"],
                        "orb": asp["orb"]
                    })

        # Check day-over-day transitions
        if prev_snapshot:
            prev_t = prev_snapshot["tropical"]["planets"]
            prev_s = prev_snapshot["sidereal"]["planets"]

            # 1. Tropical sign changes and retrograde stations
            for p_name in ["sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn"]:
                if prev_t[p_name]["sign"] != t_planets[p_name]["sign"]:
                    tropical_sign_changes.append({
                        "planet": p_name,
                        "date": str(cur_date),
                        "from_sign": prev_t[p_name]["sign"],
                        "to_sign": t_planets[p_name]["sign"]
                    })
                if prev_t[p_name]["is_retrograde"] != t_planets[p_name]["is_retrograde"]:
                    tropical_retrograde_stations.append({
                        "planet": p_name,
                        "date": str(cur_date),
                        "status": "Retrograde" if t_planets[p_name]["is_retrograde"] else "Direct"
                    })

            # 2. Sidereal sign changes and retrograde stations
            for p_name in ["sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn"]:
                if prev_s[p_name]["sign"] != s_planets[p_name]["sign"]:
                    sidereal_sign_changes.append({
                        "planet": p_name,
                        "date": str(cur_date),
                        "from_sign": prev_s[p_name]["sign"],
                        "to_sign": s_planets[p_name]["sign"]
                    })
                if prev_s[p_name]["is_retrograde"] != s_planets[p_name]["is_retrograde"]:
                    sidereal_retrograde_stations.append({
                        "planet": p_name,
                        "date": str(cur_date),
                        "status": "Retrograde" if s_planets[p_name]["is_retrograde"] else "Direct"
                    })

            # 3. Moon Phase Transitions (Elongation crossing 0° / 360° or 180°)
            prev_elong = (prev_s["moon"]["longitude"] - prev_s["sun"]["longitude"]) % 360.0
            curr_elong = (s_planets["moon"]["longitude"] - s_planets["sun"]["longitude"]) % 360.0

            if prev_elong > 330.0 and curr_elong < 30.0:
                phase_event = {
                    "date": str(cur_date),
                    "phase": "New Moon",
                    "vedic_phase": "Amavasya"
                }
                tropical_moon_phases.append(phase_event)
                sidereal_moon_phases.append(phase_event)
            elif prev_elong < 180.0 <= curr_elong:
                phase_event = {
                    "date": str(cur_date),
                    "phase": "Full Moon",
                    "vedic_phase": "Purnima"
                }
                tropical_moon_phases.append(phase_event)
                sidereal_moon_phases.append(phase_event)

        prev_snapshot = snap

    yearly_eclipses = []
    tropical_yearly_events = {}
    sidereal_yearly_events = {}
    tropical_quarterly_houses = {}
    sidereal_quarterly_houses = {}

    if period == "yearly":
        year = start_date.year
        yearly_eclipses = get_year_eclipses(year)
        tropical_yearly_events = get_year_planetary_events(year, is_sidereal=False)
        sidereal_yearly_events = get_year_planetary_events(year, is_sidereal=True)
        tropical_quarterly_houses = calc_quarterly_houses(year, is_sidereal=False)
        sidereal_quarterly_houses = calc_quarterly_houses(year, is_sidereal=True)

    return {
        "period": period,
        "period_start": str(start_date),
        "period_end": str(end_date),
        "snapshots": snapshots,
        "primary_snapshot": snapshots[0],
        "tropical_summary": {
            "sign_changes": tropical_sign_changes,
            "retrograde_stations": tropical_retrograde_stations,
            "moon_signs": tropical_moon_signs,
            "moon_phases": tropical_moon_phases,
            "slow_planet_aspects": tropical_slow_aspects,
            "slow_planet_ingresses": tropical_yearly_events.get("slow_ingresses", []),
            "inner_planet_ingresses": tropical_yearly_events.get("inner_ingresses", []),
            "stations": tropical_yearly_events.get("stations", []),
            "eclipses": [
                {"date": e["date"], "type": e["type"], "sign": e["tropical_sign"]}
                for e in yearly_eclipses
            ],
            "quarterly_houses": tropical_quarterly_houses
        },
        "sidereal_summary": {
            "sign_changes": sidereal_sign_changes,
            "retrograde_stations": sidereal_retrograde_stations,
            "moon_signs": sidereal_moon_signs,
            "moon_phases": sidereal_moon_phases,
            "slow_planet_aspects": sidereal_slow_aspects,
            "slow_planet_ingresses": sidereal_yearly_events.get("slow_ingresses", []),
            "inner_planet_ingresses": sidereal_yearly_events.get("inner_ingresses", []),
            "stations": sidereal_yearly_events.get("stations", []),
            "eclipses": [
                {"date": e["date"], "type": e["type"], "sign": e["sidereal_sign"]}
                for e in yearly_eclipses
            ],
            "quarterly_houses": sidereal_quarterly_houses
        },
        "sign_changes": sidereal_sign_changes,
        "retrograde_stations": sidereal_retrograde_stations,
        "moon_signs": sidereal_moon_signs,
        "moon_phases": sidereal_moon_phases,
        "eclipses": yearly_eclipses,
        "quarterly_houses": sidereal_quarterly_houses
    }


def get_month_ingresses(year: int, month: int, system: str) -> list:
    """
    Computes all planetary ingresses and retrograde/direct stations in Indian Standard Time (IST)
    for the specified month and system (tropical or sidereal) using pyswisseph.
    Planets tracked: Sun, Mercury, Venus, Mars, Jupiter, Saturn, Rahu, Ketu.
    For sidereal: includes nakshatra at entry in details.
    """
    system_key = system.lower().strip()
    is_sid = (system_key == "sidereal")
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if is_sid:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        flags |= swe.FLG_SIDEREAL

    planet_ids = {
        "sun": swe.SUN,
        "mercury": swe.MERCURY,
        "venus": swe.VENUS,
        "mars": swe.MARS,
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN,
        "rahu": swe.MEAN_NODE,
    }

    _, last_day = calendar.monthrange(year, month)
    start_dt = datetime(year, month, 1, 0, 0)
    end_dt = datetime(year, month, last_day, 23, 59)

    def calc_at_dt(cur_dt):
        utc_dt = cur_dt - timedelta(hours=5, minutes=30)
        jd_ut = swe.julday(
            utc_dt.year, utc_dt.month, utc_dt.day,
            utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0, 1
        )
        res = {}
        for p, pid in planet_ids.items():
            r, _ = swe.calc_ut(jd_ut, pid, flags)
            lon = r[0] % 360.0
            spd = r[3]
            s_idx = int(lon // 30)
            res[p] = {
                "sign_idx": s_idx,
                "sign": ZODIAC_SIGNS[s_idx],
                "lon": lon,
                "speed": spd,
                "is_retro": spd < 0
            }
        # Ketu is exactly 180° opposite to Rahu
        k_lon = (res["rahu"]["lon"] + 180.0) % 360.0
        k_s_idx = int(k_lon // 30)
        res["ketu"] = {
            "sign_idx": k_s_idx,
            "sign": ZODIAC_SIGNS[k_s_idx],
            "lon": k_lon,
            "speed": res["rahu"]["speed"],
            "is_retro": res["rahu"]["is_retro"]
        }
        return res

    prev = calc_at_dt(start_dt)
    events = []
    seen_keys = set()
    cur = start_dt + timedelta(hours=1)

    while cur <= end_dt:
        curr_state = calc_at_dt(cur)
        for p in ["sun", "mercury", "venus", "mars", "jupiter", "saturn", "rahu", "ketu"]:
            # 1. Ingress
            if curr_state[p]["sign_idx"] != prev[p]["sign_idx"]:
                from_s = prev[p]["sign"]
                to_s = curr_state[p]["sign"]
                dt_str = cur.strftime("%Y-%m-%d")
                time_str = cur.strftime("%H:%M:%S")
                ev_key = (year, month, system_key, p, "ingress", dt_str)
                if ev_key not in seen_keys:
                    seen_keys.add(ev_key)
                    details = {"longitude": round(curr_state[p]["lon"], 2)}
                    if is_sid:
                        nak_idx = int(curr_state[p]["lon"] // (360.0 / 27.0))
                        details["nakshatra"] = NAKSHATRAS[nak_idx % 27]
                    events.append({
                        "year": year,
                        "month": month,
                        "system": system_key,
                        "planet": p,
                        "from_sign": from_s,
                        "to_sign": to_s,
                        "event_date": dt_str,
                        "event_time": time_str,
                        "event_type": "ingress",
                        "details": details
                    })

            # 2. Retrograde / Direct (for planets that change direction, excluding lunar nodes)
            if p not in ["rahu", "ketu"]:
                dt_str = cur.strftime("%Y-%m-%d")
                time_str = cur.strftime("%H:%M:%S")
                if not prev[p]["is_retro"] and curr_state[p]["is_retro"]:
                    ev_key = (year, month, system_key, p, "retrograde", dt_str)
                    if ev_key not in seen_keys:
                        seen_keys.add(ev_key)
                        events.append({
                            "year": year,
                            "month": month,
                            "system": system_key,
                            "planet": p,
                            "from_sign": curr_state[p]["sign"],
                            "to_sign": curr_state[p]["sign"],
                            "event_date": dt_str,
                            "event_time": time_str,
                            "event_type": "retrograde",
                            "details": {"motion": "Stationary Retrograde"}
                        })
                elif prev[p]["is_retro"] and not curr_state[p]["is_retro"]:
                    ev_key = (year, month, system_key, p, "direct", dt_str)
                    if ev_key not in seen_keys:
                        seen_keys.add(ev_key)
                        events.append({
                            "year": year,
                            "month": month,
                            "system": system_key,
                            "planet": p,
                            "from_sign": curr_state[p]["sign"],
                            "to_sign": curr_state[p]["sign"],
                            "event_date": dt_str,
                            "event_time": time_str,
                            "event_type": "direct",
                            "details": {"motion": "Stationary Direct"}
                        })
        prev = curr_state
        cur += timedelta(hours=1)

    return events


if __name__ == "__main__":
    snap = get_snapshot()
    print("=== Today's Planetary Snapshot (Noon IST) ===")
    print(json.dumps(snap, indent=2))

