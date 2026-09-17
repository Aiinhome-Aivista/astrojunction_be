import io
import os
import re
import json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle,
)
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from io import BytesIO
from reportlab.lib.enums import TA_CENTER

GOLD = colors.HexColor("#8C6D23")
DARK = colors.HexColor("#1A1A1A")


GOLD_DARK = colors.HexColor("#7E5F18")
GOLD_MAIN = colors.HexColor("#C9A050")
GOLD_LIGHT = colors.HexColor("#FFFFFF")
GOLD_BORDER = colors.HexColor("#E2D3B0")
TEXT_DARK = colors.HexColor("#1A1A1E")
TEXT_MUTED = colors.HexColor("#5A554C")


def _pdf_text(val) -> str:
    if val is None:
        return ""
    return str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles():
    styles = getSampleStyleSheet()

    # =========================================================
    # BRAND
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVBrand",
        fontSize=21,
        leading=25,
        alignment=0,
        fontName="Helvetica-Bold",
        textColor=GOLD_DARK,
    ))

    styles.add(ParagraphStyle(
        name="JVTitle",
        fontSize=21,
        leading=25,
        alignment=1,
        fontName="Helvetica-Bold",
        textColor=GOLD_DARK,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name="JVSubtitle",
        fontSize=9.5,
        leading=13,
        alignment=1,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
        spaceAfter=10,
    ))

    # =========================================================
    # SECTIONS
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVSection",
        fontSize=10,
        leading=13,
        spaceBefore=4,
        spaceAfter=3,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
    ))

    styles.add(ParagraphStyle(
        name="JVSubSection",
        fontSize=9,
        leading=12,
        spaceBefore=5,
        spaceAfter=3,
        textColor=TEXT_DARK,
        fontName="Helvetica-Bold",
    ))

    # =========================================================
    # BODY
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVBody",
        fontSize=8.5,
        leading=12,
        textColor=TEXT_DARK,
    ))

    styles.add(ParagraphStyle(
        name="JVBodyBold",
        fontSize=9,
        leading=12.5,
        textColor=TEXT_DARK,
        fontName="Helvetica-Bold",
    ))

    styles.add(ParagraphStyle(
        name="JVBodyMuted",
        fontSize=8,
        leading=11,
        textColor=TEXT_MUTED,
    ))

    styles.add(ParagraphStyle(
        name="JVSmall",
        fontSize=7.5,
        leading=10,
        textColor=TEXT_DARK,
    ))

    # =========================================================
    # SCORE
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVScore",
        fontSize=18,
        leading=22,
        alignment=1,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
    ))

    styles.add(ParagraphStyle(
        name="ScoreCenter",
        parent=styles["JVBody"],
        alignment=1,
        leading=14,
    ))

    # =========================================================
    # TABLE HEADERS
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVTableHead",
        fontSize=8.5,
        leading=11.5,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
        alignment=0,
    ))

    styles.add(ParagraphStyle(
        name="JVTableHeadCenter",
        fontSize=8.5,
        leading=11.5,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
        alignment=1,
    ))

    styles.add(ParagraphStyle(
        name="JVTableHeadRight",
        fontSize=8.5,
        leading=11.5,
        textColor=GOLD_DARK,
        fontName="Helvetica-Bold",
        alignment=2,
    ))

    # =========================================================
    # TABLE CELLS
    # =========================================================

    styles.add(ParagraphStyle(
        name="JVTableCellCenter",
        fontSize=8.5,
        leading=11.5,
        textColor=TEXT_DARK,
        alignment=1,
    ))

    styles.add(ParagraphStyle(
        name="JVTableCellRight",
        fontSize=8.5,
        leading=11.5,
        textColor=TEXT_DARK,
        alignment=2,
        fontName="Helvetica-Bold",
    ))

    return styles

# ============================================================
# HELPERS
# ============================================================

def _value(data, *keys, default=None):
    """
    Return first available non-empty value.
    """

    if not isinstance(data, dict):
        return default

    for key in keys:
        value = data.get(key)

        if value is not None and str(value).strip() != "":
            return value

    return default


def _clean_sanskrit(value):
    if not value:
        return ""
    # Remove first braces/parentheses and whatever is inside them, e.g. "Meena (मीन)" -> "Meena"
    return re.sub(r"\s*\([^)]*\)", "", str(value)).strip()


def _text(value, default="N/A"):
    if value is None:
        return default

    if isinstance(value, bool):
        return "Yes" if value else "No"

    value = str(value).strip()
    if not value:
        return default

    # Remove any parentheses containing non-ASCII / Devanagari characters
    value = re.sub(r"\s*\([^)]*[^\x00-\x7F]+[^)]*\)", "", value).strip()

    return value if value else default


def _number(value, default="0"):
    """
    7.0 -> 7
    7.50 -> 7.5
    """

    if value is None:
        return default

    try:
        number = float(value)

        if number.is_integer():
            return str(int(number))

        return f"{number:.2f}".rstrip("0").rstrip(".")

    except (ValueError, TypeError):
        return _text(value, default)


def _safe_paragraph(value, styles):
    """
    Convert arbitrary value into a ReportLab Paragraph.
    """

    return Paragraph(
        _text(value),
        styles["JVSmall"],
    )


# ============================================================
# PARSE REPORT JSON
# ============================================================

def _get_report_json(report):

    report_json = report.get("report_json") or {}

    if isinstance(report_json, str):

        try:
            report_json = json.loads(report_json)

        except json.JSONDecodeError:
            report_json = {}

    if not isinstance(report_json, dict):
        report_json = {}

    return report_json


# ============================================================
# PARTNER INFORMATION
# ============================================================

def _get_partner(report_json, report, partner_key):

    # Direct partner data
    direct_partner = report_json.get(partner_key)

    if not isinstance(direct_partner, dict):
        direct_partner = {}

    # Matching-specific partner data
    # Example:
    # report_json["partners"]["partner1"]
    partners = report_json.get("partners")

    if not isinstance(partners, dict):
        partners = {}

    nested_partner = partners.get(partner_key)

    if not isinstance(nested_partner, dict):
        nested_partner = {}

    # Merge both sources
    # nested_partner values will override direct_partner values
    partner = {
        **direct_partner,
        **nested_partner,
    }

    db_prefix = partner_key

    return {
        "fullName": _value(
            partner,
            "fullName",
            "name",
            default=report.get(
                f"{db_prefix}_name",
                "N/A",
            ),
        ),

        "dob": _value(
            partner,
            "birthDate",
            "dob",
            default=report.get(
                f"{db_prefix}_birth_date",
                "N/A",
            ),
        ),

        "birthTime": _value(
            partner,
            "birthTime",
            "time",
            default=report.get(
                f"{db_prefix}_birth_time",
                "N/A",
            ),
        ),

        "birthPlace": _value(
            partner,
            "birthPlace",
            "place",
            default=report.get(
                f"{db_prefix}_birth_place",
                "N/A",
            ),
        ),

        "rashi": _value(
            partner,
            "rashi",
            "rashiName",
            default="N/A",
        ),

        "nakshatra": _value(
            partner,
            "nakshatra",
            "nakshatraName",
            default="N/A",
        ),

        "nakshatraPada": _value(
            partner,
            "nakshatraPada",
            "pada",
            default="N/A",
        ),
    }
# ============================================================
# GET STATUS
# ============================================================

def _get_partner_status(
    report_json,
    partner_key,
):

    # --------------------------------------------------------
    # First check partner itself
    # --------------------------------------------------------

    partner = report_json.get(partner_key)

    if isinstance(partner, dict):

        status = _value(
            partner,
            "status",
            "manglikStatus",
            default=None,
        )

        if status is not None:
            return status

    # --------------------------------------------------------
    # Then check manglik.status
    # --------------------------------------------------------

    manglik = report_json.get("manglik")

    if isinstance(manglik, dict):

        status = manglik.get("status")

        if isinstance(status, dict):

            value = status.get(partner_key)

            if value is not None:
                return value

    return "N/A"


# ============================================================
# NUMEROLOGY / MULANK
# ============================================================

def _get_mulank(report_json, partner_key):

    numerology = report_json.get("numerologyMilan")

    if not isinstance(numerology, dict):
        return "N/A"

    partner = numerology.get(partner_key)

    if not isinstance(partner, dict):
        return "N/A"

    return _value(
        partner,
        "mulank",
        default="N/A",
    )


# ============================================================
# PARTNER INFORMATION TABLE
# ============================================================

