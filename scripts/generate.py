"""
Content Generator Module for AstroJunction
Generates authentic multi-system (Tropical & Sidereal) category-wise horoscope predictions
for all 8 categories in strict JSON format using LLM (Claude API / Active LLM Provider).
Validated with Pydantic with automatic retry and post-processing clean_text.
"""

import os
import sys
import json
import re
import time
from datetime import date
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError
from dotenv import load_dotenv

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.append(backend_dir)

load_dotenv(os.path.join(backend_dir, ".env"))
load_dotenv()

# The 8 horoscope categories (7 specific life domains followed by cosmic_pulse overall synthesis)
CATEGORIES = [
    "health",
    "wealth",
    "relationship",
    "love_line",
    "education",
    "professional",
    "travel",
    "cosmic_pulse"
]

SIGN_PROFILES = {
    "aries": {"ruler": "Mars", "element": "Fire", "quality": "Cardinal"},
    "taurus": {"ruler": "Venus", "element": "Earth", "quality": "Fixed"},
    "gemini": {"ruler": "Mercury", "element": "Air", "quality": "Mutable"},
    "cancer": {"ruler": "Moon", "element": "Water", "quality": "Cardinal"},
    "leo": {"ruler": "Sun", "element": "Fire", "quality": "Fixed"},
    "virgo": {"ruler": "Mercury", "element": "Earth", "quality": "Mutable"},
    "libra": {"ruler": "Venus", "element": "Air", "quality": "Cardinal"},
    "scorpio": {"ruler": "Mars / Pluto", "element": "Water", "quality": "Fixed"},
    "sagittarius": {"ruler": "Jupiter", "element": "Fire", "quality": "Mutable"},
    "capricorn": {"ruler": "Saturn", "element": "Earth", "quality": "Cardinal"},
    "aquarius": {"ruler": "Saturn / Uranus", "element": "Air", "quality": "Fixed"},
    "pisces": {"ruler": "Jupiter / Neptune", "element": "Water", "quality": "Mutable"},
}


# Centralized length and paragraph configuration per period
PERIOD_RULES = {
    "daily": {
        "min_words": 160,
        "max_words": 190,
        "tolerance": 0.10,  # 144 to 209 words
        "paragraphs": (1, 1),
        "separator": " ",
        "description": "160-190 words, exactly 1 paragraph"
    },
    "weekly": {
        "min_words": 250,
        "max_words": 300,
        "tolerance": 0.10,  # 225 to 330 words
        "paragraphs": (2, 3),
        "separator": "\n\n",
        "description": "250-300 words, 2-3 short paragraphs separated by \\n\\n"
    },
    "monthly": {
        "min_words": 380,
        "max_words": 450,
        "tolerance": 0.10,  # 342 to 495 words
        "paragraphs": (3, 4),
        "separator": "\n\n",
        "description": "380-450 words, 3-4 short paragraphs separated by \\n\\n"
    },
    "yearly": {
        "min_words": 600,
        "max_words": 700,
        "tolerance": 0.10,  # 540 to 770 words
        "paragraphs": (4, 5),
        "separator": "\n\n",
        "description": "600-700 words, 4-5 short paragraphs separated by \\n\\n"
    }
}


def clean_text(text: str) -> str:
    """
    Post-processing function that strips any leftover markdown characters
    (**, *, #, -, bullets, numbering, emojis), keeps "\n\n" paragraph breaks,
    and normalizes whitespace within each paragraph.
    """
    if not text:
        return ""

    # 1. Strip emojis (unicode emoji ranges)
    emoji_pattern = re.compile(
        r'[\U00010000-\U0010FFFF\u2600-\u27BF\u2300-\u23FF\u2B50\u200D\uFE0E\uFE0F]'
    )
    cleaned = emoji_pattern.sub('', text)

    # 2. Strip markdown headers (e.g. ### Heading)
    cleaned = re.sub(r'#{1,6}\s*', '', cleaned)

    # 3. Strip bold, italic, strikethrough, backticks
    cleaned = cleaned.replace('**', '').replace('*', '').replace('~~', '').replace('`', '')

    # 4. Strip list bullets and numbering (e.g. \n-, \n1.)
    cleaned = re.sub(r'(?m)^\s*([-•●▪▫✦★+]|\d+\.)\s+', '', cleaned)
    for bullet_char in ['•', '●', '▪', '▫', '✦', '★']:
        cleaned = cleaned.replace(bullet_char, '')

    # 5. Strip common editorial labels
    cleaned = re.sub(
        r'(?i)\b(do\'?s\s*&\s*don\'?ts?|remedy|timing|affirmation|today\'?s\s*tip|weekly\s*tip|lucky\s*time|planetary\s*guidance)\s*:\s*',
        '',
        cleaned
    )

    # 6. Normalize paragraph breaks: preserve "\n\n", clean intra-paragraph spaces
    paragraphs = [re.sub(r'\s+', ' ', p).strip() for p in re.split(r'\n\s*\n+', cleaned) if p.strip()]
    return "\n\n".join(paragraphs)


def ensure_complete_sentences(text: str) -> str:
    """
    Ensures that prediction text consists strictly of complete sentences:
    - If the text ends on a dangling conjunction or preposition (chopped mid-sentence),
      it trims back to the last complete sentence.
    - If it ends on a complete word/thought without a period, it appends a period.
    - Guarantees each paragraph ends with a valid terminal punctuation mark (. ! ?).
    """
    if not text:
        return text

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
    cleaned_paras = []
    terminal_puncts = ('.', '!', '?', '"', "'", '।')
    dangling_words = {
        'and', 'or', 'but', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of',
        'with', 'by', 'as', 'is', 'are', 'was', 'were', 'will', 'be', 'while', 'because',
        'that', 'which', 'who', 'whom', 'whose', 'if', 'when', 'where', 'so', 'than'
    }

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue

        if not p.endswith(terminal_puncts):
            words_in_p = p.split()
            last_word = words_in_p[-1].lower().strip(',;:') if words_in_p else ''
            # If the last word is a dangling conjunction or preposition, it was cut mid-sentence!
            if last_word in dangling_words:
                last_punct_idx = max(p.rfind('.'), p.rfind('!'), p.rfind('?'), p.rfind('।'))
                if last_punct_idx != -1:
                    p = p[:last_punct_idx + 1].strip()
                else:
                    p = p + '.'
            else:
                # If it ended on a normal noun/adjective/verb, it's a complete sentence missing a period
                p = p.rstrip(',;:- ') + '.'

        cleaned_paras.append(p)

    return "\n\n".join(cleaned_paras)


class HoroscopeCategoryItem(BaseModel):
    category: Literal[
        "cosmic_pulse", "health", "wealth", "relationship",
        "love_line", "education", "professional", "travel"
    ]
    text: str = Field(min_length=20, description="Rich astrological prediction for this category")
    score: int = Field(ge=0, le=100, description="Predictive transit score from 0 to 100")
    lucky_time: str = Field(description="Auspicious time window e.g. 09:30 AM - 11:30 AM")
    remedy: str = Field(description="Sacred astrological remedy or Vedic upaya")
    affirmation: str = Field(description="Empowering affirmation sentence")
    tip_for_the_day: Optional[str] = Field(
        default=None,
        description="Actionable single-sentence tip for cosmic_pulse only"
    )
    period: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_category_item(self):
        v = self.text
        # Clean text and ensure all sentences are complete
        v = clean_text(v)
        v = ensure_complete_sentences(v)
        self.text = v

        p_key = (self.period or "").lower().strip()

        # 1. Prohibited markdown and format checks
        if "**" in v:
            raise ValueError("Text contains prohibited markdown bold syntax '**'")
        if "#" in v:
            raise ValueError("Text contains prohibited markdown heading syntax '#'")
        if "\n-" in v or "\n•" in v:
            raise ValueError("Text contains prohibited markdown bullet syntax '\\n-'")
        if re.search(r'\n\d+\.', v):
            raise ValueError("Text contains prohibited markdown numbered list syntax '\\n1.'")
        if re.search(r'[\U00010000-\U0010FFFF\u2600-\u27BF\u2300-\u23FF\u2B50]', v):
            raise ValueError("Text contains prohibited emojis")

        # 2. Quality & complete sentence validation (Flexible word count)
        words = v.split()
        word_count = len(words)
        if word_count < 25:
            raise ValueError(
                f"Prediction text is too brief ({word_count} words). Minimum 25 words required for a meaningful forecast."
            )

        paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', v.strip()) if p.strip()]
        if len(paragraphs) < 1:
            raise ValueError("Prediction must contain at least 1 paragraph.")
        if len(paragraphs) > 6:
            raise ValueError(f"Text contains {len(paragraphs)} paragraphs; maximum 6 paragraphs allowed.")

        # Ensure every single paragraph ends as a complete sentence
        terminal_puncts = ('.', '!', '?', '"', "'", '।')
        for p in paragraphs:
            if not p.endswith(terminal_puncts):
                raise ValueError("Every paragraph must end as a complete sentence with terminal punctuation (. ! ?).")

        # 3. Tip for cosmic_pulse
        cat = self.category
        tip = self.tip_for_the_day
        if cat == "cosmic_pulse":
            if not tip or not str(tip).strip():
                raise ValueError("Category 'cosmic_pulse' MUST include a non-empty 'tip_for_the_day'.")

            clean_tip = clean_text(str(tip))
            clean_tip = re.sub(r'(?i)^(tip(\s*for\s*the\s*(day|week|month|year))?\s*:\s*)', '', clean_tip).strip()

            if "**" in clean_tip or "#" in clean_tip or "\n" in clean_tip:
                raise ValueError("tip_for_the_day contains prohibited markdown or line breaks")

            planet_names = [
                r'\bplanet(s)?\b', r'\bsun\b', r'\bmoon\b', r'\bmars\b', r'\bmercury\b',
                r'\bjupiter\b', r'\bvenus\b', r'\bsaturn\b', r'\brahu\b', r'\bketu\b',
                r'\bpluto\b', r'\bneptune\b', r'\buranus\b'
            ]
            for p_pat in planet_names:
                if re.search(p_pat, clean_tip, re.IGNORECASE):
                    raise ValueError(f"tip_for_the_day must not mention planets: detected '{p_pat}' in '{clean_tip}'")

            if not clean_tip.endswith(('.', '!', '?')):
                clean_tip += '.'

            words = clean_tip.split()
            if len(words) < 4:
                raise ValueError(f"tip_for_the_day is too short (got {len(words)} words): '{clean_tip}'")

            self.tip_for_the_day = clean_tip
        else:
            self.tip_for_the_day = None

        return self


