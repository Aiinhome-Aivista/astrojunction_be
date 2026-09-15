import re
from datetime import datetime
from flask import request, jsonify
import os

MONTHS_MAP = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'september': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12
}

def extract_birth_date(text: str):
    """
    Extracts dates in various formats:
    - 15-08-1995, 15/08/1995, 15.08.1995, 15 08 1995
    - 1995-08-15, 1995/08/15
    - 15 Aug 1995, 15th August 1995, 15-August-1995
    - August 15, 1995, Aug 15 1995
    """
    text_clean = text.lower()
    
    # 1. Matches like 15th August 1995, 15 Aug 1995, 15-August-1995
    match_named = re.search(r'(\b\d{1,2})(?:st|nd|rd|th)?[\s\-_,]+([a-z]{3,9})[\s\-_,]+(\d{4}\b)', text_clean)
    if match_named:
        d = int(match_named.group(1))
        m_str = match_named.group(2)
        y = int(match_named.group(3))
        for m_key, m_val in MONTHS_MAP.items():
            if m_str.startswith(m_key):
                return y, m_val, d

    # 2. Matches like August 15 1995, Aug 15th, 1995
    match_named_rev = re.search(r'([a-z]{3,9})[\s\-_,]+(\b\d{1,2})(?:st|nd|rd|th)?[\s\-_,]+(\d{4}\b)', text_clean)
    if match_named_rev:
        m_str = match_named_rev.group(1)
        d = int(match_named_rev.group(2))
        y = int(match_named_rev.group(3))
        for m_key, m_val in MONTHS_MAP.items():
            if m_str.startswith(m_key):
                return y, m_val, d

    # 3. Matches DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY, DD MM YYYY
    match_num = re.search(r'(\b\d{1,2})[-/.\s](\d{1,2})[-/.\s](\d{4}\b)', text)
    if match_num:
        d, m, y = int(match_num.group(1)), int(match_num.group(2)), int(match_num.group(3))
        if d > 12 and m <= 12:
            return y, m, d
        elif m > 12 and d <= 12:
            return y, d, m
        return y, m, d

    # 4. Matches YYYY-MM-DD, YYYY/MM/DD
    match_iso = re.search(r'(\b\d{4})[-/.\s](\d{1,2})[-/.\s](\d{1,2}\b)', text)
    if match_iso:
        return int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))

    return None

def calculate_life_path(year: int, month: int, day: int) -> int:
    digits = [int(c) for c in f"{year}{month:02d}{day:02d}" if c.isdigit()]
    total = sum(digits)
    while total > 9 and total not in [11, 22, 33]:
        total = sum(int(c) for c in str(total))
    return total

def calculate_mulank(day: int) -> int:
    total = sum(int(c) for c in str(day))
    while total > 9:
        total = sum(int(c) for c in str(total))
    return total

def get_zodiac_sign(month: int, day: int) -> str:
    zodiac_dates = [
        (1, 20, "Makara (Capricorn)"), (2, 19, "Kumbha (Aquarius)"),
        (3, 20, "Meena (Pisces)"), (4, 20, "Mesha (Aries)"),
        (5, 21, "Vrishabha (Taurus)"), (6, 21, "Mithuna (Gemini)"),
        (7, 22, "Karka (Cancer)"), (8, 23, "Simha (Leo)"),
        (9, 23, "Kanya (Virgo)"), (10, 23, "Tula (Libra)"),
        (11, 22, "Vrishchika (Scorpio)"), (12, 21, "Dhanu (Sagittarius)"),
        (12, 31, "Makara (Capricorn)")
    ]
    for m, d, sign in zodiac_dates:
        if month < m or (month == m and day <= d):
            return sign
    return "Mithuna (Gemini)"

