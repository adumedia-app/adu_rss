# main.py
"""
ArchNews Monitor - Main Entry Point (Multi-Source)

Scalable pipeline for monitoring multiple architecture news sources.

Pipeline:
    1. Fetch RSS feeds from configured sources
    2. Scrape full article content (Browserless)
    3. Download & save hero images to R2
    4. Generate AI summaries (OpenAI)
    5. Save articles to R2 storage (per source)
    6. Send digest to Telegram

Usage:
    python main.py                          # Run all configured sources
    python main.py --sources archdaily dezeen   # Run specific sources
    python main.py --rss-only               # Skip scraping
    python main.py --sources dezeen --rss-only  # Dezeen RSS only

Environment Variables (set in Railway):
    OPENAI_API_KEY          - OpenAI API key for GPT-4o-mini
    TELEGRAM_BOT_TOKEN      - Telegram bot token
    TELEGRAM_CHANNEL_ID     - Telegram channel ID
    BROWSER_PLAYWRIGHT_ENDPOINT - Railway Browserless endpoint
    R2_ACCOUNT_ID           - Cloudflare R2 account ID
    R2_ACCESS_KEY_ID        - R2 access key
    R2_SECRET_ACCESS_KEY    - R2 secret key
    R2_BUCKET_NAME          - R2 bucket name
"""

import asyncio
import argparse
import os
from datetime import datetime
from typing import Optional

# Import operators
from operators.rss_fetcher import RSSFetcher
from operators.scraper import ArticleScraper

# Import AI summarization
from operators.monitor import create_llm, summarize_article

# Import storage
from storage.r2 import R2Storage

# Import Telegram
from telegram_bot import TelegramBot

# Import prompts and config
from prompts.summarize import SUMMARIZE_PROMPT_TEMPLATE
from config.sources import SOURCES, get_source_config

# Default configuration
DEFAULT_HOURS_LOOKBACK = 24
DEFAULT_SOURCES = ["archdaily", "dezeen"]  # Sources to monitor by default


# =============================================================================
# Hero Image Processing
# =============================================================================

async def download_and_save_hero_images(
    articles: list[dict], 
    scraper: ArticleScraper, 
    r2: R2Storage,
) -> list[dict]:
    """
    Download hero images and save to R2 storage.

    Uses source_id from each article for proper storage path.
    """
    print("\n🖼️ Downloading hero images...")

    downloaded = 0
    failed = 0

    for i, article in enumerate(articles):
        hero_image = article.get("hero_image")
        source_id = article.get("source_id", "unknown")

        if not hero_image or not hero_image.get("url"):
            continue

        title_preview = article.get("title", "")[:40]
        print(f"   [{i+1}/{len(articles)}] {title_preview}...")

        try:
            image_bytes = await scraper.download_hero_image(hero_image)

            if image_bytes:
                updated_hero = r2.save_hero_image(
                    image_bytes=image_bytes,
                    article=article,
                    source=source_id
                )

                if updated_hero:
                    article["hero_image"] = updated_hero
                    downloaded += 1
            else:
                failed += 1

        except Exception as e:
            print(f"      ⚠️ Error: {e}")
            failed += 1

        await asyncio.sleep(0.3)

    print(f"   ✅ Downloaded {downloaded} hero images ({failed} failed)")
    return articles


# =============================================================================
# AI Summarization
# =============================================================================

def generate_summaries(articles: list[dict], llm, prompt_template) -> list[dict]:
    """
    Generate AI summaries for articles.

    Args:
        articles: List of article dicts
        llm: LangChain LLM instance
        prompt_template: Prompt template for summarization

    Returns:
        Articles with ai_summary and tags added
    """
    print(f"\n🤖 Generating AI summaries for {len(articles)} articles...")

    summarized = []

    for i, article in enumerate(articles, 1):
        source_name = article.get("source_name", "Unknown")
        title_preview = article.get("title", "")[:40]

        try:
            print(f"   [{i}/{len(articles)}] [{source_name}] {title_preview}...")

            summarized_article = summarize_article(article, llm, prompt_template)
            summarized.append(summarized_article)

        except Exception as e:
            print(f"   ⚠️ Summary failed: {e}")
            # Fallback: use original description
            article["ai_summary"] = article.get("description", "")[:200] + "..."
            article["tags"] = []
            summarized.append(article)

    print(f"   ✅ Generated {len(summarized)} summaries")
    return summarized


# =============================================================================
# Storage
# =============================================================================

