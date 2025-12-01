"""
Data source clients for fetching structured and unstructured data.

Structured: Alpha Vantage API (stock prices, company fundamentals)
Unstructured: NewsAPI (news articles about companies)
"""
import os
import httpx
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

# API Keys from environment
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "demo")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# Base URLs
ALPHA_VANTAGE_BASE = "https://www.alphavantage.co/query"
NEWS_API_BASE = "https://newsapi.org/v2"

# Simple in-memory cache to respect rate limits
_cache = {}
CACHE_TTL = 300  # 5 minutes


def _get_cached(key: str) -> Optional[dict]:
    """Get cached data if not expired."""
    if key in _cache:
        data, timestamp = _cache[key]
        if datetime.utcnow() - timestamp < timedelta(seconds=CACHE_TTL):
            return data
    return None


def _set_cache(key: str, data: dict):
    """Cache data with timestamp."""
    _cache[key] = (data, datetime.utcnow())


# =============================================================================
# Structured Data Source: Alpha Vantage
# =============================================================================

async def fetch_company_overview(symbol: str) -> Optional[dict]:
    """
    Fetch company fundamental data from Alpha Vantage.
    Returns structured data: name, sector, market cap, P/E ratio, etc.
    """
    cache_key = f"overview_{symbol}"
    cached = _get_cached(cache_key)
    if cached:
        logger.info(f"Using cached company overview for {symbol}")
        return cached
    
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": ALPHA_VANTAGE_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ALPHA_VANTAGE_BASE, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Check for rate limit or error
            if "Note" in data or "Error Message" in data:
                logger.warning(f"Alpha Vantage API limit/error: {data}")
                return None
            
            if not data or "Symbol" not in data:
                logger.warning(f"No data returned for symbol {symbol}")
                return None
            
            # Transform to our schema
            result = {
                "symbol": data.get("Symbol", symbol).upper(),
                "name": data.get("Name", symbol),
                "sector": data.get("Sector"),
                "industry": data.get("Industry"),
                "description": data.get("Description"),
                "market_cap": _safe_float(data.get("MarketCapitalization")),
                "pe_ratio": _safe_float(data.get("PERatio")),
                "dividend_yield": _safe_float(data.get("DividendYield")),
                "fifty_two_week_high": _safe_float(data.get("52WeekHigh")),
                "fifty_two_week_low": _safe_float(data.get("52WeekLow")),
            }
            
            _set_cache(cache_key, result)
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching company overview: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching company overview: {e}")
        return None


async def fetch_stock_data(symbol: str, days: int = 30) -> list[dict]:
    """
    Fetch daily stock price data from Alpha Vantage.
    Returns list of OHLCV data points.
    """
    cache_key = f"stock_{symbol}_{days}"
    cached = _get_cached(cache_key)
    if cached:
        logger.info(f"Using cached stock data for {symbol}")
        return cached
    
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",  # Last 100 data points
        "apikey": ALPHA_VANTAGE_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ALPHA_VANTAGE_BASE, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Check for rate limit or error
            if "Note" in data or "Error Message" in data:
                logger.warning(f"Alpha Vantage API limit/error: {data}")
                return []
            
            time_series = data.get("Time Series (Daily)", {})
            if not time_series:
                logger.warning(f"No time series data for {symbol}")
                return []
            
            # Transform to our schema
            result = []
            for date_str, values in sorted(time_series.items(), reverse=True)[:days]:
                result.append({
                    "date": datetime.strptime(date_str, "%Y-%m-%d"),
                    "open_price": _safe_float(values.get("1. open")),
                    "high_price": _safe_float(values.get("2. high")),
                    "low_price": _safe_float(values.get("3. low")),
                    "close_price": _safe_float(values.get("4. close")),
                    "volume": _safe_int(values.get("5. volume")),
                })
            
            _set_cache(cache_key, result)
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching stock data: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching stock data: {e}")
        return []


# =============================================================================
# Unstructured Data Source: NewsAPI
# =============================================================================

