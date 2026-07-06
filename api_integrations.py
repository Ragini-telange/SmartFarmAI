"""
SmartFarm AI – External API Integrations
Handles: OpenWeatherMap (current + 5-day forecast), data.gov.in Agmarknet (mandi prices)
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional
import requests
from dotenv import load_dotenv, find_dotenv

# load_dotenv called here so this module works when imported standalone too
load_dotenv(find_dotenv(usecwd=True), override=True)
logger = logging.getLogger(__name__)

OPENWEATHER_KEY = os.getenv("OPENWEATHER_API_KEY", "")
DATAGOVIN_KEY   = os.getenv("DATAGOVIN_API_KEY", "")

OWM_BASE           = "https://api.openweathermap.org/data/2.5"
# Primary: data.gov.in Agmarknet daily arrivals & prices dataset
AGMARKNET_BASE     = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
# Secondary resource ID (sometimes more up-to-date on data.gov.in)
AGMARKNET_BASE_ALT = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"


# ═══════════════════════════════════════════════════════════════════════════════
# WEATHER  –  OpenWeatherMap
# ═══════════════════════════════════════════════════════════════════════════════

def _owm_icon_url(icon_code: str) -> str:
    return f"https://openweathermap.org/img/wn/{icon_code}@2x.png"


def get_current_weather(city: str = "", lat: float = None, lon: float = None) -> dict:
    """
    Fetch current weather from OpenWeatherMap.
    Pass either city name OR lat/lon coordinates.
    """
    if not OPENWEATHER_KEY:
        return {"error": "OpenWeatherMap API key not configured. Please set OPENWEATHER_API_KEY in .env"}

    params = {
        "appid": OPENWEATHER_KEY,
        "units": "metric",
    }
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    elif city:
        params["q"] = city + ",IN"   # default to India for farming context
    else:
        return {"error": "Provide either city name or lat/lon coordinates."}

    try:
        resp = requests.get(f"{OWM_BASE}/weather", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return {
            "success": True,
            "city": data.get("name", city),
            "country": data.get("sys", {}).get("country", "IN"),
            "temperature": round(data["main"]["temp"], 1),
            "feels_like": round(data["main"]["feels_like"], 1),
            "humidity": data["main"]["humidity"],
            "pressure": data["main"]["pressure"],
            "description": data["weather"][0]["description"].title(),
            "icon": _owm_icon_url(data["weather"][0]["icon"]),
            "wind_speed": round(data.get("wind", {}).get("speed", 0) * 3.6, 1),  # m/s → km/h
            "wind_direction": data.get("wind", {}).get("deg", 0),
            "visibility": round(data.get("visibility", 0) / 1000, 1),  # m → km
            "cloudiness": data.get("clouds", {}).get("all", 0),
            "sunrise": datetime.fromtimestamp(data["sys"]["sunrise"], tz=timezone.utc).strftime("%H:%M UTC"),
            "sunset": datetime.fromtimestamp(data["sys"]["sunset"], tz=timezone.utc).strftime("%H:%M UTC"),
            "timestamp": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "farming_advice": _weather_farming_advice(data),
        }
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return {"error": "Invalid OpenWeatherMap API key."}
        if e.response.status_code == 404:
            return {"error": f"City '{city}' not found. Try a nearby larger city."}
        return {"error": f"Weather API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch weather: {str(e)}"}


def get_weather_forecast(city: str = "", lat: float = None, lon: float = None) -> dict:
    """Fetch 5-day / 3-hour forecast from OpenWeatherMap and aggregate daily."""
    if not OPENWEATHER_KEY:
        return {"error": "OpenWeatherMap API key not configured."}

    params = {"appid": OPENWEATHER_KEY, "units": "metric", "cnt": 40}
    if lat is not None and lon is not None:
        params["lat"] = lat
        params["lon"] = lon
    elif city:
        params["q"] = city + ",IN"
    else:
        return {"error": "Provide either city name or lat/lon coordinates."}

    try:
        resp = requests.get(f"{OWM_BASE}/forecast", params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # Aggregate 3-hour slots into daily summaries
        days: dict = {}
        for item in data["list"]:
            date_str = datetime.fromtimestamp(item["dt"]).strftime("%a, %d %b")
            if date_str not in days:
                days[date_str] = {
                    "date": date_str,
                    "temps": [],
                    "humidity": [],
                    "descriptions": [],
                    "icons": [],
                    "pop": [],        # probability of precipitation
                    "wind": [],
                }
            d = days[date_str]
            d["temps"].append(item["main"]["temp"])
            d["humidity"].append(item["main"]["humidity"])
            d["descriptions"].append(item["weather"][0]["description"].title())
            d["icons"].append(item["weather"][0]["icon"])
            d["pop"].append(item.get("pop", 0) * 100)
            d["wind"].append(item.get("wind", {}).get("speed", 0) * 3.6)

        daily = []
        for date_str, d in list(days.items())[:5]:
            from collections import Counter
            most_common_icon = Counter(d["icons"]).most_common(1)[0][0]
            most_common_desc = Counter(d["descriptions"]).most_common(1)[0][0]
            daily.append({
                "date": date_str,
                "temp_max": round(max(d["temps"]), 1),
                "temp_min": round(min(d["temps"]), 1),
                "humidity_avg": round(sum(d["humidity"]) / len(d["humidity"])),
                "description": most_common_desc,
                "icon": _owm_icon_url(most_common_icon),
                "rain_chance": round(max(d["pop"])),
                "wind_max": round(max(d["wind"]), 1),
            })

        return {
            "success": True,
            "city": data["city"]["name"],
            "country": data["city"]["country"],
            "forecast": daily,
        }
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            return {"error": f"City '{city}' not found."}
        return {"error": f"Forecast API error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch forecast: {str(e)}"}


def _weather_farming_advice(data: dict) -> str:
    """Generate a brief farming tip based on current weather."""
    temp = data["main"]["temp"]
    humidity = data["main"]["humidity"]
    desc = data["weather"][0]["main"].lower()
    wind_speed = data.get("wind", {}).get("speed", 0)

    tips = []
    if "rain" in desc or "drizzle" in desc:
        tips.append("Rain expected – delay pesticide spraying.")
    if temp > 38:
        tips.append("Extreme heat: irrigate fields in early morning or evening.")
    if temp < 10:
        tips.append("Cold stress risk: protect nurseries and frost-sensitive crops.")
    if humidity > 85:
        tips.append("High humidity: risk of fungal diseases – monitor crops closely.")
    if wind_speed > 10:
        tips.append("Strong winds: avoid spraying – drift hazard.")
    if not tips:
        tips.append("Weather is suitable for most field operations.")
    return " | ".join(tips)


# ═══════════════════════════════════════════════════════════════════════════════
# MANDI PRICES  –  data.gov.in Agmarknet API
# ═══════════════════════════════════════════════════════════════════════════════

# Map common crop name variants to API-recognised commodity names
COMMODITY_MAP = {
    "tomato": "Tomato", "tamatar": "Tomato", "टमाटर": "Tomato",
    "onion": "Onion", "pyaaz": "Onion", "pyaz": "Onion", "प्याज": "Onion",
    "potato": "Potato", "aloo": "Potato", "आलू": "Potato",
    "wheat": "Wheat", "gehu": "Wheat", "गेहूँ": "Wheat",
    "rice": "Rice", "chawal": "Rice", "चावल": "Rice",
    "maize": "Maize", "makka": "Maize", "मक्का": "Maize",
    "cotton": "Cotton", "kapas": "Cotton", "कपास": "Cotton",
    "soybean": "Soyabean", "soyabean": "Soyabean",
    "groundnut": "Groundnut",
    "garlic": "Garlic", "lahsun": "Garlic", "लहसुन": "Garlic",
    "ginger": "Ginger", "adrak": "Ginger", "अदरक": "Ginger",
    "chilli": "Chilli", "mirch": "Chilli", "मिर्च": "Chilli",
    "mustard": "Rapeseed/Mustard", "sarson": "Rapeseed/Mustard",
    "tur": "Arhar (Tur)", "arhar": "Arhar (Tur)", "toor": "Arhar (Tur)",
    "moong": "Green Gram (Whole)", "mung": "Green Gram (Whole)",
    "urad": "Black Gram (Urd Beans)(Whole)",
    "gram": "Gram", "chana": "Gram",
    "sugarcane": "Sugarcane", "ganna": "Sugarcane", "गन्ना": "Sugarcane",
}

# State name normalisations
STATE_MAP = {
    "maharashtra": "Maharashtra", "mh": "Maharashtra",
    "punjab": "Punjab", "pb": "Punjab",
    "haryana": "Haryana", "hr": "Haryana",
    "up": "Uttar Pradesh", "uttar pradesh": "Uttar Pradesh",
    "mp": "Madhya Pradesh", "madhya pradesh": "Madhya Pradesh",
    "rajasthan": "Rajasthan", "raj": "Rajasthan",
    "gujarat": "Gujarat", "gj": "Gujarat",
    "karnataka": "Karnataka", "ka": "Karnataka",
    "andhra": "Andhra Pradesh", "ap": "Andhra Pradesh", "andhra pradesh": "Andhra Pradesh",
    "telangana": "Telangana", "ts": "Telangana",
    "tamilnadu": "Tamil Nadu", "tn": "Tamil Nadu", "tamil nadu": "Tamil Nadu",
    "wb": "West Bengal", "west bengal": "West Bengal",
    "bihar": "Bihar", "bh": "Bihar",
    "odisha": "Odisha", "orissa": "Odisha",
    "kerala": "Kerala", "kl": "Kerala",
}


def _normalise_commodity(name: str) -> str:
    return COMMODITY_MAP.get(name.lower().strip(), name.strip().title())


def _normalise_state(name: str) -> str:
    return STATE_MAP.get(name.lower().strip(), name.strip().title())


# ── Indicative price ranges per commodity (₹/quintal) ────────────────────────
# Derived from historical Agmarknet data; used when live API is unreachable.
# Format: commodity_key → list of {state, district, market, variety, min, max, modal}
_INDICATIVE_PRICES = {
    "Onion": [
        {"state": "Maharashtra", "district": "Nashik",    "market": "Lasalgaon",  "variety": "Red",    "min": 800,  "max": 2200, "modal": 1400},
        {"state": "Maharashtra", "district": "Pune",      "market": "Pune",       "variety": "Red",    "min": 900,  "max": 2400, "modal": 1600},
        {"state": "Karnataka",   "district": "Bangalore", "market": "Bangalore",  "variety": "Local",  "min": 700,  "max": 2000, "modal": 1300},
        {"state": "Madhya Pradesh","district":"Indore",   "market": "Indore",     "variety": "White",  "min": 600,  "max": 1800, "modal": 1100},
        {"state": "Rajasthan",   "district": "Alwar",     "market": "Alwar",      "variety": "Red",    "min": 750,  "max": 2100, "modal": 1350},
    ],
    "Tomato": [
        {"state": "Maharashtra", "district": "Nashik",    "market": "Lasalgaon",  "variety": "Local",  "min": 400,  "max": 1800, "modal": 1000},
        {"state": "Karnataka",   "district": "Kolar",     "market": "Kolar",      "variety": "Hybrid", "min": 300,  "max": 1600, "modal": 900},
        {"state": "Andhra Pradesh","district":"Chittoor", "market": "Madanapalle","variety": "Local",  "min": 350,  "max": 1700, "modal": 950},
        {"state": "Madhya Pradesh","district":"Chhindwara","market":"Chhindwara", "variety": "Hybrid", "min": 500,  "max": 2000, "modal": 1200},
        {"state": "Uttar Pradesh","district": "Varanasi", "market": "Varanasi",   "variety": "Local",  "min": 400,  "max": 1500, "modal": 850},
    ],
    "Potato": [
        {"state": "Uttar Pradesh","district": "Agra",     "market": "Agra",       "variety": "Jyoti",  "min": 600,  "max": 1200, "modal": 850},
        {"state": "West Bengal",  "district": "Hooghly",  "market": "Hooghly",    "variety": "Local",  "min": 550,  "max": 1100, "modal": 800},
        {"state": "Punjab",       "district": "Jalandhar","market": "Jalandhar",  "variety": "Kufri",  "min": 700,  "max": 1300, "modal": 950},
        {"state": "Bihar",        "district": "Patna",    "market": "Patna",      "variety": "Local",  "min": 500,  "max": 1000, "modal": 720},
        {"state": "Gujarat",      "district": "Mehsana",  "market": "Mehsana",    "variety": "Hybrid", "min": 650,  "max": 1400, "modal": 1000},
    ],
    "Wheat": [
        {"state": "Punjab",          "district": "Ludhiana",  "market": "Ludhiana",   "variety": "HD-2967", "min": 2100, "max": 2400, "modal": 2275},
        {"state": "Haryana",         "district": "Karnal",    "market": "Karnal",     "variety": "PBW-343", "min": 2150, "max": 2350, "modal": 2275},
        {"state": "Uttar Pradesh",   "district": "Kanpur",    "market": "Kanpur",     "variety": "K-307",   "min": 2100, "max": 2300, "modal": 2200},
        {"state": "Madhya Pradesh",  "district": "Bhopal",    "market": "Bhopal",     "variety": "GW-322",  "min": 2050, "max": 2280, "modal": 2180},
        {"state": "Rajasthan",       "district": "Jaipur",    "market": "Jaipur",     "variety": "Local",   "min": 2000, "max": 2275, "modal": 2150},
    ],
    "Rice": [
        {"state": "West Bengal",     "district": "Burdwan",   "market": "Burdwan",    "variety": "Swarna",  "min": 1900, "max": 2300, "modal": 2183},
        {"state": "Andhra Pradesh",  "district": "Krishna",   "market": "Vijayawada", "variety": "Sona Masuri","min": 2000, "max": 2400, "modal": 2200},
        {"state": "Punjab",          "district": "Amritsar",  "market": "Amritsar",   "variety": "Basmati", "min": 3000, "max": 4500, "modal": 3800},
        {"state": "Tamil Nadu",      "district": "Thanjavur", "market": "Thanjavur",  "variety": "Ponni",   "min": 2200, "max": 2800, "modal": 2500},
        {"state": "Odisha",          "district": "Cuttack",   "market": "Cuttack",    "variety": "Lalat",   "min": 1900, "max": 2250, "modal": 2050},
    ],
    "Cotton": [
        {"state": "Gujarat",         "district": "Rajkot",    "market": "Rajkot",     "variety": "Shankar-6","min": 5800, "max": 7200, "modal": 6620},
        {"state": "Maharashtra",     "district": "Akola",     "market": "Akola",      "variety": "Bt Hybrid","min": 5600, "max": 7000, "modal": 6400},
        {"state": "Telangana",       "district": "Warangal",  "market": "Warangal",   "variety": "Bt",      "min": 5700, "max": 7100, "modal": 6500},
        {"state": "Madhya Pradesh",  "district": "Khandwa",   "market": "Khandwa",    "variety": "Local",   "min": 5500, "max": 6800, "modal": 6200},
    ],
    "Soyabean": [
        {"state": "Madhya Pradesh",  "district": "Indore",    "market": "Indore",     "variety": "Yellow",  "min": 4000, "max": 5000, "modal": 4600},
        {"state": "Maharashtra",     "district": "Latur",     "market": "Latur",      "variety": "Yellow",  "min": 3900, "max": 4900, "modal": 4500},
        {"state": "Rajasthan",       "district": "Kota",      "market": "Kota",       "variety": "Local",   "min": 3800, "max": 4800, "modal": 4400},
    ],
    "Groundnut": [
        {"state": "Gujarat",         "district": "Junagadh",  "market": "Junagadh",   "variety": "Bold",    "min": 5500, "max": 7000, "modal": 6377},
        {"state": "Andhra Pradesh",  "district": "Kurnool",   "market": "Kurnool",    "variety": "Local",   "min": 5200, "max": 6800, "modal": 6000},
        {"state": "Rajasthan",       "district": "Bikaner",   "market": "Bikaner",    "variety": "Local",   "min": 5000, "max": 6500, "modal": 5700},
    ],
    "Garlic": [
        {"state": "Madhya Pradesh",  "district": "Mandsaur",  "market": "Mandsaur",   "variety": "Local",   "min": 1500, "max": 6000, "modal": 3500},
        {"state": "Rajasthan",       "district": "Kota",      "market": "Kota",       "variety": "Desi",    "min": 1200, "max": 5500, "modal": 3200},
        {"state": "Gujarat",         "district": "Gondal",    "market": "Gondal",     "variety": "Local",   "min": 1800, "max": 6500, "modal": 3800},
    ],
    "Chilli": [
        {"state": "Andhra Pradesh",  "district": "Guntur",    "market": "Guntur",     "variety": "Teja",    "min": 8000, "max": 20000,"modal": 13000},
        {"state": "Telangana",       "district": "Khammam",   "market": "Khammam",    "variety": "334",     "min": 7500, "max": 18000,"modal": 12000},
        {"state": "Karnataka",       "district": "Byadagi",   "market": "Byadagi",    "variety": "Byadagi", "min": 10000,"max": 25000,"modal": 16000},
    ],
    "Maize": [
        {"state": "Karnataka",       "district": "Haveri",    "market": "Haveri",     "variety": "Hybrid",  "min": 1800, "max": 2300, "modal": 2090},
        {"state": "Andhra Pradesh",  "district": "Nizamabad", "market": "Nizamabad",  "variety": "Local",   "min": 1750, "max": 2200, "modal": 2000},
        {"state": "Bihar",           "district": "Begusarai", "market": "Begusarai",  "variety": "Hybrid",  "min": 1700, "max": 2150, "modal": 1950},
    ],
    "Gram": [
        {"state": "Madhya Pradesh",  "district": "Sehore",    "market": "Sehore",     "variety": "Desi",    "min": 4800, "max": 5800, "modal": 5440},
        {"state": "Rajasthan",       "district": "Bikaner",   "market": "Bikaner",    "variety": "Desi",    "min": 4600, "max": 5600, "modal": 5200},
        {"state": "Maharashtra",     "district": "Latur",     "market": "Latur",      "variety": "Desi",    "min": 4700, "max": 5700, "modal": 5300},
    ],
    "Arhar (Tur)": [
        {"state": "Maharashtra",     "district": "Latur",     "market": "Latur",      "variety": "Local",   "min": 6000, "max": 8000, "modal": 7000},
        {"state": "Karnataka",       "district": "Gulbarga",  "market": "Gulbarga",   "variety": "Local",   "min": 5800, "max": 7800, "modal": 6800},
        {"state": "Madhya Pradesh",  "district": "Sagar",     "market": "Sagar",      "variety": "Desi",    "min": 6200, "max": 8200, "modal": 7200},
    ],
    "Rapeseed/Mustard": [
        {"state": "Rajasthan",       "district": "Bharatpur", "market": "Bharatpur",  "variety": "Yellow",  "min": 5200, "max": 6200, "modal": 5650},
        {"state": "Haryana",         "district": "Hisar",     "market": "Hisar",      "variety": "Local",   "min": 5100, "max": 6100, "modal": 5600},
        {"state": "Uttar Pradesh",   "district": "Agra",      "market": "Agra",       "variety": "Local",   "min": 5000, "max": 6000, "modal": 5500},
    ],
    "Ginger": [
        {"state": "Kerala",          "district": "Wayanad",   "market": "Kalpetta",   "variety": "Fresh",   "min": 2000, "max": 5000, "modal": 3500},
        {"state": "Karnataka",       "district": "Hassan",    "market": "Hassan",     "variety": "Fresh",   "min": 2200, "max": 5200, "modal": 3700},
    ],
    "Sugarcane": [
        {"state": "Uttar Pradesh",   "district": "Muzaffarnagar","market":"Muzaffarnagar","variety":"Common","min": 340,  "max": 380,  "modal": 355},
        {"state": "Maharashtra",     "district": "Kolhapur",  "market": "Kolhapur",   "variety": "Co-86032","min": 290, "max": 320,  "modal": 305},
    ],
}


def _build_indicative_records(commodity_api: str, state_filter: str, today: str) -> list:
    """
    Return indicative price records from _INDICATIVE_PRICES for the requested
    commodity, optionally filtered by state.
    """
    base_key = commodity_api
    # Try exact match first, then fuzzy title-case lookup
    rows = _INDICATIVE_PRICES.get(base_key)
    if rows is None:
        for k in _INDICATIVE_PRICES:
            if k.lower() in base_key.lower() or base_key.lower() in k.lower():
                rows = _INDICATIVE_PRICES[k]
                break
    if not rows:
        return []

    if state_filter:
        filtered = [r for r in rows if state_filter.lower() in r["state"].lower()]
        if filtered:
            rows = filtered

    return [
        {
            "state":        r["state"],
            "district":     r["district"],
            "market":       r["market"],
            "commodity":    commodity_api,
            "variety":      r["variety"],
            "min_price":    str(r["min"]),
            "max_price":    str(r["max"]),
            "modal_price":  str(r["modal"]),
            "arrival_date": today,
        }
        for r in rows
    ]


def _call_agmarknet(url: str, params: dict, timeout: int) -> Optional[dict]:
    """Make one Agmarknet API call; return parsed JSON or None on any failure."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("records"):
            return data
    except Exception:
        pass
    return None