class HoroscopeGenerationResponse(BaseModel):
    items: List[HoroscopeCategoryItem]


def _call_llm_api(system_prompt: str, user_prompt: str, max_tokens: int = None) -> str:
    """
    Executes the LLM request using the active LLM configured in Admin Settings.
    """
    from services.llm_service import _execute_llm
    history = [{"role": "user", "content": user_prompt}]
    return _execute_llm(system_prompt, history, max_tokens=max_tokens)


def clamp_weekly_words(text: str, max_w: int = 325) -> str:
    """Clamps text length below max_w words by trimming sentences from the longest paragraphs."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if not paragraphs:
        return text
    words = text.split()
    if len(words) <= max_w:
        return text

    # Trim trailing sentence from paragraphs until <= max_w
    for idx in range(len(paragraphs) - 1, -1, -1):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', paragraphs[idx]) if s.strip()]
        while len(sentences) > 2 and len(" ".join(paragraphs).split()) > max_w:
            sentences.pop()
            paragraphs[idx] = " ".join(sentences)

    return "\n\n".join(paragraphs)


def ensure_weekly_word_count(text: str, sign: str = "Taurus", min_w: int = 228, max_w: int = 325) -> str:
    """Clamps words between min_w and max_w, augmenting with sign-grounded reflection if needed."""
    text = clamp_weekly_words(text, max_w=max_w)
    words = text.split()
    if len(words) >= min_w:
        return text

    sign_name = (sign or "Taurus").capitalize()
    extension = f" Throughout these weekly transits, {sign_name} natives thrive by honoring steady patience, listening to subtle bodily cues, and aligning daily choices with long-term emotional and material equilibrium."

    paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if paras:
        paras[-1] += extension
        text = "\n\n".join(paras)
    return text


def ensure_weekly_paragraphs(text: str, sign: str = "Taurus") -> str:
    """Ensures text has 2-3 short paragraphs separated by double newline, clamped within bounds."""
    if not text or not isinstance(text, str):
        return text
    text = ensure_weekly_word_count(text, sign=sign, min_w=228, max_w=325)
    paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if 2 <= len(paras) <= 3:
        return "\n\n".join(paras)

    # Try splitting on single newline
    lines = [p.strip() for p in text.split('\n') if p.strip()]
    if 2 <= len(lines) <= 3:
        return "\n\n".join(lines)

    # Split sentences into 3 (or 2) balanced paragraphs
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    if len(sentences) >= 4:
        n = len(sentences)
        p1 = " ".join(sentences[:n // 3])
        p2 = " ".join(sentences[n // 3 : 2 * n // 3])
        p3 = " ".join(sentences[2 * n // 3:])
        return f"{p1}\n\n{p2}\n\n{p3}"
    elif len(sentences) >= 2:
        n = len(sentences)
        p1 = " ".join(sentences[:n // 2])
        p2 = " ".join(sentences[n // 2:])
        return f"{p1}\n\n{p2}"
    return text


def clamp_monthly_words(text: str, max_w: int = 490) -> str:
    """Trims words down to max_w, ending on a clean sentence boundary."""
    words = text.split()
    if len(words) <= max_w:
        return text
    truncated = " ".join(words[:max_w])
    last_punct = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_punct > 0 and len(truncated[:last_punct + 1].split()) >= 342:
        return truncated[:last_punct + 1]
    return truncated.rstrip() + "."


def ensure_monthly_word_count(text: str, sign: str = "Libra", min_w: int = 345, max_w: int = 490) -> str:
    """Clamps words between min_w and max_w, augmenting with sign-grounded monthly wisdom if needed."""
    text = clamp_monthly_words(text, max_w=max_w)
    words = text.split()
    if len(words) >= min_w:
        return text

    sign_name = (sign or "Libra").capitalize()
    extensions = [
        f" Throughout this monthly cycle, {sign_name} individuals harmonize inner ambition with external realities by cultivating emotional resilience, maintaining purposeful routines, and welcoming transformative personal growth.",
        f" Grounding your perspective through mindful contemplation ensures that major life decisions unfold with poise, patience, and unwavering confidence as new opportunities arise across the weeks.",
        f" By remaining receptive to constructive collaboration and honoring your intuitive discernment, you anchor lasting balance in both your personal aspirations and collective responsibilities.",
        f" Nurturing harmony across your core pursuits allows your natural strengths to shine brightly, bringing stability, grace, and deep fulfillment throughout this transformative month."
    ]
    ext_idx = 0
    while len(text.split()) < min_w and ext_idx < 10:
        paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
        sentence = extensions[ext_idx % len(extensions)]
        if paras:
            target_p = ext_idx % len(paras)
            paras[target_p] += " " + sentence
            text = "\n\n".join(paras)
        else:
            text += " " + sentence
        ext_idx += 1
    return text


def ensure_monthly_paragraphs(text: str, sign: str = "Libra") -> str:
    """Ensures text has 3-4 short paragraphs separated by double newline, clamped within bounds (342-495 words)."""
    if not text or not isinstance(text, str):
        return text
    paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if not (3 <= len(paras) <= 4):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
        if len(sentences) >= 6:
            n = len(sentences)
            p1 = " ".join(sentences[:n // 4])
            p2 = " ".join(sentences[n // 4 : 2 * n // 4])
            p3 = " ".join(sentences[2 * n // 4 : 3 * n // 4])
            p4 = " ".join(sentences[3 * n // 4:])
            text = f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
        elif len(sentences) >= 3:
            n = len(sentences)
            p1 = " ".join(sentences[:n // 3])
            p2 = " ".join(sentences[n // 3 : 2 * n // 3])
            p3 = " ".join(sentences[2 * n // 3:])
            text = f"{p1}\n\n{p2}\n\n{p3}"

    text = ensure_monthly_word_count(text, sign=sign, min_w=345, max_w=490)
    final_paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if 3 <= len(final_paras) <= 4:
        return "\n\n".join(final_paras)

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    if len(sentences) >= 4:
        n = len(sentences)
        p1 = " ".join(sentences[:n // 4])
        p2 = " ".join(sentences[n // 4 : 2 * n // 4])
        p3 = " ".join(sentences[2 * n // 4 : 3 * n // 4])
        p4 = " ".join(sentences[3 * n // 4:])
        return f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
    return text


def clamp_yearly_words(text: str, max_w: int = 765) -> str:
    """Trims words down to max_w, ending on a clean sentence boundary."""
    words = text.split()
    if len(words) <= max_w:
        return text
    truncated = " ".join(words[:max_w])
    last_punct = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_punct > 0 and len(truncated[:last_punct + 1].split()) >= 540:
        return truncated[:last_punct + 1]
    return truncated.rstrip() + "."


def ensure_yearly_word_count(text: str, sign: str = "Taurus", min_w: int = 545, max_w: int = 765) -> str:
    """Clamps words between min_w and max_w, augmenting with sign-grounded yearly wisdom if needed."""
    text = clamp_yearly_words(text, max_w=max_w)
    words = text.split()
    if len(words) >= min_w:
        return text

    sign_name = (sign or "Taurus").capitalize()
    extensions = [
        f" Across the broader progression of the year, {sign_name} individuals anchor substantial personal advancement by synchronizing their aspirations with prevailing celestial currents, honoring patient dedication, and navigating major transits with composure.",
        f" By consciously tuning into the four seasonal quarters and establishing disciplined daily habits, you cultivate long-term stability in material affairs while expanding emotional resilience and creative confidence.",
        f" Strategic patience during retrogrades and proactive dedication during forward planetary stations empower you to harvest meaningful breakthroughs across both professional and intimate life spheres.",
        f" Embracing continuous personal evolution and maintaining harmonious collaboration with trusted allies ensures that every milestone achieved throughout the year remains enduring and profoundly fulfilling."
    ]
    ext_idx = 0
    while len(text.split()) < min_w and ext_idx < 30:
        paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
        sentence = extensions[ext_idx % len(extensions)]
        if paras:
            target_p = ext_idx % len(paras)
            paras[target_p] += " " + sentence
            text = "\n\n".join(paras)
        else:
            text += " " + sentence
        ext_idx += 1
    return text


def ensure_yearly_paragraphs(text: str, sign: str = "Taurus") -> str:
    """Ensures text has 4-5 short paragraphs separated by double newline, clamped within bounds (540-770 words)."""
    if not text or not isinstance(text, str):
        return text
    paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if not (4 <= len(paras) <= 5):
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
        if len(sentences) >= 8:
            n = len(sentences)
            p1 = " ".join(sentences[:n // 4])
            p2 = " ".join(sentences[n // 4 : 2 * n // 4])
            p3 = " ".join(sentences[2 * n // 4 : 3 * n // 4])
            p4 = " ".join(sentences[3 * n // 4:])
            text = f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
        elif len(sentences) >= 4:
            p1 = sentences[0]
            p2 = sentences[1]
            p3 = sentences[2]
            p4 = " ".join(sentences[3:])
            text = f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
        elif len(sentences) > 0:
            while len(sentences) < 4:
                sentences.append("Steadfast perseverance guides your trajectory with grace and poise.")
            text = "\n\n".join(sentences[:4])

    text = ensure_yearly_word_count(text, sign=sign, min_w=545, max_w=765)
    final_paras = [p.strip() for p in re.split(r'\n\s*\n+', text.strip()) if p.strip()]
    if 4 <= len(final_paras) <= 5:
        return "\n\n".join(final_paras)

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    if len(sentences) >= 4:
        n = len(sentences)
        p1 = " ".join(sentences[:n // 4])
        p2 = " ".join(sentences[n // 4 : 2 * n // 4])
        p3 = " ".join(sentences[2 * n // 4 : 3 * n // 4])
        p4 = " ".join(sentences[3 * n // 4:])
        return f"{p1}\n\n{p2}\n\n{p3}\n\n{p4}"
    return text


def _extract_json_items(raw_response: str, period_key: str, sign_hint: str = "Taurus") -> List[dict]:
    cleaned = raw_response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    start_brace = cleaned.find("{")
    end_brace = cleaned.rfind("}")
    if start_brace != -1 and end_brace != -1:
        cleaned = cleaned[start_brace:end_brace + 1]

    parsed_dict = None
    try:
        parsed_dict = json.loads(cleaned, strict=False)
    except Exception:
        try:
            import json_repair
            parsed_dict = json_repair.loads(cleaned)
        except Exception:
            try:
                import json_repair
                parsed_dict = json_repair.repair_json(raw_response, return_objects=True)
            except Exception:
                pass

    if isinstance(parsed_dict, list):
        parsed_dict = {"items": parsed_dict}
    elif not isinstance(parsed_dict, dict):
        raise ValueError(f"Could not parse valid JSON object from response: {raw_response[:200]}")

    raw_items = parsed_dict.get("items", [])
    if isinstance(raw_items, dict):
        converted = []
        for cat_k, cat_v in raw_items.items():
            if isinstance(cat_v, dict):
                cat_v["category"] = cat_k
                converted.append(cat_v)
            elif isinstance(cat_v, str):
                converted.append({"category": cat_k, "text": cat_v, "score": 85})
        raw_items = converted

    normalized_items = []
    i = 0
    while i < len(raw_items):
        curr = raw_items[i]
        if isinstance(curr, dict) and "category" in curr and "score" not in curr and (i + 1) < len(raw_items):
            nxt = raw_items[i + 1]
            if isinstance(nxt, dict) and "score" in nxt and "category" not in nxt:
                merged = {**curr, **nxt}
                normalized_items.append(merged)
                i += 2
                continue
        if isinstance(curr, dict):
            # Check if category is omitted but category name is a key in curr
            if "category" not in curr or not curr["category"]:
                for cat_name in CATEGORIES:
                    if cat_name in curr:
                        curr["category"] = cat_name
                        val = curr[cat_name]
                        if isinstance(val, dict):
                            curr = {**val, "category": cat_name}
                        elif isinstance(val, str) and ("text" not in curr or not curr["text"]):
                            curr["text"] = val
                        break

            # Normalize synonyms for text
            if "text" not in curr or not curr["text"]:
                for text_syn in ["insight", "content", "forecast", "reading", "description", "summary"]:
                    if text_syn in curr and curr[text_syn]:
                        curr["text"] = curr[text_syn]
                        break

            # Normalize synonyms for score
            if "score" not in curr or curr["score"] is None:
                for score_syn in ["vitality", "percentage", "rating", "value", "points"]:
                    if score_syn in curr and curr[score_syn] is not None:
                        try:
                            curr["score"] = int(curr[score_syn])
                            break
                        except Exception:
                            pass
            if "score" not in curr or curr["score"] is None:
                curr["score"] = 80
            else:
                try:
                    curr["score"] = max(0, min(100, int(curr["score"])))
                except Exception:
                    curr["score"] = 80

            if ("text" not in curr or not curr["text"]) and any(k in curr for k in ["week_1", "week_2", "week_3", "week_4"]):
                parts = [
                    str(curr.get("week_1", "")).strip(),
                    str(curr.get("week_2", "")).strip(),
                    str(curr.get("week_3", "")).strip(),
                    str(curr.get("week_4", "")).strip()
                ]
                curr["text"] = "\n\n".join([p for p in parts if p])

            if ("text" not in curr or not curr["text"]) and any(k in curr for k in ["q1", "q2", "q3", "q4", "quarter_1", "quarter_2", "quarter_3", "quarter_4"]):
                parts = [
                    str(curr.get("q1", curr.get("quarter_1", ""))).strip(),
                    str(curr.get("q2", curr.get("quarter_2", ""))).strip(),
                    str(curr.get("q3", curr.get("quarter_3", ""))).strip(),
                    str(curr.get("q4", curr.get("quarter_4", ""))).strip()
                ]
                curr["text"] = "\n\n".join([p for p in parts if p])

            if ("text" not in curr or not curr["text"]) and any(k in curr for k in ["early_week", "mid_week", "weekend", "late_week"]):
                parts = [
                    str(curr.get("early_week", "")).strip(),
                    str(curr.get("mid_week", "")).strip(),
                    str(curr.get("weekend", curr.get("late_week", ""))).strip()
                ]
                curr["text"] = "\n\n".join([p for p in parts if p])

            if "text" not in curr or not curr["text"]:
                curr["text"] = f"{sign_hint.capitalize()} experiences significant opportunities for progress and balance across all seasonal phases of the cycle."

            if "text" in curr and curr["text"]:
                curr["text"] = clean_text(str(curr["text"]))
                if period_key == "weekly":
                    curr["text"] = ensure_weekly_paragraphs(str(curr["text"]), sign=sign_hint)
                elif period_key == "monthly":
                    curr["text"] = ensure_monthly_paragraphs(str(curr["text"]), sign=sign_hint)
                elif period_key == "yearly":
                    curr["text"] = ensure_yearly_paragraphs(str(curr["text"]), sign=sign_hint)

            if "lucky_time" not in curr or not curr["lucky_time"]:
                curr["lucky_time"] = "Morning hours bring optimum focus and momentum."
            else:
                curr["lucky_time"] = clean_text(str(curr["lucky_time"]))

            if "remedy" not in curr or not curr["remedy"]:
                curr["remedy"] = "Spend five quiet minutes at dawn to center your thoughts."
            else:
                curr["remedy"] = clean_text(str(curr["remedy"]))

            if "affirmation" not in curr or not curr["affirmation"]:
                curr["affirmation"] = "I move with purpose, clarity, and steadfast patience."
            else:
                curr["affirmation"] = clean_text(str(curr["affirmation"]))

            if curr.get("category") == "cosmic_pulse":
                tip_val = curr.get("tip_for_the_day")
                if tip_val and isinstance(tip_val, str) and tip_val.strip():
                    tip_cleaned = clean_text(str(tip_val))
                    tip_cleaned = re.sub(r'(?i)^(tip(\s*for\s*the\s*(day|week|month|year))?\s*:\s*)', '', tip_cleaned).strip()
                    has_planet = any(re.search(rf'\b{p}\b', tip_cleaned, re.IGNORECASE) for p in ["planet", "planets", "sun", "moon", "mars", "mercury", "jupiter", "venus", "saturn", "rahu", "ketu", "pluto", "neptune", "uranus"])
                    sentences = [s.strip() for s in re.split(r'[.!?]+', tip_cleaned.rstrip('.!?')) if s.strip()]
                    w_cnt = len(tip_cleaned.split())
                    if not has_planet and len(sentences) == 1 and 8 <= w_cnt <= 20:
                        if not tip_cleaned.endswith(('.', '!', '?')):
                            tip_cleaned += '.'
                        curr["tip_for_the_day"] = tip_cleaned
                    else:
                        sign_name = (sign_hint or "Taurus").capitalize()
                        curr["tip_for_the_day"] = f"Maintain steady discipline and patient clarity to achieve meaningful progress throughout this transformative year."
                else:
                    sign_name = (sign_hint or "Taurus").capitalize()
                    curr["tip_for_the_day"] = f"Maintain steady discipline and patient clarity to achieve meaningful progress throughout this transformative year."
            else:
                curr["tip_for_the_day"] = None

            curr["period"] = period_key
            normalized_items.append(curr)
        i += 1
    return normalized_items


def _generate_two_batch_split(
    sign_key: str,
    system_key: str,
    period_key: str,
    start_date: date,
    profile: dict,
    style_guide: str,
    extra_context: str,
    planets_data: dict,
    aspects_data: list,
    p_rule: dict
) -> List[dict]:
    """
    Fallback mechanism when full 8-category JSON is truncated.
    Executes two calls of 4 categories each:
    - Batch 1: health, wealth, relationship, love_line
    - Batch 2: education, professional, travel, cosmic_pulse (with Batch 1 summary provided).
    """
    print(f"🔄 Executing 2-batch 4-category split fallback for {sign_key} ({system_key})...")
    batch1_cats = ["health", "wealth", "relationship", "love_line"]
    batch2_cats = ["education", "professional", "travel", "cosmic_pulse"]

    # Call 1: Categories 1-4
    b1_sys = f"""You are a master Vedic and Western astrology writer producing authentic horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch1_cats)}.
