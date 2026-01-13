# operators/monitor.py
"""
ArchDaily News Monitor
Collects news from ArchDaily RSS and summarizes with AI.

Usage:
    # As module (called from main.py):
    from operators.monitor import run_monitor
    articles = await run_monitor()

    # Standalone test:
    python -m operators.monitor

Environment Variables (set in Railway):
    OPENAI_API_KEY - OpenAI API key for GPT-4o-mini
"""

import os
import feedparser
import asyncio
from datetime import datetime, timedelta, timezone

from langchain_openai import ChatOpenAI

from prompts.summarize import SUMMARIZE_SYSTEM_PROMPT
from prompts.summarize import parse_summary_response

# Configuration
ARCHDAILY_RSS_URL = "https://feeds.feedburner.com/Archdaily"
HOURS_LOOKBACK = 24  # Collect articles from last N hours


def fetch_rss_feed(url: str, hours: int = 24) -> list[dict]:
    """
    Fetch and parse RSS feed, return entries from last N hours.

    Args:
        url: RSS feed URL
        hours: Look back this many hours

    Returns:
        List of article dicts
    """
    print(f"📡 Fetching RSS feed: {url}")

    feed = feedparser.parse(url)

    # Check for errors
    if feed.bozo:
        print(f"⚠️ Feed warning: {feed.bozo_exception}")

    # Filter articles from specified time window
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent_articles = []

    for entry in feed.entries:
        # Parse published date
        pub_date = None
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

        # Include if within time window (or if no date available)
        if pub_date is None or pub_date >= cutoff_time:
            article = {
                "title": entry.get("title", "No title"),
                "link": entry.get("link", ""),
                "description": entry.get("summary", ""),
                "published": pub_date.isoformat() if pub_date else None,
                "guid": entry.get("id", entry.get("link", ""))
            }
            recent_articles.append(article)

    print(f"📰 Found {len(recent_articles)} articles from last {hours} hours")
    return recent_articles


def create_llm():
    """Create and configure the LLM instance."""
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")

    return ChatOpenAI(
        model="gpt-4o-mini",
        api_key=api_key,
        max_tokens=300,
        temperature=0.3  # Lower temperature for more consistent summaries
    )


def summarize_article(article: dict, llm, prompt_template) -> dict:
    """
    Generate AI summary for an article.

    Args:
        article: Article dict with title, description, link
        llm: LangChain LLM instance
        prompt_template: LangChain prompt template

    Returns:
        Article dict with added ai_summary and tags
    """
    print(f"🤖 Summarizing: {article['title'][:50]}...")

    # Create chain and invoke
    chain = prompt_template | llm

    response = chain.invoke({
        "title": article["title"],
        "description": article["description"],
        "url": article["link"]
    })

    # Parse response
    parsed = parse_summary_response(response.content)

    # Add to article
    article["ai_summary"] = parsed["summary"]
    article["tags"] = parsed["tags"]

    return article


# =============================================================================
# NEW: Main function called by main.py
# =============================================================================

async def run_monitor(
    rss_url: str = ARCHDAILY_RSS_URL,
    hours: int = HOURS_LOOKBACK
) -> list[dict]:
    """
    Main entry point - fetches RSS and generates AI summaries.
    Called by main.py orchestrator.

    Args:
        rss_url: RSS feed URL to fetch
        hours: How many hours back to look for articles

    Returns:
        List of article dicts with ai_summary and tags added
    """
    # Validate API key
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY not set in environment")

    # Step 1: Fetch RSS feed
    articles = fetch_rss_feed(rss_url, hours)

    if not articles:
        print("📭 No new articles found")
        return []

    # Step 2: Initialize LLM
    print("🔧 Initializing AI (GPT-4o-mini)...")
    llm = create_llm()

    # Step 3: Generate summaries
    print(f"📝 Generating summaries for {len(articles)} articles...")
    summarized_articles = []

    for article in articles:
        try:
            summarized = summarize_article(article, llm, SUMMARIZE_PROMPT_TEMPLATE)
            summarized_articles.append(summarized)
        except Exception as e:
            print(f"⚠️ Error summarizing '{article['title'][:30]}...': {e}")
            # Fallback: use original description
            article["ai_summary"] = article["description"][:200] + "..."
            article["tags"] = []
            summarized_articles.append(article)

    print(f"✅ Summarized {len(summarized_articles)} articles")
    return summarized_articles


# =============================================================================
# Standalone execution (for testing)
# =============================================================================

async def main():
    """
    Standalone test - runs monitor and sends to Telegram.
    Use this for testing the monitor independently.
    """
    from telegram_bot import TelegramBot

    print("=" * 50)
    print("🏗️ ArchDaily News Monitor (Standalone Test)")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # Validate required environment variables
    required_vars = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID", "OPENAI_API_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("Please set these in Railway dashboard.")
        return

    # Run monitor
    articles = await run_monitor()

    if not articles:
        print("📭 No articles to send. Exiting.")
        return

    # Send to Telegram
    print("📱 Sending to Telegram...")
    try:
        bot = TelegramBot()
        results = await bot.send_digest(articles, "ArchDaily")

        print("=" * 50)
        print(f"✅ Complete! Sent {results['sent']} messages.")
        if results['failed'] > 0:
            print(f"⚠️ Failed: {results['failed']} messages")
        print("=" * 50)

    except Exception as e:
        print(f"❌ Telegram error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())