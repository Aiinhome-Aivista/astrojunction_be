import os
import sys
import json
import base64
import logging
import tempfile
import subprocess
from typing import Dict, Any, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger("pdf_service")

# Base directory for backend and frontend locales
BE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FE_LOCALE_DIR = os.path.join(os.path.dirname(BE_DIR), "astrojunction_fe", "src", "i18n", "locales")
FONTS_DIR = os.path.join(BE_DIR, "fonts")
TEMPLATES_DIR = os.path.join(BE_DIR, "templates", "pdf")

SUPPORTED_LANGUAGES = {"en", "hi", "bn", "ta", "fr"}

# Digit translation tables
DEVA_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
BENG_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")

ENGLISH_FALLBACK_NOTICES = {
    "en": "Some content is shown in English.",
    "hi": "कुछ सामग्री अंग्रेजी में दिखाई गई है।",
    "bn": "কিছু বিষয়বস্তু ইংরেজিতে দেখানো হয়েছে।",
    "ta": "சில உள்ளடக்கம் ஆங்கிலத்தில் காட்டப்பட்டுள்ளது.",
    "fr": "Certains contenus sont affichés en anglais."
}

# Cached fonts and locale dictionaries
_FONT_CACHE: Dict[str, str] = {}
_LOCALE_CACHE: Dict[str, Dict[str, Any]] = {}
_ASSET_CACHE: Dict[str, str] = {}

