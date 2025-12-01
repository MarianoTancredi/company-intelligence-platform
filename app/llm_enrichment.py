"""
LLM Enrichment Module using Anthropic Claude API.

Provides sentiment analysis, classification, and insight extraction
for news articles and company data.
"""
import os
import json
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Anthropic API configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


def _get_anthropic_client():
    """Get Anthropic client if API key is available."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        logger.warning("anthropic package not installed")
        return None


async def enrich_news_article(article: dict, company_name: str) -> dict:
    """
    Enrich a news article with LLM analysis.
    
    Returns:
        dict with sentiment_score, sentiment_label, classification,
        key_insights, and market_impact
    """
    client = _get_anthropic_client()
    
    if not client:
        logger.info("Using mock enrichment (no API key)")
        return _mock_enrich_article(article)
    
    title = article.get("title", "")
    content = article.get("content", "")
    
    prompt = f"""Analyze this news article about {company_name} and provide structured analysis.

ARTICLE TITLE: {title}

ARTICLE CONTENT: {content}

Provide your analysis in the following JSON format (no markdown, just raw JSON):
{{
    "sentiment_score": <float between -1.0 (very negative) and 1.0 (very positive)>,
    "sentiment_label": "<one of: positive, negative, neutral>",
    "classification": "<one of: earnings, product, legal, market, executive, partnership, other>",
    "market_impact": "<one of: high, medium, low>",
    "key_insights": {{
        "summary": "<one sentence summary of the key takeaway>",
        "risks": ["<risk 1>", "<risk 2>"],
        "opportunities": ["<opportunity 1>", "<opportunity 2>"],
        "action_items": ["<what investors should watch>"]
    }}
}}

Be objective and focused on financial/market implications. Only return valid JSON."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract text response
        response_text = response.content[0].text
        
        # Parse JSON from response
        # Clean up potential markdown code blocks
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
        
        result = json.loads(response_text.strip())
        
        # Validate and normalize
        result["sentiment_score"] = max(-1.0, min(1.0, float(result.get("sentiment_score", 0))))
        result["sentiment_label"] = result.get("sentiment_label", "neutral").lower()
        result["classification"] = result.get("classification", "other").lower()
        result["market_impact"] = result.get("market_impact", "medium").lower()
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return _mock_enrich_article(article)
    except Exception as e:
        logger.error(f"LLM enrichment error: {e}")
        return _mock_enrich_article(article)


async def generate_company_summary(company: dict, articles: list[dict]) -> str:
    """
    Generate an enriched summary of a company based on recent news.
    """
    client = _get_anthropic_client()
    
    if not client:
        return _mock_company_summary(company)
    
    company_name = company.get("name", company.get("symbol", "Unknown"))
    sector = company.get("sector", "Unknown")
    description = company.get("description", "No description available")
    
    # Summarize recent articles
    article_summaries = []
    for i, article in enumerate(articles[:5]):
        article_summaries.append(f"{i+1}. {article.get('title', 'No title')}")
    
    articles_text = "\n".join(article_summaries) if article_summaries else "No recent news available"
    
    prompt = f"""Based on the company information and recent news, provide a brief investment-focused summary.

COMPANY: {company_name}
SECTOR: {sector}
DESCRIPTION: {description}

RECENT NEWS HEADLINES:
{articles_text}

Write a 2-3 sentence summary highlighting the company's current market position and any notable recent developments. Focus on what an investor would want to know. Be concise and factual."""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return response.content[0].text.strip()
        
    except Exception as e:
        logger.error(f"Company summary generation error: {e}")
        return _mock_company_summary(company)


async def batch_enrich_articles(articles: list[dict], company_name: str) -> list[dict]:
    """
    Enrich multiple articles. In production, this would batch API calls
    for efficiency.
    """
    results = []
    for article in articles:
        enrichment = await enrich_news_article(article, company_name)
        results.append({
            "article_id": article.get("id"),
            **enrichment
        })
    return results


# =============================================================================
# Mock Functions (when API key not available)
# =============================================================================

def _mock_enrich_article(article: dict) -> dict:
    """
    Provide mock enrichment based on simple keyword analysis.
    Used when Anthropic API key is not available.
    """
    title = (article.get("title", "") + " " + article.get("content", "")).lower()
    
    # Simple keyword-based sentiment
    positive_keywords = ["growth", "beats", "exceeds", "upgrade", "strong", "success", "innovation", "profit"]
    negative_keywords = ["loss", "decline", "scrutiny", "investigation", "concern", "risk", "lawsuit", "miss"]
    
    positive_count = sum(1 for word in positive_keywords if word in title)
    negative_count = sum(1 for word in negative_keywords if word in title)
    
    if positive_count > negative_count:
        sentiment_score = 0.3 + (positive_count * 0.1)
        sentiment_label = "positive"
    elif negative_count > positive_count:
        sentiment_score = -0.3 - (negative_count * 0.1)
        sentiment_label = "negative"
    else:
        sentiment_score = 0.0
        sentiment_label = "neutral"
    
    sentiment_score = max(-1.0, min(1.0, sentiment_score))
    
    # Simple classification
    if any(word in title for word in ["earnings", "revenue", "profit", "quarter"]):
        classification = "earnings"
    elif any(word in title for word in ["product", "launch", "announce", "innovation"]):
        classification = "product"
    elif any(word in title for word in ["lawsuit", "legal", "regulatory", "investigation"]):
        classification = "legal"
    elif any(word in title for word in ["ceo", "executive", "leadership", "management"]):
        classification = "executive"
    elif any(word in title for word in ["market", "stock", "analyst", "upgrade"]):
        classification = "market"
    else:
        classification = "other"
    
    return {
        "sentiment_score": round(sentiment_score, 2),
        "sentiment_label": sentiment_label,
        "classification": classification,
        "market_impact": "medium",
        "key_insights": {
            "summary": f"Article discusses {classification} developments.",
            "risks": ["Market volatility"],
            "opportunities": ["Potential growth areas"],
            "action_items": ["Monitor for updates"]
        }
    }


def _mock_company_summary(company: dict) -> str:
    """Generate mock company summary."""
    name = company.get("name", "This company")
    sector = company.get("sector", "the market")
    return f"{name} operates in {sector} and continues to navigate current market conditions. Recent developments suggest ongoing strategic initiatives."