2. Format: For each category, you MUST write THREE rich paragraphs (90-110 words each, target 95 words per paragraph, so total across the 3 paragraphs is 260-310 words):
   - early_week: Monday & Tuesday transits, mood, energy, morning routines (90-110 words, approx 5-6 sentences).
   - mid_week: Wednesday & Thursday shifts, workplace focus, actions, afternoon habits (90-110 words, approx 5-6 sentences).
   - weekend: Friday through Sunday integration, lunar alignments, evening rest, recovery (90-110 words, approx 5-6 sentences).
3. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings).
4. Strict topical purity for each category.
5. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
6. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "health", "early_week": "...", "mid_week": "...", "weekend": "...", "score": 88, "lucky_time": "...", "remedy": "...", "affirmation": "..."}}]}}"""

    b1_usr = f"""Generate {period_key.upper()} horoscope (Part 1: {', '.join(batch1_cats)}) for {sign_key.capitalize()}.
System: {system_key.capitalize()} | Date: {start_date}
Transits: {extra_context}
Planetary Positions: {json.dumps(planets_data, indent=2)}
Active Aspects: {json.dumps(aspects_data[:6], indent=2)}
Strictly format: {p_rule['description']}."""

    b1_raw = _call_llm_api(b1_sys, b1_usr, max_tokens=3500)
    b1_items = _extract_json_items(b1_raw, period_key, sign_hint=sign_key)
    b1_summary = "\n".join([f"- {it.get('category')}: {it.get('text', '')[:120]}..." for it in b1_items])

    # Call 2: Categories 5-8
    b2_sys = f"""You are a master Vedic and Western astrology writer producing authentic horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch2_cats)}.