def get_asset_base64(filename: str) -> str:
    if filename in _ASSET_CACHE:
        return _ASSET_CACHE[filename]
    fe_public_path = os.path.join(os.path.dirname(BE_DIR), "astrojunction_fe", "public", filename)
    if os.path.exists(fe_public_path):
        try:
            with open(fe_public_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
                _ASSET_CACHE[filename] = data
                return data
        except Exception as e:
            logger.warning(f"Could not read asset {filename}: {e}")
    return ""

def get_font_base64(font_filename: str) -> str:
    if font_filename in _FONT_CACHE:
        return _FONT_CACHE[font_filename]
    path = os.path.join(FONTS_DIR, font_filename)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
                _FONT_CACHE[font_filename] = data
                return data
        except Exception as e:
            logger.warning(f"Could not read font {font_filename}: {e}")
    return ""

def load_locale_dict(lang: str) -> Dict[str, Any]:
    if lang in _LOCALE_CACHE:
        return _LOCALE_CACHE[lang]
    path = os.path.join(FE_LOCALE_DIR, f"{lang}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                _LOCALE_CACHE[lang] = data
                return data
        except Exception as e:
            logger.warning(f"Could not load locale {lang} from {path}: {e}")
    return {}

def format_localized_digits(value: Any, lang: str = "en") -> str:
    if value is None:
        return ""
    s = str(value)
    if lang == "hi":
        return s.translate(DEVA_DIGITS)
    elif lang == "bn":
        return s.translate(BENG_DIGITS)
    return s

def resolve_translation(key: str, lang: str, custom_labels: Optional[Dict[str, Any]] = None, default: str = "", **kwargs) -> str:
    # Build candidate keys to ensure full compatibility with both 'section.pdf.key' and 'section.key'
    candidate_keys = [key]
    parts = key.split(".")
    if len(parts) >= 2 and parts[1] != "pdf":
        candidate_keys.append(f"{parts[0]}.pdf.{'.'.join(parts[1:])}")
    elif len(parts) >= 3 and parts[1] == "pdf":
        candidate_keys.append(f"{parts[0]}.{'.'.join(parts[2:])}")

    # Aliases for common cross-template terms
    if key.endswith(".born") or key.endswith(".client_particulars"):
        for sec in ["birthChart", "roadmap", "numerology", "kundliMilan"]:
            candidate_keys.append(f"{sec}.pdf.{parts[-1]}")
    if key.endswith(".coordinates"):
        candidate_keys.append("birthChart.pdf.celestial_coords")
        candidate_keys.append("birthChart.pdf.coordinates")
        candidate_keys.append("roadmap.pdf.coordinates")
    if "classes.aadi" in key:
        candidate_keys.append(key.replace("classes.aadi", "classes.adi"))

    def _lookup_dict(d: Dict[str, Any], k: str) -> Any:
        if not d:
            return None
        if k in d and d[k] is not None:
            return d[k]
        curr = d
        for p in k.split("."):
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            else:
                return None
        return curr

    res = None
    # 1. Check custom labels
    if custom_labels:
        for ck in candidate_keys:
            val = _lookup_dict(custom_labels, ck)
            if val is not None:
                res = val
                break

    # 2. Check target language locale JSON
    if res is None:
        loc = load_locale_dict(lang)
        for ck in candidate_keys:
            val = _lookup_dict(loc, ck)
            if val is not None:
                res = val
                break

    # 3. Fallback to English locale JSON
    if res is None and lang != "en":
        en_loc = load_locale_dict("en")
        for ck in candidate_keys:
            val = _lookup_dict(en_loc, ck)
            if val is not None:
                logger.warning(f"Translation for '{key}' missing in '{lang}', used English fallback.")
                res = val
                break

    # 4. Provided default
    if res is None:
        res = default if default != "" else key

    # 5. Interpolate placeholders {{k}} and {k} if string
    if isinstance(res, str):
        if kwargs:
            for k, v in kwargs.items():
                res = res.replace(f"{{{{{k}}}}}", str(v))
                res = res.replace(f"{{{k}}}", str(v))
        # Safely clean any remaining un-interpolated {{placeholder}} or {placeholder}
        import re
        res = re.sub(r'\{\{\s*\w+\s*\}\}', '', res)
        res = re.sub(r'\{[a-zA-Z_]\w*\}', '', res)

    return res

def find_chrome_executable() -> str:
    # Known locations on Windows & Linux
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "chrome"

# Initialize Jinja2 Environment with autoescape
jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"])
)

def render_pdf(template_name: str, lang: str, data: Dict[str, Any], labels: Optional[Dict[str, Any]] = None) -> bytes:
    """
    Renders an HTML template into a PDF using headless Chromium with full Indic script shaping.
    Guarantees validation of language, autoescaping of inputs, embedded static fonts,
    and localized digit formatting.
    """
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = "en"

    # Context setup
    context = dict(data)
    context["lang"] = lang
    context["labels"] = labels or {}

    # Translation helper available directly in template
    def t(key: str, default: str = "", **kwargs) -> str:
        return resolve_translation(key, lang, labels, default, **kwargs)

    # Digit formatting filter
    def d(val: Any) -> str:
        return format_localized_digits(val, lang)

    context["t"] = t
    context["d"] = d
    context["english_notice"] = ENGLISH_FALLBACK_NOTICES.get(lang, ENGLISH_FALLBACK_NOTICES["en"])

    # Glossary lookup helpers
    def _clean_key(v: Any) -> str:
        if not v:
            return ""
        s = str(v).lower().strip()
        # Remove parenthetical details like (Pada 2) or (Brihaspati)
        import re
        s = re.sub(r'\(.*?\)', '', s).strip()
        return s.replace(" ", "_").replace("-", "_")

    def t_planet(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        # Normalise common variations
        m = {
            "ascendant": "lagna", "sun": "sun", "surya": "sun",
            "moon": "moon", "chandra": "moon", "soma": "moon",
            "mars": "mars", "mangal": "mars", "kuja": "mars",
            "mercury": "mercury", "budh": "mercury", "budha": "mercury",
            "jupiter": "jupiter", "guru": "jupiter", "brihaspati": "jupiter",
            "venus": "venus", "shukra": "venus",
            "saturn": "saturn", "shani": "saturn",
            "rahu": "rahu", "ketu": "ketu"
        }
        k = m.get(ck, ck)
        return resolve_translation(f"vedic.planets.{k}", lang, labels, default=str(val))

    def t_sign(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        m = {
            "aries": "aries", "mesha": "aries",
            "taurus": "taurus", "vrishabha": "taurus",
            "gemini": "gemini", "mithuna": "gemini",
            "cancer": "cancer", "karka": "cancer",
            "leo": "leo", "simha": "leo",
            "virgo": "virgo", "kanya": "virgo",
            "libra": "libra", "tula": "libra",
            "scorpio": "scorpio", "vrishchika": "scorpio",
            "sagittarius": "sagittarius", "dhanu": "sagittarius",
            "capricorn": "capricorn", "makara": "capricorn",
            "aquarius": "aquarius", "kumbha": "aquarius",
            "pisces": "pisces", "meena": "pisces"
        }
        k = m.get(ck, ck)
        return resolve_translation(f"vedic.signs.{k}", lang, labels, default=str(val))

    def t_nakshatra(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        return resolve_translation(f"vedic.nakshatras.{ck}", lang, labels, default=str(val))

    def t_dignity(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        m = {
            "exalted": "exalted", "uchcha": "exalted",
            "debilitated": "debilitated", "neecha": "debilitated",
            "moolatrikona": "moolatrikona", "own": "own",
            "neutral": "neutral", "sama": "neutral",
            "friend": "friend", "enemy": "enemy"
        }
        k = m.get(ck, ck)
        return resolve_translation(f"birthChart.planets_table.dignities.{k}", lang, labels, default=str(val))

    def t_koota(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        clean_id = ck.replace("_koota", "").replace(" ", "_")
        if clean_id in ["graha_maitri", "grahamaitri"]:
            clean_id = "graha"
        trans = resolve_translation(f"kundliMilan.kootas.{clean_id}.name", lang, labels, default="")
        if trans: return trans
        trans = resolve_translation(f"vedic.kootas.{clean_id}", lang, labels, default="")
        if trans: return trans
        return resolve_translation(f"vedic.kootas.{ck}", lang, labels, default=str(val))

    def t_koota_area(val: Any, default_val: str = "") -> str:
        ck = _clean_key(val)
        clean_id = ck.replace("_koota", "").replace(" ", "_") if ck else ""
        if clean_id in ["graha_maitri", "grahamaitri"]:
            clean_id = "graha"
        if clean_id:
            trans = resolve_translation(f"kundliMilan.kootas.{clean_id}.area", lang, labels, default="")
            if trans: return trans
        if default_val:
            return default_val
        return str(val or "")

    def t_place(val: Any) -> str:
        s = str(val or "").strip()
        if not s or s.lower() == "global":
            places = {
                "hi": "वैश्विक (Global)",
                "bn": "সার্বজনীন (Global)",
                "ta": "பொதுவானது (Global)",
                "fr": "Mondial (Global)",
                "en": "Global"
            }
            return places.get(lang, "Global")
        return s

    def t_koota_value(val: Any) -> str:
        s = str(val or "").strip()
        if not s or s == "-":
            return "-"
        
        # 1. Tara: e.g. "Tara 3/9" or "Tara 5/9"
        if s.lower().startswith("tara "):
            num_part = s[5:].strip()
            tara_word = resolve_translation("kundliMilan.classes.tara", lang, labels, default="Tara" if lang in ["en", "fr"] else ("तारा" if lang == "hi" else ("তারা" if lang == "bn" else "தாரா")))
            return f"{tara_word} {format_localized_digits(num_part, lang)}"

        # 2. Gana: e.g. "Deva Gana", "Manushya Gana", "Rakshasa Gana"
        if "gana" in s.lower():
            g_base = s.lower().replace("gana", "").strip()
            g_trans = resolve_translation(f"kundliMilan.classes.{g_base}", lang, labels, default="")
            if g_trans:
                if lang in ["en", "fr"]:
                    return f"{g_trans} Gana"
                elif lang == "hi":
                    return f"{g_trans} गण"
                elif lang == "bn":
                    return f"{g_trans} গণ"
                elif lang == "ta":
                    return f"{g_trans} கணம்"
                return f"{g_trans} Gana"

        # 3. Nadi: e.g. "Adi Nadi", "Madhya Nadi", "Antya Nadi"
        if "nadi" in s.lower():
            n_base = s.lower().replace("nadi", "").strip()
            if n_base in ["aadi", "adi"]:
                n_base = "adi"
            elif n_base in ["madhyama", "madhya"]:
                n_base = "madhya"
            n_trans = resolve_translation(f"kundliMilan.classes.{n_base}", lang, labels, default="")
            if not n_trans and n_base == "adi":
                n_trans = resolve_translation("kundliMilan.classes.adi", lang, labels, default="")
            if n_trans:
                if lang in ["en", "fr"]:
                    return f"{n_trans} Nadi"
                elif lang == "hi":
                    return f"{n_trans} नाड़ी"
                elif lang == "bn":
                    return f"{n_trans} নাড়ী"
                elif lang == "ta":
                    return f"{n_trans} நாடி"
                return f"{n_trans} Nadi"

        # 4. Graha Maitri or Bhakoot: e.g. "Cancer (Moon)" or "Cancer (4)"
        import re
        paren_match = re.match(r"^([A-Za-z]+)\s*\(([^)]+)\)$", s)
        if paren_match:
            sign_part = paren_match.group(1)
            inner_part = paren_match.group(2)
            t_s = t_sign(sign_part)
            if inner_part.isdigit():
                return f"{t_s} ({format_localized_digits(inner_part, lang)})"
            else:
                t_p = t_planet(inner_part)
                return f"{t_s} ({t_p})"

        # 5. Single class lookup: Varna, Vashya, Yoni, etc.
        ck = _clean_key(s)
        if ck in ["aadi", "adi"]:
            ck = "adi"
        elif ck in ["madhyama", "madhya"]:
            ck = "madhya"
        cls_trans = resolve_translation(f"kundliMilan.classes.{ck}", lang, labels, default="")
        if cls_trans:
            return cls_trans

        return s

    def t_gem(val: Any) -> str:
        ck = _clean_key(val)
        if not ck: return str(val or "")
        return resolve_translation(f"vedic.gems.{ck}", lang, labels, default=str(val))

    def t_loshu_cell(val: Any) -> str:
        s = str(val or "").strip()
        if not s or "absent" in s.lower() or s == "0" or s == "-":
            if lang == "en":
                return "Absent"
            return resolve_translation("numerology.loshu.absent", lang, labels, default="অনুপস্থিত")
        import re
        m = re.search(r"(\d+)", s)
        cnt = m.group(1) if m else "1"
        if lang == "en":
            return f"Present ({cnt})"
        template = resolve_translation("numerology.loshu.count_times", lang, labels, default="{{count}} বার")
        if isinstance(template, str):
            return template.replace("{{count}}", format_localized_digits(cnt, lang))
        return f"{format_localized_digits(cnt, lang)} বার"

    def t_plane_name(pl: Any) -> str:
        if not isinstance(pl, dict):
            return str(pl)
        name = pl.get("name", "")
        numbers = str(pl.get("numbers", ""))
        if lang == "en":
            return name
        nums_clean = numbers.replace(" ", "").replace("-", "")
        key_map = {
            "438": "thought", "492": "mental",
            "951": "will", "357": "emotional",
            "276": "action", "816": "practical",
            "456": "raj_yoga", "258": "spirituality"
        }
        name_lower = name.lower()
        key = key_map.get(nums_clean)
        if not key:
            if "thought" in name_lower: key = "thought"
            elif "will" in name_lower: key = "will"
            elif "action" in name_lower: key = "action"
            elif "mental" in name_lower: key = "mental"
            elif "emotional" in name_lower: key = "emotional"
            elif "practical" in name_lower: key = "practical"
            elif "raj" in name_lower or "gold" in name_lower: key = "raj_yoga"
            elif "spirit" in name_lower or "silver" in name_lower: key = "spirituality"
        
        if key:
            plane_data = resolve_translation(f"numerology.meta.planes.{key}", lang, labels, default=None)
            if isinstance(plane_data, dict) and "name" in plane_data:
                res = plane_data["name"]
                parts = numbers.split("-") if "-" in numbers else list(numbers)
                if len(parts) >= 3:
                    res = res.replace("{{n1}}", format_localized_digits(parts[0], lang))
                    res = res.replace("{{n2}}", format_localized_digits(parts[1], lang))
                    res = res.replace("{{n3}}", format_localized_digits(parts[2], lang))
                return res
        return name

    def t_plane_domain(pl: Any) -> str:
        if not isinstance(pl, dict):
            return str(pl)
        domain = pl.get("domain", "")
        if lang == "en":
            return domain
        numbers = str(pl.get("numbers", "")).replace(" ", "").replace("-", "")
        key_map = {
            "438": "thought", "492": "mental",
            "951": "will", "357": "emotional",
            "276": "action", "816": "practical",
            "456": "raj_yoga", "258": "spirituality"
        }
        name_lower = pl.get("name", "").lower()
        key = key_map.get(numbers)
        if not key:
            if "thought" in name_lower: key = "thought"
            elif "will" in name_lower: key = "will"
            elif "action" in name_lower: key = "action"
            elif "mental" in name_lower: key = "mental"
            elif "emotional" in name_lower: key = "emotional"
            elif "practical" in name_lower: key = "practical"
            elif "raj" in name_lower or "gold" in name_lower: key = "raj_yoga"
            elif "spirit" in name_lower or "silver" in name_lower: key = "spirituality"
        if key:
            plane_data = resolve_translation(f"numerology.meta.planes.{key}", lang, labels, default=None)
            if isinstance(plane_data, dict) and "meaning" in plane_data:
                return plane_data["meaning"]
        return domain

    def t_mulank_planet(val: Any) -> str:
        s = str(val or "").strip()
        num = "".join(c for c in s if c.isdigit())
        if not num:
            return t_planet(s)
        if lang == "en":
            p_map = {
                "1": "Sun (Surya - The Sovereign & Creator)",
                "2": "Moon (Chandra - The Nurturer & Intuitive)",
                "3": "Jupiter (Guru - The Supreme Preceptor)",
                "4": "Rahu (The Revolutionary Architect)",
                "5": "Mercury (Budha - The Master Strategist)",
                "6": "Venus (Shukra - The Cosmic Artist)",
                "7": "Ketu (The Mystic Philosopher)",
                "8": "Saturn (Shani - The Karmic Master & Judge)",
                "9": "Mars (Mangal - The Divine Commander)"
            }
            return p_map.get(num, str(val))
        return resolve_translation(f"numerology.meta.planets.{num}", lang, labels, default=str(val))

    def t_mission(val: Any) -> str:
        s = str(val or "").strip()
        num = "".join(c for c in s if c.isdigit())
        if not num:
            num = "1"
        if lang == "en":
            m_en = {
                "1": "To pioneer ground-breaking paths, govern with ethical authority, and illuminate institutions with visionary purpose.",
                "2": "To cultivate relational harmony, build empathetic spaces, and refine subtle diplomacy and fine arts.",
                "3": "To impart transformational knowledge, inspire through wisdom, and uphold ethical and spiritual values.",
                "4": "To engineer enduring systems, shatter archaic conventions, and establish methodical order amidst chaos.",
                "5": "To navigate expansive global networks, orchestrate commercial enterprises, and master expressive communication.",
                "6": "To nurture unconditional aesthetic grace, harmonise familial and matrimonial ecosystems, and curate worldly abundance.",
                "7": "To unveil cosmological mysteries, pursue spiritual truth through solitary contemplation, and guide humanity toward transcendence.",
                "8": "To build resilient commercial empires, enforce divine karmic justice, and uplift marginalized societal structures through perseverance.",
                "9": "To champion humanitarian righteousness, execute heroic missions, and fiercely protect the virtuous against injustice."
            }
            return m_en.get(num, "")
        return resolve_translation(f"numerology.meta.missions.{num}", lang, labels, default="")

    def t_colors(color_val: Any) -> str:
        s = str(color_val or "").strip()
        if not s: return ""
        if lang == "en": return s
        parts = [p.strip() for p in s.split(",") if p.strip()]
        translated = []
        colors_dict = resolve_translation("numerology.meta.colors", lang, labels, default={})
        if not isinstance(colors_dict, dict): colors_dict = {}
        for p in parts:
            ck = p.lower().replace(" ", "_").replace("-", "_")
            matched = colors_dict.get(ck)
            if not matched:
                for k, v in colors_dict.items():
                    if k in ck or ck in k:
                        matched = v
                        break
            translated.append(matched if matched else p)
        return ", ".join(translated)

    def t_days(days_val: Any) -> str:
        s = str(days_val or "").strip()
        if not s: return ""
        if lang == "en": return s
        parts = [p.strip() for p in s.split(",") if p.strip()]
        translated = []
        days_dict = resolve_translation("numerology.meta.days", lang, labels, default={})
        if not isinstance(days_dict, dict): days_dict = {}
        for p in parts:
            dk = p.lower().strip()
            matched = days_dict.get(dk)
            if not matched:
                for k, v in days_dict.items():
                    if k in dk or dk in k:
                        matched = v
                        break
            translated.append(matched if matched else p)
        return ", ".join(translated)

    def t_planets_list(planets_val: Any) -> str:
        s = str(planets_val or "").strip()
        if not s or s.lower() == "no planets":
            return resolve_translation("birthChart.pdf.no_planets", lang, labels, default="No Planets") if lang != "en" else "No Planets"
        if lang == "en": return s
        parts = [p.strip() for p in s.split(",") if p.strip()]
        translated = [t_planet(p) for p in parts]
        return ", ".join(translated)

    def t_house_name(house_num: Any, default_name: str = "") -> str:
        if lang == "en":
            return default_name
        hn = int(house_num or 1)
        h_data = resolve_translation(f"birthChart.houses.house_{hn}", lang, labels, default=None)
        if isinstance(h_data, dict) and "name" in h_data:
            return h_data["name"]
        return default_name

    def t_horizon(val: Any) -> str:
        s = str(val or "").strip()
        if not s: return ""
        import re
        m = re.match(r"^(\d+)-(\d+)\s*(Years?|Year|years?|year)?$", s, re.IGNORECASE)
        if m:
            start_n = m.group(1)
            end_n = m.group(2)
            d_start = format_localized_digits(start_n, lang)
            d_end = format_localized_digits(end_n, lang)
            if lang == "hi":
                unit = "वर्ष"
            elif lang == "bn":
                unit = "বছর"
            elif lang == "ta":
                unit = "வருடம்" if end_n == "1" else "வருடங்கள்"
            elif lang == "fr":
                unit = "An" if end_n == "1" else "Ans"
            else:
                unit = "Year" if end_n == "1" else "Years"
            return f"{d_start}-{d_end} {unit}"
        return format_localized_digits(s, lang)

    context["t_planet"] = t_planet
    context["t_sign"] = t_sign
    context["t_nakshatra"] = t_nakshatra
    context["t_dignity"] = t_dignity
    context["t_koota"] = t_koota
    context["t_koota_area"] = t_koota_area
    context["t_koota_value"] = t_koota_value
    context["t_place"] = t_place
    context["t_gem"] = t_gem
    context["t_loshu_cell"] = t_loshu_cell
    context["t_plane_name"] = t_plane_name
    context["t_plane_domain"] = t_plane_domain
    context["t_mulank_planet"] = t_mulank_planet
    context["t_mission"] = t_mission
    context["t_colors"] = t_colors
    context["t_days"] = t_days
    context["t_planets_list"] = t_planets_list
    context["t_house_name"] = t_house_name
    context["t_horizon"] = t_horizon

    # Fonts base64 embedding per language
    font_css = []
    # Common Nunito (Latin digits and Latin brand)
    nunito_reg = get_font_base64("Nunito-400.ttf")
    nunito_semi = get_font_base64("Nunito-600.ttf")
    if nunito_reg:
        font_css.append(f"@font-face {{ font-family: 'Nunito'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{nunito_reg}') format('truetype'); }}")
    if nunito_semi:
        font_css.append(f"@font-face {{ font-family: 'Nunito'; font-weight: 600; src: url('data:font/truetype;charset=utf-8;base64,{nunito_semi}') format('truetype'); }}")

    # Rozha One (Header accent)
    rozha_reg = get_font_base64("RozhaOne-400.ttf")
    if rozha_reg:
        font_css.append(f"@font-face {{ font-family: 'Rozha One'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{rozha_reg}') format('truetype'); }}")

    # Language-specific Indic & Latin fonts
    if lang == "hi":
        hi_reg = get_font_base64("NotoSansDevanagari-400.ttf")
        hi_bold = get_font_base64("NotoSansDevanagari-600.ttf")
        if hi_reg:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Devanagari'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{hi_reg}') format('truetype'); }}")
        if hi_bold:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Devanagari'; font-weight: 600; src: url('data:font/truetype;charset=utf-8;base64,{hi_bold}') format('truetype'); }}")
        context["font_family"] = "'Noto Sans Devanagari', 'Nirmala UI', sans-serif"
        context["heading_font"] = "'Noto Sans Devanagari', 'Rozha One', serif"
    elif lang == "bn":
        bn_reg = get_font_base64("NotoSansBengali-400.ttf")
        bn_bold = get_font_base64("NotoSansBengali-600.ttf")
        if bn_reg:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Bengali'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{bn_reg}') format('truetype'); }}")
        if bn_bold:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Bengali'; font-weight: 600; src: url('data:font/truetype;charset=utf-8;base64,{bn_bold}') format('truetype'); }}")
        context["font_family"] = "'Noto Sans Bengali', 'Nirmala UI', sans-serif"
        context["heading_font"] = "'Noto Sans Bengali', serif"
    elif lang == "ta":
        ta_reg = get_font_base64("NotoSansTamil-400.ttf")
        ta_bold = get_font_base64("NotoSansTamil-600.ttf")
        if ta_reg:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Tamil'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{ta_reg}') format('truetype'); }}")
        if ta_bold:
            font_css.append(f"@font-face {{ font-family: 'Noto Sans Tamil'; font-weight: 600; src: url('data:font/truetype;charset=utf-8;base64,{ta_bold}') format('truetype'); }}")
        context["font_family"] = "'Noto Sans Tamil', 'Nirmala UI', sans-serif"
        context["heading_font"] = "'Noto Sans Tamil', sans-serif"
    else: # en, fr
        stardom = get_font_base64("Stardom-Regular.ttf")
        if stardom:
            font_css.append(f"@font-face {{ font-family: 'Stardom'; font-weight: 400; src: url('data:font/truetype;charset=utf-8;base64,{stardom}') format('truetype'); }}")
        context["font_family"] = "'Nunito', sans-serif"
        context["heading_font"] = "'Stardom', 'Rozha One', serif"

    context["embedded_fonts_css"] = "\n".join(font_css)
    context["logo_base64"] = get_asset_base64("jyotishveda_logo.png")
    context["bg_base64"] = get_asset_base64("astrologer_bg.jpg")
    if "doc_date_full" not in context:
        from datetime import datetime
        now = datetime.now()
        month_names = {
            "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
            "hi": ["जनवरी", "फरवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
            "bn": ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"],
            "ta": ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"],
            "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        }
        day_names = {
            "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "hi": ["सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"],
            "bn": ["সোম", "মঙ্গল", "বুধ", "বৃহস্পতি", "শুক্র", "শনি", "রবি"],
            "ta": ["திங்கள்", "செவ்வாய்", "புதன்", "வியாழன்", "வெள்ளி", "சனி", "ஞாயிறு"],
            "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
        }
        m_idx = now.month - 1
        d_idx = now.weekday()
        m_str = month_names.get(lang, month_names["en"])[m_idx]
        d_str = day_names.get(lang, day_names["en"])[d_idx]
        hour_12 = now.hour % 12 or 12
        if lang == "hi":
            am_pm = "पूर्वाह्न" if now.hour < 12 else "अपराह्न"
            context["doc_date_full"] = f"{d_str}, {format_localized_digits(now.day, lang)} {m_str} {format_localized_digits(now.year, lang)}, {format_localized_digits(f'{hour_12:02d}:{now.minute:02d}', lang)} {am_pm}"
        elif lang == "bn":
            am_pm = "পূর্বাহ্ন" if now.hour < 12 else "অপরাহ্ন"
            context["doc_date_full"] = f"{d_str}, {format_localized_digits(now.day, lang)} {m_str} {format_localized_digits(now.year, lang)}, {format_localized_digits(f'{hour_12:02d}:{now.minute:02d}', lang)} {am_pm}"
        elif lang == "ta":
            am_pm = "மு.ப" if now.hour < 12 else "பி.ப"
            context["doc_date_full"] = f"{d_str}, {now.day} {m_str} {now.year}, {hour_12:02d}:{now.minute:02d} {am_pm}"
        elif lang == "fr":
            context["doc_date_full"] = f"{d_str} {now.day} {m_str} {now.year}, {now.hour:02d}h{now.minute:02d}"
        else:
            context["doc_date_full"] = now.strftime("%a, %b %d, %Y, %I:%M %p")

    # Render HTML template via Jinja2
    tmpl = jinja_env.get_template(template_name)
    rendered_html = tmpl.render(**context)

    # Write temporary files and execute headless Chrome
    tmp_html = None
    tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False) as f_html:
            f_html.write(rendered_html)
            tmp_html = f_html.name

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f_pdf:
            tmp_pdf = f_pdf.name

        chrome_bin = find_chrome_executable()
        cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            f"--print-to-pdf={tmp_pdf}",
            f"file:///{tmp_html.replace(os.sep, '/')}"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0:
            logger.error(f"Chrome PDF generation failed (rc={result.returncode}): {result.stderr}")
            raise RuntimeError(f"PDF generation process returned error: {result.stderr}")

        with open(tmp_pdf, "rb") as f_out:
            pdf_bytes = f_out.read()

        return pdf_bytes

    finally:
        if tmp_html and os.path.exists(tmp_html):
            try:
                os.remove(tmp_html)
            except Exception:
                pass
        if tmp_pdf and os.path.exists(tmp_pdf):
            try:
                os.remove(tmp_pdf)
            except Exception:
                pass