def get_astrological_knowledge(dob):
    year, month, day = dob
    life_path = calculate_life_path(year, month, day)
    mulank = calculate_mulank(day)
    sign = get_zodiac_sign(month, day)
    
    traits_map = {
        1: {
            "planet": "Surya Dev (Sun)",
            "gems": "Ruby (Manik) & Red Garnet",
            "color": "Golden Amber & Saffron",
            "day": "Ravivar (Sunday)"
        },
        2: {
            "planet": "Chandra Dev (Moon)",
            "gems": "Natural Pearl (Moti) & Moonstone",
            "color": "Silvery White & Milk Cream",
            "day": "Somvar (Monday)"
        },
        3: {
            "planet": "Devaguru Brihaspati (Jupiter)",
            "gems": "Yellow Sapphire (Pukhraj) & Citrine",
            "color": "Golden Yellow & Saffron",
            "day": "Guruvar (Thursday)"
        },
        4: {
            "planet": "Rahu Dev",
            "gems": "Hessonite Garnet (Gomed)",
            "color": "Electric Blue & Charcoal",
            "day": "Shanivar (Saturday)"
        },
        5: {
            "planet": "Budha Dev (Mercury)",
            "gems": "Emerald (Panna) & Peridot",
            "color": "Emerald Green & Light Mint",
            "day": "Budhvar (Wednesday)"
        },
        6: {
            "planet": "Shukra Dev (Venus)",
            "gems": "Diamond / White Zircon & Opal",
            "color": "Diamond White & Soft Rose",
            "day": "Shukravar (Friday)"
        },
        7: {
            "planet": "Ketu Dev",
            "gems": "Cat's Eye (Lehsuniya)",
            "color": "Smoky Grey & Earth Brown",
            "day": "Guruvar (Thursday)"
        },
        8: {
            "planet": "Shani Dev (Saturn)",
            "gems": "Blue Sapphire (Neelam) & Amethyst",
            "color": "Royal Blue & Navy",
            "day": "Shanivar (Saturday)"
        },
        9: {
            "planet": "Mangal Dev (Mars)",
            "gems": "Red Coral (Moonga) & Carnelian",
            "color": "Bright Coral Red & Royal Saffron",
            "day": "Mangalvar (Tuesday)"
        }
    }
    
    t = traits_map.get(mulank, traits_map.get(life_path, traits_map[1]))
    return {
        "dob_str": f"{day:02d}-{month:02d}-{year}",
        "sign": sign,
        "life_path": life_path,
        "mulank": mulank,
        "planet": t["planet"],
        "gems": t["gems"],
        "color": t["color"],
        "day": t["day"]
    }

def public_chat():
    body = request.get_json(silent=True) or {}
    messages = body.get("messages", [])
    msg_count = body.get("msgCount", 0)
    saved_dob = body.get("dob", None)

    # 1. If limit reached, return login gate prompt
    if msg_count >= 3:
        return jsonify({
            "status": "success",
            "reply": "Please login to unlock deep analysis and detailed celestial wisdom.",
            "isLimitReached": True,
            "msgCount": msg_count,
            "dob": saved_dob
        })

    if not messages:
        return jsonify({
            "status": "success",
            "reply": "Namaste. I am AstroJunction, your Vedic Daivajna. How may I guide your astrological journey today?",
            "isLimitReached": False,
            "msgCount": msg_count,
            "dob": saved_dob
        })

    last_user_msg = messages[-1].get("content", "").strip()
    detected_dob = extract_birth_date(last_user_msg) or saved_dob

    # 2. If NO birth date provided yet: prompt for Date of Birth & Birth Time
    if not detected_dob:
        return jsonify({
            "status": "success",
            "reply": "Ayushman Bhava! To look into your Janma Kundli and reveal the precise planetary alignments for your query, please share your Date of Birth (DD-MM-YYYY) and Birth Time.",
            "dob": None,
            "isLimitReached": False,
            "msgCount": msg_count + 1
        })

    # 3. If DOB is provided: Calculate instant Vedic summary (Sign, Mulank, Ruling Graha, Gems, Color, Day) + Login Gate
    k = get_astrological_knowledge(detected_dob)
    reply = (
        f"🕉️ Kalyan Ho! Detailed Janma Kundli Overview ({k['dob_str']}):\n\n"
        f"• Zodiac Sign (Janma Rashi): {k['sign']}\n"
        f"• Mulank (Root Number): {k['mulank']} | Life Path: {k['life_path']}\n"
        f"• Ruling Graha (Planet): {k['planet']}\n"
        f"• Auspicious Gemstone: {k['gems']}\n"
        f"• Auspicious Color: {k['color']}\n"
        f"• Auspicious Day: {k['day']}"
    )

    return jsonify({
        "status": "success",
        "reply": reply,
        "dob": detected_dob,
        "isLimitReached": True,
        "msgCount": msg_count + 1
    })
