"""
Minimal RAG retrieval layer.

This is intentionally NOT a vector-embedding pipeline — that requires an
embedding model and a vector store, which is a separate infrastructure
decision the user hasn't made yet (and would need real credentials/infra
to test honestly). What this DOES do, correctly, is the core RAG
contract: given a user's question and their chart data, retrieve
relevant *classical reference knowledge* deterministically, so the LLM
is grounded in real traditional rules instead of inventing them.

Swap KNOWLEDGE_BASE for a real vector store later without changing the
retrieve() contract used by the counselling controller.
"""

KNOWLEDGE_BASE = [
    {
        "id": "house_10_career",
        "keywords": ["career", "job", "profession", "work", "promotion", "business", "10th house", "tenth house"],
        "text": (
            "The 10th house (Karma Bhava) governs career, public status, and professional "
            "reputation. Its lord's placement and strength, along with planets occupying "
            "it, indicate the native's vocational direction. Saturn in the 10th typically "
            "grants a career built on discipline and longevity; the Sun there favors "
            "authority and government-linked roles; Mercury favors trade, writing, or "
            "analytical professions."
        ),
    },
    {
        "id": "house_7_marriage",
        "keywords": ["marriage", "relationship", "spouse", "partner", "7th house", "seventh house", "love"],
        "text": (
            "The 7th house (Yuvati Bhava) governs marriage, partnerships, and one-to-one "
            "relationships. Its lord's dignity and any aspects from Venus, Jupiter, or "
            "malefics like Mars/Saturn shape relationship timing and harmony. Venus is the "
            "natural karaka (significator) of marriage in most classical systems."
        ),
    },
    {
        "id": "manglik_dosha",
        "keywords": ["manglik", "mangal dosha", "kuja dosha", "mars dosha"],
        "text": (
            "Manglik (Kuja) Dosha arises when Mars occupies the 1st, 2nd, 4th, 7th, 8th, or "
            "12th house from the Ascendant (or from the Moon, per some traditions). Its "
            "severity varies by house and sign; several classical cancellation (Bhanga) "
            "rules exist, e.g. Mars in its own sign (Aries/Scorpio) or exaltation (Capricorn) "
            "significantly reduces or nullifies the dosha."
        ),
    },
    {
        "id": "sade_sati",
        "keywords": ["sade sati", "saturn transit", "shani"],
        "text": (
            "Sade Sati is the ~7.5-year period when transiting Saturn moves through the 12th, "
            "1st, and 2nd houses counted from the natal Moon sign. It is traditionally "
            "associated with tests of endurance, restructuring, and karmic lessons rather "
            "than uniform misfortune; its actual effect depends heavily on Saturn's natal "
            "placement and dignity."
        ),
    },
    {
        "id": "raja_yoga",
        "keywords": ["raja yoga", "dhana yoga", "wealth yoga", "power yoga"],
        "text": (
            "Raja Yogas form primarily through connections (conjunction, mutual aspect, or "
            "exchange) between lords of Kendra houses (1,4,7,10) and Trikona houses "
            "(1,5,9). Dhana Yogas relate to connections among the 2nd, 11th, and 5th/9th "
            "house lords, indicating wealth accumulation potential."
        ),
    },
    {
        "id": "dasha_system",
        "keywords": ["dasha", "mahadasha", "antardasha", "vimshottari"],
        "text": (
            "The Vimshottari Dasha system allocates planetary periods (Mahadasha) totaling "
            "120 years based on the Moon's Nakshatra at birth. Each Mahadasha is further "
            "divided into Antardashas of the same nine planets, and the interaction between "
            "the ruling Mahadasha and Antardasha lords is used to time life events."
        ),
    },
    {
        "id": "gemstones",
        "keywords": ["gemstone", "gem", "ratna", "remedy", "stone"],
        "text": (
            "Vedic gemstone remedies are traditionally prescribed based on the strength or "
            "affliction of specific planets relevant to the querent's goals, not merely "
            "Sun-sign. A weak or well-placed benefic ruling a key house is often strengthened "
            "with its corresponding gem after consultation, since an ill-suited gem for a "
            "malefic-ruled house can amplify rather than mitigate difficulty."
        ),
    },
    {
        "id": "numerology_basics",
        "keywords": ["mulank", "bhagyank", "numerology", "lo shu", "chaldean"],
        "text": (
            "In Vedic numerology, Mulank (Psychic Number) derives from the birth day reduced "
            "to a single digit and reflects innate personality. Bhagyank (Destiny Number) "
            "derives from the full birth date and reflects life direction. The Lo Shu grid "
            "maps birth-date digits onto a 3x3 magic square to reveal psychological planes "
            "of strength and deficiency."
        ),
    },
]


def retrieve(query: str, max_results: int = 3):
    """Keyword-overlap retrieval. Returns the top matching knowledge
    entries as a list of {id, text} dicts. Deterministic — no LLM call."""
    query_lower = query.lower()
    scored = []
    for entry in KNOWLEDGE_BASE:
        score = sum(1 for kw in entry["keywords"] if kw in query_lower)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [{"id": e["id"], "text": e["text"]} for _, e in scored[:max_results]]