def _partner_information_table(
    report_json,
    report,
    partner1,
    partner2,
    styles,
):

    p1_status = _get_partner_status(
        report_json,
        "partner1",
    )

    p2_status = _get_partner_status(
        report_json,
        "partner2",
    )

    p1_mulank = _get_mulank(
        report_json,
        "partner1",
    )

    p2_mulank = _get_mulank(
        report_json,
        "partner2",
    )

    rows = [
        [
            Paragraph(
                "<b>Information</b>",
                styles["JVSmall"],
            ),

            Paragraph(
                "<b>Partner 1</b>",
                styles["JVSmall"],
            ),

            Paragraph(
                "<b>Partner 2</b>",
                styles["JVSmall"],
            ),
        ],

        [
            "Full Name",
            _text(partner1["fullName"]),
            _text(partner2["fullName"]),
        ],

        [
            "Date of Birth",
            _text(partner1["dob"]),
            _text(partner2["dob"]),
        ],

        [
            "Birth Time",
            _text(partner1["birthTime"]),
            _text(partner2["birthTime"]),
        ],

        [
            "Birth Place",
            _text(partner1["birthPlace"]),
            _text(partner2["birthPlace"]),
        ],

        [
            "Rashi",
            _text(partner1["rashi"]),
            _text(partner2["rashi"]),
        ],

        [
            "Nakshatra",
            _text(partner1["nakshatra"]),
            _text(partner2["nakshatra"]),
        ],

        [
            "Nakshatra Pada",
            _text(partner1["nakshatraPada"]),
            _text(partner2["nakshatraPada"]),
        ],

        [
            "Status",
            _text(p1_status),
            _text(p2_status),
        ],

        [
            "Mulank",
            _number(p1_mulank),
            _number(p2_mulank),
        ],
    ]

    table = Table(
        rows,
        colWidths=[
            54 * mm,
            65 * mm,
            65 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "FONTNAME",
            (0, 1),
            (0, -1),
            "Helvetica-Bold",
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            8.5,
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            6,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            6,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            6,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            6,
        ),
    ]))

    return table


# ============================================================
# ASHTA KOOTA
# ============================================================

def _get_kootas(report_json):

    # --------------------------------------------------------
    # Preferred:
    #
    # kootas: [...]
    # --------------------------------------------------------

    kootas = report_json.get("kootas")

    if isinstance(kootas, list) and kootas:
        return kootas

    # --------------------------------------------------------
    # Your JSON:
    #
    # ashtaKoota: {
    #     gana: {...},
    #     nadi: {...},
    #     ...
    # }
    # --------------------------------------------------------

    ashta = report_json.get("ashtaKoota")

    if isinstance(ashta, dict):

        result = []

        # Desired display order
        order = [
            "varna",
            "vashya",
            "tara",
            "yoni",
            "grahaMaitri",
            "gana",
            "bhakoot",
            "nadi",
        ]

        for key in order:

            value = ashta.get(key)

            if isinstance(value, dict):

                item = dict(value)

                item["_key"] = key

                if not item.get("name"):
                    item["name"] = key

                result.append(item)

        return result

    return []


# ============================================================
# KOOTA DISPLAY NAME
# ============================================================

def _koota_name(koota):

    name = _value(
        koota,
        "name",
        "area",
        "sanskritName",
        default=None,
    )

    if name:
        return str(name)

    key = koota.get("_key")

    names = {
        "varna": "Varna",
        "vashya": "Vashya",
        "tara": "Tara",
        "yoni": "Yoni",
        "grahaMaitri": "Graha Maitri",
        "gana": "Gana",
        "bhakoot": "Bhakoot",
        "nadi": "Nadi",
    }

    return names.get(
        key,
        "Koota",
    )


# ============================================================
# KOOTA PARTNER VALUES
# ============================================================

def _koota_partner_values(koota):

    key = koota.get("_key")

    p1 = "N/A"
    p2 = "N/A"

    # --------------------------------------------------------
    # Generic structure
    # --------------------------------------------------------

    generic_p1 = _value(
        koota,
        "p1Value",
        "partner1Value",
        default=None,
    )

    generic_p2 = _value(
        koota,
        "p2Value",
        "partner2Value",
        default=None,
    )

    if generic_p1 is not None:
        p1 = generic_p1

    if generic_p2 is not None:
        p2 = generic_p2

    # --------------------------------------------------------
    # Specific ashtaKoota structures from your JSON
    # --------------------------------------------------------

    if key == "yoni":

        p1 = _value(
            koota,
            "yoni1",
            default=p1,
        )

        p2 = _value(
            koota,
            "yoni2",
            default=p2,
        )

    elif key == "vashya":

        p1 = _value(
            koota,
            "class1",
            default=p1,
        )

        p2 = _value(
            koota,
            "class2",
            default=p2,
        )

    elif key == "grahaMaitri":

        p1 = _value(
            koota,
            "lord1",
            default=p1,
        )

        p2 = _value(
            koota,
            "lord2",
            default=p2,
        )

    elif key == "tara":

        tara1 = _value(
            koota,
            "tara1",
            default=None,
        )

        tara2 = _value(
            koota,
            "tara2",
            default=None,
        )

        if tara1 is not None:
            p1 = tara1

        if tara2 is not None:
            p2 = tara2

    elif key == "bhakoot":

        relation = _value(
            koota,
            "relation",
            default=None,
        )

        if relation:
            p1 = relation
            p2 = relation

    elif key == "nadi":
        nadi1 = _value(koota, "nadi1", "p1Value", default=None)
        nadi2 = _value(koota, "nadi2", "p2Value", default=None)
        if nadi1 and ("Nadi" in str(nadi1) or str(nadi1) in {"Adi", "Madhya", "Antya"}):
            p1 = nadi1 if "Nadi" in str(nadi1) else f"{nadi1} Nadi"
        if nadi2 and ("Nadi" in str(nadi2) or str(nadi2) in {"Adi", "Madhya", "Antya"}):
            p2 = nadi2 if "Nadi" in str(nadi2) else f"{nadi2} Nadi"

        if not p1 or not p2 or p1 == "—" or p2 == "—":
            same_nadi = _value(
                koota,
                "sameNadi",
                default=None,
            )
            if same_nadi is not None:
                if not p1 or p1 == "—":
                    p1 = "Same Nadi" if same_nadi else "Different Nadi"
                if not p2 or p2 == "—":
                    p2 = "Same Nadi" if same_nadi else "Different Nadi"

    return p1, p2


# ============================================================
# KOOTA DESCRIPTION
# ============================================================

def _koota_description(koota):

    key = koota.get("_key")

    description = _value(
        koota,
        "description",
        "verdict",
        "note",
        "notes",
        "result",
        default=None,
    )

    if description:
        return description

    # --------------------------------------------------------
    # Automatically describe available raw information
    # --------------------------------------------------------

    if key == "tara":

        tara1 = _value(
            koota,
            "tara1",
            default="N/A",
        )

        tara2 = _value(
            koota,
            "tara2",
            default="N/A",
        )

        return (
            f"Tara values: Partner 1 = {tara1}, "
            f"Partner 2 = {tara2}."
        )

    if key == "bhakoot":

        relation = _value(
            koota,
            "relation",
            default="N/A",
        )

        dosha = _value(
            koota,
            "dosha",
            default=None,
        )

        cancellation = _value(
            koota,
            "cancellationApplied",
            default=None,
        )

        result = f"Relation: {relation}."

        if dosha is not None:
            result += f" Dosha: {'Yes' if dosha else 'No'}."

        if cancellation is not None:
            result += (
                f" Cancellation applied: "
                f"{'Yes' if cancellation else 'No'}."
            )

        return result

    if key == "nadi":

        same_nadi = _value(
            koota,
            "sameNadi",
            default=None,
        )

        cancellation = _value(
            koota,
            "cancellationApplied",
            default=None,
        )

        result = ""

        if same_nadi is not None:
            result += (
                f"Same Nadi: "
                f"{'Yes' if same_nadi else 'No'}."
            )

        if cancellation is not None:
            result += (
                f" Cancellation applied: "
                f"{'Yes' if cancellation else 'No'}."
            )

        return result or "N/A"

    return "N/A"


# ============================================================
# ASHTA KOOTA TABLE
# ============================================================