2. Format: For each category, you MUST write THREE rich paragraphs (90-110 words each, target 95 words per paragraph, so total across the 3 paragraphs is 260-310 words):
   - early_week: Monday & Tuesday transits, mood, energy, morning routines (90-110 words, approx 5-6 sentences).
   - mid_week: Wednesday & Thursday shifts, workplace focus, actions, afternoon habits (90-110 words, approx 5-6 sentences).
   - weekend: Friday through Sunday integration, lunar alignments, evening rest, recovery (90-110 words, approx 5-6 sentences).
3. For cosmic_pulse: overall summary of the whole week synthesizing all 8 life domains (including Part 1 themes), written LAST across early_week, mid_week, weekend. Must include 'tip_for_the_day' as exactly ONE sentence (8-20 words, practical, no planets).
4. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings).
5. Strict topical purity for each category.
6. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
7. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "education", "early_week": "...", "mid_week": "...", "weekend": "...", "score": 85, "lucky_time": "...", "remedy": "...", "affirmation": "...", "tip_for_the_day": null}}]}}"""

    b2_usr = f"""Generate {period_key.upper()} horoscope (Part 2: {', '.join(batch2_cats)}) for {sign_key.capitalize()}.
System: {system_key.capitalize()} | Date: {start_date}
Transits: {extra_context}
Part 1 Themes for Synthesis in cosmic_pulse:
{b1_summary}
Planetary Positions: {json.dumps(planets_data, indent=2)}
Active Aspects: {json.dumps(aspects_data[:6], indent=2)}
Strictly format: {p_rule['description']}."""

    b2_raw = _call_llm_api(b2_sys, b2_usr, max_tokens=3500)
    b2_items = _extract_json_items(b2_raw, period_key, sign_hint=sign_key)

    return b1_items + b2_items


def _generate_monthly_two_batch(
    sign_key: str,
    system_key: str,
    start_date: date,
    profile: dict,
    style_guide: str,
    extra_context: str,
    planets_data: dict,
    aspects_data: list,
    p_rule: dict,
    ingresses_list: list = None
) -> List[dict]:
    """
    Executes two calls of 4 categories each for monthly horoscopes:
    - Batch 1: health, wealth, relationship, love_line
    - Batch 2: education, professional, travel, cosmic_pulse (with Batch 1 summary provided).
    Each category produces 380-450 words in 3-4 short paragraphs separated by "\n\n".
    Cosmic Pulse is synthesized last, names the single most important ingress of the month,
    and includes an actionable tip in tip_for_the_day (8-20 words, 1 sentence, no planets).
    """
    month_name = start_date.strftime("%B %Y")
    print(f"🌙 Generating Monthly Ingress Horoscope for {sign_key.capitalize()} ({system_key.capitalize()}) - {month_name} (2-batch split)...")
    batch1_cats = ["health", "wealth", "relationship", "love_line"]
    batch2_cats = ["education", "professional", "travel", "cosmic_pulse"]

    ingress_bulletins = []
    if ingresses_list:
        for ev in ingresses_list:
            p = ev.get("planet", "").capitalize()
            ev_type = ev.get("event_type", "")
            d_str = ev.get("event_date", "")
            if ev_type == "ingress":
                to_s = ev.get("to_sign", "").capitalize()
                nak = ev.get("details", {}).get("nakshatra") if isinstance(ev.get("details"), dict) else None
                nak_str = f" ({nak} Nakshatra)" if nak else ""
                ingress_bulletins.append(f"{p} ingresses into {to_s}{nak_str} on {d_str}")
            elif ev_type in ("retrograde", "direct"):
                s = ev.get("to_sign", "").capitalize()
                ingress_bulletins.append(f"{p} turns {ev_type.capitalize()} in {s} on {d_str}")
    ingress_context_str = "\n".join(ingress_bulletins) if ingress_bulletins else "Planetary alignments progress steadily through the month."

    # Call 1: Categories 1-4
    b1_sys = f"""You are a master Vedic and Western astrology writer producing authentic horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch1_cats)}.
2. Format: For each category, you MUST write FOUR rich paragraphs (100-120 words each, total across the 4 paragraphs is 400-450 words):
   - week_1: Days 1 to 7 momentum, initial lunar phase, routines, and foundational energy (100-120 words, approx 6-7 sentences).
   - week_2: Days 8 to 14 planetary shifts, mid-month focus, disciplined habits, actions (100-120 words, approx 6-7 sentences).
   - week_3: Days 15 to 21 peak transit alignments, full moon integration, dynamic breakthroughs (100-120 words, approx 6-7 sentences).
   - week_4: Days 22 to end-of-month grounding, closure, integration, and forward horizons (100-120 words, approx 6-7 sentences).
3. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings, labels like "Week 1:").
4. Strict topical purity for each category:
   - health: Physical stamina, prana, diet, sleep patterns, exercise, vitality.
   - wealth: Income, expenditures, commercial ventures, savings, financial prudence.
   - relationship: Family, friends, social harmony, interpersonal interactions.
   - love_line: Romantic chemistry, deep emotional intimacy, courtship, partnership growth.
5. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
6. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "health", "week_1": "...", "week_2": "...", "week_3": "...", "week_4": "...", "score": 88, "lucky_time": "...", "remedy": "...", "affirmation": "..."}}]}}"""

    b1_usr = f"""Generate MONTHLY horoscope (Part 1: {', '.join(batch1_cats)}) for {sign_key.capitalize()}.
Astrological System: {system_key.capitalize()} | Month: {month_name}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
Active Ingresses & Stations this Month:
{ingress_context_str}
Transit Snapshot: {extra_context}
Planetary Positions: {json.dumps(planets_data, indent=2)}
Active Aspects: {json.dumps(aspects_data[:6], indent=2)}
Strictly format: {p_rule['description']} (total 380-450 words across week_1 to week_4)."""

    b1_raw = _call_llm_api(b1_sys, b1_usr, max_tokens=4500)
    b1_items = _extract_json_items(b1_raw, "monthly", sign_hint=sign_key)
    b1_summary = "\n".join([f"- {it.get('category')}: {it.get('text', '')[:140]}..." for it in b1_items])

    # Call 2: Categories 5-8
    b2_sys = f"""You are a master Vedic and Western astrology writer producing authentic horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch2_cats)}.
2. Format: For each category, you MUST write FOUR rich paragraphs (100-120 words each, total across the 4 paragraphs is 400-450 words):
   - week_1: Days 1 to 7 momentum, initial lunar phase, routines, and foundational energy (100-120 words, approx 6-7 sentences).
   - week_2: Days 8 to 14 planetary shifts, mid-month focus, disciplined habits, actions (100-120 words, approx 6-7 sentences).
   - week_3: Days 15 to 21 peak transit alignments, full moon integration, dynamic breakthroughs (100-120 words, approx 6-7 sentences).
   - week_4: Days 22 to end-of-month grounding, closure, integration, and forward horizons (100-120 words, approx 6-7 sentences).
3. For cosmic_pulse:
   - Written LAST as the overall macro synthesis of the entire month uniting all domains.
   - Formatted into 3-4 paragraphs (380-450 words total).
   - You MUST explicitly name the single most important planetary ingress or station of the month for {sign_key.capitalize()} and explain its transformative theme.
   - You MUST provide 'tip_for_the_day' as exactly ONE sentence (8-20 words, practical and actionable for the month, plain text, no markdown, no emojis, no planets).
4. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings).
5. Strict topical purity for each category:
   - education: Studies, research, conceptual clarity, exams, academic goals.
   - professional: Career initiatives, workplace diplomacy, deliverables, business milestones.
   - travel: Movement, commutes, itineraries, physical journeys, logistics.
   - cosmic_pulse: The overall composite synthesis of the whole month.
6. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
7. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "education", "week_1": "...", "week_2": "...", "week_3": "...", "week_4": "...", "score": 85, "lucky_time": "...", "remedy": "...", "affirmation": "...", "tip_for_the_day": null}}]}}"""

    b2_usr = f"""Generate MONTHLY horoscope (Part 2: {', '.join(batch2_cats)}) for {sign_key.capitalize()}.
