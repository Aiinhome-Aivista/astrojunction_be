"""
GeoIP Language Resolution Service.

Maps visitor geolocation to one of the 5 supported platform languages:
('en', 'hi', 'bn', 'ta', 'fr').

Rules:
1. India (IN):
   - West Bengal (WB) & Tripura (TR) -> 'bn'
   - Tamil Nadu (TN) & Puducherry (PY) -> 'ta'
   - Hindi Belt: Delhi (DL), Uttar Pradesh (UP), Bihar (BR), Madhya Pradesh (MP),
     Rajasthan (RJ), Haryana (HR), Jharkhand (JH), Uttarakhand (UT/UK),
     Himachal Pradesh (HP), Chhattisgarh (CT/CG) -> 'hi'
   - EVERY OTHER Indian state or unknown region -> 'en'
   - If region is missing for an Indian visitor -> 'en' with source 'country-only'
2. Bangladesh (BD) -> 'bn'
3. France (FR) -> 'fr'
4. All other countries or fallback -> 'en'

Cloudflare Security:
- Headers (CF-Connecting-IP, CF-IPCountry, CF-Region, CF-Region-Code) are trusted
  ONLY when the request genuinely originates from verified Cloudflare IP ranges.

Privacy:
- Client IP addresses are never logged, persisted, or returned in responses.
"""

import os
import json
import ipaddress
import importlib
import urllib.request
from typing import Optional, Tuple, Dict, Any

# ==========================================
# 1. CENTRALIZED MAPPING CONFIGURATION
# ==========================================
GEO_LANGUAGE_CONFIG: Dict[str, Any] = {
    # Non-India direct country mappings
    "countries": {
        "BD": "bn",  # Bangladesh -> bn
        "FR": "fr",  # France -> fr
    },
    # Indian state mappings (ISO 3166-2:IN standard codes + common aliases)
    "india_regions": {
        # West Bengal & Tripura -> bn
        "WB": "bn",
        "TR": "bn",
        # Tamil Nadu & Puducherry -> ta
        "TN": "ta",
        "PY": "ta",
        # Hindi Belt states -> hi
        "DL": "hi",  # National Capital Territory of Delhi
        "UP": "hi",  # Uttar Pradesh
        "BR": "hi",  # Bihar
        "MP": "hi",  # Madhya Pradesh
        "RJ": "hi",  # Rajasthan
        "HR": "hi",  # Haryana
        "JH": "hi",  # Jharkhand
        "UT": "hi",  # Uttarakhand (ISO 3166-2:IN)
        "UK": "hi",  # Uttarakhand (common alternative)
        "HP": "hi",  # Himachal Pradesh
        "CT": "hi",  # Chhattisgarh (ISO 3166-2:IN)
        "CG": "hi",  # Chhattisgarh (common alternative)
    },
    # Strictly supported language set
    "allowed_languages": {"en", "hi", "bn", "ta", "fr"},
    "default_language": "en"
}

# ==========================================
# 2. OFFICIAL CLOUDFLARE IP RANGES (CIDR)
# ==========================================
CLOUDFLARE_IPV4_CIDRS = [
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
]

CLOUDFLARE_IPV6_CIDRS = [
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]

_CF_NETWORKS = [
    ipaddress.ip_network(cidr)
    for cidr in (CLOUDFLARE_IPV4_CIDRS + CLOUDFLARE_IPV6_CIDRS)
]

def is_cloudflare_ip(ip_str: Optional[str]) -> bool:
    """Verifies whether an IP address belongs to Cloudflare's published networks."""
    if not ip_str:
        return False
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return any(ip in net for net in _CF_NETWORKS)
    except ValueError:
        return False

# ==========================================
# 3. CORE GEOGRAPHIC LANGUAGE RESOLVER
# ==========================================
def resolve_language_from_location(
    country: Optional[str],
    region: Optional[str]
) -> Tuple[str, str]:
    """
    Resolves language and source from 2-letter ISO country code and region/state code.
    Returns: (lang, source)
    Where lang is guaranteed to be in {'en', 'hi', 'bn', 'ta', 'fr'}.
    """
    c = (country or "").strip().upper()
    r = (region or "").strip().upper()

    if not c:
        return GEO_LANGUAGE_CONFIG["default_language"], "default"

    # Rule 1: India
    if c == "IN":
        if not r:
            # Region missing: do not guess, return 'en' with source 'country-only'
            return "en", "country-only"

        in_lang = GEO_LANGUAGE_CONFIG["india_regions"].get(r)
        if in_lang and in_lang in GEO_LANGUAGE_CONFIG["allowed_languages"]:
            return in_lang, "cf-region" if "cf" in r.lower() else "region"

        # Every other Indian state or unknown region -> 'en'
        return "en", "region-fallback"

    # Rule 2 & 3: Other mapped countries (BD -> bn, FR -> fr)
    c_lang = GEO_LANGUAGE_CONFIG["countries"].get(c)
    if c_lang and c_lang in GEO_LANGUAGE_CONFIG["allowed_languages"]:
        return c_lang, "country"

    # Rule 4: Everything else -> 'en'
    return GEO_LANGUAGE_CONFIG["default_language"], "default"

# ==========================================
# 4. OFFLINE MAXMIND GEOLITE2-CITY FALLBACK & LOCAL DEV RESOLVER
# ==========================================
_LOCAL_DEV_CACHE: Dict[str, Any] = {
    "country": os.getenv("DEV_DEFAULT_COUNTRY", "IN"),
    "region": os.getenv("DEV_DEFAULT_REGION", "WB"),
    "checked": True,
}