def _build_koota_table(report_json, styles):

    kootas = _get_kootas(report_json)

    if not kootas:
        return None

    rows = [
        [
            Paragraph("<b>Koota</b>", styles["JVSmall"]),
            Paragraph("<b>Partner 1</b>", styles["JVSmall"]),
            Paragraph("<b>Partner 2</b>", styles["JVSmall"]),
            Paragraph("<b>Score</b>", styles["JVSmall"]),
            Paragraph("<b>Max</b>", styles["JVSmall"]),
            Paragraph(
                "<b>Description / Result</b>",
                styles["JVSmall"],
            ),
        ]
    ]

    for koota in kootas:

        if not isinstance(koota, dict):
            continue

        name = _koota_name(koota)

        p1, p2 = _koota_partner_values(
            koota
        )

        score = _value(
            koota,
            "score",
            "points",
            "obtainedPoints",
            default=0,
        )

        max_score = _value(
            koota,
            "maxScore",
            "maxPoints",
            "max",
            default=0,
        )

        description = _koota_description(
            koota
        )

        rows.append([
            Paragraph(
                _text(name),
                styles["JVSmall"],
            ),

            Paragraph(
                _text(p1),
                styles["JVSmall"],
            ),

            Paragraph(
                _text(p2),
                styles["JVSmall"],
            ),

            Paragraph(
                _number(score),
                styles["JVSmall"],
            ),

            Paragraph(
                _number(max_score),
                styles["JVSmall"],
            ),

            Paragraph(
                _text(description),
                styles["JVSmall"],
            ),
        ])

    table = Table(
        rows,
        colWidths=[
            28 * mm,
            30 * mm,
            30 * mm,
            17 * mm,
            17 * mm,
            62 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "ALIGN",
            (3, 1),
            (4, -1),
            "CENTER",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
    ]))

    return table


# ============================================================
# OVERALL SCORE
# ============================================================

def _get_overall_score(
    report_json,
    report,
):

    summary = report_json.get("summary")

    if not isinstance(summary, dict):
        summary = {}

    total = _value(
        report_json,
        "totalPoints",
        "totalScore",
        default=None,
    )

    if total is None:

        total = _value(
            summary,
            "totalScore",
            "totalPoints",
            default=None,
        )

    if total is None:
        total = report.get(
            "total_score",
            0,
        )

    max_points = _value(
        report_json,
        "maxPoints",
        "maxScore",
        default=None,
    )

    if max_points is None:

        max_points = _value(
            summary,
            "maxScore",
            "maxPoints",
            default=None,
        )

    if max_points is None:
        max_points = report.get(
            "max_score",
            36,
        )

    percentage = _value(
        report_json,
        "percentage",
        default=None,
    )

    if percentage is None:

        percentage = _value(
            summary,
            "percentage",
            default=None,
        )

    if percentage is None:

        try:

            if float(max_points) > 0:

                percentage = (
                    float(total)
                    / float(max_points)
                    * 100
                )

            else:
                percentage = 0

        except (
            ValueError,
            TypeError,
            ZeroDivisionError,
        ):
            percentage = 0

    return (
        total,
        max_points,
        percentage,
    )


# ============================================================
# CHART HELPERS
# ============================================================

def _get_chart(report_json, partner_key):

    charts = report_json.get("charts")

    if not isinstance(charts, dict):
        return {}

    chart = charts.get(partner_key)

    if not isinstance(chart, dict):
        return {}

    return chart


# ============================================================
# CHART PARTNER BASIC INFORMATION
# ============================================================

def _build_chart_basic_info(
    chart,
    styles,
):

    partner = chart.get("partner")

    if not isinstance(partner, dict):
        partner = {}

    rows = [
        [
            Paragraph(
                "<b>Chart Information</b>",
                styles["JVSmall"],
            ),
            Paragraph(
                "<b>Value</b>",
                styles["JVSmall"],
            ),
        ],

        [
            "Name",
            _safe_paragraph(
                _value(
                    partner,
                    "fullName",
                    "name",
                ),
                styles,
            ),
        ],

        [
            "Date of Birth",
            _safe_paragraph(
                _value(
                    partner,
                    "birthDate",
                    "dob",
                ),
                styles,
            ),
        ],

        [
            "Birth Time",
            _safe_paragraph(
                _value(
                    partner,
                    "birthTime",
                    "time",
                ),
                styles,
            ),
        ],

        [
            "Birth Place",
            _safe_paragraph(
                _value(
                    partner,
                    "birthPlace",
                    "place",
                ),
                styles,
            ),
        ],

        [
            "Timezone",
            _safe_paragraph(
                partner.get("timezone"),
                styles,
            ),
        ],

        [
            "Latitude",
            _safe_paragraph(
                partner.get("latitude"),
                styles,
            ),
        ],

        [
            "Longitude",
            _safe_paragraph(
                partner.get("longitude"),
                styles,
            ),
        ],

        [
            "House System",
            _safe_paragraph(
                partner.get("houseSystem"),
                styles,
            ),
        ],

        [
            "Horoscope System",
            _safe_paragraph(
                partner.get("horoscopeSystem"),
                styles,
            ),
        ],

        [
            "Node Type",
            _safe_paragraph(
                partner.get("nodeType"),
                styles,
            ),
        ],
    ]

    table = Table(
        rows,
        colWidths=[
            55 * mm,
            129 * mm,
        ],
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "FONTNAME",
            (0, 1),
            (0, -1),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            8,
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
    ]))

    return table


# ============================================================
# ASCENDANT TABLE
# ============================================================

def _build_ascendant_table(
    chart,
    styles,
):

    ascendant = chart.get("ascendant")

    if not isinstance(ascendant, dict):
        return None

    rows = [
        [
            Paragraph(
                "<b>Ascendant</b>",
                styles["JVSmall"],
            ),
            Paragraph(
                "<b>Value</b>",
                styles["JVSmall"],
            ),
        ],

        [
            "Sign",
            _safe_paragraph(
                ascendant.get("signName"),
                styles,
            ),
        ],

        [
            "Sign Sanskrit",
            _safe_paragraph(
                _clean_sanskrit(ascendant.get("signSanskrit")),
                styles,
            ),
        ],

        [
            "Degree",
            _safe_paragraph(
                ascendant.get("degree"),
                styles,
            ),
        ],

        [
            "Degree DMS",
            _safe_paragraph(
                ascendant.get("degreeDMS"),
                styles,
            ),
        ],

        [
            "Nakshatra",
            _safe_paragraph(
                ascendant.get("nakshatra"),
                styles,
            ),
        ],

        [
            "Nakshatra Lord",
            _safe_paragraph(
                ascendant.get("nakshatraLord"),
                styles,
            ),
        ],

        [
            "Pada",
            _safe_paragraph(
                ascendant.get("pada"),
                styles,
            ),
        ],
    ]

    table = Table(
        rows,
        colWidths=[
            55 * mm,
            129 * mm,
        ],
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "FONTNAME",
            (0, 1),
            (0, -1),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            8,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),
    ]))

    return table


# ============================================================
# PLANET TABLE
# ============================================================

def _build_planet_table(
    chart,
    styles,
):

    planets = chart.get("planets")

    if not isinstance(planets, list):
        return None

    if not planets:
        return None

    rows = [
        [
            Paragraph("<b>Planet</b>", styles["JVSmall"]),
            Paragraph("<b>Sign</b>", styles["JVSmall"]),
            Paragraph("<b>Degree</b>", styles["JVSmall"]),
            Paragraph("<b>House</b>", styles["JVSmall"]),
            Paragraph("<b>Nakshatra</b>", styles["JVSmall"]),
            Paragraph("<b>Pada</b>", styles["JVSmall"]),
            Paragraph("<b>Retro</b>", styles["JVSmall"]),
        ]
    ]

    for planet in planets:

        if not isinstance(planet, dict):
            continue

        rows.append([
            _safe_paragraph(
                _value(
                    planet,
                    "name",
                    "sanskritName",
                ),
                styles,
            ),

            _safe_paragraph(
                _value(
                    planet,
                    "signName",
                    "sign",
                ),
                styles,
            ),

            _safe_paragraph(
                _value(
                    planet,
                    "degreeDMS",
                    "degree",
                ),
                styles,
            ),

            _safe_paragraph(
                planet.get("house"),
                styles,
            ),

            _safe_paragraph(
                planet.get("nakshatra"),
                styles,
            ),

            _safe_paragraph(
                planet.get("pada"),
                styles,
            ),

            _safe_paragraph(
                planet.get("retrograde"),
                styles,
            ),
        ])

    table = Table(
        rows,
        colWidths=[
            28 * mm,
            28 * mm,
            30 * mm,
            18 * mm,
            42 * mm,
            18 * mm,
            20 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            7,
        ),

        (
            "ALIGN",
            (3, 1),
            (3, -1),
            "CENTER",
        ),

        (
            "ALIGN",
            (5, 1),
            (6, -1),
            "CENTER",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            3,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),
    ]))

    return table


