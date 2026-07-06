# SmartFarm AI 🌾

> **AI-Powered Smart Farming Advisory Agent**  
> Built with Python Flask · IBM watsonx.ai (Granite LLM) · ChromaDB RAG · OpenWeatherMap · Agmarknet

---

## Features

| Panel | What It Does |
|-------|-------------|
| 🤖 **AI Chat** | Natural-language Q&A in English + Hindi, grounded in local knowledge base via RAG |
| 🌤️ **Weather Dashboard** | Current conditions + 5-day forecast with farming advisories (via OpenWeatherMap) |
| 💹 **Mandi Prices** | Daily APMC crop prices by state/market (via data.gov.in Agmarknet) |
| 🌱 **Crop Advisor** | AI-powered sowing recommendations based on soil, season, location, water |
| 🪲 **Pest & Disease Help** | IPM diagnosis and treatment advice from embedded knowledge base |

---

## Architecture

```
SmartFarmAI/
├── app.py                          # Flask application & API routes
├── rag_pipeline.py                 # ChromaDB indexing & retrieval
├── api_integrations.py             # Weather & Mandi price APIs
├── agent_instructions.py           # ← CUSTOMIZE AGENT BEHAVIOUR HERE
├── requirements.txt
├── .env.example                    # Copy to .env and fill credentials
│
├── knowledge_base/                 # Source documents for RAG
│   ├── crop_guides/
│   │   ├── rice_guide.txt
│   │   ├── wheat_guide.txt
│   │   ├── tomato_guide.txt
│   │   ├── cotton_guide.txt
│   │   └── sowing_season_calendar.txt
│   ├── pest_control/
│   │   └── ipm_advisory.txt
│   └── agri_schemes/
│       └── government_schemes.txt
│
├── chromadb_store/                 # Auto-created: persistent vector DB
│
├── templates/
│   └── index.html                  # Main frontend (Jinja2)
└── static/
    ├── css/style.css
    └── js/app.js
```

**RAG Pipeline Flow:**

```
User Question
    ↓
Sentence-Transformer (all-MiniLM-L6-v2) → embed query
    ↓
ChromaDB cosine similarity search → top-4 KB chunks
    ↓
Chunks injected into SYSTEM_PROMPT (agent_instructions.py)
    ↓
IBM Granite-13b-chat-v2 (watsonx.ai) → answer
    ↓
Safety disclaimer appended if pesticide-related
    ↓
Response to farmer
```

---

## Quick Start

### Prerequisites
- Python 3.10 or higher
- An IBM Cloud account with a watsonx.ai project
- OpenWeatherMap API key (free tier works)
- data.gov.in API key (optional; mock data shown without it)

### 1. Clone / set up the project

```bash
cd SmartFarmAI
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` will download the `all-MiniLM-L6-v2` model (~90 MB) on first run.

### 3. Configure credentials

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
WATSONX_API_KEY=your_ibm_cloud_api_key
WATSONX_PROJECT_ID=your_watsonx_project_id
WATSONX_URL=https://us-south.ml.cloud.ibm.com
OPENWEATHER_API_KEY=your_openweathermap_key
DATAGOVIN_API_KEY=your_data_gov_in_key    # optional
FLASK_SECRET_KEY=your_random_secret_key
```

#### Getting API Keys

| Service | How to get |
|---------|-----------|
| **IBM watsonx.ai** | Create account at [cloud.ibm.com](https://cloud.ibm.com) → Create Watson Studio project → Generate API key in IAM |
| **OpenWeatherMap** | Register at [openweathermap.org/api](https://openweathermap.org/api) → Free plan → Copy API key |
| **data.gov.in** | Register at [data.gov.in](https://data.gov.in) → My Account → API key (instant) |

### 4. Run the app

```bash
python app.py
```

Open your browser at **http://localhost:5000**

The knowledge base will be indexed in the background on first startup (takes ~15–30 seconds).

---

## Adding to the Knowledge Base

Drop any `.txt`, `.pdf`, or `.docx` file into a subfolder of `knowledge_base/` and restart the app.

```
knowledge_base/
├── crop_guides/        ← Crop cultivation guides
├── pest_control/       ← IPM advisories
├── agri_schemes/       ← Government scheme documents
└── market_info/        ← Add price/market reports here
```

To **force re-index** without restarting:

```bash
curl -X POST http://localhost:5000/api/admin/reindex \
  -H "Content-Type: application/json" \
  -d '{"admin_key": "your_FLASK_SECRET_KEY"}'
