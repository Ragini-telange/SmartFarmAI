"""
SmartFarm AI – Flask Application
Main entry point; wires RAG pipeline + watsonx.ai Granite LLM + external APIs
"""

import os
import logging
import warnings
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv, find_dotenv

# Load .env FIRST before any other project imports so all os.getenv() calls
# in this file and submodules see the credentials immediately.
load_dotenv(find_dotenv(usecwd=True), override=True)

# ── Project modules ──────────────────────────────────────────────────────────
import json
from agent_instructions import (
    AGENT_NAME, AGENT_TAGLINE, SYSTEM_PROMPT, CROP_RECOMMENDATION_PROMPT,
    BILINGUAL_MODE, PRIMARY_LANGUAGE, SECONDARY_LANGUAGE,
    PESTICIDE_DISCLAIMER, GENERAL_DISCLAIMER,
    LLM_MAX_NEW_TOKENS, LLM_TEMPERATURE, LLM_TOP_P, LLM_REPETITION_PENALTY,
    MAX_CHAT_HISTORY, ENABLE_SAFETY_DISCLAIMERS,
    ENABLE_WEATHER, ENABLE_MANDI_PRICES, ENABLE_CROP_RECOMMENDATION,
    GREETING_PHRASES, TOP_K_RETRIEVAL,
)
from rag_pipeline import index_knowledge_base, retrieve_context, get_kb_status

# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Flask app init ──────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "smartfarm-dev-secret-key")
CORS(app)

# ─── IBM watsonx.ai init ─────────────────────────────────────────────────────
WATSONX_API_KEY    = os.getenv("WATSONX_API_KEY", "")
WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")
WATSONX_URL        = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
GRANITE_LLM_MODEL  = os.getenv("GRANITE_LLM_MODEL", "ibm/granite-4-h-small")

_llm = None
_llm_lock = threading.Lock()

KEYWORDS_PESTICIDE = [
    "pesticide", "spray", "insecticide", "fungicide", "chemical", "dose",
    "कीटनाशक", "दवाई", "स्प्रे", "fungal", "weed", "herbicide",
]


def _get_llm():
    """Lazy-init IBM watsonx.ai LLM (thread-safe singleton)."""
    global _llm
    if _llm is not None:
        return _llm
    with _llm_lock:
        if _llm is not None:
            return _llm
        placeholders = ("your_ibm_cloud_api_key_here", "", None)
        if WATSONX_API_KEY in placeholders or WATSONX_PROJECT_ID in placeholders:
            logger.warning(
                "watsonx.ai credentials not set – LLM calls will return mock responses. "
                "KEY_SET=%s  PID_SET=%s  URL=%s",
                bool(WATSONX_API_KEY), bool(WATSONX_PROJECT_ID), WATSONX_URL,
            )
            return None
        try:
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference
            from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams

            logger.info("Connecting to watsonx.ai: url=%s model=%s", WATSONX_URL, GRANITE_LLM_MODEL)
            creds = Credentials(url=WATSONX_URL, api_key=WATSONX_API_KEY)
            params = {
                GenParams.MAX_NEW_TOKENS: LLM_MAX_NEW_TOKENS,
                GenParams.TEMPERATURE: LLM_TEMPERATURE,
                GenParams.TOP_P: LLM_TOP_P,
                GenParams.REPETITION_PENALTY: LLM_REPETITION_PENALTY,
            }
            _llm = ModelInference(
                model_id=GRANITE_LLM_MODEL,
                credentials=creds,
                project_id=WATSONX_PROJECT_ID,
                params=params,
            )
            logger.info("IBM watsonx.ai LLM initialized OK: %s", GRANITE_LLM_MODEL)
        except ImportError:
            logger.error("ibm-watsonx-ai package not installed. Run: pip install ibm-watsonx-ai")
            _llm = None
        except Exception as e:
            logger.error("Failed to init watsonx.ai LLM – FULL ERROR: %s", e, exc_info=True)
            _llm = None
    return _llm


