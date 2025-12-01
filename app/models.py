"""
Data models for the Company Intelligence Platform.
Includes Pydantic schemas for validation and SQLAlchemy ORM models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, JSON, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


# =============================================================================
# SQLAlchemy ORM Models (Database Tables)
# =============================================================================

class CompanyDB(Base):
    """Core company information from structured data source."""
    __tablename__ = "companies"
    
    symbol = Column(String(10), primary_key=True)
    name = Column(String(255), nullable=False)
    sector = Column(String(100))
    industry = Column(String(100))
    description = Column(Text)
    market_cap = Column(Float)
    pe_ratio = Column(Float)
    dividend_yield = Column(Float)
    fifty_two_week_high = Column(Float)
    fifty_two_week_low = Column(Float)
    enriched_summary = Column(Text)  # LLM-generated summary
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    stock_data = relationship("StockDataDB", back_populates="company", cascade="all, delete-orphan")
    news_articles = relationship("NewsArticleDB", back_populates="company", cascade="all, delete-orphan")


class StockDataDB(Base):
    """Daily stock price data from structured source."""
    __tablename__ = "stock_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), ForeignKey("companies.symbol"), nullable=False)
    date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Integer)
    
    # Relationship
    company = relationship("CompanyDB", back_populates="stock_data")


class NewsArticleDB(Base):
    """News articles from unstructured source, enriched by LLM."""
    __tablename__ = "news_articles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), ForeignKey("companies.symbol"), nullable=False)
    title = Column(String(500), nullable=False)
    source = Column(String(100))
    author = Column(String(200))
    url = Column(String(1000))
    published_at = Column(DateTime)
    content = Column(Text)
    
    # LLM-enriched fields
    sentiment_score = Column(Float)  # -1.0 to 1.0
    sentiment_label = Column(String(20))  # positive, negative, neutral
    classification = Column(String(50))  # earnings, product, legal, market, executive
    key_insights = Column(JSON)  # Structured insights from LLM
    market_impact = Column(String(20))  # high, medium, low
    enriched_at = Column(DateTime)
    
    # Relationship
    company = relationship("CompanyDB", back_populates="news_articles")


# =============================================================================
# Pydantic Schemas (API Request/Response Models)
# =============================================================================

class IngestRequest(BaseModel):
    """Request to ingest data for a company."""
    symbol: str = Field(..., description="Stock ticker symbol", min_length=1, max_length=10)
    fetch_news: bool = Field(default=True, description="Whether to fetch news articles")
    fetch_stock: bool = Field(default=True, description="Whether to fetch stock data")
    enrich_with_llm: bool = Field(default=True, description="Whether to run LLM enrichment")


class CompanyOverview(BaseModel):
    """Company information response."""
    symbol: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    enriched_summary: Optional[str] = None
    
    class Config:
        from_attributes = True


class StockDataPoint(BaseModel):
    """Single stock data point."""
    date: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    
    class Config:
        from_attributes = True


class NewsArticleResponse(BaseModel):
    """News article with LLM enrichment."""
    id: int
    title: str
    source: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    sentiment_score: Optional[float] = None
    sentiment_label: Optional[str] = None
    classification: Optional[str] = None
    key_insights: Optional[dict] = None
    market_impact: Optional[str] = None
    
    class Config:
        from_attributes = True


class CompanyDetailResponse(BaseModel):
    """Full company detail with related data."""
    company: CompanyOverview
    recent_stock_data: list[StockDataPoint]
    news_articles: list[NewsArticleResponse]
    aggregate_sentiment: Optional[float] = None


class InsightSummary(BaseModel):
    """Aggregated insights across companies."""
    symbol: str
    company_name: str
    avg_sentiment: float
    article_count: int
    recent_classifications: list[str]
    top_insight: Optional[str] = None


class PipelineStatus(BaseModel):
    """Status of a pipeline run."""
    status: str  # running, completed, failed
    symbol: str
    steps_completed: list[str]
    current_step: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class HealthCheck(BaseModel):
    """API health check response."""
    status: str
    database: str
    timestamp: datetime
