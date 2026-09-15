import math
from typing import Dict, Any, List

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

MULANK_META = {
    1: {
      "planet": 'Sun (Surya - The Sovereign Creator)',
      "traits": ['Natural Leader', 'Independent & Ambitious', 'Visionary Authority', 'High Vitality & Dignity'],
      "mission": 'To pioneer trailblazing innovations, command respect through honorable leadership, and illuminate organizations with clarity.',
      "gems": ['Ruby', 'Red Garnet'],
      "colors": ['Gold', 'Copper', 'Orange', 'Yellow'],
      "days": ['Sunday', 'Monday'],
      "lucky": [1, 2, 3, 9],
      "enemy": [8, 6],
    },
    2: {
      "planet": 'Moon (Chandra - The Intuitive Healer)',
      "traits": ['Empathetic & Diplomatic', 'Creative Imagination', 'Peaceful Harmony', 'Deep Emotional Resonance'],
      "mission": 'To build bridges of mutual understanding, foster nurturing environments, and express subtle artistic beauty.',
      "gems": ['Natural Pearl', 'Moonstone'],
      "colors": ['Pearl White', 'Cream', 'Silver', 'Light Green'],
      "days": ['Monday', 'Sunday'],
      "lucky": [1, 2, 4, 7],
      "enemy": [8, 9],
    },
    3: {
      "planet": 'Jupiter (Brihaspati - The Wise Guru)',
      "traits": ['Philosophical Wisdom', 'Expansive Optimism', 'Master Communicator', 'Lifelong Teacher & Advisor'],
      "mission": 'To disseminate transformative knowledge, mentor rising generations, and uphold ethical and spiritual righteousness.',
      "gems": ['Yellow Sapphire', 'Topaz'],
      "colors": ['Bright Yellow', 'Golden Saffron', 'Amber'],
      "days": ['Thursday', 'Tuesday'],
      "lucky": [1, 2, 3, 9],
      "enemy": [6],
    },
    4: {
      "planet": 'Rahu (The Revolutionary Architect)',
      "traits": ['Methodical Organizer', 'Out-of-the-Box Thinker', 'Technological Genius', 'Courageous Reformer'],
      "mission": 'To dismantle outdated paradigms, engineer futuristic structural frameworks, and bring order to chaotic systems.',
      "gems": ['Hessonite (Gomed)'],
      "colors": ['Electric Blue', 'Grey', 'Brown', 'Khaki'],
      "days": ['Saturday', 'Sunday'],
      "lucky": [1, 4, 5, 6, 7],
      "enemy": [8, 2],
    },
    5: {
      "planet": 'Mercury (Budha - The Master Trader & Strategist)',
      "traits": ['Rapid Adaptability', 'Commercial Brilliance', 'Witty Eloquence', 'Multi-Faceted Curiosity'],
      "mission": 'To connect global networks, orchestrate thriving commercial ventures, and convey complex ideas with effortless charm.',
      "gems": ['Emerald', 'Peridot'],
      "colors": ['Emerald Green', 'Light Turquoise', 'Pistachio'],
      "days": ['Wednesday', 'Friday'],
      "lucky": [1, 5, 6],
      "enemy": [2],
    },
    6: {
      "planet": 'Venus (Shukra - The Aesthetic Alchemist)',
      "traits": ['Refined Aesthetics', 'Sensory Luxury', 'Magnetic Charisma', 'Devoted Compassion'],
      "mission": 'To infuse life with artistic elegance, foster harmonious relationships, and design sublime experiences of abundance.',
      "gems": ['Diamond', 'White Zircon', 'Opal'],
      "colors": ['Royal Blue', 'Pristine White', 'Rose Pink', 'Silvery Lilac'],
      "days": ['Friday', 'Wednesday'],
      "lucky": [5, 6, 8],
      "enemy": [3],
    },
    7: {
      "planet": 'Ketu (The Mystic Philosopher & Researcher)',
      "traits": ['Deep Introspection', 'Occult & Metaphysical Insight', 'Analytical Researcher', 'Detached Clarity'],
      "mission": 'To unravel universal mysteries, discover hidden metaphysical truths, and guide humanity toward spiritual liberation (Moksha).',
      "gems": ["Cat's Eye (Lehsuniya)"],
      "colors": ['Smoky Grey', 'Olive Green', 'White', 'Variegated'],
      "days": ['Tuesday', 'Thursday'],
      "lucky": [1, 2, 7],
      "enemy": [8, 9],
    },
    8: {
      "planet": 'Saturn (Shani - The Karmic Master & Judge)',
      "traits": ['Unyielding Endurance', 'Mastery of Discipline', 'Deep Justice & Humility', 'Empire Builder'],
      "mission": 'To construct enduring legacies through relentless perseverance, honor divine justice, and uplift the underprivileged.',
      "gems": ['Blue Sapphire', 'Amethyst'],
      "colors": ['Deep Navy', 'Midnight Black', 'Dark Violet'],
      "days": ['Saturday', 'Friday'],
      "lucky": [5, 6],
      "enemy": [1, 2, 9],
    },
    9: {
      "planet": 'Mars (Mangal - The Valiant Warrior & Champion)',
      "traits": ['Fearless Courage', 'Dynamic Action', 'Generous Passion', 'Protector of the Righteous'],
      "mission": 'To champion righteous causes, execute ambitious physical and leadership feats, and channel raw power into noble protection.',
      "gems": ['Red Coral', 'Carnelian'],
      "colors": ['Crimson Red', 'Scarlet', 'Coral Pink'],
      "days": ['Tuesday', 'Sunday'],
      "lucky": [1, 2, 3, 9],
      "enemy": [5, 8],
    },
}

