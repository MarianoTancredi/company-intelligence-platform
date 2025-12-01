# Company Intelligence Platform

A prototype AI-powered workflow that aggregates company data from multiple sources, enriches it with LLM-based analysis, and exposes results through an API and dashboard.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                  │
├─────────────────────────┬───────────────────────────────────────────┤
│   STRUCTURED            │         UNSTRUCTURED                       │
│   Alpha Vantage API     │         NewsAPI.org                        │
│   (Stock prices,        │         (News articles,                    │
│    company overview)    │          headlines, content)               │
└───────────┬─────────────┴──────────────────┬────────────────────────┘
            │                                │
            ▼                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATION LAYER                               │
│                      (FastAPI + AsyncIO)                             │
├─────────────────────────────────────────────────────────────────────┤
│  1. DataIngestionPipeline    - Fetches and validates raw data       │
│  2. DataCleaningPipeline     - Normalizes and structures data       │
│  3. LLMEnrichmentPipeline    - Sentiment + insight extraction       │
│  4. StoragePipeline          - Persists to SQLite                   │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       STORAGE LAYER                                  │
│                         (SQLite)                                     │
├─────────────────────────────────────────────────────────────────────┤
│  companies        │  stock_data       │  news_articles              │
│  - symbol         │  - symbol         │  - company_symbol           │
│  - name           │  - date           │  - title                    │
│  - sector         │  - open/close     │  - content                  │
│  - description    │  - volume         │  - sentiment_score          │
│  - market_cap     │  - high/low       │  - key_insights (JSON)      │
│  - enriched_at    │                   │  - llm_classification       │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      INTERFACE LAYER                                 │
├────────────────────────┬────────────────────────────────────────────┤
│      REST API          │           Web Dashboard                     │
│  GET /api/companies    │     Interactive charts                      │
│  GET /api/company/{s}  │     Sentiment trends                        │
│  POST /api/ingest      │     News feed with insights                 │
│  GET /api/insights     │     Company cards                           │
└────────────────────────┴────────────────────────────────────────────┘
```

## Design Decisions

### 1. Data Sources Choice

**Structured: Alpha Vantage API**
- Free tier available for prototyping
- Provides stock prices, company fundamentals, market cap
- Well-documented JSON responses
- Rate-limited (5 calls/min on free tier) - handled with caching

**Unstructured: NewsAPI.org**  
- Free tier with 100 requests/day
- Returns news articles with full text
- Easy to query by company name/ticker
- Perfect for sentiment analysis use case

### 2. Why FastAPI for Orchestration?

- **Async-native**: Perfect for I/O-bound operations (API calls, LLM requests)
- **Type safety**: Pydantic models ensure data integrity
- **Auto-documentation**: OpenAPI/Swagger built-in
- **Production-ready**: Easy to scale with Gunicorn/Uvicorn workers
- **Familiar to Python data engineers**: Lower barrier than n8n/Airflow for small workflows

### 3. LLM Integration Strategy

Using **Claude via Anthropic API** for:
- **Sentiment Analysis**: Score articles -1.0 to 1.0 with reasoning
- **Key Insight Extraction**: Structured JSON output with market impact, risks, opportunities
- **Classification**: Categorize news (earnings, product, legal, market, executive)

**Why Claude over embeddings-only approach?**
- Richer semantic understanding vs simple vector similarity
- Structured output with explanations (auditable)
- Can handle nuanced financial language

### 4. Database Choice: SQLite

For a prototype, SQLite is ideal:
- Zero configuration
- Single file, easy to share/demo
- Good enough for thousands of records
- Easy migration path to PostgreSQL

### 5. Scaling Considerations

**Current Architecture (Prototype)**:
- Single process, synchronous pipeline
- In-memory caching for API responses
- SQLite for persistence

**Production Scale-Up Path**:

```
┌──────────────────────────────────────────────────────────────────┐
│                    PRODUCTION ARCHITECTURE                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │   Celery    │    │   Celery    │    │   Celery    │          │
│  │  Worker 1   │    │  Worker 2   │    │  Worker N   │          │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘          │
│         │                  │                  │                  │
│         └─────────────────┬┴──────────────────┘                  │
│                           │                                       │
│                    ┌──────▼──────┐                                │
│                    │   Redis     │                                │
│                    │   (Queue)   │                                │
│                    └──────┬──────┘                                │
│                           │                                       │
│  ┌────────────────────────▼────────────────────────────────────┐ │
│  │                    FastAPI Cluster                           │ │
│  │  (Load balanced, horizontal scaling)                         │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                       │
│         ┌─────────────────┼─────────────────┐                    │
│         │                 │                 │                    │
│  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐            │
│  │ PostgreSQL  │   │    Redis    │   │     S3      │            │
│  │  (Primary)  │   │   (Cache)   │   │  (Raw Data) │            │
│  └─────────────┘   └─────────────┘   └─────────────┘            │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**Key Scaling Strategies**:

1. **Horizontal API Scaling**: Kubernetes pods behind load balancer
2. **Background Processing**: Celery workers for LLM calls (expensive, async)
3. **Caching Layer**: Redis for API responses, LLM results
4. **Database**: PostgreSQL with read replicas for dashboard queries
5. **Rate Limiting**: Token bucket per API key, circuit breakers for external APIs
6. **LLM Cost Control**: 
   - Batch similar requests
   - Cache identical queries
   - Use smaller models for simple classifications
   - Implement request queuing with priorities

## Project Structure

```
company-intelligence-platform/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── models.py            # Pydantic models & SQLAlchemy ORM
│   ├── pipeline.py          # Orchestration pipeline
│   ├── data_sources.py      # API clients for data ingestion
│   ├── llm_enrichment.py    # Claude integration
│   └── database.py          # SQLite connection & queries
├── templates/
│   └── dashboard.html       # Jinja2 template for web UI
├── static/
│   └── styles.css           # Dashboard styling
├── data/
│   └── company_intel.db     # SQLite database (generated)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup & Installation

```bash
# Clone repository
git clone https://github.com/your-repo/company-intelligence-platform
cd company-intelligence-platform

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
# - ANTHROPIC_API_KEY
# - ALPHA_VANTAGE_API_KEY  
# - NEWS_API_KEY

# Run the application
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard |
| GET | `/api/companies` | List all companies with latest data |
| GET | `/api/company/{symbol}` | Detailed company view with news & insights |
| POST | `/api/ingest` | Trigger data ingestion for a company |
| GET | `/api/insights` | Aggregated insights across all companies |
| GET | `/api/health` | Health check endpoint |

## Example Usage

```bash
# Ingest data for Apple
curl -X POST "http://localhost:8000/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL"}'

# Get company details with enriched insights
curl "http://localhost:8000/api/company/AAPL"

# Get all insights
curl "http://localhost:8000/api/insights"
```

## Tech Stack

- **Backend**: FastAPI, Python 3.11+
- **Database**: SQLite (SQLAlchemy ORM)
- **LLM**: Anthropic Claude API
- **Data Sources**: Alpha Vantage, NewsAPI
- **Frontend**: HTML/CSS/JS with Chart.js
- **Async**: asyncio, httpx

## Future Improvements

1. **Real-time Updates**: WebSocket for live price feeds
2. **More Data Sources**: SEC filings, social media sentiment
3. **Advanced Analytics**: Trend detection, anomaly alerts
4. **User Management**: Multi-tenant with API keys
5. **ML Pipeline**: Train custom models on enriched data
6. **Observability**: OpenTelemetry, structured logging

## License

MIT License - Free for educational and commercial use.