def _parse_agmarknet_records(data: dict, limit: int) -> list:
    """Normalise raw Agmarknet JSON records into our standard format."""
    records = []
    for r in data["records"][:limit]:
        records.append({
            "state":        r.get("state", ""),
            "district":     r.get("district", ""),
            "market":       r.get("market", ""),
            "commodity":    r.get("commodity", ""),
            "variety":      r.get("variety", ""),
            "min_price":    r.get("min_price", "N/A"),
            "max_price":    r.get("max_price", "N/A"),
            "modal_price":  r.get("modal_price", "N/A"),
            "arrival_date": r.get("arrival_date", ""),
        })
    return records


def _compute_stats(records: list) -> dict:
    modal_prices = [
        float(r["modal_price"]) for r in records
        if r["modal_price"] not in ("N/A", "", None)
    ]
    if not modal_prices:
        return {}
    return {
        "avg_modal": round(sum(modal_prices) / len(modal_prices), 2),
        "max_modal": max(modal_prices),
        "min_modal": min(modal_prices),
    }


def get_mandi_prices(
    commodity: str,
    state: str = "",
    market: str = "",
    limit: int = 15,
) -> dict:
    """
    Fetch mandi (APMC) prices with three-layer fallback:
      1. data.gov.in Agmarknet live API  (requires DATAGOVIN_API_KEY, fast timeout)
      2. Alternate Agmarknet resource ID (same host, sometimes different dataset)
      3. Indicative price data embedded in code (always works, clearly labelled)
    """
    commodity_api = _normalise_commodity(commodity)
    state_api     = _normalise_state(state) if state else ""
    today         = datetime.now().strftime("%d/%m/%Y")

    # ── Layer 1 & 2: live Agmarknet API ──────────────────────────────────────
    if DATAGOVIN_KEY and DATAGOVIN_KEY not in ("your_data_gov_in_api_key_here", ""):
        base_params = {
            "api-key":             DATAGOVIN_KEY,
            "format":              "json",
            "limit":               limit,
            "filters[commodity]":  commodity_api,
        }
        if state_api:
            base_params["filters[state]"] = state_api
        if market:
            base_params["filters[market]"] = market.strip().title()

        # Try primary resource
        data = _call_agmarknet(AGMARKNET_BASE, base_params, timeout=6)
        # Try alternate resource if primary times out or returns no records
        if data is None:
            data = _call_agmarknet(AGMARKNET_BASE_ALT, base_params, timeout=6)

        if data is not None:
            records = _parse_agmarknet_records(data, limit)
            if records:
                return {
                    "success":       True,
                    "source":        "live",
                    "commodity":     commodity_api,
                    "state_filter":  state_api or "All India",
                    "market_filter": market or "All Markets",
                    "record_count":  len(records),
                    "stats":         _compute_stats(records),
                    "records":       records,
                }

        # API key present but API unreachable — fall through to indicative data
        logger.warning(
            "Agmarknet API unreachable or returned no records for '%s'. "
            "Using indicative data. Check DATAGOVIN_API_KEY and network access "
            "to api.data.gov.in.", commodity_api
        )

    # ── Layer 3: indicative / reference price data ────────────────────────────
    records = _build_indicative_records(commodity_api, state_api, today)

    if not records:
        return {
            "success": False,
            "source":  "none",
            "commodity": commodity_api,
            "message": (
                f"No price data available for '{commodity_api}'"
                + (f" in {state_api}" if state_api else "") + ". "
                "Try: Tomato, Onion, Potato, Wheat, Rice, Cotton, Soyabean, "
                "Groundnut, Garlic, Chilli, Maize, Gram, Arhar (Tur), Mustard."
            ),
        }

    return {
        "success":       True,
        "source":        "indicative",
        "commodity":     commodity_api,
        "state_filter":  state_api or "All India",
        "market_filter": market or "All Markets",
        "record_count":  len(records),
        "stats":         _compute_stats(records),
        "records":       records,
        "indicative_note": (
            "Indicative prices based on historical Agmarknet data. "
            "Add DATAGOVIN_API_KEY to .env or check network access to "
            "api.data.gov.in for live daily prices."
        ),
    }
