from flask import request, jsonify
from services.calendar_service import convert_calendar_date, generate_month_calendar, calculate_panjika_details, reverse_convert_bengali, reverse_convert_hindi

def parse_location(data):
    # Check if a language or calendar type is provided
    cal_type = data.get("from_type") or data.get("language") or data.get("calendar_type", "english")
    cal_type = cal_type.lower()
    
    if cal_type == "bengali":
        default_lat, default_lon = 22.5726, 88.3639 # Kolkata, West Bengal
    elif cal_type == "hindi":
        default_lat, default_lon = 25.3176, 82.9739 # Varanasi, UP (Standard for Hindi Panchang)
    else:
        default_lat, default_lon = 28.6139, 77.209 # New Delhi (Standard for Generic English)

    lat = float(data.get("lat", default_lat))
    lon = float(data.get("lon", default_lon))
    return lat, lon

def convert_date():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "Payload is required"}), 400
    
    try:
        from_type = data.get("from_type", "english")
        lat, lon = parse_location(data)
        
        if from_type == "english":
            if "date" not in data: return jsonify({"status": "error", "message": "Date is required (YYYY-MM-DD)"}), 400
            result = convert_calendar_date(data["date"], lat, lon)
        elif from_type == "bengali":
            if not all(k in data for k in ["day", "month", "year"]): return jsonify({"status": "error", "message": "Day, month, and year are required for Bengali conversion"}), 400
            result = reverse_convert_bengali(data["day"], data["month"], data["year"], lat, lon)
        elif from_type == "hindi":
            if not all(k in data for k in ["tithi", "paksha", "month", "year"]): return jsonify({"status": "error", "message": "Tithi, paksha, month, and year are required for Hindi conversion"}), 400
            result = reverse_convert_hindi(data["tithi"], data["paksha"], data["month"], data["year"], lat, lon)
        else:
            return jsonify({"status": "error", "message": "Invalid from_type"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
        
    if "error" in result:
        return jsonify({"status": "error", "message": result["error"]}), 400
        
    return jsonify({"status": "success", "data": result})

def get_panjika_month():
    data = request.json
    if not data or "year" not in data or "month" not in data:
        return jsonify({"status": "error", "message": "Year and month are required"}), 400
    
    try:
        year = int(data["year"])
        month = int(data["month"])
        lat, lon = parse_location(data)
        
        days = generate_month_calendar(year, month, lat, lon)
        return jsonify({"status": "success", "data": {"year": year, "month": month, "lat": lat, "lon": lon, "days": days}})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

def get_full_panjika():
    data = request.json
    if not data or "date" not in data:
        return jsonify({"status": "error", "message": "Date is required (YYYY-MM-DD)"}), 400
    
    from datetime import datetime
    try:
        dt = datetime.strptime(data["date"], "%Y-%m-%d")
        lat, lon = parse_location(data)
        result = calculate_panjika_details(dt, lat, lon)
        return jsonify({"status": "success", "data": result})
    except Exception as e:
         return jsonify({"status": "error", "message": str(e)}), 400