# ============================================================
# HOUSE CUSPS
# ============================================================

def _build_house_cusp_table(
    chart,
    styles,
):

    cusps = chart.get("houseCusps")

    if not isinstance(cusps, list):
        return None

    if not cusps:
        return None

    rows = [
        [
            Paragraph("<b>House</b>", styles["JVSmall"]),
            Paragraph("<b>Sign</b>", styles["JVSmall"]),
            Paragraph("<b>Degree</b>", styles["JVSmall"]),
            Paragraph(
                "<b>Sidereal Longitude</b>",
                styles["JVSmall"],
            ),
        ]
    ]

    for cusp in cusps:

        if not isinstance(cusp, dict):
            continue

        rows.append([
            _safe_paragraph(
                cusp.get("house"),
                styles,
            ),

            _safe_paragraph(
                cusp.get("signName"),
                styles,
            ),

            _safe_paragraph(
                cusp.get("degree"),
                styles,
            ),

            _safe_paragraph(
                cusp.get("longitudeSidereal"),
                styles,
            ),
        ])

    table = Table(
        rows,
        colWidths=[
            30 * mm,
            56 * mm,
            48 * mm,
            50 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            7.5,
        ),

        (
            "ALIGN",
            (0, 1),
            (0, -1),
            "CENTER",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),
    ]))

    return table


# ============================================================
# CALCULATION INFORMATION
# ============================================================

def _build_calculation_table(
    chart,
    styles,
):

    calculation = chart.get("calculation")

    if not isinstance(calculation, dict):
        return None

    rows = [
        [
            Paragraph(
                "<b>Calculation Parameter</b>",
                styles["JVSmall"],
            ),
            Paragraph(
                "<b>Value</b>",
                styles["JVSmall"],
            ),
        ]
    ]

    preferred_keys = [
        "engine",
        "zodiac",
        "ayanamsha",
        "latitude",
        "longitude",
        "timezone",
        "houseSystem",
        "nodeType",
        "julianDayUT",
        "ephemerisFlags",
        "coordinateFrame",
    ]

    for key in preferred_keys:

        if key not in calculation:
            continue

        value = calculation.get(key)

        # Don't show huge nested structures here
        if isinstance(value, (dict, list)):
            value = json.dumps(
                value,
                ensure_ascii=False,
            )

        rows.append([
            Paragraph(
                str(key),
                styles["JVSmall"],
            ),

            Paragraph(
                _text(value),
                styles["JVSmall"],
            ),
        ])

    if len(rows) == 1:
        return None

    table = Table(
        rows,
        colWidths=[
            65 * mm,
            119 * mm,
        ],
        repeatRows=1,
    )

    table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#F0E6C8"),
        ),

        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            GOLD_DARK,
        ),

        (
            "FONTNAME",
            (0, 0),
            (-1, 0),
            "Helvetica-Bold",
        ),

        (
            "FONTNAME",
            (0, 1),
            (0, -1),
            "Helvetica-Bold",
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "FONTSIZE",
            (0, 0),
            (-1, -1),
            7.5,
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "TOP",
        ),

        (
            "LEFTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "RIGHTPADDING",
            (0, 0),
            (-1, -1),
            5,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            4,
        ),
    ]))

    return table


# ============================================================
# FULL CHART SECTION
# ============================================================

def _build_chart_section(
    report_json,
    partner_key,
    partner_label,
    styles,
):

    chart = _get_chart(
        report_json,
        partner_key,
    )

    if not chart:
        return []

    story = []

    story.append(
        Paragraph(
            partner_label,
            styles["JVSection"],
        )
    )

    # --------------------------------------------------------
    # Basic birth information
    # --------------------------------------------------------

    basic_table = _build_chart_basic_info(
        chart,
        styles,
    )

    if basic_table:
        story.append(basic_table)
        story.append(Spacer(1, 7))

    # --------------------------------------------------------
    # Ascendant
    # --------------------------------------------------------

    ascendant_table = _build_ascendant_table(
        chart,
        styles,
    )

    if ascendant_table:

        story.append(
            Paragraph(
                "Ascendant",
                styles["JVSubSection"],
            )
        )

        story.append(
            ascendant_table
        )

        story.append(
            Spacer(1, 7)
        )

    # --------------------------------------------------------
    # Planets
    # --------------------------------------------------------

    planet_table = _build_planet_table(
        chart,
        styles,
    )

    if planet_table:

        story.append(
            Paragraph(
                "Planetary Positions",
                styles["JVSubSection"],
            )
        )

        story.append(
            planet_table
        )

        story.append(
            Spacer(1, 7)
        )

    # --------------------------------------------------------
    # House Cusps
    # --------------------------------------------------------

    house_table = _build_house_cusp_table(
        chart,
        styles,
    )

    if house_table:

        story.append(
            Paragraph(
                "House Cusps",
                styles["JVSubSection"],
            )
        )

        story.append(
            house_table
        )

        story.append(
            Spacer(1, 7)
        )

    # --------------------------------------------------------
    # Calculation
    # --------------------------------------------------------

    calculation_table = _build_calculation_table(
        chart,
        styles,
    )

    if calculation_table:

        story.append(
            Paragraph(
                "Calculation Details",
                styles["JVSubSection"],
            )
        )

        story.append(
            calculation_table
        )

    return story


# ============================================================
# DECORATIVE CANVAS & BRAND HEADER
# ============================================================

def _draw_page_decorations(canvas, doc_):
    canvas.saveState()
        
    # 1. Full Page Background Astrologer / Sage Image Watermark
    img_candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "astrologer_bg.jpg")),
        os.path.abspath(os.path.join("public", "astrologer_bg.jpg")),
        os.path.abspath("astrologer_bg.jpg"),
    ]
    img_path = next((p for p in img_candidates if os.path.exists(p)), None)
        
    if img_path:
        try:
            canvas.setFillAlpha(0.09)
            # Full page watermark across the entire 210mm x 297mm page
            canvas.drawImage(
                img_path,
                0,
                0,
                width=210 * mm,
                height=297 * mm,
                preserveAspectRatio=False,
                mask='auto'
            )
        except Exception:
            pass

    # Outer Decorative Golden Double Border
    canvas.setFillAlpha(1.0)
    canvas.setStrokeColor(GOLD_MAIN)
    canvas.setLineWidth(1.2)
    canvas.rect(8 * mm, 8 * mm, (210 - 16) * mm, (297 - 16) * mm)
    canvas.setLineWidth(0.4)
    canvas.rect(10 * mm, 10 * mm, (210 - 20) * mm, (297 - 20) * mm)

    # Corner Golden Rosettes
    canvas.setFillColor(GOLD_MAIN)
    canvas.circle(10 * mm, 10 * mm, 1.2 * mm, fill=1, stroke=0)
    canvas.circle((210 - 10) * mm, 10 * mm, 1.2 * mm, fill=1, stroke=0)
    canvas.circle(10 * mm, (297 - 10) * mm, 1.2 * mm, fill=1, stroke=0)
    canvas.circle((210 - 10) * mm, (297 - 10) * mm, 1.2 * mm, fill=1, stroke=0)

    # Footer Divider Line
    canvas.setStrokeColor(GOLD_BORDER)
    canvas.setLineWidth(0.4)
    canvas.line(13 * mm, 16 * mm, (210 - 13) * mm, 16 * mm)

    # Footer Details (Only Generation Date and Page Number)
    gen_date = datetime.utcnow().strftime("%d %b %Y")
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(14 * mm, 11.5 * mm, f"Generated: {gen_date}")
    canvas.drawRightString((210 - 14) * mm, 11.5 * mm, f"Page {doc_.page}")

    canvas.restoreState()