def reduce_to_single_digit(num: int, keep_masters: bool = False) -> int:
    if keep_masters and num in (11, 22, 33):
        return num
    while num > 9:
        num = sum(int(d) for d in str(num))
    return num

def calculate_numerology_report(full_name: str, dob_str: str) -> Dict[str, Any]:
    full_name = full_name or "Divine Seeker"
    dob_str = dob_str or "1995-06-15"
    
    parts = dob_str.split('-')
    year = int(parts[0]) if len(parts) > 0 else 1995
    month = int(parts[1]) if len(parts) > 1 else 6
    day = int(parts[2]) if len(parts) > 2 else 15
    
    # 1. Mulank
    mulank = reduce_to_single_digit(day)
    
    # 2. Bhagyank
    total_date_sum = day + month + year
    bhagyank = reduce_to_single_digit(total_date_sum, keep_masters=True)
    bhagyank_reduced = reduce_to_single_digit(bhagyank)
    
    # 3. Namank
    clean_name = ''.join(c for c in full_name.upper() if c.isalpha())
    chaldean_sum = sum(CHALDEAN_VALUES.get(ch, 0) for ch in clean_name)
    pythagorean_sum = sum(PYTHAGOREAN_VALUES.get(ch, 0) for ch in clean_name)
    
    namank_chaldean = reduce_to_single_digit(chaldean_sum)
    namank_pythagorean = reduce_to_single_digit(pythagorean_sum)
    
    # 4. Lo Shu 3x3 Magic Grid
    date_digits_string = f"{year}{month:02d}{day:02d}"
    grid_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0}
    for digit in date_digits_string:
        if digit.isdigit():
            d = int(digit)
            if 1 <= d <= 9:
                grid_counts[d] += 1
            
    # Lo Shu Planes
    def get_status(strength: float) -> str:
        if strength >= 100: return 'Strong'
        if strength >= 66: return 'Moderate'
        if strength >= 33: return 'Weak'
        return 'Empty'
        
    lo_shu_planes = [
        {
            "name": 'Thought Plane (4 - 9 - 2)',
            "numbers": [4, 9, 2],
            "strength": ((1 if grid_counts[4] > 0 else 0) + (1 if grid_counts[9] > 0 else 0) + (1 if grid_counts[2] > 0 else 0)) / 3 * 100,
            "meaning": 'Strategic foresight, deep planning capabilities, photographic memory, and conceptual thinking.'
        },
        {
            "name": 'Will Plane (3 - 5 - 7)',
            "numbers": [3, 5, 7],
            "strength": ((1 if grid_counts[3] > 0 else 0) + (1 if grid_counts[5] > 0 else 0) + (1 if grid_counts[7] > 0 else 0)) / 3 * 100,
            "meaning": 'Unshakeable willpower, persistence, spiritual resilience, and capacity to overcome adversity.'
        },
        {
            "name": 'Action Plane (8 - 1 - 6)',
            "numbers": [8, 1, 6],
            "strength": ((1 if grid_counts[8] > 0 else 0) + (1 if grid_counts[1] > 0 else 0) + (1 if grid_counts[6] > 0 else 0)) / 3 * 100,
            "meaning": 'Execution speed, commercial pragmatism, physical stamina, and turning concepts into physical assets.'
        },
        {
            "name": 'Mental Plane (4 - 3 - 8)',
            "numbers": [4, 3, 8],
            "strength": ((1 if grid_counts[4] > 0 else 0) + (1 if grid_counts[3] > 0 else 0) + (1 if grid_counts[8] > 0 else 0)) / 3 * 100,
            "meaning": 'High analytical IQ, intellectual curiosity, structured logic, and academic brilliance.'
        },
        {
            "name": 'Emotional Plane (9 - 5 - 1)',
            "numbers": [9, 5, 1],
            "strength": ((1 if grid_counts[9] > 0 else 0) + (1 if grid_counts[5] > 0 else 0) + (1 if grid_counts[1] > 0 else 0)) / 3 * 100,
            "meaning": 'Intuitive empathy, emotional intelligence, charisma, and ability to connect deeply with others.'
        },
        {
            "name": 'Practical Plane (2 - 7 - 6)',
            "numbers": [2, 7, 6],
            "strength": ((1 if grid_counts[2] > 0 else 0) + (1 if grid_counts[7] > 0 else 0) + (1 if grid_counts[6] > 0 else 0)) / 3 * 100,
            "meaning": 'Attention to detail, material execution, artistic craftsmanship, and dependable consistency.'
        },
        {
            "name": 'Golden Raj Yoga Line (4 - 5 - 6)',
            "numbers": [4, 5, 6],
            "strength": ((1 if grid_counts[4] > 0 else 0) + (1 if grid_counts[5] > 0 else 0) + (1 if grid_counts[6] > 0 else 0)) / 3 * 100,
            "meaning": 'Supreme financial prosperity, steady business expansions, political/administrative victory, and immense prestige.'
        },
        {
            "name": 'Silver Spirituality Line (2 - 5 - 8)',
            "numbers": [2, 5, 8],
            "strength": ((1 if grid_counts[2] > 0 else 0) + (1 if grid_counts[5] > 0 else 0) + (1 if grid_counts[8] > 0 else 0)) / 3 * 100,
            "meaning": 'Real estate acumen, grounded stability, spiritual mastery, emotional maturity, and ancestral blessings.'
        }
    ]
    
    for plane in lo_shu_planes:
        plane["status"] = get_status(plane["strength"])
        
    meta = MULANK_META.get(mulank, MULANK_META[1])
    
    # Name Corrections
    name_corrections = []
    if namank_chaldean not in [1, 3, 5, 6]:
        name_corrections.append(f"Adjust spelling slightly (e.g. adding or modifying an 'A', 'E', or 'N') to bring Chaldean vibration to 1 (Solar Authority), 5 (Mercury Commerce), or 6 (Venus Abundance).")
        name_corrections.append(f"Your current name vibrates to Chaldean {namank_chaldean}, which may attract periodic delays in legal or financial transactions.")
    else:
        name_corrections.append(f"Your name resonates on auspicious Chaldean vibration {namank_chaldean}, in harmony with commercial prosperity and public recognition.")
        
    # Remedies
    remedies = []
    if grid_counts[1] == 0: remedies.append('Place a small indoor water fountain or image of flowing water in the North zone to activate Career & Communication flow (Number 1).')
    if grid_counts[2] == 0: remedies.append('Keep a pair of rose quartz crystals or earthy pottery in the South-West corner to ground Relationships & Emotional balance (Number 2).')
    if grid_counts[3] == 0: remedies.append('Introduce lush green plants or wooden artifacts in the East direction to stimulate Knowledge & Family blessings (Number 3).')
    if grid_counts[4] == 0: remedies.append('Keep a wooden money plant or green aventurine in the South-East corner to anchor Discipline & Financial discipline (Number 4).')
    if grid_counts[5] == 0: remedies.append('Keep the central Brahmasthan of your home open, clutter-free, and well-lit to maintain core stability and vitality (Number 5).')
    if grid_counts[6] == 0: remedies.append('Hang a 6-rod metal wind chime or silver bowl with water in the North-West zone to magnetize Helpful Friends & Travel luck (Number 6).')
    if grid_counts[7] == 0: remedies.append('Wear a silver bracelet or cat’s eye gemstone to boost spiritual focus, creative progeny, and mental stamina (Number 7).')
    if grid_counts[8] == 0: remedies.append('Place 8 natural crystals or river stones in the North-East zone to enhance Wisdom & Systematic wealth accumulation (Number 8).')
    if grid_counts[9] == 0: remedies.append('Place bright warm lighting or a red pyramid in the South zone to amplify Fame, Social recognition, and Ambition (Number 9).')
    
    # Missing numbers array
    missing_numbers = [num for num, count in grid_counts.items() if count == 0]
    
    bhagyank_meta = MULANK_META.get(bhagyank_reduced, meta)
    
    return {
        "mulank": mulank,
        "mulankPlanet": meta["planet"],
        "mulankCharacteristics": meta["traits"],
        "bhagyank": bhagyank,
        "bhagyankPlanet": bhagyank_meta["planet"],
        "bhagyankMission": meta["mission"],
        "namankChaldean": namank_chaldean,
        "namankPythagorean": namank_pythagorean,
        "nameCompatibility": 'Highly Harmonious & Auspicious' if namank_chaldean in [1, 3, 5, 6] else 'Moderate - Minor Phonetic Adjustment Recommended',
        "nameCorrectionSuggestions": name_corrections,
        "loShuGrid": grid_counts,
        "loShuPlanes": lo_shu_planes,
        "luckyNumbers": meta["lucky"],
        "unfavorableNumbers": meta["enemy"],
        "luckyDays": meta["days"],
        "luckyColors": meta["colors"],
        "luckyGemstones": meta["gems"],
        "remedies": remedies,
        "missingNumbers": missing_numbers
    }

calculate_numerology_details = calculate_numerology_report