def save_to_r2(articles: list[dict], r2: R2Storage) -> dict[str, str]:
    """
    Save articles to R2, grouped by source.

    Args:
        articles: List of article dicts with source_id
        r2: R2Storage instance

    Returns:
        Dict mapping source_id to storage path
    """
    print("\n☁️ Saving to Cloudflare R2...")

    # Group articles by source
    by_source: dict[str, list[dict]] = {}
    for article in articles:
        source_id = article.get("source_id", "unknown")
        if source_id not in by_source:
            by_source[source_id] = []
        by_source[source_id].append(article)

    paths = {}

    for source_id, source_articles in by_source.items():
        try:
            # Prepare articles for storage
            storage_articles = []
            for article in source_articles:
                hero_image_data = None
                hero = article.get("hero_image")
                if hero:
                    hero_image_data = {
                        "url": hero.get("url"),
                        "r2_path": hero.get("r2_path"),
                        "r2_url": hero.get("r2_url"),
                        "width": hero.get("width"),
                        "height": hero.get("height"),
                        "source": hero.get("source"),
                    }

                storage_article = {
                    "title": article.get("title"),
                    "link": article.get("link"),
                    "published": article.get("published"),
                    "guid": article.get("guid"),
                    "ai_summary": article.get("ai_summary"),
                    "tags": article.get("tags", []),
                    "image_count": article.get("image_count", 0),
                    "hero_image": hero_image_data,
                    "images": article.get("images", [])[:3],
                    "scrape_success": article.get("scrape_success", False),
                }
                storage_articles.append(storage_article)

            # Save to R2
            storage_path = r2.save_articles(storage_articles, source=source_id)
            paths[source_id] = storage_path

            saved_heroes = sum(1 for a in storage_articles if a.get("hero_image", {}).get("r2_path"))
            print(f"   ✅ {source_id}: {len(storage_articles)} articles saved")
            if saved_heroes > 0:
                print(f"      {saved_heroes} hero images saved")

        except Exception as e:
            print(f"   ⚠️ {source_id} storage failed: {e}")

    return paths


# =============================================================================
# Telegram
# =============================================================================

async def send_telegram_digest(articles: list[dict]) -> dict:
    """
    Send articles to Telegram channel.

    Args:
        articles: List of summarized articles

    Returns:
        Dict with sent/failed counts
    """
    print("\n📱 Sending Telegram digest...")

    try:
        bot = TelegramBot()
        results = await bot.send_digest(articles)
        print(f"   ✅ Sent {results['sent']} messages")
        if results['failed'] > 0:
            print(f"   ⚠️ Failed: {results['failed']} messages")
        return results
    except Exception as e:
        print(f"   ❌ Telegram error: {e}")
        return {"sent": 0, "failed": len(articles)}


# =============================================================================
# Main Pipeline
# =============================================================================