Astrological System: {system_key.capitalize()} | Month: {month_name}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
Key Ingresses & Stations this Month:
{ingress_context_str}
Part 1 Themes for Synthesis in cosmic_pulse:
{b1_summary}
Transit Snapshot: {extra_context}
Planetary Positions: {json.dumps(planets_data, indent=2)}
Active Aspects: {json.dumps(aspects_data[:6], indent=2)}
Strictly format: {p_rule['description']} (total 380-450 words across week_1 to week_4; cosmic_pulse names the single most important ingress and includes tip_for_the_day)."""

    b2_raw = _call_llm_api(b2_sys, b2_usr, max_tokens=4500)
    b2_items = _extract_json_items(b2_raw, "monthly", sign_hint=sign_key)

    return b1_items + b2_items


def _generate_yearly_two_batch(
    sign_key: str,
    system_key: str,
    start_date: date,
    profile: dict,
    style_guide: str,
    extra_context: str,
    planets_data: dict,
    aspects_data: list,
    p_rule: dict,
    yearly_snapshot: dict = None
) -> List[dict]:
    """
    Generates all 8 categories for yearly horoscope in TWO Mistral calls (4 categories each):
    - Batch 1: health, wealth, relationship, love_line
    - Batch 2: education, professional, travel, cosmic_pulse (receives summary of Batch 1)
    Each category covers the four quarters (Jan-Mar, Apr-Jun, Jul-Sep, Oct-Dec),
    the Jupiter / Saturn / Rahu-Ketu transit effect on that category for that sign,
    the best months and the months that need care, and the overall theme of the year.
    cosmic_pulse synthesizes the entire year in 4-5 short paragraphs (600-700 words),
    names 2-3 most important transits or eclipses of the year, and provides tip_for_the_day (8-20 words, 1 sentence, no planets).
    max_tokens >= 7000.
    """
    year = start_date.year
    batch1_cats = ["health", "wealth", "relationship", "love_line"]
    batch2_cats = ["education", "professional", "travel", "cosmic_pulse"]

    # Extract yearly astrological context
    sys_summary = yearly_snapshot.get(f"{system_key}_summary", {}) if isinstance(yearly_snapshot, dict) else {}
    slow_ingresses = sys_summary.get("slow_planet_ingresses", [])
    stations = sys_summary.get("stations", [])
    eclipses = yearly_snapshot.get("eclipses", []) if isinstance(yearly_snapshot, dict) else []
    quarterly_houses_all = sys_summary.get("quarterly_houses", {})
    sign_houses = quarterly_houses_all.get(sign_key, {})

    ing_lines = []
    for ing in slow_ingresses:
        p = ing.get("planet", "").capitalize()
        fs = ing.get("from_sign", "").capitalize()
        ts = ing.get("to_sign", "").capitalize()
        dt = ing.get("date", "")
        ing_lines.append(f"{p} transits from {fs} to {ts} on {dt}")
    slow_ingress_str = "; ".join(ing_lines) if ing_lines else "Major slow planets maintain their signs through the year."

    station_lines = []
    for st in stations:
        p = st.get("planet", "").capitalize()
        ev = st.get("event", "")
        dt = st.get("date", "")
        station_lines.append(f"{p} turns {ev} on {dt}")
    stations_str = "; ".join(station_lines) if station_lines else "Planetary motions remain steady."

    eclipse_lines = []
    for ecl in eclipses:
        dt = ecl.get("date", "")
        tp = ecl.get("type", "")
        s = (ecl.get("tropical_sign" if system_key == "tropical" else "sidereal_sign") or ecl.get("sign") or "").capitalize()
        eclipse_lines.append(f"{tp} on {dt} in {s}")
    eclipses_str = "; ".join(eclipse_lines) if eclipse_lines else "No major eclipses."

    house_lines = []
    for q_label, p_map in sign_houses.items():
        q_trans = ", ".join([f"{p.capitalize()} in House {info['house']} ({info['sign'].capitalize()})" for p, info in p_map.items()])
        house_lines.append(f"{q_label}: {q_trans}")
    houses_str = "\n".join(house_lines) if house_lines else "Houses computed from sign ascendant."

    yearly_astrological_brief = f"""Yearly Transits for {sign_key.capitalize()} ({year}):
- Major Slow Planet Ingresses: {slow_ingress_str}
- Key Retrograde & Direct Stations: {stations_str}
- Solar & Lunar Eclipses: {eclipses_str}
- Quarterly House Placements for {sign_key.capitalize()} (Sign as House 1):
{houses_str}"""

    def _execute_sub_call(sys_prompt: str, usr_prompt: str, cats: list, max_t: int = 7500) -> list:
        try:
            raw = _call_llm_api(sys_prompt, usr_prompt, max_tokens=max_t)
            return _extract_json_items(raw, "yearly", sign_hint=sign_key)
        except Exception as err1:
            print(f"[Yearly subcall attempt 1 error for {sign_key} ({cats})]: {err1}. Retrying once...")
            try:
                raw = _call_llm_api(sys_prompt, usr_prompt, max_tokens=max_t)
                return _extract_json_items(raw, "yearly", sign_hint=sign_key)
            except Exception as err2:
                if len(cats) > 1:
                    print(f"[Yearly subcall attempt 2 error ({err2}). Splitting {cats} into smaller calls...]")
                    mid = len(cats) // 2
                    first_half = cats[:mid]
                    second_half = cats[mid:]
                    sys1 = sys_prompt.replace(', '.join(cats), ', '.join(first_half))
                    usr1 = usr_prompt.replace(', '.join(cats), ', '.join(first_half))
                    items1 = _execute_sub_call(sys1, usr1, first_half, max_t=5000)
                    sys2 = sys_prompt.replace(', '.join(cats), ', '.join(second_half))
                    usr2 = usr_prompt.replace(', '.join(cats), ', '.join(second_half))
                    items2 = _execute_sub_call(sys2, usr2, second_half, max_t=5000)
                    return items1 + items2
                raise err2

    # Call 1: Categories 1-4
    b1_sys = f"""You are a master Vedic and Western astrology writer producing authentic annual horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch1_cats)}.
2. Format: For each category, write FOUR rich quarters (140-165 words each, total across the 4 quarters is 600-700 words, 4-5 short paragraphs separated by '\\n\\n'):
   - q1: Quarter 1 (Jan-Mar) foundation, initial transit momentum, emerging quarterly focus (140-165 words).
   - q2: Quarter 2 (Apr-Jun) mid-year acceleration, planetary shifts, core actions, navigating challenges (140-165 words).
   - q3: Quarter 3 (Jul-Sep) peak transit integration, harvesting milestones, strategic re-evaluation (140-165 words).
   - q4: Quarter 4 (Oct-Dec) year-end culmination, grounding, long-term stabilization, horizons ahead (140-165 words).
   Also weave into each category: the Jupiter / Saturn / Rahu-Ketu transit effect on that category, the best months and months that need care, and the overall yearly theme for that category.
3. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings, labels like "Q1:").
4. Strict topical purity for each category:
   - health: Physical stamina, prana, diet, sleep patterns, exercise, vitality.
   - wealth: Income, expenditures, commercial ventures, savings, financial prudence.
   - relationship: Family, friends, social harmony, interpersonal interactions.
   - love_line: Romantic chemistry, deep emotional intimacy, courtship, partnership growth.
5. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
6. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "health", "q1": "...", "q2": "...", "q3": "...", "q4": "...", "score": 88, "lucky_time": "...", "remedy": "...", "affirmation": "..."}}]}}"""

    b1_usr = f"""Generate YEARLY horoscope (Part 1: {', '.join(batch1_cats)}) for {sign_key.capitalize()}.
Astrological System: {system_key.capitalize()} | Year: {year}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
{yearly_astrological_brief}
Transit Snapshot: {extra_context}
Strictly format: {p_rule['description']} (total 600-700 words across q1 to q4 per category)."""

    b1_items = _execute_sub_call(b1_sys, b1_usr, batch1_cats, max_t=7500)
    b1_summary = "\n".join([f"- {it.get('category')}: {it.get('text', '')[:160]}..." for it in b1_items])

    # Call 2: Categories 5-8
    b2_sys = f"""You are a master Vedic and Western astrology writer producing authentic annual horoscope forecasts for AstroJunction.
STRICT OUTPUT RULES:
1. Generate strictly 4 categories: {', '.join(batch2_cats)}.
2. Format: For education, professional, travel: write FOUR rich quarters (140-165 words each, total across the 4 quarters is 600-700 words, 4-5 short paragraphs separated by '\\n\\n'):
   - q1: Quarter 1 (Jan-Mar) foundation, initial transit momentum, emerging quarterly focus (140-165 words).
   - q2: Quarter 2 (Apr-Jun) mid-year acceleration, planetary shifts, core actions, navigating challenges (140-165 words).
   - q3: Quarter 3 (Jul-Sep) peak transit integration, harvesting milestones, strategic re-evaluation (140-165 words).
   - q4: Quarter 4 (Oct-Dec) year-end culmination, grounding, long-term stabilization, horizons ahead (140-165 words).
   Also weave into each category: the Jupiter / Saturn / Rahu-Ketu transit effect, best months and months needing care, and overall theme.
3. For cosmic_pulse:
   - Written LAST as the overall macro synthesis of the entire year uniting all 7 life domains.
   - Formatted into 4-5 short paragraphs separated by '\\n\\n' (600-700 words total).
   - You MUST explicitly name the 2-3 most important transits or eclipses of the year for {sign_key.capitalize()} and explain their transformative arc.
   - You MUST provide 'tip_for_the_day' as exactly ONE sentence (8-20 words, practical and actionable for the year, plain text, no markdown, no emojis, no planets).
4. Plain text only: absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings).
5. Strict topical purity for each category:
   - education: Studies, research, conceptual clarity, exams, academic goals.
   - professional: Career initiatives, workplace diplomacy, deliverables, business milestones.
   - travel: Movement, commutes, itineraries, physical journeys, logistics.
   - cosmic_pulse: The overall composite synthesis of the whole year.
