from flask import request, jsonify, make_response
from services.geo_service import detect_geo_language_from_request

def resolve_geo_language():
    """
    GET /geo/language and /api/geo/language
    
    Detects recommended interface language for first-time visitors based on IP location.
    
    Security & Privacy:
    - Never stores, logs, or returns the visitor's IP address.
    - Cloudflare headers are only honored if incoming request is from verified Cloudflare IP ranges.
    - Disables all client/CDN caching with 'Cache-Control: private, no-store'.
    - Safe fallback to {'lang': 'en', 'source': 'default'} on any error or timeout.
    """
    try:
        data = detect_geo_language_from_request(request)
        response = make_response(jsonify({
            "status": "success",
            **data
        }), 200)
    except Exception:
        response = make_response(jsonify({
            "status": "success",
            "lang": "en",
            "source": "default",
            "country": None,
            "region": None
        }), 200)

    # Explicit privacy & dynamic detection headers (must never be cached by CDN or browser)
    response.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Vary"] = "CF-IPCountry, CF-Region-Code, CF-Region"

    return response