async def run_pipeline(
    source_ids: Optional[list[str]] = None,
    hours: int = DEFAULT_HOURS_LOOKBACK,
    skip_scraping: bool = False,
    skip_telegram: bool = False,
):
    """
    Run the complete news monitoring pipeline.

    Args:
        source_ids: List of sources to process (None = defaults)
        hours: How many hours back to look for articles
        skip_scraping: Skip Browserless scraping (use RSS data only)
        skip_telegram: Skip sending to Telegram
    """
    # Determine sources to process
    if source_ids is None:
        source_ids = DEFAULT_SOURCES

    # Filter to only sources with RSS feeds
    valid_sources = []
    for sid in source_ids:
        config = get_source_config(sid)
        if config and config.get("rss_url"):
            valid_sources.append(sid)
        else:
            print(f"⚠️ Skipping {sid}: no RSS URL configured")

    if not valid_sources:
        print("❌ No valid sources to process")
        return

    print(f"\n{'=' * 60}")
    print("🏛️ ArchNews Monitor (Multi-Source)")
    print(f"📅 {datetime.now().strftime('%B %d, %Y at %H:%M')}")
    print(f"📡 Sources: {', '.join(valid_sources)}")
    print(f"⏰ Looking back: {hours} hours")
    print(f"{'=' * 60}")

    scraper = None
    r2 = None

    try:
        # Initialize R2 storage
        try:
            r2 = R2Storage()
            print("✅ R2 storage connected")
        except Exception as e:
            print(f"⚠️ R2 not configured: {e}")
            r2 = None

        # =================================================================
        # Step 1: Fetch RSS Feeds
        # =================================================================
        print(f"\n📡 Step 1: Fetching RSS feeds...")

        fetcher = RSSFetcher()
        articles = fetcher.fetch_all_sources(
            hours=hours,
            source_ids=valid_sources
        )

        if not articles:
            print("📭 No new articles found. Exiting.")
            return

        print(f"   ✅ Found {len(articles)} articles total")

        # Show breakdown by source
        by_source = {}
        for article in articles:
            sid = article.get("source_id", "unknown")
            by_source[sid] = by_source.get(sid, 0) + 1
        for sid, count in by_source.items():
            print(f"      - {sid}: {count}")

        # =================================================================
        # Step 2: Scrape Full Content (optional)
        # =================================================================
        browserless_available = os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT')

        if not skip_scraping and browserless_available:
            print(f"\n🌐 Step 2: Scraping full article content...")

            scraper = ArticleScraper(browser_pool_size=2)

            try:
                articles = await scraper.scrape_articles(articles)

                successful = sum(1 for a in articles if a.get("scrape_success"))
                hero_count = sum(1 for a in articles if a.get("hero_image"))
                print(f"   ✅ Scraped {successful}/{len(articles)} articles")
                print(f"   ✅ Found {hero_count} hero images (og:image)")

                # Use scraped content for description if available
                for article in articles:
                    if article.get("scrape_success") and article.get("full_content"):
                        article["description"] = article["full_content"][:2000]

                # Step 2b: Download & Save Hero Images
                if r2 and hero_count > 0:
                    articles = await download_and_save_hero_images(
                        articles=articles,
                        scraper=scraper,
                        r2=r2,
                    )

            except Exception as e:
                print(f"   ⚠️ Scraping failed: {e}")
                print("   ℹ️ Continuing with RSS data...")
        else:
            if skip_scraping:
                print(f"\n⏭️ Step 2: Skipping scraping (--rss-only mode)")
            else:
                print(f"\n⏭️ Step 2: Skipping scraping (Browserless not configured)")

            # Use RSS images as hero images when not scraping
            for article in articles:
                rss_image = article.get("rss_image")
                if rss_image and rss_image.get("url"):
                    article["hero_image"] = {
                        "url": rss_image["url"],
                        "width": rss_image.get("width"),
                        "height": rss_image.get("height"),
                        "source": "rss",
                    }

        # =================================================================
        # Step 3: Generate AI Summaries
        # =================================================================
        print(f"\n🤖 Step 3: Generating AI summaries...")

        try:
            llm = create_llm()
            articles = generate_summaries(articles, llm, SUMMARIZE_PROMPT_TEMPLATE)
        except Exception as e:
            print(f"   ⚠️ AI summarization failed: {e}")
            # Fallback: use RSS descriptions
            for article in articles:
                if not article.get("ai_summary"):
                    article["ai_summary"] = article.get("description", "")[:200] + "..."
                    article["tags"] = []

        # =================================================================
        # Step 4: Save to R2 Storage
        # =================================================================
        if r2:
            storage_paths = save_to_r2(articles, r2)
        else:
            print("\n⚠️ Step 4: Skipping R2 storage (not configured)")

        # =================================================================
        # Step 5: Send to Telegram
        # =================================================================
        if not skip_telegram:
            await send_telegram_digest(articles)
        else:
            print("\n⏭️ Step 5: Skipping Telegram (disabled)")

        # =================================================================
        # Done
        # =================================================================
        print(f"\n{'=' * 60}")
        print("✅ Pipeline completed!")
        print(f"   📰 Total articles: {len(articles)}")
        for sid, count in by_source.items():
            print(f"      - {sid}: {count}")
        hero_saved = sum(1 for a in articles if a.get("hero_image", {}).get("r2_path"))
        if hero_saved > 0:
            print(f"   🖼️ Hero images saved: {hero_saved}")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n❌ Pipeline error: {e}")
        import traceback
        traceback.print_exc()

        try:
            bot = TelegramBot()
            await bot.send_error_notification(f"Pipeline failed: {str(e)}")
        except:
            pass
        raise

    finally:
        if scraper:
            await scraper.close()


# =============================================================================
# CLI Entry Point
# =============================================================================

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="ArchNews Monitor - Multi-source architecture news pipeline"
    )

    parser.add_argument(
        "--sources",
        nargs="+",
        default=None,
        help=f"Sources to fetch (default: {', '.join(DEFAULT_SOURCES)})"
    )

    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS_LOOKBACK,
        help=f"Hours to look back (default: {DEFAULT_HOURS_LOOKBACK})"
    )

    parser.add_argument(
        "--rss-only",
        action="store_true",
        help="Skip Browserless scraping, use RSS data only"
    )

    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Skip sending to Telegram"
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="List all available sources and exit"
    )

    return parser.parse_args()


def list_available_sources():
    """Print all available sources."""
    print("\nAvailable sources:")
    print("=" * 50)
    for source_id, config in SOURCES.items():
        name = config.get("name", source_id)
        rss = "✅ RSS" if config.get("rss_url") else "❌ No RSS"
        print(f"  {source_id:20} {name:25} {rss}")
    print()


if __name__ == "__main__":
    args = parse_args()

    if args.list_sources:
        list_available_sources()
    else:
        asyncio.run(run_pipeline(
            source_ids=args.sources,
            hours=args.hours,
            skip_scraping=args.rss_only,
            skip_telegram=args.no_telegram,
        ))