def _generate_with_llm(prompt: str) -> str:
    """Call model via chat API; fall back to mock if credentials are missing."""
    llm = _get_llm()
    if llm is None:
        return _mock_llm_response(prompt)
    try:
        # Use the modern chat completions endpoint (avoids deprecation warning)
        messages = [{"role": "user", "content": prompt}]
        response = llm.chat(messages=messages)
        # Extract text from chat response structure
        choices = response.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
        return str(response).strip()
    except Exception as e:
        logger.error("LLM generation error: %s", e)
        return f"I encountered an error while processing your query. Please try again. (Detail: {str(e)[:100]})"


def _mock_llm_response(prompt: str) -> str:
    """Helpful fallback when IBM credentials are not yet configured."""
    return (
        "🌾 **SmartFarm AI Demo Mode**\n\n"
        "Your IBM watsonx.ai credentials are not yet configured. "
        "Please copy `.env.example` → `.env` and fill in your IBM Cloud API key, "
        "Project ID, and watsonx URL.\n\n"
        "Once configured, I will answer your farming questions using the IBM Granite model "
        "backed by the local knowledge base.\n\n"
        "_Current KB status:_ " + str(get_kb_status().get("chunk_count", 0)) + " chunks indexed."
    )


def _detect_language(text: str) -> str:
    """Simple heuristic: check for Devanagari script → Hindi/Marathi."""
    devanagari_count = sum(1 for ch in text if '\u0900' <= ch <= '\u097F')
    if devanagari_count > 3:
        return "hindi"
    return "english"


def _format_chat_history(history: list) -> str:
    lines = []
    for turn in history[-MAX_CHAT_HISTORY:]:
        lines.append(f"Farmer: {turn.get('user', '')}")
        lines.append(f"KisanAI: {turn.get('assistant', '')}")
    return "\n".join(lines)


def _needs_pesticide_disclaimer(text: str) -> bool:
    if not ENABLE_SAFETY_DISCLAIMERS:
        return False
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS_PESTICIDE)


# ─── Background indexing on startup ──────────────────────────────────────────
def _index_kb_background():
    logger.info("Starting background knowledge-base indexing…")
    try:
        count = index_knowledge_base()
        logger.info("KB indexing complete: %d chunks.", count)
    except Exception as e:
        logger.error("KB indexing failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template(
        "index.html",
        agent_name=AGENT_NAME,
        agent_tagline=AGENT_TAGLINE,
        greeting=GREETING_PHRASES.get(PRIMARY_LANGUAGE, GREETING_PHRASES["english"]),
    )


# ── Health check ──────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "agent": AGENT_NAME,
        "llm_model": GRANITE_LLM_MODEL,
        "llm_ready": _llm is not None or (WATSONX_API_KEY and WATSONX_API_KEY != "your_ibm_cloud_api_key_here"),
        "kb": get_kb_status(),
        "timestamp": datetime.now().isoformat(),
    })


