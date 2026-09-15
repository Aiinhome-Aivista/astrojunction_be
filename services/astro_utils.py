import math
from datetime import datetime

def format_time(total_mins):
    h = int(total_mins // 60)
    m = int(total_mins % 60)
    ampm = 'PM' if h >= 12 else 'AM'
    display_h = 12 if h % 12 == 0 else h % 12
    return f"{display_h:02d}:{m:02d} {ampm}"

def get_day_of_week(year, month, day):
    # 0 = Sunday, 1 = Monday, ... 6 = Saturday (JS style)
    dt = datetime(year, month, day)
    return dt.isoweekday() % 7

def calculate_sun_times_and_muhurtas(year, month, day, lat, longitude, tz_offset):
    date = datetime(year, month, day)
    dayOfYear = (date - datetime(year, 1, 1)).days
    
    N = dayOfYear
    lngHour = longitude / 15.0
    tSunrise = N + ((6 - lngHour) / 24.0)
    tSunset = N + ((18 - lngHour) / 24.0)
    
    M_sunrise = (0.9856 * tSunrise) - 3.289
    M_sunset = (0.9856 * tSunset) - 3.289
    
    L_sunrise = (M_sunrise + (1.916 * math.sin(math.radians(M_sunrise))) + (0.020 * math.sin(math.radians(2 * M_sunrise))) + 282.634 + 360) % 360
    L_sunset = (M_sunset + (1.916 * math.sin(math.radians(M_sunset))) + (0.020 * math.sin(math.radians(2 * M_sunset))) + 282.634 + 360) % 360
    
    RA_sunrise = (math.degrees(math.atan(0.91764 * math.tan(math.radians(L_sunrise)))) + 360) % 360
    RA_sunset = (math.degrees(math.atan(0.91764 * math.tan(math.radians(L_sunset)))) + 360) % 360
    
    RA_sunrise = (RA_sunrise + (math.floor(L_sunrise / 90) * 90 - math.floor(RA_sunrise / 90) * 90)) / 15.0
    RA_sunset = (RA_sunset + (math.floor(L_sunset / 90) * 90 - math.floor(RA_sunset / 90) * 90)) / 15.0
    
    sinDec_sunrise = 0.39782 * math.sin(math.radians(L_sunrise))
    cosDec_sunrise = math.cos(math.asin(sinDec_sunrise))
    sinDec_sunset = 0.39782 * math.sin(math.radians(L_sunset))
    cosDec_sunset = math.cos(math.asin(sinDec_sunset))
    
    val_sunrise = (math.cos(math.radians(90.833)) - (sinDec_sunrise * math.sin(math.radians(lat)))) / (cosDec_sunrise * math.cos(math.radians(lat)))
    val_sunset = (math.cos(math.radians(90.833)) - (sinDec_sunset * math.sin(math.radians(lat)))) / (cosDec_sunset * math.cos(math.radians(lat)))
    
    cosH_sunrise = max(-1, min(1, val_sunrise))
    cosH_sunset = max(-1, min(1, val_sunset))
    
    H_sunrise = (360 - math.degrees(math.acos(cosH_sunrise))) / 15.0
    H_sunset = math.degrees(math.acos(cosH_sunset)) / 15.0
    
    UT_sunrise = (H_sunrise + RA_sunrise - (0.06571 * tSunrise) - 6.622 - lngHour + 24) % 24
    UT_sunset = (H_sunset + RA_sunset - (0.06571 * tSunset) - 6.622 - lngHour + 24) % 24
    
    totalSunriseMins = ((UT_sunrise + tz_offset + 24) % 24) * 60
    totalSunsetMins = ((UT_sunset + tz_offset + 24) % 24) * 60
    
    totalDaylightMins = totalSunsetMins - totalSunriseMins
    if totalDaylightMins < 0:
        totalDaylightMins += 24 * 60
        
    partMins = totalDaylightMins / 8.0
    
    day_of_week = get_day_of_week(year, month, day)
    rahuParts = [8, 2, 7, 5, 6, 4, 3]
    rahuPart = rahuParts[day_of_week]
    
    rahuStartMins = totalSunriseMins + partMins * (rahuPart - 1)
    rahuEndMins = rahuStartMins + partMins
    
    abhijitStartMins = totalSunriseMins + (totalDaylightMins / 2.0) - 24
    abhijitEndMins = abhijitStartMins + 48
    
    # Real Brahma Muhurta
    brahmaStartMins = totalSunriseMins - 96
    if brahmaStartMins < 0:
        brahmaStartMins += 24 * 60
    brahmaEndMins = brahmaStartMins + 48
    
    return {
        "sunrise": format_time(totalSunriseMins),
        "sunset": format_time(totalSunsetMins),
        "rahuKaal": f"{format_time(rahuStartMins)} - {format_time(rahuEndMins)} (Avoid new tasks, sign agreements)",
        "abhijitMuhurta": f"{format_time(abhijitStartMins)} - {format_time(abhijitEndMins)} (Highly auspicious for success)",
        "brahmaMuhurta": f"{format_time(brahmaStartMins)} - {format_time(brahmaEndMins)} (Ideal for Meditation & Sadhana)"
    }

def get_daily_rituals(nakshatra_idx):
    # Nakshatra Lords follow a strict sequence of 9: 
    # Ketu, Venus, Sun, Moon, Mars, Rahu, Jupiter, Saturn, Mercury
    lord_idx = nakshatra_idx % 9
    
    rituals = [
        { # 0: Ketu
            "morningTitle": "Ganesha Atharvashirsha",
            "morningDesc": "Offer durva grass to Lord Ganesha to remove unseen obstacles and calm the restless mind.",
            "eveningTitle": "Ketu Beej Mantra",
            "eveningDesc": "Chant 'Om Sraam Sreem Sraum Sah Ketave Namah' to enhance intuition and spiritual detachment."
        },
        { # 1: Venus (Shukra)
            "morningTitle": "Sri Suktam Path",
            "morningDesc": "Offer white flowers or fragrant perfumes to Goddess Lakshmi. Recite the Sri Suktam for luxury and harmonious relationships.",
            "eveningTitle": "Shukra Beej Mantra",
            "eveningDesc": "Light a ghee diya at dusk. Recite 'Om Dram Dreem Draum Sah Shukraya Namah' to enhance magnetism."
        },
        { # 2: Sun (Surya)
            "morningTitle": "Surya Arghya & Aditya Hrudayam",
            "morningDesc": "Offer water to the rising Sun with red flowers and a pinch of kumkum. Recite the Aditya Hrudayam Stotram for vitality.",
            "eveningTitle": "Gayatri Mantra Japa",
            "eveningDesc": "Light a sesame oil diya. Chant the Gayatri Mantra 108 times to illuminate the intellect."
        },
        { # 3: Moon (Chandra)
            "morningTitle": "Shiva Linga Abhishekam",
            "morningDesc": "Offer raw milk, water, and bel patra to a Shiva Linga. Chant 'Om Namah Shivaya' to calm the restless mind.",
            "eveningTitle": "Chandra Beej Mantra",
            "eveningDesc": "Sit facing the Northwest. Recite 'Om Shram Shreem Shraum Sah Chandraya Namah' for emotional intelligence."
        },
        { # 4: Mars (Mangal)
            "morningTitle": "Hanuman Chalisa",
            "morningDesc": "Wear red garments. Recite the Hanuman Chalisa or Bajrang Baan to overcome obstacles and cultivate martial courage.",
            "eveningTitle": "Mangal Mantra",
            "eveningDesc": "Light a ghee diya. Chant 'Om Kram Kreem Kroum Sah Bhaumaya Namah' to channel raw energy into productive action."
        },
        { # 5: Rahu
            "morningTitle": "Durga Saptashati & Bhairava",
            "morningDesc": "Offer prayers to Goddess Durga to dispel illusions and anxieties caused by Rahu's shadowy energy.",
            "eveningTitle": "Rahu Beej Mantra",
            "eveningDesc": "Recite 'Om Bhraam Bhreem Bhraum Sah Rahave Namah' after sunset to protect against sudden setbacks."
        },
        { # 6: Jupiter (Guru)
            "morningTitle": "Guru Mantra & Yellow Offerings",
            "morningDesc": "Wear yellow or apply a turmeric tilak. Chant 'Om Brihaspataye Namah' 108 times for wisdom and expansion.",
            "eveningTitle": "Dakshinamurthy Stotram",
            "eveningDesc": "Light a ghee diya at dusk. Meditate upon Lord Dakshinamurthy for profound spiritual insight and clarity."
        },
        { # 7: Saturn (Shani)
            "morningTitle": "Shani Mantra & Charity",
            "morningDesc": "Offer black sesame seeds and mustard oil to Lord Shani. Feed crows or street dogs to appease karmic blockages.",
            "eveningTitle": "Maha Mrityunjaya & Shiva Japa",
            "eveningDesc": "Light a mustard oil diya at dusk. Recite 'Om Tryambakam Yajamahe...' for protection."
        },
        { # 8: Mercury (Budh)
            "morningTitle": "Vishnu Sahasranama",
            "morningDesc": "Offer Tulsi leaves to Lord Vishnu. Listen to or recite the Vishnu Sahasranama for financial stability.",
            "eveningTitle": "Budh Beej Mantra",
            "eveningDesc": "Chant 'Om Bram Breem Braum Sah Budhaya Namah' to sharpen intellect and improve communication."
        }
    ]
    return rituals[lord_idx]

def get_numerology_daily(mulank, year, month, day):
    # Dynamic Daily Numerology: 
    # Personal Day Number = (Mulank + Current Day + Current Month + Current Year) reduced to single digit
    def reduce_to_single_digit(n):
        while n > 9:
            n = sum(int(digit) for digit in str(n))
        return n
        
    date_sum = sum(int(d) for d in f"{year}{month:02d}{day:02d}")
    personal_day_number = reduce_to_single_digit(int(mulank) + date_sum)
    
    # Map the Personal Day Number to its ruling planet's attributes for the day
    planet_attributes = {
        1: {"color": "Gold / Saffron (Sun)", "vibe": "New beginnings & Leadership"},
        2: {"color": "White / Pearl (Moon)", "vibe": "Cooperation & Intuition"},
        3: {"color": "Yellow (Jupiter)", "vibe": "Creativity & Expansion"},
        4: {"color": "Grey / Blue (Rahu)", "vibe": "Hard work & Organization"},
        5: {"color": "Green (Mercury)", "vibe": "Communication & Change"},
        6: {"color": "Pink / White (Venus)", "vibe": "Love & Harmony"},
        7: {"color": "Light Green (Ketu)", "vibe": "Spirituality & Analysis"},
        8: {"color": "Black / Dark Blue (Saturn)", "vibe": "Karma & Financial Power"},
        9: {"color": "Red (Mars)", "vibe": "Energy & Completion"}
    }
    
    day_data = planet_attributes.get(personal_day_number, planet_attributes[1])
    
    return personal_day_number, day_data["color"]



DASHA_ORDER = [
    {"planet": "Ketu", "sanskrit": "केतु", "years": 7},
    {"planet": "Venus", "sanskrit": "शुक्र", "years": 20},
    {"planet": "Sun", "sanskrit": "सूर्य", "years": 6},
    {"planet": "Moon", "sanskrit": "चन्द्र", "years": 10},
    {"planet": "Mars", "sanskrit": "मंगल", "years": 7},
    {"planet": "Rahu", "sanskrit": "राहु", "years": 18},
    {"planet": "Jupiter", "sanskrit": "गुरु", "years": 16},
    {"planet": "Saturn", "sanskrit": "शनि", "years": 19},
    {"planet": "Mercury", "sanskrit": "बुध", "years": 17}
]

def calculate_vimshottari_dasha(moon_longitude, birth_date_str):
    """
    Calculate Vimshottari Dasha up to Pratyantardasha (3 levels).
    """
    from datetime import datetime, timedelta

    birth_date = datetime.strptime(birth_date_str, "%Y-%m-%d")
    
    # 1. Determine Moon Nakshatra and Balance of Dasha
    nakshatra_span = 360.0 / 27.0
    moon_nakshatra_idx = int(moon_longitude / nakshatra_span)
    nakshatra_start_deg = moon_nakshatra_idx * nakshatra_span
    
    degrees_remaining = (nakshatra_start_deg + nakshatra_span) - moon_longitude
    fraction_remaining = degrees_remaining / nakshatra_span
    
    first_dasha_lord_idx = moon_nakshatra_idx % 9
    first_dasha_total_years = DASHA_ORDER[first_dasha_lord_idx]["years"]
    first_dasha_balance_years = first_dasha_total_years * fraction_remaining
    
    dashas = []
    
    # Calculate exactly 120 years of Dasha
    # For the first MD, start is birth date.
    # To keep the logic simple, we calculate the absolute start of the first dasha in the past
    # and then just truncate it.
    
    first_dasha_elapsed_years = first_dasha_total_years - first_dasha_balance_years
    md_start = birth_date - timedelta(days=first_dasha_elapsed_years * 365.2425)
    
    current_lord_idx = first_dasha_lord_idx
    
    for i in range(9):
        md_lord = DASHA_ORDER[current_lord_idx]
        md_years = md_lord["years"]
        md_end = md_start + timedelta(days=md_years * 365.2425)
        
        # Calculate Antardashas
        antardashas = []
        ad_start = md_start
        ad_lord_idx = current_lord_idx
        
        for j in range(9):
            ad_lord = DASHA_ORDER[ad_lord_idx]
            ad_total_years = (md_years * ad_lord["years"]) / 120.0
            ad_end = ad_start + timedelta(days=ad_total_years * 365.2425)
            
            # Pratyantardashas
            pratyantardashas = []
            pd_start = ad_start
            pd_lord_idx = ad_lord_idx
            for k in range(9):
                pd_lord = DASHA_ORDER[pd_lord_idx]
                pd_total_years = (ad_total_years * pd_lord["years"]) / md_years
                pd_end = pd_start + timedelta(days=pd_total_years * 365.2425)
                
                # Only add if it's after birth date
                if pd_end > birth_date:
                    pratyantardashas.append({
                        "planet": pd_lord["planet"],
                        "sanskrit": pd_lord["sanskrit"],
                        "startDate": max(pd_start, birth_date).strftime("%Y-%m-%d"),
                        "endDate": pd_end.strftime("%Y-%m-%d")
                    })
                pd_start = pd_end
                pd_lord_idx = (pd_lord_idx + 1) % 9
            
            if ad_end > birth_date:
                antardashas.append({
                    "planet": ad_lord["planet"],
                    "sanskrit": ad_lord["sanskrit"],
                    "startDate": max(ad_start, birth_date).strftime("%Y-%m-%d"),
                    "endDate": ad_end.strftime("%Y-%m-%d"),
                    "pratyantardashas": pratyantardashas
                })
            
            ad_start = ad_end
            ad_lord_idx = (ad_lord_idx + 1) % 9
            
        if md_end > birth_date:
            dashas.append({
                "planet": md_lord["planet"],
                "sanskrit": md_lord["sanskrit"],
                "startDate": max(md_start, birth_date).strftime("%Y-%m-%d"),
                "endDate": md_end.strftime("%Y-%m-%d"),
                "antardashas": antardashas
            })
        
        md_start = md_end
        current_lord_idx = (current_lord_idx + 1) % 9
        
    return dashas

def calculate_yogas(planets_data):
    # A simplified yoga calculator
    yogas = []
    
    # 1. Gajakesari Yoga (Jupiter in Kendra from Moon)
    moon = planets_data.get("moon")
    jupiter = planets_data.get("jupiter")
    if moon and jupiter:
        moon_sign = int(moon["longitude"] / 30)
        jup_sign = int(jupiter["longitude"] / 30)
        diff = (jup_sign - moon_sign + 12) % 12
        if diff in [0, 3, 6, 9]:
            yogas.append({
                "id": "yoga_gajakesari",
                "name": "Gajakesari Yoga",
                "type": "Auspicious",
                "effect": "Grants wisdom, wealth, eloquence, and a lasting reputation. Ensures comfort and overcoming of enemies."
            })
            
    # 2. Ruchaka Yoga (Mars in Kendra from Asc in own sign or exaltation)
    # (Simplified: just checking exaltation/own sign for Mars for demo purposes)
    mars = planets_data.get("mars")
    if mars:
        mars_sign = int(mars["longitude"] / 30)
        if mars_sign in [0, 7, 9]: # Aries, Scorpio (Own), Capricorn (Exalted)
            yogas.append({
                "id": "yoga_ruchaka",
                "name": "Ruchaka Mahapurusha Yoga",
                "type": "Auspicious",
                "effect": "Bestows immense courage, leadership, stamina, and success in police, military, or sports."
            })
            
    # Default fallback
    if len(yogas) == 0:
        yogas.append({
            "id": "yoga_budhaditya",
            "name": "Budhaditya Yoga",
            "type": "Auspicious",
            "effect": "Confers sharp intellect, business acumen, and strong communication skills."
        })
        
    return yogas

def calculate_doshas(planets_data, asc_deg):
    doshas = []
    
    # 1. Manglik Dosha (Kuja Dosha)
    mars = planets_data.get("mars")
    if mars:
        asc_sign = int(asc_deg / 30)
        mars_sign = int(mars["longitude"] / 30)
        house = (mars_sign - asc_sign + 12) % 12 + 1
        if house in [1, 4, 7, 8, 12]:
            doshas.append({
                "id": "dosha_manglik",
                "name": "Manglik (Kuja) Dosha",
                "isPresent": True,
                "severity": "High",
                "description": f"Mars is placed in the {house}th house. This can cause friction in marriage and partnerships. Remedies like Kumbh Vivah or fasting on Tuesdays are advised."
            })
        else:
            doshas.append({
                "id": "dosha_manglik",
                "name": "Manglik (Kuja) Dosha",
                "isPresent": False,
                "severity": "None",
                "description": "No significant Mars affliction detected for marriage."
            })
            
    return doshas


def calculate_divisional_chart(planet_results, ascendant_degree, division):
    # division = 9 for Navamsha, 10 for Dasamsha
    chart = {}
    
    # Calculate Ascendant
    d_asc_deg = (ascendant_degree * division) % 360.0
    chart["ascendant"] = {
        "degree": d_asc_deg,
        "signIndex": int(d_asc_deg // 30)
    }
    
    planets = {}
    for p_name, p_data in planet_results.items():
        d_deg = (p_data["longitude"] * division) % 360.0
        planets[p_name] = {
            "longitude": d_deg,
            "signIndex": int(d_deg // 30),
            "house": ((int(d_deg // 30) - chart["ascendant"]["signIndex"] + 12) % 12) + 1
        }
    chart["planets"] = planets
    return chart

def calculate_jaimini_karakas(planet_results):
    # Exclude Rahu and Ketu
    classical = []
    for p_name, p_data in planet_results.items():
        if p_name not in ["rahu", "ketu"]:
            deg_in_sign = p_data["longitude"] % 30
            classical.append({
                "name": p_name,
                "deg_in_sign": deg_in_sign
            })
            
    # Sort descending by degree in sign
    classical.sort(key=lambda x: x["deg_in_sign"], reverse=True)
    
    karaka_names = ["AK (Atmakaraka)", "AmK (Amatyakaraka)", "BK (Bhratrukaraka)", 
                    "MK (Matrukaraka)", "PK (Putrakaraka)", "GK (Gnatikaraka)", "DK (Darakaraka)"]
    
    karakas = {}
    for i, p in enumerate(classical):
        if i < len(karaka_names):
            karakas[p["name"]] = karaka_names[i]
            
    return karakas

def calculate_gemstones(lagna_sign_idx):
    # Functional benefics based on Ascendant (Lagna) sign index (0-11)
    # Rules: Lords of 1, 5, 9 are generally benefic. 
    # Sun=0, Moon=1, Mars=2, Mercury=3, Jupiter=4, Venus=5, Saturn=6
    
    # Gemstone mapping
    gems = {
        "sun": "Ruby (Manikya)",
        "moon": "Pearl (Moti)",
        "mars": "Red Coral (Moonga)",
        "mercury": "Emerald (Panna)",
        "jupiter": "Yellow Sapphire (Pukhraj)",
        "venus": "Diamond / White Sapphire",
        "saturn": "Blue Sapphire (Neelam)"
    }
    
    # Sign lords: 0:Mars, 1:Venus, 2:Mercury, 3:Moon, 4:Sun, 5:Mercury, 6:Venus, 7:Mars, 8:Jupiter, 9:Saturn, 10:Saturn, 11:Jupiter
    lords = ["mars", "venus", "mercury", "moon", "sun", "mercury", "venus", "mars", "jupiter", "saturn", "saturn", "jupiter"]
    
    lagna_lord = lords[lagna_sign_idx]
    fifth_lord = lords[(lagna_sign_idx + 4) % 12]
    ninth_lord = lords[(lagna_sign_idx + 8) % 12]
    
    recommended = []
    
    # We can add them with categories
    if lagna_lord in gems:
        recommended.append({"planet": lagna_lord, "gem": gems[lagna_lord], "purpose": "Life Force & Health (Lagna Lord)"})
    if fifth_lord in gems and fifth_lord != lagna_lord:
        recommended.append({"planet": fifth_lord, "gem": gems[fifth_lord], "purpose": "Intelligence & Luck (5th Lord)"})
    if ninth_lord in gems and ninth_lord != lagna_lord and ninth_lord != fifth_lord:
        recommended.append({"planet": ninth_lord, "gem": gems[ninth_lord], "purpose": "Fortune & Dharma (9th Lord)"})
        
    return recommended

def calculate_planetary_aspects(planet_results):
    aspects = []
    
    # Standard Vedic Aspects (Drishti)
    # All planets aspect the 7th house from themselves.
    # Mars: 4, 7, 8
    # Jupiter: 5, 7, 9
    # Saturn: 3, 7, 10
    # Rahu/Ketu: 5, 7, 9
    
    special_aspects = {
        "mars": [4, 7, 8],
        "jupiter": [5, 7, 9],
        "saturn": [3, 7, 10],
        "rahu": [5, 7, 9]
    }
    
    for p1_name, p1_data in planet_results.items():
        if p1_name == "ketu":
            continue
            
        p1_sign = int(p1_data["longitude"] // 30)
        
        aspect_houses = special_aspects.get(p1_name, [7])
        
        for aspect_house in aspect_houses:
            target_sign = (p1_sign + aspect_house - 1) % 12
            
            # Find planets in target sign
            for p2_name, p2_data in planet_results.items():
                if p1_name != p2_name:
                    p2_sign = int(p2_data["longitude"] // 30)
                    if p2_sign == target_sign:
                        aspects.append({
                            "aspectingPlanet": p1_name,
                            "aspectedPlanet": p2_name,
                            "aspectType": f"{aspect_house}th Drishti"
                        })
                        
    return aspects