```

---

## Customising the Agent

All agent behaviour is controlled in **`agent_instructions.py`**:

```python
# Change response language
PRIMARY_LANGUAGE = "hindi"          # Respond in Hindi by default
BILINGUAL_MODE   = True             # Append Hindi summary to English answers

# Change farming region / crop focus
FARMING_REGION = "Punjab"
CROP_FOCUS     = ["Wheat", "Rice", "Maize", "Cotton"]

# Change tone
AGENT_TONE       = "simple"         # "formal" | "friendly" | "simple"
SIMPLIFY_LANGUAGE = True            # Use simple farmer-friendly language

# Disable safety disclaimers (not recommended)
ENABLE_SAFETY_DISCLAIMERS = False

# Fine-tune LLM
LLM_TEMPERATURE  = 0.2   # Lower = more factual answers
LLM_MAX_NEW_TOKENS = 1000
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/` | Main web application |
| `GET`  | `/api/health` | Health check + KB status |
| `POST` | `/api/chat` | RAG-powered chat response |
| `POST` | `/api/weather` | Current weather + 5-day forecast |
| `POST` | `/api/mandi` | APMC mandi price lookup |
| `POST` | `/api/crop-recommendation` | AI crop advisor |
| `POST` | `/api/pest-help` | IPM diagnosis |
| `POST` | `/api/admin/reindex` | Re-index knowledge base |

### Example: Chat API

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the MSP for rice in 2024?", "history": []}'
```

### Example: Mandi prices

```bash
curl -X POST http://localhost:5000/api/mandi \
  -H "Content-Type: application/json" \
  -d '{"commodity": "Tomato", "state": "Maharashtra"}'
```

---

## Production Deployment

### Option A: Gunicorn (Linux/macOS)

```bash
gunicorn -w 2 -b 0.0.0.0:5000 --timeout 120 app:app
```

### Option B: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
```

```bash
docker build -t smartfarm-ai .
docker run -p 5000:5000 --env-file .env smartfarm-ai
```

### Option C: IBM Code Engine / Cloud Foundry

```bash
# Install IBM Cloud CLI + Code Engine plugin
ibmcloud ce application create \
  --name smartfarm-ai \
  --image icr.io/your-namespace/smartfarm-ai \
  --port 5000 \
  --min-scale 1
```

### Environment Variables for Production

```env
FLASK_DEBUG=false
FLASK_SECRET_KEY=<strong-random-secret>   # use: python -c "import secrets; print(secrets.token_hex(32))"
CHROMA_PERSIST_DIR=/data/chromadb_store   # mount a persistent volume
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ibm-watsonx-ai package not installed` | Run `pip install ibm-watsonx-ai` |
| Weather shows error | Check `OPENWEATHER_API_KEY` in `.env`; API key takes ~2 min to activate |
| Mandi shows demo data | Set `DATAGOVIN_API_KEY` in `.env` |
| KB shows 0 chunks | Wait 30s for background indexing; check `knowledge_base/` has `.txt` files |
| LLM returns mock response | Verify `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL` in `.env` |
| Hindi text garbled | Ensure UTF-8 terminal; browser font supports Devanagari |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10+, Flask 3.0, Flask-CORS |
| **LLM** | IBM watsonx.ai · Granite-13b-chat-v2 |
| **Embeddings** | Sentence-Transformers (all-MiniLM-L6-v2) |
| **Vector DB** | ChromaDB (persistent, local) |
| **Weather** | OpenWeatherMap API |
| **Market Data** | data.gov.in Agmarknet API |
| **Frontend** | Bootstrap 5.3, Vanilla JS, Bootstrap Icons |
| **Document parsing** | pypdf, python-docx |

---

## License & Disclaimer

This is an advisory tool only. Crop and pesticide recommendations are based on general best practices.  
Always consult your local **Krishi Vigyan Kendra (KVK)** or State Agriculture Officer for field-specific guidance.  
Pesticide use should comply with CIBRC regulations. The developers are not responsible for crop losses.

---

*Built with ❤️ for Indian farmers · Powered by IBM watsonx.ai*