# ── Chat endpoint ─────────────────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True) or {}
    query = (body.get("message") or "").strip()
    chat_history = body.get("history", [])   # list of {user, assistant} dicts
    profile = body.get("profile")
    simple_mode = body.get("simple_mode", False)

    if not query:
        return jsonify({"error": "Empty message."}), 400
    if len(query) > 2000:
        return jsonify({"error": "Message too long (max 2000 chars)."}), 400

    # Detect language
    lang = _detect_language(query)
    lang_label = "Hindi" if lang == "hindi" else "English"
    if BILINGUAL_MODE and lang == "english":
        lang_label = "English with a brief Hindi summary"

    # Retrieve relevant KB context
    context_str, sources = retrieve_context(query, top_k=TOP_K_RETRIEVAL)

    # Inject farmer profile details into context if present
    if profile and isinstance(profile, dict):
        loc = profile.get("location") or "Unknown"
        soil = profile.get("soil_type") or "Unknown"
        size = profile.get("farm_size") or "Unknown"
        profile_context = f"\n\nFarmer Profile Context:\n- Farm Location/State: {loc}\n- Soil Type: {soil}\n- Land/Farm Size: {size}"
        context_str += profile_context

    # Build prompt
    history_str = _format_chat_history(chat_history)
    
    prompt_template = SYSTEM_PROMPT
    if simple_mode:
        parts = prompt_template.rsplit("Helpful, accurate answer", 1)
        if len(parts) == 2:
            prompt_template = parts[0] + "CRITICAL: Please provide your response in extremely simple, plain language suitable for a farmer with low literacy. Avoid technical jargon, complex terms, or scientific names. Explain simply. " + "\n\nHelpful, accurate answer" + parts[1]

    prompt = prompt_template.format(
        context=context_str,
        chat_history=history_str or "No prior conversation.",
        query=query,
        language=lang_label,
    )

    # Generate answer
    answer = _generate_with_llm(prompt)

    # Append disclaimer if pesticide-related
    if _needs_pesticide_disclaimer(query + " " + answer):
        answer += f"\n\n{PESTICIDE_DISCLAIMER}"
    else:
        answer += f"\n\n{GENERAL_DISCLAIMER}"

    return jsonify({
        "answer": answer,
        "sources": sources,
        "language_detected": lang,
        "kb_chunks_used": len(sources),
    })


# ── Crop recommendation endpoint ──────────────────────────────────────────────
@app.route("/api/crop-recommendation", methods=["POST"])
def crop_recommendation():
    if not ENABLE_CROP_RECOMMENDATION:
        return jsonify({"error": "Crop recommendation is disabled."}), 403

    body = request.get_json(silent=True) or {}
    season    = body.get("season", "Kharif")
    soil_type = body.get("soil_type", "Loam")
    location  = body.get("location", "Maharashtra")
    water     = body.get("water", "Irrigated")
    farm_size = body.get("farm_size", "2 acres")
    simple_mode = body.get("simple_mode", False)

    query = f"Best crop for {season} season, {soil_type} soil, {location}, {water} conditions"
    context_str, sources = retrieve_context(query, top_k=5)

    lang = body.get("language", PRIMARY_LANGUAGE)
    lang_label = "Hindi" if lang == "hindi" else "English"

    prompt_template = CROP_RECOMMENDATION_PROMPT
    if simple_mode:
        prompt_template += "\n\nCRITICAL: Answer using extremely simple, non-technical words. Avoid scientific names or jargon."

    prompt = prompt_template.format(
        season=season,
        soil_type=soil_type,
        location=location,
        water=water,
        farm_size=farm_size,
        context=context_str,
        language=lang_label,
    )

    answer = _generate_with_llm(prompt)
    answer += f"\n\n{GENERAL_DISCLAIMER}"

    return jsonify({
        "recommendation": answer,
        "inputs": {"season": season, "soil_type": soil_type, "location": location,
                   "water": water, "farm_size": farm_size},
        "sources": sources,
    })