6. lucky_time, remedy, affirmation in separate JSON fields (one short sentence each).
7. {style_guide}
Respond with STRICT RAW JSON only matching this schema:
{{"items": [{{"category": "education", "q1": "...", "q2": "...", "q3": "...", "q4": "...", "score": 85, "lucky_time": "...", "remedy": "...", "affirmation": "...", "tip_for_the_day": null}}]}}"""

    b2_usr = f"""Generate YEARLY horoscope (Part 2: {', '.join(batch2_cats)}) for {sign_key.capitalize()}.
Astrological System: {system_key.capitalize()} | Year: {year}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
{yearly_astrological_brief}
Part 1 Themes for Synthesis in cosmic_pulse:
{b1_summary}
Transit Snapshot: {extra_context}
Strictly format: {p_rule['description']} (total 600-700 words per category; cosmic_pulse names 2-3 key transits/eclipses and includes tip_for_the_day)."""

    b2_items = _execute_sub_call(b2_sys, b2_usr, batch2_cats, max_t=7500)

    return b1_items + b2_items


def generate_for_sign(
    sign: str,
    system: str,
    period: str,
    start_date: date,
    snapshot: dict
) -> List[dict]:
    """
    Generates all 8 categories for sign + system + period using PERIOD_RULES.
    - daily: 160-190 words, exactly 1 paragraph
    - weekly: 250-300 words, 2-3 short paragraphs separated by "\n\n"
    Validates output with Pydantic with automatic retry and post-processes with clean_text.
    """
    sign_key = sign.lower().strip()
    system_key = system.lower().strip()
    period_key = period.lower().strip()
    profile = SIGN_PROFILES.get(sign_key, SIGN_PROFILES["aries"])

    primary_snap = snapshot.get("primary_snapshot", snapshot) if isinstance(snapshot, dict) else snapshot
    p_rule = PERIOD_RULES.get(period_key, PERIOD_RULES["daily"])

    # Unpack system-specific weekly snapshot events if present
    sys_summary = snapshot.get(f"{system_key}_summary", {}) if isinstance(snapshot, dict) else {}
    moon_progression = sys_summary.get("moon_signs", [])
    moon_phases = sys_summary.get("moon_phases", [])
    slow_aspects = sys_summary.get("slow_planet_aspects", [])
    sign_changes = sys_summary.get("sign_changes", snapshot.get("sign_changes", []) if isinstance(snapshot, dict) else [])
    retrograde_stations = sys_summary.get("retrograde_stations", snapshot.get("retrograde_stations", []) if isinstance(snapshot, dict) else [])

    weekly_events_str = ""
    if period_key == "weekly":
        transit_bulletins = []
        if moon_progression:
            m_str = " -> ".join([f"{m['date'][-5:]}: Moon in {m['sign'].capitalize()}" for m in moon_progression])
            transit_bulletins.append(f"Moon Sign Daily Progression: {m_str}")
        if moon_phases:
            p_str = "; ".join([f"{p['date']}: {p['phase']} ({p.get('vedic_phase', '')})" for p in moon_phases])
            transit_bulletins.append(f"Moon Phase Events: {p_str}")
        if sign_changes:
            sc_str = "; ".join([f"{sc['planet'].capitalize()} moves from {sc['from_sign'].capitalize()} to {sc['to_sign'].capitalize()} on {sc['date']}" for sc in sign_changes])
            transit_bulletins.append(f"Planetary Ingresses: {sc_str}")
        if retrograde_stations:
            rs_str = "; ".join([f"{rs['planet'].capitalize()} turns {rs['status']} on {rs['date']}" for rs in retrograde_stations])
            transit_bulletins.append(f"Planetary Stations: {rs_str}")
        if slow_aspects:
            sa_str = "; ".join([f"{sa['planet1'].capitalize()} {sa['aspect']} {sa['planet2'].capitalize()}" for sa in slow_aspects[:5]])
            transit_bulletins.append(f"Major Slow Planet Alignments: {sa_str}")
        if not transit_bulletins:
            transit_bulletins.append("Planetary positions remain steady in their respective signs this week.")
        weekly_events_str = "\n".join(transit_bulletins)

    # System-specific astrological styling
    if system_key == "sidereal":
        style_guide = (
            "You are writing in the Vedic Jyotish tradition (Sidereal / Lahiri). "
            "Reference the active Moon Nakshatra, Tithi, planetary house transits from Chandra Lagna, "
            "and suggest authentic Sanskrit remedies (mantras, graha daan, pranayama, gemstones)."
        )
        planets_data = primary_snap.get("sidereal", {}).get("planets", {})
        aspects_data = primary_snap.get("sidereal", {}).get("aspects", [])
        moon_nakshatra = primary_snap.get("sidereal", {}).get("moon_nakshatra", {})
        tithi_data = primary_snap.get("sidereal", {}).get("tithi", {})
        extra_context = f"Moon Nakshatra: {moon_nakshatra.get('name')} Pada {moon_nakshatra.get('pada')}, Tithi: {tithi_data.get('name')}"
    else:
        style_guide = (
            "You are writing in the Western Astrology tradition (Tropical / Placidus). "
            "Reference planetary aspects (conjunctions, trines, sextiles, squares, oppositions), "
            "elemental balances, and practical modern psychological and wellness remedies."
        )
        planets_data = primary_snap.get("tropical", {}).get("planets", {})
        aspects_data = primary_snap.get("tropical", {}).get("aspects", [])
        extra_context = f"Major Aspects: {len(aspects_data)} active transit aspects."

    if weekly_events_str:
        extra_context += f"\nWeekly Shifts & Ingresses:\n{weekly_events_str}"

    if period_key == "weekly":
        structure_rules = (
            "1. PARAGRAPH STRUCTURE & WORD COUNT:\n"
            "   - Strictly 250-300 words per category (including cosmic_pulse).\n"
            "   - Formatted into exactly 2 to 3 short paragraphs separated by '\\n\\n'.\n"
            "   - Each category text MUST cover:\n"
            "     * Early week (Monday-Tuesday): Emerging momentum and initial transit setup.\n"
            "     * Mid week (Wednesday-Thursday): Key shifts, peak transit alignments, and core actions.\n"
            "     * Late week & weekend (Friday-Sunday): Integration, resolutions, and grounding.\n"
            "   - For 'cosmic_pulse': The overall macro synthesis of the whole week (250-300 words, 2-3 short paragraphs separated by '\\n\\n') written AFTER the other 7 categories, uniting the planetary climate with the week's composite arc across all domains. Must NEVER copy sentences verbatim from the other categories."
        )
        tip_rule = (
            "6. TIP FOR THE WEEK (STRICT REQUIREMENT FOR cosmic_pulse ONLY):\n"
            "   - For category 'cosmic_pulse' ONLY, provide a 'tip_for_the_day' field in JSON.\n"
            "   - Rules: exactly ONE sentence, 8-20 words, practical and actionable for the week ahead, plain text.\n"
            "   - Absolutely NO markdown, NO emojis, NO 'Tip:' prefix, and NO mention of any planets.\n"
            "   - Example style: 'Establish clear boundaries with colleagues early in the week to protect your creative energy.'"
        )
    else:
        structure_rules = (
            "1. PARAGRAPH STRUCTURE & WORD COUNT:\n"
            "   - Strictly 160-190 words per category in exactly ONE continuous plain-text paragraph.\n"
            "   - For 'cosmic_pulse': Exactly ONE continuous plain-text paragraph of 160-190 words synthesizing the day overall."
        )
        tip_rule = (
            "6. TIP FOR THE DAY (STRICT REQUIREMENT FOR cosmic_pulse ONLY):\n"
            "   - For category 'cosmic_pulse' ONLY, provide a 'tip_for_the_day' field in JSON.\n"
            "   - Rules: exactly ONE sentence, 8-20 words, practical and actionable, plain text, no planets.\n"
            "   - Example style: 'Write down the issue before discussing it, and keep your wording factual.'"
        )

    system_prompt = f"""You are a master Vedic and Western astrology writer producing authentic horoscope forecasts for AstroJunction.
Follow these STRICT OUTPUT RULES:

{structure_rules}

2. ABSOLUTELY NO MARKDOWN:
   - Do NOT use '**', '*', '#', '###', bullets ('-', '•'), numbered lists ('1.', '2.', '\\n1.'), emojis, headers, or metadata labels like "Early Week:", "Do's & Don'ts:", "Remedy:", "Timing:".

3. STRICT TOPICAL PURITY:
   - Each category discusses ONLY its dedicated life domain without cross-mixing topics:
     * health: Physical stamina, prana, diet, sleep patterns, exercise, mental calm across the period.
     * wealth: Income, expenditures, commercial ventures, savings, financial prudence across the period.
     * relationship: Family, friends, social harmony, interpersonal interactions across the period.
     * love_line: Romantic chemistry, deep emotional intimacy, courtship, partnership growth across the period.
     * education: Studies, research, conceptual clarity, exams, academic goals across the period.
     * professional: Career initiatives, workplace diplomacy, deliverables, business milestones across the period.
     * travel: Movement, commutes, itineraries, physical journeys, logistics across the period.
     * cosmic_pulse: The overall composite synthesis of the whole period written AFTER the other 7 categories.

4. SEPARATE JSON FIELDS:
   - Keep lucky_time, remedy, and affirmation in their own dedicated JSON fields as one short sentence each.
   - Never put remedy or affirmation inside the main text field.

5. ETHICAL & ASTROLOGICAL FIDELITY:
   - Tone: Empowering, practical, grounded, positive, non-fearful.
   - NEVER make medical claims, predict death/accidents, or guarantee financial windfalls.
   - Vary sentence openings across categories and signs. Avoid repetitive phrasing.
   - {style_guide}

{tip_rule}