def _build_brand_header(title_text: str, subtitle_text: str, styles) -> Table:
    logo_candidates = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "jyotishveda_logo_standard.png")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "jyotishveda_logo_standard.png")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "jyotishveda_logo.png")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "jyotishveda_logo.png")),
        os.path.abspath("jyotishveda_logo_standard.png"),
        os.path.abspath("jyotishveda_logo.png"),
    ]
    logo_path = next((p for p in logo_candidates if os.path.exists(p)), None)

    brand_style = ParagraphStyle(
        name="HeaderBrandTitle",
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=19,
        textColor=colors.HexColor("#141418"),
        spaceAfter=2,
    )
    title_style = ParagraphStyle(
        name="HeaderSubTitle",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor("#7E5F18"),
        spaceAfter=2,
    )
    desc_style = ParagraphStyle(
        name="HeaderDesc",
        fontName="Helvetica-Oblique",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#6E695F"),
        spaceAfter=0,
    )

    text_flowables = [
        Paragraph("<font color='#141418'><b>ASTRO</b></font><font color='#B58328'><b>JUNCTION</b></font>", brand_style),
        Paragraph(f"<b>{title_text}</b>", title_style),
        Paragraph(f"<i>{subtitle_text}</i>", desc_style),
    ]

    brand_cells = []
    if logo_path:
        brand_cells.append(Image(logo_path, width=15 * mm, height=15 * mm))
    else:
        brand_cells.append(Paragraph("<b>AJ</b>", brand_style))

    brand_cells.append(text_flowables)

    header_table = Table([brand_cells], colWidths=[17 * mm, 167 * mm] if logo_path else [12 * mm, 172 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 3 * mm),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
    ]))
    return header_table


# ============================================================
# MAIN PDF FUNCTION: KUNDLI MILAN & ASHTA KOOTA DOSSIER
# ============================================================

def generate_match_report_pdf(
    report: dict
) -> bytes:

    styles = _styles()

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,

        topMargin=12 * mm,
        bottomMargin=18 * mm,

        leftMargin=13 * mm,
        rightMargin=13 * mm,

        title="AstroJunction Kundli Milan Report",
        author="AstroJunction",
    )

    story = []

    # ========================================================
    # JSON
    # ========================================================

    report_json = _get_report_json(
        report
    )

    # ========================================================
    # PARTNERS
    # ========================================================

    partner1 = _get_partner(
        report_json,
        report,
        "partner1",
    )

    partner2 = _get_partner(
        report_json,
        report,
        "partner2",
    )

    # ========================================================
    # BRAND HEADER
    # ========================================================

    story.append(
        _build_brand_header(
            "OFFICIAL VEDIC KUNDLI MILAN & ASHTA KOOTA DOSSIER",
            "Comprehensive 36-Point Compatibility Analysis & Astronomical Synthesis",
            styles
        )
    )
    story.append(Spacer(1, 3 * mm))

    # ========================================================
    # PARTNER INFORMATION
    # ========================================================

    story.append(
        Paragraph(
            "Partner Information",
            styles["JVSection"],
        )
    )

    story.append(
        _partner_information_table(
            report_json,
            report,
            partner1,
            partner2,
            styles,
        )
    )

    story.append(
        Spacer(1, 4)
    )

    # ========================================================
    # OVERALL SCORE
    # ========================================================

    total, max_points, percentage = (
        _get_overall_score(
            report_json,
            report,
        )
    )

    story.append(
        Paragraph(
            "Overall Compatibility Score",
            styles["JVSection"],
        )
    )

    score_table = Table(
        [
            [
                Paragraph(
                    _number(total),
                    styles["JVScore"],
                ),

                Paragraph(
                    _number(max_points),
                    styles["JVScore"],
                ),

                Paragraph(
                    f"{float(percentage):.2f}%",
                    styles["JVScore"],
                ),
            ],

            [
                "Total Points (Gunas)",
                "Maximum Points",
                "Compatibility Index",
            ],
        ],

        colWidths=[
            61 * mm,
            62 * mm,
            61 * mm,
        ],
    )

    score_table.setStyle(TableStyle([

        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#FFFDF7"),
        ),
        (
            "BACKGROUND",
            (0, 1),
            (-1, 1),
            colors.HexColor("#F9F4E8"),
        ),

        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.5,
            GOLD_BORDER,
        ),

        (
            "ALIGN",
            (0, 0),
            (-1, -1),
            "CENTER",
        ),

        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE",
        ),

        (
            "FONTNAME",
            (0, 1),
            (-1, 1),
            "Helvetica-Bold",
        ),

        (
            "TEXTCOLOR",
            (0, 1),
            (-1, 1),
            GOLD_DARK,
        ),

        (
            "FONTSIZE",
            (0, 1),
            (-1, 1),
            8,
        ),

        (
            "TOPPADDING",
            (0, 0),
            (-1, 0),
            8,
        ),

        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, 0),
            8,
        ),

        (
            "TOPPADDING",
            (0, 1),
            (-1, 1),
            4,
        ),

        (
            "BOTTOMPADDING",
            (0, 1),
            (-1, 1),
            4,
        ),
    ]))

    story.append(
        score_table
    )
    story.append(Spacer(1, 4))

    # ========================================================
    # VERDICT
    # ========================================================

    summary = report_json.get(
        "summary"
    )

    if not isinstance(summary, dict):
        summary = {}

    verdict_title = _value(
        report_json,
        "verdictTitle",
        default=None,
    )

    if verdict_title is None:
        verdict_title = _value(
            summary,
            "verdictTitle",
            default=None,
        )

    description = _value(
        report_json,
        "description",
        "verdictDescription",
        default=None,
    )

    if description is None:
        description = _value(
            summary,
            "description",
            "verdictDescription",
            default=None,
        )

    if verdict_title or description:

        story.append(
            Paragraph(
                "Astrological Verdict & Assessment",
                styles["JVSection"],
            )
        )

        verdict_elements = []
        if verdict_title:
            verdict_elements.append(
                Paragraph(
                    f"<font color='#7E5F18' size=9.5><b>Verdict: {_text(verdict_title)}</b></font>",
                    styles["JVBodyBold"],
                )
            )
        if description:
            if verdict_title:
                verdict_elements.append(Spacer(1, 2))
            verdict_elements.append(
                Paragraph(
                    _text(description),
                    styles["JVBody"],
                )
            )

        verdict_card = Table(
            [[verdict_elements]],
            colWidths=[184 * mm]
        )
        verdict_card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFDF7")),
            ("BOX", (0, 0), (-1, -1), 0.8, GOLD_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(verdict_card)
        story.append(Spacer(1, 4))

    # ========================================================
    # ASHTA KOOTA
    # ========================================================

    story.append(
        Paragraph(
            "Ashta Koota Detailed Breakdown",
            styles["JVSection"],
        )
    )

    koota_table = _build_koota_table(
        report_json,
        styles,
    )

    if koota_table:
        story.append(
            koota_table
        )
    else:
        story.append(
            Paragraph(
                "Ashta Koota result is not available.",
                styles["JVBody"],
            )
        )

    # ========================================================
    # CHARTS
    # ========================================================

    charts_exist = isinstance(
        report_json.get("charts"),
        dict,
    )

    if charts_exist:

        story.append(
            PageBreak()
        )

        story.append(
            Paragraph(
                "Vedic Kundli Astronomical Charts",
                styles["JVSection"],
            )
        )

        # ----------------------------------------------------
        # Partner 1 Chart
        # ----------------------------------------------------

        story.extend(
            _build_chart_section(
                report_json,
                "partner1",
                "Partner 1 - Kundli Chart & Planetary Positions",
                styles,
            )
        )

        # ----------------------------------------------------
        # Partner 2 Chart
        # ----------------------------------------------------

        story.append(
            Spacer(1, 8)
        )

        story.extend(
            _build_chart_section(
                report_json,
                "partner2",
                "Partner 2 - Kundli Chart & Planetary Positions",
                styles,
            )
        )

    # ========================================================
    # DISCLAIMER
    # ========================================================

    story.append(
        Spacer(1, 8)
    )

    story.append(
        Paragraph(
            "Disclaimer",
            styles["JVSection"],
        )
    )

    story.append(
        Paragraph(
            "This report reflects traditional Vedic astrological "
            "interpretation and is provided for informational and "
            "cultural purposes. It does not constitute a guaranteed "
            "prediction and is not a substitute for professional "
            "medical, legal, or financial advice. Final decisions "
            "rest with the individuals concerned.",
            styles["JVBody"],
        )
    )

    # ========================================================
    # BUILD PDF
    # ========================================================

    doc.build(
        story,
        onFirstPage=_draw_page_decorations,
        onLaterPages=_draw_page_decorations,
    )

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
def _pdf_text(value, default=""):
    """
    Safely convert a value into text for PDF rendering.
    Handles None, dict, list and normal values.
    """

    if value is None:
        return default

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2
        )

    return str(value)