# ── Pest & disease help endpoint ──────────────────────────────────────────────
@app.route("/api/pest-help", methods=["POST"])
def pest_help():
    body = request.get_json(silent=True) or {}
    crop     = (body.get("crop") or "").strip()
    symptoms = (body.get("symptoms") or "").strip()
    simple_mode = body.get("simple_mode", False)

    if not crop and not symptoms:
        return jsonify({"error": "Provide crop name and/or symptoms."}), 400

    query = f"Pest disease problem in {crop}: {symptoms}"
    context_str, sources = retrieve_context(query, top_k=5)

    lang = _detect_language(symptoms + crop)
    lang_label = "Hindi" if lang == "hindi" else "English"

    simple_instruction = ""
    if simple_mode:
        simple_instruction = "Answer in extremely simple, plain language. Avoid scientific names or technical jargon. "

    prompt = (
        f"You are {AGENT_NAME}, an expert Indian agricultural advisor.\n\n"
        f"A farmer reports the following problem:\n"
        f"Crop: {crop or 'Not specified'}\n"
        f"Symptoms: {symptoms or 'Not described'}\n\n"
        f"Knowledge Base:\n{context_str}\n\n"
        f"Please diagnose the likely pest/disease and provide:\n"
        f"1. Probable cause\n"
        f"2. Immediate action (cultural/biological)\n"
        f"3. Chemical option (with dosage and PHI)\n"
        f"4. Prevention for next season\n\n"
        f"{simple_instruction}Answer in {lang_label}:"
    )

    answer = _generate_with_llm(prompt)
    answer += f"\n\n{PESTICIDE_DISCLAIMER}"

    return jsonify({
        "diagnosis": answer,
        "crop": crop,
        "symptoms": symptoms,
        "sources": sources,
    })


# ── Static seasonal weather endpoint ─────────────────────────────────────────
_WEATHER_DATA_PATH = os.path.join(os.path.dirname(__file__), "static", "data", "seasonal_weather.json")
_weather_data: dict = {}

def _load_weather_data():
    global _weather_data
    if not _weather_data:
        try:
            with open(_WEATHER_DATA_PATH, encoding="utf-8") as f:
                _weather_data = json.load(f)
        except Exception as e:
            logger.error("Failed to load seasonal_weather.json: %s", e)
    return _weather_data

@app.route("/api/weather", methods=["POST"])
def weather():
    if not ENABLE_WEATHER:
        return jsonify({"error": "Weather feature is disabled."}), 403

    body  = request.get_json(silent=True) or {}
    state = body.get("state", "").strip()
    month = body.get("month", datetime.now().strftime("%b")).strip()  # e.g. "Jan"

    data = _load_weather_data()
    states_data = data.get("states", {})

    # Exact match first, then case-insensitive partial match
    matched_state = None
    matched_key   = None
    for key in states_data:
        if key.lower() == state.lower():
            matched_state = states_data[key]
            matched_key   = key
            break
    if not matched_state:
        for key in states_data:
            if state.lower() in key.lower() or key.lower() in state.lower():
                matched_state = states_data[key]
                matched_key   = key
                break

    if not matched_state:
        return jsonify({
            "error": f"No data for state '{state}'.",
            "available_states": list(states_data.keys()),
        }), 404

    month_data = matched_state.get("months", {}).get(month)
    if not month_data:
        # Try first 3 letters match
        for m_key, m_val in matched_state.get("months", {}).items():
            if m_key.lower().startswith(month.lower()[:3]):
                month_data = m_val
                month = m_key
                break

    if not month_data:
        return jsonify({"error": f"No data for month '{month}'."}), 404

    return jsonify({
        "success":       True,
        "state":         matched_key,
        "region":        matched_state.get("region", ""),
        "month":         month,
        "seasons":       matched_state.get("seasons", {}),
        "weather":       month_data,
        "all_months":    matched_state.get("months", {}),
        "disclaimer":    data.get("_meta", {}).get("disclaimer", ""),
    })


@app.route("/api/weather/states", methods=["GET"])
def weather_states():
    """Return list of states available in the static dataset."""
    data = _load_weather_data()
    return jsonify({"states": list(data.get("states", {}).keys())})


# ── Static mandi prices endpoint ──────────────────────────────────────────────
_MANDI_DATA_PATH = os.path.join(os.path.dirname(__file__), "static", "data", "mandi_prices.json")
_mandi_data: dict = {}

def _load_mandi_data():
    global _mandi_data
    if not _mandi_data:
        try:
            with open(_MANDI_DATA_PATH, encoding="utf-8") as f:
                _mandi_data = json.load(f)
        except Exception as e:
            logger.error("Failed to load mandi_prices.json: %s", e)
    return _mandi_data

