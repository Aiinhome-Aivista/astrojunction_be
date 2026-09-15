import swisseph as swe
from datetime import datetime, timedelta
from functools import lru_cache

BENGALI_MONTHS = ["Baisakh", "Jaistha", "Ashar", "Sraban", "Bhadra", "Aswin", "Kartik", "Agrahayan", "Poush", "Magh", "Falgun", "Chaitra"]
HINDI_MONTHS = ["Chaitra", "Vaisakha", "Jyaistha", "Ashadha", "Shravana", "Bhadrapada", "Ashvina", "Kartika", "Margashirsha", "Pausha", "Magha", "Phalguna"]
TITHIS = ["Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Purnima", "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya"]
NAKSHATRAS = ["Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"]
YOGAS = ["Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana", "Atiganda", "Sukarma", "Dhriti", "Shula", "Ganda", "Vriddhi", "Dhruva", "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata", "Variyan", "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma", "Indra", "Vaidhriti"]
KARANAS_MOVABLE = ["Bava", "Balava", "Kaulava", "Taitila", "Garija", "Vanija", "Vishti"]
KARANAS_FIXED = ["Shakuni", "Chatushpada", "Naga", "Kintughna"]
RASHIS = ["Mesha (Aries)", "Vrishabha (Taurus)", "Mithuna (Gemini)", "Karka (Cancer)", "Simha (Leo)", "Kanya (Virgo)", "Tula (Libra)", "Vrishchika (Scorpio)", "Dhanu (Sagittarius)", "Makara (Capricorn)", "Kumbha (Aquarius)", "Meena (Pisces)"]
RITUS = ["Vasant (Spring)", "Grishma (Summer)", "Varsha (Monsoon)", "Sharad (Autumn)", "Hemant (Pre-Winter)", "Shishir (Winter)"]

def get_julian_day(date_obj, timezone_offset=5.5):
    dt_utc = date_obj - timedelta(hours=timezone_offset)
    hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, 1)

def format_jd_to_time(jd, tz_offset=5.5):
    if jd == 0 or jd is None: return ""
    y, m, d, h_float = swe.revjul(jd, 1)
    dt = datetime(y, m, d) + timedelta(hours=h_float) + timedelta(hours=tz_offset)
    return dt.strftime("%I:%M %p")

