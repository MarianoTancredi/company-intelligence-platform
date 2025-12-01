"""
Database connection and query utilities.
Uses SQLAlchemy with SQLite for the prototype.
"""
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager

from app.models import Base, CompanyDB, StockDataDB, NewsArticleDB

# Database URL from environment or default
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/company_intel.db")

# Create engine with appropriate settings for SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=os.getenv("DEBUG", "false").lower() == "true"
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db_session():
    """Context manager for database sessions."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """Dependency for FastAPI - yields database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =============================================================================
# Company Queries
# =============================================================================

def get_company(db: Session, symbol: str) -> Optional[CompanyDB]:
    """Get company by symbol."""
    return db.query(CompanyDB).filter(CompanyDB.symbol == symbol.upper()).first()


def get_all_companies(db: Session) -> list[CompanyDB]:
    """Get all companies."""
    return db.query(CompanyDB).order_by(CompanyDB.name).all()


def upsert_company(db: Session, company_data: dict) -> CompanyDB:
    """Insert or update company data."""
    symbol = company_data.get("symbol", "").upper()
    existing = get_company(db, symbol)
    
    if existing:
        for key, value in company_data.items():
            if hasattr(existing, key) and value is not None:
                setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    else:
        company = CompanyDB(**company_data)
        db.add(company)
        db.commit()
        db.refresh(company)
        return company


# =============================================================================
# Stock Data Queries
# =============================================================================

def add_stock_data(db: Session, symbol: str, stock_records: list[dict]) -> int:
    """Add stock data records for a company."""
    symbol = symbol.upper()
    count = 0
    
    for record in stock_records:
        # Check if record already exists for this date
        existing = db.query(StockDataDB).filter(
            StockDataDB.symbol == symbol,
            StockDataDB.date == record["date"]
        ).first()
        
        if not existing:
            stock_data = StockDataDB(symbol=symbol, **record)
            db.add(stock_data)
            count += 1
    
    db.commit()
    return count


def get_recent_stock_data(db: Session, symbol: str, limit: int = 30) -> list[StockDataDB]:
    """Get most recent stock data for a company."""
    return db.query(StockDataDB).filter(
        StockDataDB.symbol == symbol.upper()
    ).order_by(StockDataDB.date.desc()).limit(limit).all()


# =============================================================================
# News Article Queries
# =============================================================================

def add_news_article(db: Session, symbol: str, article_data: dict) -> NewsArticleDB:
    """Add a news article for a company."""
    # Check for duplicates by URL
    if article_data.get("url"):
        existing = db.query(NewsArticleDB).filter(
            NewsArticleDB.url == article_data["url"]
        ).first()
        if existing:
            return existing
    
    article = NewsArticleDB(symbol=symbol.upper(), **article_data)
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def get_unenriched_articles(db: Session, symbol: str = None) -> list[NewsArticleDB]:
    """Get articles that haven't been enriched by LLM yet."""
    query = db.query(NewsArticleDB).filter(NewsArticleDB.enriched_at.is_(None))
    if symbol:
        query = query.filter(NewsArticleDB.symbol == symbol.upper())
    return query.all()


def update_article_enrichment(db: Session, article_id: int, enrichment: dict):
    """Update article with LLM enrichment data."""
    article = db.query(NewsArticleDB).filter(NewsArticleDB.id == article_id).first()
    if article:
        article.sentiment_score = enrichment.get("sentiment_score")
        article.sentiment_label = enrichment.get("sentiment_label")
        article.classification = enrichment.get("classification")
        article.key_insights = enrichment.get("key_insights")
        article.market_impact = enrichment.get("market_impact")
        article.enriched_at = datetime.utcnow()
        db.commit()


def get_company_news(db: Session, symbol: str, limit: int = 20) -> list[NewsArticleDB]:
    """Get news articles for a company."""
    return db.query(NewsArticleDB).filter(
        NewsArticleDB.symbol == symbol.upper()
    ).order_by(NewsArticleDB.published_at.desc()).limit(limit).all()


# =============================================================================
# Aggregation Queries
# =============================================================================

def get_company_sentiment_avg(db: Session, symbol: str) -> Optional[float]:
    """Get average sentiment score for a company's recent news."""
    result = db.query(func.avg(NewsArticleDB.sentiment_score)).filter(
        NewsArticleDB.symbol == symbol.upper(),
        NewsArticleDB.sentiment_score.isnot(None)
    ).scalar()
    return round(result, 3) if result else None


def get_all_insights(db: Session) -> list[dict]:
    """Get aggregated insights for all companies."""
    companies = get_all_companies(db)
    insights = []
    
    for company in companies:
        articles = get_company_news(db, company.symbol, limit=10)
        enriched_articles = [a for a in articles if a.sentiment_score is not None]
        
        if enriched_articles:
            avg_sentiment = sum(a.sentiment_score for a in enriched_articles) / len(enriched_articles)
            classifications = list(set(a.classification for a in enriched_articles if a.classification))
            top_insight = None
            
            # Get most impactful insight
            for article in enriched_articles:
                if article.key_insights and article.market_impact == "high":
                    insights_data = article.key_insights
                    if isinstance(insights_data, dict) and "summary" in insights_data:
                        top_insight = insights_data["summary"]
                        break
            
            insights.append({
                "symbol": company.symbol,
                "company_name": company.name,
                "avg_sentiment": round(avg_sentiment, 3),
                "article_count": len(enriched_articles),
                "recent_classifications": classifications[:5],
                "top_insight": top_insight
            })
    
    return sorted(insights, key=lambda x: abs(x["avg_sentiment"]), reverse=True)
