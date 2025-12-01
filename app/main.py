"""
Company Intelligence Platform - FastAPI Application

Main application with REST API endpoints and web dashboard.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for debugging
parent_dir = Path(__file__).parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

import logging
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.models import (
    IngestRequest, CompanyOverview, CompanyDetailResponse,
    StockDataPoint, NewsArticleResponse, InsightSummary,
    PipelineStatus, HealthCheck
)
from app.database import (
    init_db, get_db, get_all_companies, get_company,
    get_recent_stock_data, get_company_news, get_company_sentiment_avg,
    get_all_insights
)
from app.pipeline import run_pipeline, PipelineResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Store pipeline status in memory (in production, use Redis)
pipeline_status: dict[str, PipelineResult] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize database on startup."""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Application shutting down")


# Create FastAPI app
app = FastAPI(
    title="Company Intelligence Platform",
    description="AI-powered company data aggregation and enrichment pipeline",
    version="1.0.0",
    lifespan=lifespan
)

# Templates for dashboard
templates = Jinja2Templates(directory="templates")


# =============================================================================
# Dashboard Endpoint
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Render the web dashboard."""
    companies = get_all_companies(db)
    insights = get_all_insights(db)
    
    # Get company details with sentiment
    company_data = []
    for company in companies:
        avg_sentiment = get_company_sentiment_avg(db, company.symbol)
        recent_news = get_company_news(db, company.symbol, limit=5)
        stock_data = get_recent_stock_data(db, company.symbol, limit=10)
        
        company_data.append({
            "symbol": company.symbol,
            "name": company.name,
            "sector": company.sector,
            "market_cap": company.market_cap,
            "enriched_summary": company.enriched_summary,
            "avg_sentiment": avg_sentiment,
            "recent_news": [
                {
                    "title": n.title,
                    "sentiment_score": n.sentiment_score,
                    "sentiment_label": n.sentiment_label,
                    "classification": n.classification,
                    "published_at": n.published_at
                }
                for n in recent_news
            ],
            "stock_data": [
                {
                    "date": s.date.strftime("%Y-%m-%d"),
                    "close": s.close_price
                }
                for s in reversed(stock_data)
            ]
        })
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "companies": company_data,
            "insights": insights,
            "total_companies": len(companies),
            "total_articles": sum(len(c["recent_news"]) for c in company_data)
        }
    )


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/api/health", response_model=HealthCheck)
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Test database connection
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"
    
    return HealthCheck(
        status="healthy" if db_status == "healthy" else "degraded",
        database=db_status,
        timestamp=datetime.utcnow()
    )


@app.get("/api/companies", response_model=list[CompanyOverview])
async def list_companies(db: Session = Depends(get_db)):
    """List all companies with basic info."""
    companies = get_all_companies(db)
    return [
        CompanyOverview(
            symbol=c.symbol,
            name=c.name,
            sector=c.sector,
            industry=c.industry,
            description=c.description[:200] + "..." if c.description and len(c.description) > 200 else c.description,
            market_cap=c.market_cap,
            pe_ratio=c.pe_ratio,
            enriched_summary=c.enriched_summary
        )
        for c in companies
    ]


@app.get("/api/company/{symbol}", response_model=CompanyDetailResponse)
async def get_company_detail(symbol: str, db: Session = Depends(get_db)):
    """Get detailed company information with news and stock data."""
    company = get_company(db, symbol)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {symbol} not found")
    
    stock_data = get_recent_stock_data(db, symbol, limit=30)
    news = get_company_news(db, symbol, limit=20)
    avg_sentiment = get_company_sentiment_avg(db, symbol)
    
    return CompanyDetailResponse(
        company=CompanyOverview(
            symbol=company.symbol,
            name=company.name,
            sector=company.sector,
            industry=company.industry,
            description=company.description,
            market_cap=company.market_cap,
            pe_ratio=company.pe_ratio,
            enriched_summary=company.enriched_summary
        ),
        recent_stock_data=[
            StockDataPoint(
                date=s.date,
                open_price=s.open_price or 0,
                high_price=s.high_price or 0,
                low_price=s.low_price or 0,
                close_price=s.close_price or 0,
                volume=s.volume or 0
            )
            for s in stock_data
        ],
        news_articles=[
            NewsArticleResponse(
                id=n.id,
                title=n.title,
                source=n.source,
                url=n.url,
                published_at=n.published_at,
                sentiment_score=n.sentiment_score,
                sentiment_label=n.sentiment_label,
                classification=n.classification,
                key_insights=n.key_insights,
                market_impact=n.market_impact
            )
            for n in news
        ],
        aggregate_sentiment=avg_sentiment
    )


@app.post("/api/ingest", response_model=dict)
async def ingest_company(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Trigger data ingestion pipeline for a company.
    Runs asynchronously in background.
    """
    symbol = request.symbol.upper()
    
    # Check if pipeline is already running for this symbol
    if symbol in pipeline_status and pipeline_status[symbol].status == "running":
        return {
            "message": f"Pipeline already running for {symbol}",
            "status": pipeline_status[symbol].to_dict()
        }
    
    # Create pipeline options from request
    options = {
        "fetch_news": request.fetch_news,
        "fetch_stock": request.fetch_stock,
        "enrich_with_llm": request.enrich_with_llm
    }
    
    # Run pipeline in background
    async def run_and_store():
        result = await run_pipeline(symbol, options)
        pipeline_status[symbol] = result
    
    background_tasks.add_task(run_and_store)
    
    # Initialize status
    pipeline_status[symbol] = PipelineResult(
        status="running",
        symbol=symbol,
        started_at=datetime.utcnow()
    )
    
    return {
        "message": f"Pipeline started for {symbol}",
        "status_url": f"/api/status/{symbol}"
    }


@app.get("/api/status/{symbol}", response_model=dict)
async def get_pipeline_status(symbol: str):
    """Get the status of a running or completed pipeline."""
    symbol = symbol.upper()
    
    if symbol not in pipeline_status:
        raise HTTPException(status_code=404, detail=f"No pipeline found for {symbol}")
    
    return pipeline_status[symbol].to_dict()


@app.get("/api/insights", response_model=list[InsightSummary])
async def get_insights(db: Session = Depends(get_db)):
    """Get aggregated insights across all companies."""
    insights = get_all_insights(db)
    return [
        InsightSummary(
            symbol=i["symbol"],
            company_name=i["company_name"],
            avg_sentiment=i["avg_sentiment"],
            article_count=i["article_count"],
            recent_classifications=i["recent_classifications"],
            top_insight=i["top_insight"]
        )
        for i in insights
    ]


@app.get("/api/news/{symbol}", response_model=list[NewsArticleResponse])
async def get_news(symbol: str, limit: int = 20, db: Session = Depends(get_db)):
    """Get news articles for a specific company."""
    company = get_company(db, symbol)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {symbol} not found")
    
    news = get_company_news(db, symbol, limit=limit)
    return [
        NewsArticleResponse(
            id=n.id,
            title=n.title,
            source=n.source,
            url=n.url,
            published_at=n.published_at,
            sentiment_score=n.sentiment_score,
            sentiment_label=n.sentiment_label,
            classification=n.classification,
            key_insights=n.key_insights,
            market_impact=n.market_impact
        )
        for n in news
    ]


# =============================================================================
# Run with: uvicorn app.main:app --reload
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
