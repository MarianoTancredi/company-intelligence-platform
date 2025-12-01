"""
Orchestration Pipeline for Company Intelligence Platform.

Coordinates the workflow:
1. Data Ingestion - Fetch from structured + unstructured sources
2. Data Cleaning - Normalize and validate
3. LLM Enrichment - Sentiment, classification, insights
4. Storage - Persist to database
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from app.data_sources import fetch_company_overview, fetch_stock_data, fetch_news_articles
from app.llm_enrichment import enrich_news_article, generate_company_summary
from app.database import (
    get_db_session, upsert_company, add_stock_data, 
    add_news_article, update_article_enrichment, get_company
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result of a pipeline execution."""
    status: str = "pending"  # pending, running, completed, failed
    symbol: str = ""
    steps_completed: list = field(default_factory=list)
    current_step: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Metrics
    articles_ingested: int = 0
    articles_enriched: int = 0
    stock_records_added: int = 0
    
    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "steps_completed": self.steps_completed,
            "current_step": self.current_step,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metrics": {
                "articles_ingested": self.articles_ingested,
                "articles_enriched": self.articles_enriched,
                "stock_records_added": self.stock_records_added
            }
        }


class CompanyIntelligencePipeline:
    """
    Main orchestration pipeline for processing company data.
    
    Workflow Steps:
    1. fetch_company_data - Get structured data from Alpha Vantage
    2. fetch_stock_prices - Get historical stock data
    3. fetch_news - Get unstructured news articles
    4. enrich_articles - Run LLM analysis on each article
    5. generate_summary - Create company-level insights
    6. persist_data - Store everything in database
    """
    
    def __init__(self, symbol: str, options: dict = None):
        self.symbol = symbol.upper()
        self.options = options or {}
        self.result = PipelineResult(symbol=self.symbol)
        
        # Pipeline data storage
        self.company_data: dict = {}
        self.stock_data: list = []
        self.news_articles: list = []
        self.enriched_articles: list = []
    
    async def run(self) -> PipelineResult:
        """Execute the full pipeline."""
        self.result.status = "running"
        self.result.started_at = datetime.utcnow()
        
        try:
            # Step 1: Fetch company overview (structured)
            await self._step_fetch_company()
            
            # Step 2: Fetch stock data (structured)
            if self.options.get("fetch_stock", True):
                await self._step_fetch_stock()
            
            # Step 3: Fetch news articles (unstructured)
            if self.options.get("fetch_news", True):
                await self._step_fetch_news()
            
            # Step 4: Enrich articles with LLM
            if self.options.get("enrich_with_llm", True) and self.news_articles:
                await self._step_enrich_articles()
            
            # Step 5: Generate company summary
            if self.options.get("enrich_with_llm", True):
                await self._step_generate_summary()
            
            # Step 6: Persist all data
            await self._step_persist_data()
            
            self.result.status = "completed"
            self.result.completed_at = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"Pipeline failed for {self.symbol}: {e}")
            self.result.status = "failed"
            self.result.error = str(e)
            self.result.completed_at = datetime.utcnow()
        
        return self.result
    
    async def _step_fetch_company(self):
        """Fetch and clean company overview data."""
        self.result.current_step = "fetch_company_data"
        logger.info(f"Fetching company data for {self.symbol}")
        
        data = await fetch_company_overview(self.symbol)
        
        if data:
            self.company_data = self._clean_company_data(data)
            logger.info(f"Fetched company: {self.company_data.get('name', self.symbol)}")
        else:
            # Use minimal data if API fails
            self.company_data = {
                "symbol": self.symbol,
                "name": self.symbol,
                "sector": "Unknown",
                "description": "Company data not available"
            }
            logger.warning(f"Using fallback data for {self.symbol}")
        
        self.result.steps_completed.append("fetch_company_data")
    
    async def _step_fetch_stock(self):
        """Fetch historical stock price data."""
        self.result.current_step = "fetch_stock_prices"
        logger.info(f"Fetching stock data for {self.symbol}")
        
        days = self.options.get("stock_days", 30)
        self.stock_data = await fetch_stock_data(self.symbol, days=days)
        
        logger.info(f"Fetched {len(self.stock_data)} stock records")
        self.result.steps_completed.append("fetch_stock_prices")
    
    async def _step_fetch_news(self):
        """Fetch news articles about the company."""
        self.result.current_step = "fetch_news"
        company_name = self.company_data.get("name", self.symbol)
        logger.info(f"Fetching news for {company_name}")
        
        days = self.options.get("news_days", 7)
        max_articles = self.options.get("max_articles", 10)
        
        self.news_articles = await fetch_news_articles(
            company_name=company_name,
            symbol=self.symbol,
            days=days,
            max_articles=max_articles
        )
        
        self.result.articles_ingested = len(self.news_articles)
        logger.info(f"Fetched {len(self.news_articles)} news articles")
        self.result.steps_completed.append("fetch_news")
    
    async def _step_enrich_articles(self):
        """Enrich articles with LLM analysis."""
        self.result.current_step = "enrich_articles"
        company_name = self.company_data.get("name", self.symbol)
        logger.info(f"Enriching {len(self.news_articles)} articles with LLM")
        
        for i, article in enumerate(self.news_articles):
            try:
                enrichment = await enrich_news_article(article, company_name)
                self.enriched_articles.append({
                    "article": article,
                    "enrichment": enrichment
                })
                self.result.articles_enriched += 1
                logger.debug(f"Enriched article {i+1}/{len(self.news_articles)}")
            except Exception as e:
                logger.error(f"Failed to enrich article: {e}")
                # Still store article without enrichment
                self.enriched_articles.append({
                    "article": article,
                    "enrichment": None
                })
        
        logger.info(f"Enriched {self.result.articles_enriched} articles")
        self.result.steps_completed.append("enrich_articles")
    
    async def _step_generate_summary(self):
        """Generate company-level summary from enriched data."""
        self.result.current_step = "generate_summary"
        logger.info(f"Generating company summary for {self.symbol}")
        
        summary = await generate_company_summary(
            self.company_data,
            [item["article"] for item in self.enriched_articles]
        )
        
        self.company_data["enriched_summary"] = summary
        logger.info("Generated company summary")
        self.result.steps_completed.append("generate_summary")
    
    async def _step_persist_data(self):
        """Persist all data to database."""
        self.result.current_step = "persist_data"
        logger.info(f"Persisting data for {self.symbol}")
        
        with get_db_session() as db:
            # Save company
            upsert_company(db, self.company_data)
            
            # Save stock data
            if self.stock_data:
                count = add_stock_data(db, self.symbol, self.stock_data)
                self.result.stock_records_added = count
            
            # Save articles with enrichment
            for item in self.enriched_articles:
                article = add_news_article(db, self.symbol, item["article"])
                if item["enrichment"]:
                    update_article_enrichment(db, article.id, item["enrichment"])
        
        logger.info(f"Persisted data: {self.result.stock_records_added} stock records, {len(self.enriched_articles)} articles")
        self.result.steps_completed.append("persist_data")
    
    def _clean_company_data(self, data: dict) -> dict:
        """Clean and normalize company data."""
        # Remove None values
        cleaned = {k: v for k, v in data.items() if v is not None}
        
        # Ensure required fields
        cleaned.setdefault("symbol", self.symbol)
        cleaned.setdefault("name", self.symbol)
        
        # Truncate long descriptions
        if "description" in cleaned and len(cleaned["description"]) > 2000:
            cleaned["description"] = cleaned["description"][:2000] + "..."
        
        return cleaned


async def run_pipeline(symbol: str, options: dict = None) -> PipelineResult:
    """
    Convenience function to run the pipeline.
    
    Args:
        symbol: Stock ticker symbol
        options: Pipeline options
            - fetch_stock: bool (default True)
            - fetch_news: bool (default True)
            - enrich_with_llm: bool (default True)
            - stock_days: int (default 30)
            - news_days: int (default 7)
            - max_articles: int (default 10)
    """
    pipeline = CompanyIntelligencePipeline(symbol, options)
    return await pipeline.run()


async def run_batch_pipeline(symbols: list[str], options: dict = None) -> list[PipelineResult]:
    """
    Run pipeline for multiple companies.
    In production, this would use proper rate limiting and queuing.
    """
    results = []
    for symbol in symbols:
        result = await run_pipeline(symbol, options)
        results.append(result)
        # Simple rate limiting
        await asyncio.sleep(1)
    return results
