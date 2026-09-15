import swisseph as swe
from datetime import datetime, timedelta

def get_julian_day_ut(date_str, time_str, timezone_offset):
    """
    Convert local date and time to UTC Julian Day.
    date_str: "YYYY-MM-DD"
    time_str: "HH:mm"
    timezone_offset: float (e.g., 5.5 for IST)
    """
    try:
        dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        dt_utc = dt_local - timedelta(hours=timezone_offset)
        
        year = dt_utc.year
        month = dt_utc.month
        day = dt_utc.day
        hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
        
        # 1 means Gregorian Calendar
        jd_ut = swe.julday(year, month, day, hour, 1)
        return jd_ut
    except Exception as e:
        raise ValueError(f"Invalid date/time format: {e}")

def calculate_panchang_data(date_str, time_str, timezone_offset, lat=28.6139, lon=77.209, mulank=1):
    jd_ut = get_julian_day_ut(date_str, time_str, timezone_offset)
    
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    flags = swe.FLG_SIDEREAL | swe.FLG_SWIEPH | swe.FLG_SPEED
    
    # Calculate Sun and Moon positions
    sun_res, _ = swe.calc_ut(jd_ut, swe.SUN, flags)
    moon_res, _ = swe.calc_ut(jd_ut, swe.MOON, flags)
    
    sun_lon = sun_res[0]
    moon_lon = moon_res[0]
    
    # Panchang Calculations
    diff = (moon_lon - sun_lon) % 360
    tithi_idx = int(diff / 12)
    karana_idx = int(diff / 6)
    
    sum_lon = (sun_lon + moon_lon) % 360
    yoga_idx = int(sum_lon / (40.0 / 3.0))
    nak_idx = int(moon_lon / (40.0 / 3.0))
    
    # Parse date
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year, month, day = dt.year, dt.month, dt.day
    day_of_year = (dt - datetime(year, 1, 1)).days
    
    # Calculate Auspicious Score
    auspicious_score = 50 + ((tithi_idx * 3 + nak_idx * 2 + day_of_year) % 50)
    
    from services.astro_utils import calculate_sun_times_and_muhurtas, get_daily_rituals, get_numerology_daily
    
    # Get Timings
    timings = calculate_sun_times_and_muhurtas(year, month, day, lat, lon, timezone_offset)
    
    # Get Rituals (Dynamic based on Nakshatra Lord)
    rituals = get_daily_rituals(nak_idx)
    
    # Get Numerology (Dynamic based on Personal Day Number)
    lucky_num, lucky_col = get_numerology_daily(mulank, year, month, day)
    
    return {
        "sunLongitude": sun_lon,
        "moonLongitude": moon_lon,
        "tithiIndex": tithi_idx,
        "karanaIndex": karana_idx,
        "yogaIndex": yoga_idx,
        "nakshatraIndex": nak_idx,
        "auspiciousScore": auspicious_score,
        "timings": timings,
        "rituals": rituals,
        "luckyData": {
            "luckyNumber": lucky_num,
            "luckyColor": lucky_col
        }
    }

def calculate_chart_data(date_str, time_str, lat, lon, timezone_offset):
    jd_ut = get_julian_day_ut(date_str, time_str, timezone_offset)
    
    # Set Sidereal mode to Lahiri
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    
    # Flags: Sidereal + Moshier/Swiss + Speed calculation
    flags = swe.FLG_SIDEREAL | swe.FLG_SWIEPH | swe.FLG_SPEED
    
    planets_to_calc = {
        "sun": swe.SUN,
        "moon": swe.MOON,
        "mars": swe.MARS,
        "mercury": swe.MERCURY,
        "jupiter": swe.JUPITER,
        "venus": swe.VENUS,
        "saturn": swe.SATURN,
        "rahu": swe.TRUE_NODE, # True Node for Rahu
    }
    
    planet_results = {}
    for p_name, p_id in planets_to_calc.items():
        res, _ = swe.calc_ut(jd_ut, p_id, flags)
        lon_deg = res[0]
        speed = res[3]
        
        planet_results[p_name] = {
            "longitude": lon_deg,
            "isRetrograde": speed < 0
        }
        
    # Calculate Ketu (180 degrees opposite to Rahu)
    rahu_lon = planet_results["rahu"]["longitude"]
    planet_results["ketu"] = {
        "longitude": (rahu_lon + 180.0) % 360.0,
        "isRetrograde": planet_results["rahu"]["isRetrograde"]
    }
    
    # Ascendant Calculation
    # swe.houses returns tropical cusps and ascmc (Ascendant is ascmc[0])
    cusps, ascmc = swe.houses(jd_ut, lat, lon, b'W') # Whole Sign or Placidus (W / P) doesn't matter for exact ASC degree
    trop_asc = ascmc[0]
    
    # Get Ayanamsha for this epoch
    aya = swe.get_ayanamsa_ut(jd_ut)
    sid_asc = (trop_asc - aya) % 360.0
    if sid_asc < 0:
        sid_asc += 360.0
        
    from services.astro_utils import calculate_vimshottari_dasha, calculate_yogas, calculate_doshas, calculate_divisional_chart, calculate_jaimini_karakas, calculate_gemstones, calculate_planetary_aspects
    
    # Calculate Dashas
    dashas = calculate_vimshottari_dasha(planet_results["moon"]["longitude"], date_str)
    
    # Calculate Yogas
    yogas = calculate_yogas(planet_results)
    
    # Calculate Doshas
    doshas = calculate_doshas(planet_results, sid_asc)
    
    # Calculate Divisional Charts
    d9_chart = calculate_divisional_chart(planet_results, sid_asc, 9)
    d10_chart = calculate_divisional_chart(planet_results, sid_asc, 10)
    
    # Calculate Jaimini Karakas
    karakas = calculate_jaimini_karakas(planet_results)
    
    # Calculate Gemstones
    gemstones = calculate_gemstones(int(sid_asc // 30))
    
    # Calculate Aspects
    aspects = calculate_planetary_aspects(planet_results)
    
    # Calculate KP System Houses (Placidus)
    kp_cusps, _ = swe.houses_ex(jd_ut, lat, lon, b'P', flags)
    
    # Normalize KP Cusps
    kp_houses = []
    for i in range(12):
        cusp_deg = kp_cusps[i]
        sid_cusp = (cusp_deg - aya) % 360.0
        kp_houses.append(sid_cusp)
        
    return {
        "ascendant": sid_asc,
        "planets": planet_results,
        "ayanamsha": aya,
        "dashas": dashas,
        "yogas": yogas,
        "doshas": doshas,
        "divisionalCharts": {
            "d9": d9_chart,
            "d10": d10_chart
        },
        "karakas": karakas,
        "gemstones": gemstones,
        "aspects": aspects,
        "kpSystem": {
            "houses": kp_houses
        }
    }