@lru_cache(maxsize=2048)
def calculate_panjika_details(date_obj, lat=22.5726, lon=88.3639, tz_offset=5.5):
    # Noon calculation for standard details
    jd_noon = get_julian_day(date_obj.replace(hour=12, minute=0, second=0), tz_offset)
    
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    flags = swe.FLG_SIDEREAL | swe.FLG_SWIEPH

    sun_res, _ = swe.calc_ut(jd_noon, swe.SUN, flags)
    moon_res, _ = swe.calc_ut(jd_noon, swe.MOON, flags)
    
    sun_lon = sun_res[0]
    moon_lon = moon_res[0]
    
    # Sun Sign & Ritu
    sun_sign_idx = int(sun_lon / 30)
    ritu = RITUS[(sun_sign_idx + 1) // 2 % 6]
    
    # Moon Sign (Rashi)
    moon_sign_idx = int(moon_lon / 30)
    
    # Tithi
    diff = (moon_lon - sun_lon) % 360
    tithi_idx = int(diff / 12)
    paksha = "Shukla" if tithi_idx < 15 else "Krishna"
    
    # Karana (Half Tithi = 6 degrees)
    karana_val = int(diff / 6)
    if karana_val == 0:
        karana = KARANAS_FIXED[3] # Kintughna
    elif karana_val >= 57:
        karana = KARANAS_FIXED[karana_val - 57] # 57=Shakuni, 58=Chatushpada, 59=Naga
    else:
        karana = KARANAS_MOVABLE[(karana_val - 1) % 7]
        
    # Nakshatra
    nakshatra_idx = int(moon_lon / (360.0 / 27.0))
    
    # Yoga
    yoga_idx = int((moon_lon + sun_lon) % 360 / (360.0 / 27.0))
    
    # Rise/Set times (Calculated at 00:00 UTC)
    jd_start = get_julian_day(date_obj.replace(hour=0, minute=0, second=0), tz_offset)
    geopos = (lon, lat, 0.0)
    
    try:
        sunrise_res = swe.rise_trans(jd_start, swe.SUN, swe.CALC_RISE, geopos)
        sunset_res = swe.rise_trans(jd_start, swe.SUN, swe.CALC_SET, geopos)
        
        # Depending on version, rise_trans might return (flags, (tret_tuple...)) or just (tret_tuple)
        sunrise_jd = sunrise_res[1][0] if isinstance(sunrise_res, tuple) and len(sunrise_res) > 1 and isinstance(sunrise_res[1], tuple) else (sunrise_res[0] if isinstance(sunrise_res, tuple) else sunrise_res)
        sunset_jd = sunset_res[1][0] if isinstance(sunset_res, tuple) and len(sunset_res) > 1 and isinstance(sunset_res[1], tuple) else (sunset_res[0] if isinstance(sunset_res, tuple) else sunset_res)

        sunrise = format_jd_to_time(sunrise_jd, tz_offset)
        sunset = format_jd_to_time(sunset_jd, tz_offset)
    except:
        sunrise, sunset = "", ""

    try:
        moonrise_res = swe.rise_trans(jd_start, swe.MOON, swe.CALC_RISE, geopos)
        moonset_res = swe.rise_trans(jd_start, swe.MOON, swe.CALC_SET, geopos)
        
        moonrise_jd = moonrise_res[1][0] if isinstance(moonrise_res, tuple) and len(moonrise_res) > 1 and isinstance(moonrise_res[1], tuple) else (moonrise_res[0] if isinstance(moonrise_res, tuple) else moonrise_res)
        moonset_jd = moonset_res[1][0] if isinstance(moonset_res, tuple) and len(moonset_res) > 1 and isinstance(moonset_res[1], tuple) else (moonset_res[0] if isinstance(moonset_res, tuple) else moonset_res)
        
        moonrise = format_jd_to_time(moonrise_jd, tz_offset)
        moonset = format_jd_to_time(moonset_jd, tz_offset)
    except:
        moonrise, moonset = "", ""
        
    # Festivals (Simple rules based on Tithi + Month)
    festivals = []
    if tithi_idx == 14: festivals.append("Purnima Vrat")
    if tithi_idx == 29: festivals.append("Amavasya (New Moon)")
    if tithi_idx == 10 or tithi_idx == 25: festivals.append("Ekadashi Vrat")

    return {
        "sun_sign_idx": sun_sign_idx,
        "tithi": TITHIS[tithi_idx],
        "tithi_idx": tithi_idx,
        "paksha": paksha,
        "nakshatra": NAKSHATRAS[nakshatra_idx],
        "yoga": YOGAS[yoga_idx],
        "karana": karana,
        "rashi": RASHIS[moon_sign_idx],
        "ritu": ritu,
        "sunrise": sunrise,
        "sunset": sunset,
        "moonrise": moonrise,
        "moonset": moonset,
        "festivals": festivals
    }

def get_bengali_date(date_obj, lat=22.5726, lon=88.3639):
    panjika = calculate_panjika_details(date_obj, lat, lon)
    sun_sign_idx = panjika['sun_sign_idx']
    bengali_month = BENGALI_MONTHS[sun_sign_idx]
    
    temp_date = date_obj
    day_count = 1
    for _ in range(32):
        temp_date -= timedelta(days=1)
        temp_panjika = calculate_panjika_details(temp_date, lat, lon)
        if temp_panjika['sun_sign_idx'] != sun_sign_idx:
            break
        day_count += 1
        
    bengali_year = date_obj.year - 593
    if sun_sign_idx >= 9:
        bengali_year -= 1 

    return f"{day_count} {bengali_month} {bengali_year} BS", day_count, bengali_month, bengali_year

def get_hindi_date(date_obj, lat=22.5726, lon=88.3639):
    panjika = calculate_panjika_details(date_obj, lat, lon)
    temp_date = date_obj
    for _ in range(32):
        t = calculate_panjika_details(temp_date, lat, lon)['tithi']
        if t == "Amavasya":
            break
        temp_date -= timedelta(days=1)
    
    amavasya_panjika = calculate_panjika_details(temp_date, lat, lon)
    sun_sign_at_amavasya = amavasya_panjika['sun_sign_idx']
    
    hindi_month_idx = (sun_sign_at_amavasya + 1) % 12
    hindi_month = HINDI_MONTHS[hindi_month_idx]
    
    tithi = panjika['tithi']
    paksha = panjika['paksha']
    
    vikram_samvat = date_obj.year + 57
    if hindi_month_idx >= 9:
        vikram_samvat -= 1
        
    return f"{tithi} ({paksha} Paksha), {hindi_month} {vikram_samvat} VS", tithi, paksha, hindi_month, vikram_samvat

def generate_month_calendar(year, month, lat=22.5726, lon=88.3639):
    import calendar
    num_days = calendar.monthrange(year, month)[1]
    
    days = []
    for day in range(1, num_days + 1):
        dt = datetime(year, month, day)
        panjika = calculate_panjika_details(dt, lat, lon)
        bengali_date_str, _, _, _ = get_bengali_date(dt, lat, lon)
        hindi_date_str, _, _, _, _ = get_hindi_date(dt, lat, lon)
        
        days.append({
            "day": day,
            "tithi": panjika['tithi'],
            "paksha": panjika['paksha'],
            "nakshatra": panjika['nakshatra'],
            "bengali_date": bengali_date_str,
            "hindi_date": hindi_date_str,
            "english_date": dt.strftime("%Y-%m-%d")
        })
        
    return days

def convert_calendar_date(date_str, lat=22.5726, lon=88.3639):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        bengali_str, b_day, b_month, b_year = get_bengali_date(dt, lat, lon)
        hindi_str, h_tithi, h_paksha, h_month, h_year = get_hindi_date(dt, lat, lon)
        panjika = calculate_panjika_details(dt, lat, lon)
        
        return {
            "english": dt.strftime("%d %B %Y"),
            "english_date": dt.strftime("%Y-%m-%d"),
            "bengali": bengali_str,
            "bengali_parts": {"day": b_day, "month": b_month, "year": b_year},
            "hindi": hindi_str,
            "hindi_parts": {"tithi": h_tithi, "paksha": h_paksha, "month": h_month, "year": h_year},
            **panjika
        }
    except Exception as e:
        return {"error": str(e)}

def reverse_convert_bengali(day, month_str, year, lat=22.5726, lon=88.3639):
    eng_year = int(year) + 593
    current_dt = datetime(eng_year, 4, 15)
    
    for i in range(-50, 365):
        test_dt = current_dt + timedelta(days=i)
        b_str, b_day, b_month, b_year = get_bengali_date(test_dt, lat, lon)
        if b_day == int(day) and b_month == month_str and b_year == int(year):
            return convert_calendar_date(test_dt.strftime("%Y-%m-%d"), lat, lon)
    return {"error": "Date not found or invalid."}

def reverse_convert_hindi(tithi_str, paksha_str, month_str, year, lat=22.5726, lon=88.3639):
    eng_year = int(year) - 57
    current_dt = datetime(eng_year, 3, 15)
    
    for i in range(-50, 365):
        test_dt = current_dt + timedelta(days=i)
        h_str, h_tithi, h_paksha, h_month, h_year = get_hindi_date(test_dt, lat, lon)
        if h_tithi == tithi_str and h_paksha == paksha_str and h_month == month_str and h_year == int(year):
            return convert_calendar_date(test_dt.strftime("%Y-%m-%d"), lat, lon)
    return {"error": "Date not found or invalid (perhaps Kshaya Tithi)."}