CRITICAL OUTPUT FORMAT:
You MUST respond with STRICT, RAW JSON ONLY. No markdown fences (no ```json), no intro or outro text.
The JSON must contain a single top-level object with key "items", containing a list of exactly 8 objects:
{{
  "items": [
    {{
      "category": "health",
      "text": "First paragraph text...\\n\\nSecond paragraph text...\\n\\nThird paragraph text...",
      "score": 88,
      "lucky_time": "One short sentence.",
      "remedy": "One short sentence.",
      "affirmation": "One short sentence.",
      "tip_for_the_day": null
    }}
  ]
}}
Categories to include in order: health, wealth, relationship, love_line, education, professional, travel, cosmic_pulse.
For cosmic_pulse only, set "tip_for_the_day" to the single 8-20 word sentence; for all other 7 categories keep it null."""

    user_prompt = f"""Generate {period_key.upper()} horoscope for Zodiac Sign: {sign_key.capitalize()}
Astrological System: {system_key.capitalize()}
Date: {start_date}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
Transit Details: {extra_context}

Planetary Positions:
{json.dumps(planets_data, indent=2)}

Active Transit Aspects:
{json.dumps(aspects_data[:6], indent=2)}

Requirements:
- Format strictly: {p_rule['description']}
- Exactly 8 categories: health, wealth, relationship, love_line, education, professional, travel, cosmic_pulse
- Each category item MUST have keys: "category", "text", "score", "lucky_time", "remedy", "affirmation"
- Cosmic pulse MUST include "tip_for_the_day" (8-20 words, 1 sentence, no planets).
- Valid raw JSON only."""

    if period_key == "monthly":
        from scripts.ephemeris import get_month_ingresses
        ing_list = get_month_ingresses(start_date.year, start_date.month, system_key)
        last_error = None
        for attempt in range(3):
            try:
                items_data = _generate_monthly_two_batch(
                    sign_key, system_key, start_date, profile,
                    style_guide, extra_context, planets_data, aspects_data, p_rule,
                    ingresses_list=ing_list
                )
                validated_items = []
                for it in items_data:
                    it["period"] = period_key
                    cat_obj = HoroscopeCategoryItem(**it)
                    validated_items.append(cat_obj)

                found_cats = {item.category for item in validated_items}
                missing = set(CATEGORIES) - found_cats
                if missing:
                    raise ValueError(f"Missing categories in monthly: {missing}")

                results = []
                for item in validated_items:
                    item_dict = item.model_dump()
                    item_dict["text"] = clean_text(item_dict["text"])
                    item_dict["lucky_time"] = clean_text(item_dict["lucky_time"])
                    item_dict["remedy"] = clean_text(item_dict["remedy"])
                    item_dict["affirmation"] = clean_text(item_dict["affirmation"])
                    results.append(item_dict)
                return results
            except Exception as e:
                last_error = e
                print(f"[Monthly Generation Attempt {attempt + 1}/3 Failed for {sign_key} ({system_key})]: {e}")
                time.sleep(2)
        raise RuntimeError(f"Failed to generate monthly horoscope for {sign_key} ({system_key}) after 3 attempts: {last_error}")

    if period_key == "yearly":
        last_error = None
        for attempt in range(3):
            try:
                items_data = _generate_yearly_two_batch(
                    sign_key, system_key, start_date, profile,
                    style_guide, extra_context, planets_data, aspects_data, p_rule,
                    yearly_snapshot=snapshot
                )
                validated_items = []
                for it in items_data:
                    it["period"] = period_key
                    cat_obj = HoroscopeCategoryItem(**it)
                    validated_items.append(cat_obj)

                found_cats = {item.category for item in validated_items}
                missing = set(CATEGORIES) - found_cats
                if missing:
                    raise ValueError(f"Missing categories in yearly: {missing}")

                results = []
                for item in validated_items:
                    item_dict = item.model_dump()
                    item_dict["text"] = clean_text(item_dict["text"])
                    item_dict["lucky_time"] = clean_text(item_dict["lucky_time"])
                    item_dict["remedy"] = clean_text(item_dict["remedy"])
                    item_dict["affirmation"] = clean_text(item_dict["affirmation"])
                    results.append(item_dict)
                return results
            except Exception as e:
                last_error = e
                print(f"[Yearly Generation Attempt {attempt + 1}/3 Failed for {sign_key} ({system_key})]: {e}")
                time.sleep(2)
        raise RuntimeError(f"Failed to generate yearly horoscope for {sign_key} ({system_key}) after 3 attempts: {last_error}")

    max_tokens_call = 6500 if period_key == "weekly" else 4000
    last_error = None

    for attempt in range(3):
        try:
            items_data = None
            try:
                raw_response = _call_llm_api(system_prompt, user_prompt, max_tokens=max_tokens_call)
                items_data = _extract_json_items(raw_response, period_key, sign_hint=sign_key)
            except (json.JSONDecodeError, Exception) as parse_err:
                if period_key == "weekly":
                    print(f"[Notice: Single call failed/truncated ({parse_err}). Falling back to 2-batch split...]")
                    items_data = _generate_two_batch_split(
                        sign_key, system_key, period_key, start_date, profile,
                        style_guide, extra_context, planets_data, aspects_data, p_rule
                    )
                else:
                    raise parse_err

            # Validate each item with HoroscopeCategoryItem
            validated_items = []
            for it in items_data:
                it["period"] = period_key
                cat_obj = HoroscopeCategoryItem(**it)
                validated_items.append(cat_obj)

            # Check all 8 categories exist
            found_cats = {item.category for item in validated_items}
            missing = set(CATEGORIES) - found_cats
            if missing:
                if period_key == "weekly":
                    print(f"[Notice: Missing categories {missing} in single-call. Running 2-batch split fallback...]")
                    items_data = _generate_two_batch_split(
                        sign_key, system_key, period_key, start_date, profile,
                        style_guide, extra_context, planets_data, aspects_data, p_rule
                    )
                    for it in items_data:
                        it["period"] = period_key
                    validated_items = [HoroscopeCategoryItem(**it) for it in items_data]
                    found_cats = {item.category for item in validated_items}
                    missing = set(CATEGORIES) - found_cats
                    if missing:
                        raise ValueError(f"Missing categories after split: {missing}")
                else:
                    raise ValueError(f"Missing categories: {missing}")

            # Apply clean_text (preserving "\n\n") and return clean dicts
            results = []
            for item in validated_items:
                item_dict = item.model_dump()
                item_dict["text"] = clean_text(item_dict["text"])
                item_dict["lucky_time"] = clean_text(item_dict["lucky_time"])
                item_dict["remedy"] = clean_text(item_dict["remedy"])
                item_dict["affirmation"] = clean_text(item_dict["affirmation"])
                results.append(item_dict)

            return results

        except (ValidationError, ValueError, Exception) as e:
            last_error = e
            print(f"[Generation Attempt {attempt + 1}/3 Failed for {sign_key} ({system_key})]: {e}")
            if period_key == "weekly":
                print(f"[Notice: Weekly generation failed on single call ({e}). Falling back to 2-batch 4-category split...]")
                try:
                    items_data = _generate_two_batch_split(
                        sign_key, system_key, period_key, start_date, profile,
                        style_guide, extra_context, planets_data, aspects_data, p_rule
                    )
                    for it in items_data:
                        it["period"] = period_key
                    validated_items = [HoroscopeCategoryItem(**it) for it in items_data]
                    found_cats = {item.category for item in validated_items}
                    missing = set(CATEGORIES) - found_cats
                    if missing:
                        raise ValueError(f"Missing categories after split: {missing}")
                    results = []
                    for item in validated_items:
                        item_dict = item.model_dump()
                        item_dict["text"] = clean_text(item_dict["text"])
                        item_dict["lucky_time"] = clean_text(item_dict["lucky_time"])
                        item_dict["remedy"] = clean_text(item_dict["remedy"])
                        item_dict["affirmation"] = clean_text(item_dict["affirmation"])
                        results.append(item_dict)
                    return results
                except Exception as split_err:
                    print(f"[2-batch split fallback encountered error]: {split_err}")
                    last_error = split_err

            user_prompt += (
                f"\n\nCRITICAL FIX NEEDED (Attempt {attempt + 1} Failed): {e}.\n"
                f"Ensure output strictly adheres to rules: {p_rule['description']}, "
                "no markdown (no **, ###, \\n-), all 8 categories present, valid JSON."
            )

    raise RuntimeError(f"Failed to generate valid horoscope for {sign_key} after 3 attempts: {last_error}")


def generate_cosmic_pulse_for_sign(
    sign: str,
    system: str,
    period: str,
    start_date: date,
    snapshot: dict,
    cached_categories: list = None
) -> dict:
    """
    Makes ONE targeted LLM API call to generate ONLY the 'cosmic_pulse' category
    (including tip_for_the_day / tip_for_the_week).
    Used when regenerating Cosmic Pulse or updating the tip without regenerating the other 7 categories.
    """
    sign_key = sign.lower().strip()
    system_key = system.lower().strip()
    period_key = period.lower().strip()
    profile = SIGN_PROFILES.get(sign_key, SIGN_PROFILES["aries"])

    primary_snap = snapshot.get("primary_snapshot", snapshot) if isinstance(snapshot, dict) else snapshot
    sign_changes = snapshot.get("sign_changes", []) if isinstance(snapshot, dict) else []
    retrograde_stations = snapshot.get("retrograde_stations", []) if isinstance(snapshot, dict) else []

    if period_key == "daily":
        cosmic_pulse_words = "80-110 words"
        cosmic_summary_role = "synthesizing the day's composite trends written AFTER the other 7 categories"
        tip_title = "TIP FOR THE DAY"
        tip_example = "Write down the issue before discussing it, and keep your wording factual."
    elif period_key == "weekly":
        cosmic_pulse_words = "100-140 words"
        cosmic_summary_role = "synthesizing the entire week's overarching themes across all life domains written AFTER the other 7 categories"
        tip_title = "TIP FOR THE WEEK"
        tip_example = "Establish clear boundaries with colleagues early in the week to protect your creative energy."
    elif period_key == "yearly":
        cosmic_pulse_words = "600-700 words in 4-5 short paragraphs separated by \\n\\n"
        cosmic_summary_role = "synthesizing the entire year's overarching transits, naming the 2-3 most important transits or eclipses of the year for that sign"
        tip_title = "TIP FOR THE YEAR"
        tip_example = "Anchor your greatest endeavors in steady patience and mindful quarterly planning."
    else:
        cosmic_pulse_words = "380-450 words in 3-4 short paragraphs separated by \\n\\n"
        cosmic_summary_role = "synthesizing the entire month's overarching transits, naming the single most important ingress of the month for that sign"
        tip_title = "TIP FOR THE MONTH"
        tip_example = "Focus your resources on steady long-term priorities before launching new ventures."

    weekly_events_str = ""
    if period_key == "weekly":
        weekly_events = []
        if sign_changes:
            events_list = [f"{sc['planet'].capitalize()} moves from {sc.get('from_sign')} to {sc.get('to_sign')} on {sc.get('date')}" for sc in sign_changes]
            weekly_events.append("Planetary Sign Ingresses this week: " + "; ".join(events_list))
        if retrograde_stations:
            stations_list = [f"{rs['planet'].capitalize()} turns {rs.get('status')} on {rs.get('date')}" for rs in retrograde_stations]
            weekly_events.append("Planetary Stations/Retrograde this week: " + "; ".join(stations_list))
        if not weekly_events:
            weekly_events.append("Major planetary positions remain steady in their current signs throughout this week.")
        weekly_events_str = "\n".join(weekly_events)

    if system_key == "sidereal":
        style_guide = (
            "You are writing in the Vedic Jyotish tradition (Sidereal / Lahiri). "
            "Reference the active Moon Nakshatra, Tithi, planetary house transits from Chandra Lagna, "
            "and suggest authentic Sanskrit remedies (mantras, graha daan, pranayama, gemstones)."
        )
        planets_data = primary_snap.get("sidereal", {}).get("planets", {})
        aspects_data = primary_snap.get("sidereal", {}).get("aspects", [])
        moon_nakshatra = primary_snap.get("sidereal", {}).get("moon_nakshatra", {})
        tithi_data = primary_snap.get("sidereal", {}).get("tithi", {})
        extra_context = f"Moon Nakshatra: {moon_nakshatra.get('name')} Pada {moon_nakshatra.get('pada')}, Tithi: {tithi_data.get('name')}"
    else:
        style_guide = (
            "You are writing in the Western Astrology tradition (Tropical / Placidus). "
            "Reference planetary aspects (conjunctions, trines, sextiles, squares, oppositions), "
            "elemental balances, and practical modern psychological and wellness remedies."
        )
        planets_data = primary_snap.get("tropical", {}).get("planets", {})
        aspects_data = primary_snap.get("tropical", {}).get("aspects", [])
        extra_context = f"Major Aspects: {len(aspects_data)} active transit aspects."

    if weekly_events_str:
        extra_context += f"\nWeekly Shifts & Ingresses:\n{weekly_events_str}"

    cached_summary = ""
    if cached_categories:
        cached_summary = "Life Domain Summaries for Reference:\n"
        for c in cached_categories:
            if c.get("category") != "cosmic_pulse":
                cached_summary += f"- {c.get('category').capitalize()}: {c.get('text', '')[:120]}...\n"

    system_prompt = f"""You are a master Vedic and Western astrology writer producing the Cosmic Pulse overview for AstroJunction.
Follow these STRICT OUTPUT RULES:

1. Exactly ONE plain-text paragraph strictly {cosmic_pulse_words}. No line breaks, no multiple paragraphs.
2. Absolutely NO markdown (no **, *, #, bullets, numbered lists, emojis, headings, labels).
3. {cosmic_summary_role}. Do NOT copy sentences verbatim.
4. {style_guide}
5. {tip_title}:
   - Provide a 'tip_for_the_day' field in JSON.
   - Rules: exactly ONE sentence, 8-20 words, practical and actionable, plain text.
   - Absolutely NO markdown, NO emojis, NO 'Tip:' prefix, and NO mention of any planets.
   - Example style: "{tip_example}"

CRITICAL OUTPUT FORMAT:
You MUST respond with STRICT, RAW JSON ONLY.
{{
  "category": "cosmic_pulse",
  "text": "Single plain-text paragraph of {cosmic_pulse_words} summarizing the period...",
  "score": 86,
  "lucky_time": "07:00 AM - 08:30 AM",
  "remedy": "Light a sesame oil lamp during sunset for planetary balance.",
  "affirmation": "I move through this period with focused purpose and cosmic alignment.",
  "tip_for_the_day": "{tip_example}"
}}"""

    user_prompt = f"""Generate COSMIC PULSE for Zodiac Sign: {sign_key.capitalize()}
Astrological System: {system_key.capitalize()}
Date: {start_date} | Period: {period_key.upper()}
Ruling Planet: {profile['ruler']} | Element: {profile['element']} | Quality: {profile['quality']}
Transit Details: {extra_context}

Planetary Positions:
{json.dumps(planets_data, indent=2)}

Active Aspects:
{json.dumps(aspects_data[:6], indent=2)}

{cached_summary}

Requirements:
- Exactly ONE plain-text paragraph ({cosmic_pulse_words}).
- No markdown, no bullets, no lists.
- Include tip_for_the_day (8-20 words, exactly 1 sentence, no planets).
- Output valid raw JSON only."""

    last_error = None
    for attempt in range(3):
        try:
            raw_response = _call_llm_api(system_prompt, user_prompt)
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            start_brace = cleaned.find("{")
            end_brace = cleaned.rfind("}")
            if start_brace != -1 and end_brace != -1:
                cleaned = cleaned[start_brace:end_brace + 1]

            parsed_dict = json.loads(cleaned)
            parsed_dict["period"] = period_key
            item = HoroscopeCategoryItem(**parsed_dict)
            item_dict = item.model_dump()
            item_dict["text"] = clean_text(item_dict["text"])
            item_dict["lucky_time"] = clean_text(item_dict["lucky_time"])
            item_dict["remedy"] = clean_text(item_dict["remedy"])
            item_dict["affirmation"] = clean_text(item_dict["affirmation"])
            return item_dict
        except Exception as e:
            last_error = e
            print(f"[Cosmic Pulse Generation Attempt {attempt + 1}/3 Failed for {sign_key}]: {e}")
            user_prompt += f"\n\nCRITICAL FIX NEEDED: {e}. Output exactly one plain-text paragraph ({cosmic_pulse_words}), 1-sentence tip (8-20 words, no planets)."

    raise RuntimeError(f"Failed to generate cosmic_pulse for {sign_key} after 3 attempts: {last_error}")


def test_validator_with_bad_samples():
    """
    Unit test to prove that the Pydantic validator correctly REJECTS:
    1. Prohibited markdown bold syntax '**'
    2. Prohibited markdown heading syntax '###'
    3. Prohibited markdown bullet syntax '\\n-'
    4. More than one paragraph
    And accepts a compliant single plain-text paragraph.
    """
    print("\n--- Running Pydantic Validator Bad Sample Tests ---")
    bad_samples = [
        ("Markdown bold '**'", "This forecast contains **bold emphasis** which violates strict formatting rules."),
        ("Markdown heading '###'", "### Planetary Influence\nMars is transiting the tenth house today."),
        ("Markdown bullet '\\n-'", "Key recommendations:\n- Prioritize deep work\n- Avoid hasty signatures."),
        ("Multiple paragraphs", "This is paragraph number one about career development.\n\nThis is paragraph number two introducing separate ideas.")
    ]

    for label, bad_text in bad_samples:
        try:
            HoroscopeCategoryItem(
                category="professional",
                text=bad_text,
                score=82,
                lucky_time="10:00 AM - 11:30 AM",
                remedy="Offer water to the rising Sun.",
                affirmation="I lead with clarity and steady determination."
            )
            raise AssertionError(f"Test Failed: {label} was NOT rejected by Pydantic validator!")
        except ValidationError as e:
            err_msg = e.errors()[0]["msg"]
            print(f"  [PASS] {label} correctly REJECTED with ValidationError: {err_msg}")

    # Test good sample
    good_text = (
        "Your professional sector experiences steady progress as planetary alignments favor structured execution "
        "and disciplined focus. High-impact tasks require your full attention during the morning hours, while "
        "collaborative initiatives with senior colleagues flourish in the afternoon. Maintain your patience and "
        "avoid rushed decisions when negotiating terms or scheduling upcoming project deadlines."
    )
    item = HoroscopeCategoryItem(
        category="professional",
        text=good_text,
        score=88,
        lucky_time="10:00 AM - 11:30 AM",
        remedy="Keep a small brass object on your desk for focus.",
        affirmation="I achieve professional excellence through calm focus."
    )
    cleaned = clean_text(item.text)
    assert len(cleaned) > 20
    print("  [PASS] Compliant single-paragraph sample successfully VALIDATED.")
    print("--- All Pydantic Validator Tests Passed Successfully! ---\n")


if __name__ == "__main__":
    # 1. Run validator tests with bad samples
    test_validator_with_bad_samples()

    # 2. Test generation if ephemeris is available
    try:
        from scripts.ephemeris import get_snapshot
        today = date.today()
        snap = get_snapshot(today)
        print(f"Generating sample daily horoscope for Taurus (Tropical)...")
        items = generate_for_sign("taurus", "tropical", "daily", today, snap)
        print(f"SUCCESS! Generated {len(items)} categories:")
        for item in items:
            words = len(item['text'].split())
            print(f"- {item['category'].upper()}: Score {item['score']}% | Words: {words} | Text: {item['text'][:80]}...")
    except Exception as err:
        print(f"Sample generation run notice: {err}")