def generate_ai_synthesis_pdf(row: dict) -> bytes:

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=18 * mm,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        title="AstroJunction AI Compatibility Synthesis",
    )

    styles = _styles()

    title_style = styles["JVTitle"]
    subtitle_style = styles["JVSubtitle"]
    heading_style = styles["JVSection"]
    body_style = styles["JVBody"]

    bullet_style = ParagraphStyle(
        "AIBullet",
        parent=styles["JVBody"],
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=6,
    )

    story = []

    # =========================================================
    # BASIC DATA
    # =========================================================

    partner1_name = (
        row.get("partner1_name")
        or "Partner 1"
    )

    partner2_name = (
        row.get("partner2_name")
        or "Partner 2"
    )

    total_score = (
        row.get("total_score")
        if row.get("total_score") is not None
        else "N/A"
    )

    max_score = (
        row.get("max_score")
        if row.get("max_score") is not None
        else 36
    )

    # =========================================================
    # SYNTHESIS JSON
    # =========================================================

    synthesis_json = row.get("synthesis_json")

    if isinstance(synthesis_json, str):

        synthesis = json.loads(
            synthesis_json
        )

    elif isinstance(synthesis_json, dict):

        synthesis = synthesis_json

    else:

        synthesis = {}

    # =========================================================
    # BRAND HEADER
    # =========================================================

    story.append(
        _build_brand_header(
            "DAIVAJNA RELATIONSHIP SYNTHESIS & ASTROLOGICAL COUNCIL",
            f"Deep Vedic Psychodynamic & Karmic Synthesis for {_pdf_text(partner1_name)} & {_pdf_text(partner2_name)}",
            styles
        )
    )
    story.append(Spacer(1, 3 * mm))

    # =========================================================
    # ASHTA KOOTA SCORE
    # =========================================================

    story.append(
        Paragraph(
            "Ashta Koota Compatibility Score",
            heading_style
        )
    )

    score_table = Table(
        [
            [
                "Total Score",
                "Maximum Score"
            ],
            [
                str(total_score),
                str(max_score)
            ]
        ],
        colWidths=[
            92 * mm,
            92 * mm
        ]
    )

    score_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F9F4E8")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#FFFDF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), GOLD_DARK),
            ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#1A1A1E")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 1), (-1, 1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, GOLD_BORDER),
            ("BOX", (0, 0), (-1, -1), 0.8, GOLD_BORDER),
        ])
    )

    story.append(score_table)

    story.append(Spacer(1, 4))

    # =========================================================
    # MANGLIK DOSHA
    # =========================================================

    story.append(
        Paragraph(
            "Manglik Dosha Analysis",
            heading_style
        )
    )

    manglik = synthesis.get(
        "manglik_dosha",
        {}
    )

    if not isinstance(manglik, dict):
        manglik = {}

    p1_manglik = manglik.get("partner1")
    if not p1_manglik or "unavailable" in str(p1_manglik).lower():
        p1_manglik = row.get("partner1_manglik_status")
    if not p1_manglik or "unavailable" in str(p1_manglik).lower():
        p1_manglik = f"{partner1_name} has no Manglik Dosha"

    p2_manglik = manglik.get("partner2")
    if not p2_manglik or "unavailable" in str(p2_manglik).lower():
        p2_manglik = row.get("partner2_manglik_status")
    if not p2_manglik or "unavailable" in str(p2_manglik).lower():
        p2_manglik = f"{partner2_name} has no Manglik Dosha"

    manglik_present = manglik.get(
        "present",
        False
    )
    if not manglik_present and ("has manglik dosha" in str(p1_manglik).lower() or "has manglik dosha" in str(p2_manglik).lower()):
        manglik_present = True

    manglik_table = Table(
        [
            [
                "Partner",
                "Manglik Status"
            ],
            [
                str(partner1_name),
                str(p1_manglik)
            ],
            [
                str(partner2_name),
                str(p2_manglik)
            ],
            [
                "Dosha Present",
                "Yes" if manglik_present else "No"
            ]
        ],
        colWidths=[
            64 * mm,
            120 * mm
        ]
    )

    manglik_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F9F4E8")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#FFFDF7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), GOLD_DARK),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, GOLD_BORDER),
            ("BOX", (0, 0), (-1, -1), 0.8, GOLD_BORDER),
        ])
    )

    story.append(manglik_table)
    story.append(Spacer(1, 4))

    # =========================================================
    # AI SYNTHESIS SECTIONS
    # =========================================================

    sections = [

        (
            "Overall Compatibility",
            "overall_compatibility"
        ),

        (
            "Guna Milan",
            "guna_milan"
        ),

        (
            "Psychological Affinity",
            "psychological_affinity"
        ),

        (
            "Emotional Resonance",
            "emotional_resonance"
        ),

        (
            "Karmic Bond",
            "karmic_bond"
        ),

        (
            "Physical Harmonization",
            "physical_harmonization"
        ),

        (
            "Nadi Analysis",
            "nadi_analysis"
        ),

        (
            "Bhakoot Analysis",
            "bhakoot_analysis"
        ),

        (
            "Family and Married Life",
            "family_and_married_life"
        ),

        (
            "Wealth and Prosperity",
            "wealth_and_prosperity"
        ),

        (
            "Major Strengths",
            "major_strengths"
        ),

        (
            "Major Challenges",
            "major_challenges"
        ),

        (
            "Conflict Resolution",
            "conflict_resolution"
        ),

        (
            "Vedic Remedies",
            "vedic_remedies"
        ),

        (
            "Final Assessment",
            "final_assessment"
        ),
    ]

    # =========================================================
    # RENDER SECTIONS
    # =========================================================

    for title, key in sections:

        value = synthesis.get(key)

        if value is None:
            continue

        story.append(
            Paragraph(
                _pdf_text(title),
                heading_style
            )
        )

        section_story = []

        # -----------------------------------------------------
        # LIST
        # -----------------------------------------------------

        if isinstance(value, list):

            if not value:

                section_story.append(
                    Paragraph(
                        "No information available.",
                        body_style
                    )
                )

            else:

                for item in value:

                    if isinstance(item, dict):

                        parts = []

                        for k, v in item.items():

                            if isinstance(v, list):

                                v = ", ".join(
                                    str(x)
                                    for x in v
                                )

                            parts.append(
                                f"<b>{_pdf_text(k)}:</b> "
                                f"{_pdf_text(v)}"
                            )

                        text = "<br/>".join(parts)

                    else:

                        text = _pdf_text(item)

                    section_story.append(
                        Paragraph(
                            f"• {text}",
                            bullet_style
                        )
                    )

        # -----------------------------------------------------
        # DICTIONARY
        # -----------------------------------------------------

        elif isinstance(value, dict):

            for k, v in value.items():

                if isinstance(v, list):

                    if v:

                        v = ", ".join(
                            str(x)
                            for x in v
                        )

                    else:

                        v = "None"

                elif isinstance(v, dict):

                    v = json.dumps(
                        v,
                        ensure_ascii=False
                    )

                section_story.append(
                    Paragraph(
                        (
                            f"<b>{_pdf_text(k)}:</b> "
                            f"{_pdf_text(v)}"
                        ),
                        body_style
                    )
                )

        # -----------------------------------------------------
        # STRING / NUMBER
        # -----------------------------------------------------

        else:

            section_story.append(
                Paragraph(
                    _pdf_text(value),
                    body_style
                )
            )

        card_table = Table(
            [[section_story]],
            colWidths=[184 * mm]
        )
        card_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFDF7")),
            ("BOX", (0, 0), (-1, -1), 0.6, GOLD_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(card_table)
        story.append(Spacer(1, 4))

    # =========================================================
    # DISCLAIMER
    # =========================================================

    story.append(
        Spacer(1, 8)
    )

    story.append(
        Paragraph(
            (
                "<b>Disclaimer:</b> "
                "This report is based on the supplied "
                "Vedic astrology data and traditional "
                "Jyotish compatibility framework. "
                "It should not be considered a scientifically "
                "proven guarantee of relationship or marital "
                "outcomes."
            ),
            body_style
        )
    )

    # =========================================================
    # BUILD PDF
    # =========================================================

    doc.build(story, onFirstPage=_draw_page_decorations, onLaterPages=_draw_page_decorations)

    pdf_bytes = buffer.getvalue()

    buffer.close()

    return pdf_bytes






def generate_roadmap_report_pdf(payload: dict) -> bytes:
    """Builds a comprehensive 25-Year Vedic Destiny Roadmap & Life Blueprint PDF."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=18 * mm,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        title="AstroJunction 25-Year Vedic Destiny Roadmap",
    )

    story = []

    def _normalize_tf(tf_str: str) -> str:
        if not tf_str:
            return "0-5 Years"
        clean = str(tf_str).strip().lower().replace("–", "-").replace(" ", "")
        if clean in ("0-5", "0-5years", "0-12months", "1-3years"):
            return "0-5 Years"
        if clean in ("0-10", "0-10years", "3-5years", "5-10years"):
            return "0-10 Years"
        if clean in ("0-15", "0-15years", "10-15years"):
            return "0-15 Years"
        if clean in ("0-20", "0-20years", "15-20years"):
            return "0-20 Years"
        if clean in ("0-25", "0-25years", "20-25years"):
            return "0-25 Years"
        return str(tf_str).strip()

    profile = payload.get("profile") or {}
    selected_horizon = (payload.get("selectedHorizon") or "All Available Guidance").strip()
    norm_selected = _normalize_tf(selected_horizon)
    raw_milestones = payload.get("roadmap") or payload.get("milestones") or []
    include_all = payload.get("includeAll", False)
    is_all_horizons = include_all or "all" in selected_horizon.lower() or "complete" in selected_horizon.lower() or "available" in selected_horizon.lower() or "25-year" in selected_horizon.lower()

    chart_data = payload.get("chartData") or {}
    numerology = payload.get("numerology") or {}

    p_name = profile.get("fullName") or profile.get("name") or "Vedic Seeker"
    p_dob = profile.get("birthDate") or profile.get("dob") or "N/A"
    p_tob = profile.get("birthTime") or profile.get("tob") or ""
    p_place = profile.get("birthPlace") or profile.get("place") or "Global"

    asc_sign = chart_data.get("ascendant", {}).get("signName") or chart_data.get("ascendant", {}).get("signSanskrit") or "Vedic Lagna"
    moon_planet = next((p for p in chart_data.get("planets", []) if str(p.get("id", "")).lower() == "moon" or str(p.get("name", "")).lower() == "moon"), {})
    moon_sign = chart_data.get("moonSign") or moon_planet.get("signName") or "Chandra Rashi"

    dasha_list = chart_data.get("dashas", []) or chart_data.get("dashaPeriods", [])
    current_dasha_obj = next((d for d in dasha_list if d.get("isCurrent")), {})
    if current_dasha_obj and current_dasha_obj.get("planet"):
        active_dasha = f"{current_dasha_obj.get('planet')} Mahadasha"
    elif chart_data.get("currentDasha", {}).get("mahadasha"):
        active_dasha = f"{chart_data['currentDasha']['mahadasha']} Mahadasha"
    else:
        active_dasha = "Jupiter Mahadasha"

    # Default fallback milestones if raw_milestones is empty
    if not raw_milestones:
        dasha_name = active_dasha.replace(" Mahadasha", "")
        raw_milestones = [
            {
                "id": "ms-1",
                "timeframe": "0-5 Years",
                "category": "Career",
                "title": "Strategic Role Transition & Leadership Visibility",
                "guidance": f"Under the active {dasha_name} Mahadasha and {asc_sign} lagna, Jupiter transit over your 10th house stimulates executive authority and strategic visibility.",
                "favorableTransits": f"Auspicious Jupiter transit trines your {asc_sign} Ascendant",
                "remedialAction": "Chant Brihaspati Beej Mantra on Thursdays; donate yellow lentils.",
                "status": "In-Progress"
            },
            {
                "id": "ms-2",
                "timeframe": "0-5 Years",
                "category": "Wealth",
                "title": "Diversified Asset Allocation & Real Estate Review",
                "guidance": "Favorable aspect on 2nd and 11th houses indicates strong liquidity growth. Avoid speculative short-term gambling during Rahu Kaal periods.",
                "favorableTransits": "Venus exalted in 11th house sub-period",
                "remedialAction": "Offer water to rising Sun (Surya Arghya) with red sandalwood.",
                "status": "In-Progress"
            },
            {
                "id": "ms-3",
                "timeframe": "0-5 Years",
                "category": "Relationships",
                "title": "Harmonious Bonding & Family Expansion",
                "guidance": "Benefic aspects on the 5th and 7th houses foster mutual understanding, emotional closeness, and celebrations at home.",
                "favorableTransits": "Jupiter aspecting Venus & 7th Lord",
                "remedialAction": "Light a pure ghee lamp before Radha-Krishna on Fridays.",
                "status": "In-Progress"
            },
            {
                "id": "ms-4",
                "timeframe": "0-5 Years",
                "category": "Health",
                "title": "Immunity Enhancement & Lifestyle Rhythm",
                "guidance": "Align your circadian cycle with Ayurvedic Dinacharya principles. Morning Surya Namaskar preserves radiant vitality and mental clarity.",
                "favorableTransits": "Sun-Mars trine vitality boost in Lagna",
                "remedialAction": "Drink warm water from a copper vessel every morning.",
                "status": "In-Progress"
            },
            {
                "id": "ms-5",
                "timeframe": "0-5 Years",
                "category": "Spirituality",
                "title": "Mantra Sadhana & Daily Spiritual Foundation",
                "guidance": "Establishing regular meditation and Gayatri Japa awakens deep intuition, inner serenity, and karmic clarity.",
                "favorableTransits": "Jupiter-Ketu auspicious 9th house connection",
                "remedialAction": "Chant Gayatri Mantra 108 times at sunrise daily.",
                "status": "In-Progress"
            },
            {
                "id": "ms-6",
                "timeframe": "0-5 Years",
                "category": "Family",
                "title": "Family Lineage Harmony & Domestic Stability",
                "guidance": "Auspicious planetary aspects to the 2nd and 4th houses foster familial mutual respect, ancestral blessings, and peaceful living environment.",
                "favorableTransits": "Moon-Jupiter benefic aspect on 4th house (Sukha Sthana)",
                "remedialAction": "Perform Satyanarayan Puja with family on Purnima days.",
                "status": "In-Progress"
            },
            {
                "id": "ms-7",
                "timeframe": "0-5 Years",
                "category": "Education",
                "title": "Skill Mastery & Higher Knowledge Attainment",
                "guidance": "Mercury and Jupiter transits bless intellectual focus, competitive examination success, and acquisition of valuable vocational certifications.",
                "favorableTransits": "Budhaditya Yoga alignment influencing the 5th house of intellect",
                "remedialAction": "Recite Saraswati Vandana and offer green grass to cows on Wednesdays.",
                "status": "In-Progress"
            },
            {
                "id": "ms-8",
                "timeframe": "0-5 Years",
                "category": "Travel",
                "title": "Favorable Relocation & Sacred Journeys",
                "guidance": "Short and medium-distance travel windows open up for business expansion, professional assignments, and sacred Teertha yatras.",
                "favorableTransits": "3rd and 9th Lord mutual aspect favoring travel safety and gains",
                "remedialAction": "Chant Hanuman Chalisa before commencing journeys.",
                "status": "In-Progress"
            }
        ]

    # Normalize timeframes on all milestones
    normalized_milestones = []
    for m in raw_milestones:
        if isinstance(m, dict):
            m_copy = dict(m)
            m_copy["timeframe"] = _normalize_tf(m.get("timeframe"))
            normalized_milestones.append(m_copy)

    if not is_all_horizons and selected_horizon and selected_horizon != "All Available Guidance":
        milestones = [
            m for m in normalized_milestones 
            if _normalize_tf(m.get("timeframe")) == norm_selected
        ]
        if not milestones:
            milestones = normalized_milestones
    else:
        milestones = normalized_milestones

    nakshatra = moon_planet.get("nakshatra") or "Vedic Nakshatra"
    if moon_planet.get("pada"):
        nakshatra += f" (Pada {moon_planet.get('pada')})"

    mulank_val = f"Mulank {numerology.get('mulank')}" if numerology.get("mulank") else "Mulank -"
    bhagyank_val = f"Bhagyank {numerology.get('bhagyank')}" if numerology.get("bhagyank") else "Bhagyank -"

    if is_all_horizons or "available" in selected_horizon.lower():
        header_title = "VEDIC DESTINY ROADMAP & LIFE BLUEPRINT (ALL AVAILABLE GUIDANCE)"
    else:
        header_title = f"VEDIC DESTINY ROADMAP & LIFE BLUEPRINT ({selected_horizon.upper()})"

    # 1. Header Title & Brand
    story.append(
        _build_brand_header(
            header_title,
            f"Synthesized through Vimshottari Mahadasha/Antardasha cycles & planetary transits ({datetime.utcnow().year} – {datetime.utcnow().year + 25})",
            styles
        )
    )
    story.append(Spacer(1, 3 * mm))

    # 2. Client & Astro Particulars Box
    astro_info_box = [
        [
            Paragraph(
                f"<font size=7.5 color='#7E5F18'><b>CLIENT &amp; NATAL PARTICULARS</b></font><br/>"
                f"<font size=10.5 color='#1A1A1E'><b>{_pdf_text(p_name)}</b></font><br/>"
                f"<font size=7.2 color='#505050'>Born: {_pdf_text(p_dob)}{f' at {_pdf_text(p_tob)}' if p_tob else ''} | {_pdf_text(p_place)}</font><br/>"
                f"<font size=7.2 color='#505050'>Active Dasha: <b>{active_dasha}</b></font>",
                styles["JVBody"]
            ),
            Paragraph(
                f"<font size=7.5 color='#7E5F18'><b>CELESTIAL &amp; NUMEROLOGICAL COORDINATES</b></font><br/>"
                f"<font size=8.5 color='#1A1A1E'>Lagna: <b>{_pdf_text(asc_sign)}</b> | Rashi: <b>{_pdf_text(moon_sign)}</b></font><br/>"
                f"<font size=7.2 color='#505050'>Nakshatra: {_pdf_text(nakshatra)}</font><br/>"
                f"<font size=7.2 color='#505050'>Numerology: <b>{mulank_val}</b> | <b>{bhagyank_val}</b></font>",
                styles["JVBody"]
            )
        ]
    ]
    astro_table = Table(astro_info_box, colWidths=[92 * mm, 92 * mm])
    astro_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, GOLD_LIGHT),
        ("LINEBEFORE", (1, 0), (1, -1), 0.4, GOLD_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(astro_table)
    story.append(Spacer(1, 4 * mm))

    # All milestones received from the Filter API are included in the PDF export
    unlocked_milestones = milestones

    # 3. Overview Arc Banner
    total_ms = len(unlocked_milestones)
    overview_sub = (
        f"Coverage: <b>All Available Horizons &amp; Life Spheres</b> | Total Predictions: <b>{total_ms}</b> | Comprehensive Kundli Synthesis"
        if is_all_horizons else
        f"Active Horizon: <b>{selected_horizon}</b> | Dimension Predictions: <b>{total_ms}</b> | Planetary Transit Synthesis"
    )
    overview_box = [
        [
            Paragraph(
                f"<font size=8 color='#7E5F18'><b>VEDIC DESTINY ROADMAP — AVAILABLE LIFE BLUEPRINT</b></font><br/>"
                f"<font size=7.5 color='#444444'>{overview_sub}</font>",
                styles["JVBody"]
            )
        ]
    ]
    overview_table = Table(overview_box, colWidths=[184 * mm])
    overview_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FAF7F0")),
        ("BOX", (0, 0), (-1, -1), 0.6, GOLD_MAIN),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 4 * mm))

    # 4. Milestone Cards (Only Unlocked Milestones)
    story.append(Paragraph("STRATEGIC MILESTONES &amp; TIMELINE PREDICTIONS", styles["JVSection"]))

    if not unlocked_milestones:
        locked_msg_box = [
            [
                Paragraph(
                    f"<font size=8.5 color='#8C6D23'><b>[{selected_horizon.upper()}] CONSULTATION &amp; GATEWAY ROADMAP ACCESS</b></font><br/>"
                    f"<font size=7.5 color='#555555'>The astrological roadmap milestones for {selected_horizon} require comprehensive chart synthesis. Please unlock this tier in Consultations &amp; Gateway.</font>",
                    styles["JVBody"]
                )
            ]
        ]
        locked_msg_table = Table(locked_msg_box, colWidths=[184 * mm])
        locked_msg_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F9F7F1")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DFC896")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(locked_msg_table)
        story.append(Spacer(1, 4 * mm))
    else:
        for idx, m in enumerate(unlocked_milestones):
            cat = m.get("category", "General")
            title = m.get("title", f"Vedic Destiny Phase {idx + 1}")
            timeframe = m.get("timeframe", selected_horizon)
            guidance = m.get("guidance") or "Comprehensive transit guidance and astrological timing."
            transits = m.get("favorableTransits") or "Favorable planetary aspect and Mahadasha support."
            remedy = m.get("remedialAction") or "Chant Gayatri Mantra & perform planetary seva."

            tf_label = f" &nbsp;•&nbsp; <font size=7.5 color='#966C1E'><b>[{timeframe}]</b></font>" if timeframe else ""
            card_content = [
                [
                    Paragraph(
                        f"<font size=10 color='#1A1A1E'><b>{idx + 1}.  {title}</b></font>{tf_label}<br/><br/>"
                        f"<font size=7 color='#7E5F18'><b>DASHA &amp; LIFE STRATEGY GUIDANCE</b></font><br/>"
                        f"<font size=7.8 color='#2A2A2E'>{guidance}</font><br/><br/>"
                        f"<font size=7 color='#966C1E'><b>ASTROLOGICAL WINDOW &amp; TRANSITS</b></font><br/>"
                        f"<font size=7.8 color='#2A2A2E'>{transits}</font><br/><br/>"
                        f"<font size=7 color='#7E5F18'><b>RECOMMENDED UPAYA / SADHANA</b></font><br/>"
                        f"<font size=7.8 color='#2A2A2E'>{remedy}</font>",
                        styles["JVBody"]
                    )
                ]
            ]
            card_table = Table(card_content, colWidths=[184 * mm])
            card_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCFBF8")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E8DFC8")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, GOLD_MAIN),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]))
            story.append(card_table)
            if idx < len(unlocked_milestones) - 1:
                story.append(Spacer(1, 2.5 * mm))

    # Page Decorations (Watermark, Golden Borders, Footers)
    def _draw_roadmap_decorations(canvas, doc_):
        canvas.saveState()
        img_candidates = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "astrologer_bg.jpg")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public", "astrologer_bg.jpg")),
            os.path.abspath(os.path.join("public", "astrologer_bg.jpg")),
            os.path.abspath("astrologer_bg.jpg"),
        ]
        img_path = next((p for p in img_candidates if os.path.exists(p)), None)
        if img_path:
            try:
                canvas.setFillAlpha(0.08)
                canvas.drawImage(img_path, 0, 0, width=210 * mm, height=297 * mm, preserveAspectRatio=False, mask='auto')
            except Exception:
                pass

        # Outer Decorative Golden Double Border
        canvas.setFillAlpha(1.0)
        canvas.setStrokeColor(GOLD_MAIN)
        canvas.setLineWidth(1.1)
        canvas.rect(8 * mm, 8 * mm, (210 - 16) * mm, (297 - 16) * mm)
        canvas.setLineWidth(0.35)
        canvas.rect(10 * mm, 10 * mm, (210 - 20) * mm, (297 - 20) * mm)

        # Corner Rosettes
        canvas.setFillColor(GOLD_MAIN)
        canvas.circle(10 * mm, 10 * mm, 1.2 * mm, fill=1, stroke=0)
        canvas.circle((210 - 10) * mm, 10 * mm, 1.2 * mm, fill=1, stroke=0)
        canvas.circle(10 * mm, (297 - 10) * mm, 1.2 * mm, fill=1, stroke=0)
        canvas.circle((210 - 10) * mm, (297 - 10) * mm, 1.2 * mm, fill=1, stroke=0)

        # Footer Divider Line
        canvas.setStrokeColor(GOLD_BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(13 * mm, 16 * mm, (210 - 13) * mm, 16 * mm)

        # Footer Details (Only Generation Date and Page Number)
        gen_date = datetime.utcnow().strftime("%d %b %Y")
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(14 * mm, 11.5 * mm, f"Generated: {gen_date}")
        canvas.drawRightString((210 - 14) * mm, 11.5 * mm, f"Page {doc_.page}")

        canvas.restoreState()

    doc.build(story, onFirstPage=_draw_roadmap_decorations, onLaterPages=_draw_roadmap_decorations)
    return buffer.getvalue()