def get_local_dev_location() -> Tuple[Optional[str], Optional[str]]:
    """
    In local development (when remote_ip is 127.0.0.1 / localhost),
    resolves the local developer's location from environment configuration.
    """
    country = os.getenv("DEV_DEFAULT_COUNTRY", _LOCAL_DEV_CACHE.get("country", "IN"))
    region = os.getenv("DEV_DEFAULT_REGION", _LOCAL_DEV_CACHE.get("region", "WB"))
    return country, region

def lookup_offline_city_db(ip_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Queries local GeoLite2-City.mmdb if installed and available on disk.
    Returns: (country_iso, region_iso) or (None, None)
    """
    if not ip_str:
        return None, None

    # Common search paths for offline GeoLite2-City.mmdb
    search_paths = [
        os.getenv("GEOLITE2_CITY_PATH"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "geoip", "GeoLite2-City.mmdb"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "GeoLite2-City.mmdb"),
    ]

    db_path = next((p for p in search_paths if p and os.path.isfile(p)), None)
    if not db_path:
        return None, None

    try:
        maxminddb = importlib.import_module("maxminddb")
        with maxminddb.open_database(db_path) as reader:
            record = reader.get(ip_str.strip())
            if not record or not isinstance(record, dict):
                return None, None

            country_code = record.get("country", {}).get("iso_code")
            subdivisions = record.get("subdivisions", [])
            region_code = subdivisions[0].get("iso_code") if subdivisions and isinstance(subdivisions, list) else None
            return country_code, region_code
    except Exception:
        return None, None

# ==========================================
# 5. REQUEST HANDLER & DETECTION FLOW
# ==========================================
def detect_geo_language_from_request(req) -> Dict[str, Any]:
    """
    Detects language from Flask request:
    1. Checks if request comes from Cloudflare (validates remote_addr against Cloudflare CIDRs).
       - If verified: trusts CF-IPCountry and CF-Region / CF-Region-Code.
    2. If not Cloudflare or CF headers absent:
       - Uses offline GeoLite2-City database fallback using client IP.
       - In local dev (localhost/loopback): detects machine public IP location or dev overrides.
    3. Guarantees safe fallback to {'lang': 'en', 'source': 'default'} on any error.
    4. NO client IP is ever returned or logged.
    """
    try:
        remote_ip = getattr(req, "remote_addr", "") or ""
        is_loopback = remote_ip in ("127.0.0.1", "::1", "localhost", "")
        req_headers = getattr(req, "headers", None) or {}
        req_args = getattr(req, "args", None) or {}

        # Check for Cloudflare origin verification
        # Allow testing override if explicitly set in environment
        allow_dev = os.getenv("ALLOW_DEV_CF_HEADERS", "false").lower() in ("true", "1")

        # Check Cloudflare origin: direct connection OR via trusted local reverse proxy (Nginx)
        cf_check_ip = remote_ip
        if is_loopback:
            # When behind local reverse proxy, verify upstream IP passed in X-Real-IP or X-Forwarded-For
            real_ip = req_headers.get("X-Real-IP")
            if real_ip and is_cloudflare_ip(real_ip):
                cf_check_ip = real_ip
            elif req_headers.get("X-Forwarded-For"):
                hops = [h.strip() for h in req_headers.get("X-Forwarded-For").split(",")]
                for hop in reversed(hops):
                    if is_cloudflare_ip(hop):
                        cf_check_ip = hop
                        break

        is_cf = is_cloudflare_ip(cf_check_ip) or (allow_dev and (is_loopback or getattr(req, "is_test", False)))

        country: Optional[str] = None
        region: Optional[str] = None
        source_prefix = "cf" if is_cf else "offline"

        if is_cf:
            # Read Cloudflare location headers
            country = req_headers.get("CF-IPCountry")
            region = req_headers.get("CF-Region-Code") or req_headers.get("CF-Region")

        # Allow query/header override in local dev/testing
        if not country and is_loopback:
            dev_country = req_args.get("dev_country") or req_headers.get("X-Dev-Country")
            dev_region = req_args.get("dev_region") or req_headers.get("X-Dev-Region")
            if dev_country or dev_region:
                country = (dev_country or "IN").strip().upper()
                region = (dev_region or "").strip().upper()
                source_prefix = "dev"

        # If Cloudflare didn't provide country or request was not from Cloudflare, attempt offline DB
        if not country:
            # Client IP: from CF-Connecting-IP only if CF is verified, else remote_addr
            client_ip = req_headers.get("CF-Connecting-IP") if is_cf else remote_ip
            if not client_ip or client_ip in ("127.0.0.1", "::1"):
                # In development/local proxy, check X-Forwarded-For if remote_addr is loopback
                if is_loopback:
                    xff = req_headers.get("X-Forwarded-For")
                    if xff:
                        client_ip = xff.split(",")[0].strip()

            country, region = lookup_offline_city_db(client_ip)
            source_prefix = "offline"

        # If still not found and running locally on loopback/localhost dev, resolve from local dev config
        host_header = (req_headers.get("Host") or "").lower()
        is_local_host = any(h in host_header for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        if not country and is_loopback and is_local_host:
            country = os.getenv("DEV_DEFAULT_COUNTRY", "IN")
            region = os.getenv("DEV_DEFAULT_REGION", "WB")
            source_prefix = "dev-ip"

        if not country:
            return {
                "lang": GEO_LANGUAGE_CONFIG["default_language"],
                "source": "default",
                "country": None,
                "region": None
            }

        lang, source = resolve_language_from_location(country, region)
        final_source = f"{source_prefix}-{source}" if source not in ("default", "country-only") else source

        return {
            "lang": lang,
            "source": final_source,
            "country": country.upper() if country else None,
            "region": region.upper() if region else None
        }
    except Exception:
        return {
            "lang": GEO_LANGUAGE_CONFIG["default_language"],
            "source": "default",
            "country": None,
            "region": None
        }