async def fetch_news_articles(company_name: str, symbol: str, days: int = 7, max_articles: int = 10) -> list[dict]:
    """
    Fetch news articles about a company from NewsAPI.
    Returns unstructured text data: title, content, source, etc.
    """
    if not NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set, using mock data")
        return _get_mock_news(company_name, symbol)
    
    cache_key = f"news_{symbol}_{days}"
    cached = _get_cached(cache_key)
    if cached:
        logger.info(f"Using cached news for {symbol}")
        return cached
    
    # Calculate date range
    to_date = datetime.utcnow()
    from_date = to_date - timedelta(days=days)
    
    # Search query - use company name and symbol
    query = f'"{company_name}" OR "{symbol}"'
    
    params = {
        "q": query,
        "from": from_date.strftime("%Y-%m-%d"),
        "to": to_date.strftime("%Y-%m-%d"),
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": max_articles,
        "apiKey": NEWS_API_KEY
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{NEWS_API_BASE}/everything", params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "ok":
                logger.warning(f"NewsAPI error: {data.get('message')}")
                return _get_mock_news(company_name, symbol)
            
            articles = data.get("articles", [])
            
            # Transform to our schema
            result = []
            for article in articles:
                result.append({
                    "title": article.get("title", ""),
                    "source": article.get("source", {}).get("name"),
                    "author": article.get("author"),
                    "url": article.get("url"),
                    "published_at": _parse_date(article.get("publishedAt")),
                    "content": article.get("content") or article.get("description", ""),
                })
            
            _set_cache(cache_key, result)
            return result
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching news: {e}")
        return _get_mock_news(company_name, symbol)
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return _get_mock_news(company_name, symbol)


# =============================================================================
# Helper Functions
# =============================================================================

def _safe_float(value) -> Optional[float]:
    """Safely convert value to float."""
    if value is None or value == "None" or value == "-":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value) -> Optional[int]:
    """Safely convert value to int."""
    if value is None or value == "None" or value == "-":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse ISO date string."""
    if not date_str:
        return None
    try:
        # Handle ISO format with Z suffix
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get_mock_news(company_name: str, symbol: str) -> list[dict]:
    """
    Return mock news data for demonstration when API keys aren't available.
    This allows the prototype to function without requiring real API keys.
    """
    logger.info(f"Using mock news data for {company_name}")
    
    mock_articles = [
        {
            "title": f"{company_name} Reports Strong Q4 Earnings, Beats Analyst Expectations",
            "source": "Financial Times",
            "author": "Market Reporter",
            "url": f"https://example.com/news/{symbol.lower()}-earnings",
            "published_at": datetime.utcnow() - timedelta(days=1),
            "content": f"{company_name} announced quarterly earnings that exceeded Wall Street expectations. Revenue grew 15% year-over-year, driven by strong demand in core business segments. The company also raised its full-year guidance, citing improved market conditions and successful cost optimization initiatives."
        },
        {
            "title": f"{company_name} Announces New AI-Powered Product Line",
            "source": "TechCrunch",
            "author": "Tech Editor",
            "url": f"https://example.com/news/{symbol.lower()}-ai-product",
            "published_at": datetime.utcnow() - timedelta(days=3),
            "content": f"In a move to strengthen its competitive position, {company_name} unveiled a new suite of AI-powered products today. The company's CEO stated that this represents a significant investment in emerging technologies and positions the firm for long-term growth in the rapidly evolving market landscape."
        },
        {
            "title": f"Analysts Upgrade {company_name} Following Market Expansion",
            "source": "Bloomberg",
            "author": "Senior Analyst",
            "url": f"https://example.com/news/{symbol.lower()}-upgrade",
            "published_at": datetime.utcnow() - timedelta(days=5),
            "content": f"Several major investment banks have upgraded their rating on {company_name} stock following the company's successful expansion into Asian markets. Analysts cite strong execution and favorable regulatory environment as key factors. Price targets have been raised by an average of 12%."
        },
        {
            "title": f"{company_name} Faces Regulatory Scrutiny Over Data Practices",
            "source": "Reuters",
            "author": "Legal Correspondent",
            "url": f"https://example.com/news/{symbol.lower()}-regulatory",
            "published_at": datetime.utcnow() - timedelta(days=2),
            "content": f"Regulators have opened an inquiry into {company_name}'s data handling practices. While the company maintains it operates in full compliance with all applicable laws, investors are watching closely. Legal experts suggest the investigation could take several months to conclude."
        },
        {
            "title": f"{company_name} CEO Discusses Future Strategy in Investor Call",
            "source": "CNBC",
            "author": "Business Reporter",
            "url": f"https://example.com/news/{symbol.lower()}-strategy",
            "published_at": datetime.utcnow() - timedelta(days=4),
            "content": f"During the latest investor call, {company_name}'s leadership outlined ambitious plans for the coming year. Key initiatives include expanding digital capabilities, pursuing strategic acquisitions, and increasing R&D spending by 20%. Management expressed confidence in achieving double-digit growth."
        }
    ]
    
    return mock_articles