@app.route("/api/mandi", methods=["POST"])
def mandi():
    if not ENABLE_MANDI_PRICES:
        return jsonify({"error": "Mandi prices feature is disabled."}), 403

    body      = request.get_json(silent=True) or {}
    commodity = body.get("commodity", "").strip()
    state     = body.get("state",     "").strip()
    market    = body.get("market",    "").strip()

    if not commodity:
        return jsonify({"error": "Commodity name is required."}), 400

    data = _load_mandi_data()
    commodities = data.get("commodities", {})

    # Fuzzy match: exact title → partial match
    matched_key  = None
    matched_data = None
    for key in commodities:
        if key.lower() == commodity.lower():
            matched_key  = key
            matched_data = commodities[key]
            break
    if not matched_key:
        for key in commodities:
            if commodity.lower() in key.lower() or key.lower() in commodity.lower():
                matched_key  = key
                matched_data = commodities[key]
                break

    if not matched_data:
        return jsonify({
            "success":   False,
            "message":   f"No data for '{commodity}'. Available: " + ", ".join(commodities.keys()),
            "available": list(commodities.keys()),
        })

    records = matched_data.get("records", [])

    # Filter by state if provided
    if state:
        filtered = [r for r in records if state.lower() in r["state"].lower()]
        if filtered:
            records = filtered

    # Filter by market if provided
    if market:
        filtered = [r for r in records if market.lower() in r["market"].lower()]
        if filtered:
            records = filtered

    # Build response records
    today = datetime.now().strftime("%d/%m/%Y")
    out_records = [
        {
            "state":        r["state"],
            "district":     r["district"],
            "market":       r["market"],
            "commodity":    matched_key,
            "variety":      r.get("variety", "Local"),
            "min_price":    str(r["min"]),
            "max_price":    str(r["max"]),
            "modal_price":  str(r["modal"]),
            "arrival_date": today,
        }
        for r in records
    ]

    modal_prices = [r["modal"] for r in records]
    stats = {
        "avg_modal": round(sum(modal_prices) / len(modal_prices), 2),
        "max_modal": max(modal_prices),
        "min_modal": min(modal_prices),
    } if modal_prices else {}

    return jsonify({
        "success":        True,
        "source":         "indicative",
        "commodity":      matched_key,
        "msp":            matched_data.get("msp"),
        "typical_season": matched_data.get("typical_season", ""),
        "state_filter":   state or "All India",
        "market_filter":  market or "All Markets",
        "record_count":   len(out_records),
        "stats":          stats,
        "records":        out_records,
        "disclaimer":     data.get("_meta", {}).get("disclaimer", ""),
    })


@app.route("/api/mandi/commodities", methods=["GET"])
def mandi_commodities():
    """Return list of available commodities."""
    data = _load_mandi_data()
    return jsonify({"commodities": list(data.get("commodities", {}).keys())})


# ── KB re-index trigger (admin) ───────────────────────────────────────────────
@app.route("/api/admin/reindex", methods=["POST"])
def reindex():
    body = request.get_json(silent=True) or {}
    admin_key = body.get("admin_key", "")
    expected  = os.getenv("FLASK_SECRET_KEY", "")
    if admin_key != expected or not expected:
        return jsonify({"error": "Unauthorized."}), 401

    def _do_reindex():
        index_knowledge_base(force_reindex=True)

    t = threading.Thread(target=_do_reindex, daemon=True)
    t.start()
    return jsonify({"message": "Re-indexing started in background."})


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════
with app.app_context():
    # Start KB indexing in background (non-blocking)
    t = threading.Thread(target=_index_kb_background, daemon=True)
    t.start()

    # Eagerly try to init LLM (logs warning if not configured)
    _get_llm()


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", 5000)))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting %s on port %d (debug=%s)", AGENT_NAME, port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
