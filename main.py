"""
ArchNews Monitor - Main Entry Point
Central orchestrator for the architecture news monitoring application.

Pipeline:
    1. Fetch RSS feed (get article URLs)
    2. Scrape full article content (Browserless)
    3. Generate AI summaries (OpenAI)
    4. Save to R2 storage (Cloudflare)
    5. Send digest to Telegram

Usage:
    python main.py              # Run full pipeline
    python main.py --test       # Test all connections
    python main.py --rss-only   # Just fetch RSS (no scraping)
"""

import asyncio
import sys
import os
from datetime import datetime

# Import operators
from operators.monitor import fetch_rss_feed, create_llm, summarize_article, ARCHDAILY_RSS_URL, HOURS_LOOKBACK
from operators.scraper import ArticleScraper

# Import storage
from storage.r2 import R2Storage

# Import Telegram
from telegram_bot import TelegramBot

# Import prompts
from prompts import SUMMARIZE_PROMPT_TEMPLATE


# =============================================================================
# Connection Tests
# =============================================================================

async def test_connections():
    """Test all external service connections."""
    print("🧪 Testing connections...\n")

    results = {"passed": 0, "failed": 0}

    # Test 1: Telegram
    print("📱 Testing Telegram...")
    try:
        bot = TelegramBot()
        if await bot.test_connection():
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        print(f"   ❌ Telegram error: {e}")
        results["failed"] += 1

    # Test 2: R2 Storage
    print("\n☁️ Testing Cloudflare R2...")
    try:
        r2 = R2Storage()
        if r2.test_connection():
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        print(f"   ❌ R2 error: {e}")
        results["failed"] += 1

    # Test 3: OpenAI API
    print("\n🤖 Testing OpenAI API...")
    try:
        llm = create_llm()
        # Quick test call
        response = llm.invoke("Say 'OK' if you can hear me.")
        if response:
            print("   ✅ OpenAI API connected")
            results["passed"] += 1
        else:
            results["failed"] += 1
    except Exception as e:
        print(f"   ❌ OpenAI error: {e}")
        results["failed"] += 1

    # Test 4: Browserless (optional)
    print("\n🌐 Testing Browserless...")
    browserless_url = os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT') or os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT_PRIVATE')
    if browserless_url:
        try:
            scraper = ArticleScraper(browser_pool_size=1)
            await scraper._initialize_browser_pool()
            if scraper.session_active:
                print("   ✅ Browserless connected")
                results["passed"] += 1
            else:
                results["failed"] += 1
            await scraper.close()
        except Exception as e:
            print(f"   ❌ Browserless error: {e}")
            results["failed"] += 1
    else:
        print("   ⚠️ Browserless not configured (BROWSER_PLAYWRIGHT_ENDPOINT not set)")
        print("   ℹ️ Scraping will use RSS descriptions only")

    # Summary
    print(f"\n{'=' * 40}")
    print(f"✅ Passed: {results['passed']}")
    print(f"❌ Failed: {results['failed']}")

    return results["failed"] == 0


# =============================================================================
# Main Pipeline
# =============================================================================

async def run_pipeline(skip_scraping: bool = False):
    """
    Run the complete news monitoring pipeline.

    Args:
        skip_scraping: If True, use RSS descriptions instead of full scraping
    """
    print(f"\n{'=' * 60}")
    print("🏛️ ArchNews Monitor")
    print(f"📅 {datetime.now().strftime('%B %d, %Y at %H:%M')}")
    print(f"{'=' * 60}")

    scraper = None

    try:
        # =====================================================================
        # Step 1: Fetch RSS Feed
        # =====================================================================
        print("\n📡 Step 1: Fetching RSS feed...")
        articles = fetch_rss_feed(ARCHDAILY_RSS_URL, HOURS_LOOKBACK)

        if not articles:
            print("📭 No new articles found. Exiting.")
            return

        print(f"   ✅ Found {len(articles)} articles")

        # =====================================================================
        # Step 2: Scrape Full Content (optional)
        # =====================================================================
        if not skip_scraping and os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT'):
            print("\n🌐 Step 2: Scraping full article content...")

            scraper = ArticleScraper(browser_pool_size=2)

            try:
                articles = await scraper.scrape_articles(articles)

                successful = sum(1 for a in articles if a.get("scrape_success"))
                print(f"   ✅ Scraped {successful}/{len(articles)} articles")

                # Use full_content for summarization if available
                for article in articles:
                    if article.get("scrape_success") and article.get("full_content"):
                        # Replace RSS description with full content (truncated)
                        article["description"] = article["full_content"][:2000]

            except Exception as e:
                print(f"   ⚠️ Scraping failed: {e}")
                print("   ℹ️ Continuing with RSS descriptions...")
        else:
            if skip_scraping:
                print("\n⏭️ Step 2: Skipping scraping (--rss-only mode)")
            else:
                print("\n⏭️ Step 2: Skipping scraping (Browserless not configured)")

        # =====================================================================
        # Step 3: Generate AI Summaries
        # =====================================================================
        print("\n🤖 Step 3: Generating AI summaries...")

        llm = create_llm()
        summarized_articles = []

        for i, article in enumerate(articles, 1):
            try:
                print(f"   [{i}/{len(articles)}] {article['title'][:50]}...")
                summarized = summarize_article(article, llm, SUMMARIZE_PROMPT_TEMPLATE)
                summarized_articles.append(summarized)
            except Exception as e:
                print(f"   ⚠️ Summary failed: {e}")
                # Fallback: use original description
                article["ai_summary"] = article.get("description", "")[:200] + "..."
                article["tags"] = []
                summarized_articles.append(article)

        print(f"   ✅ Generated {len(summarized_articles)} summaries")

        # =====================================================================
        # Step 4: Save to R2 Storage
        # =====================================================================
        print("\n☁️ Step 4: Saving to Cloudflare R2...")

        try:
            r2 = R2Storage()

            # Prepare data for storage (remove large full_content to save space)
            storage_articles = []
            for article in summarized_articles:
                storage_article = {
                    "title": article.get("title"),
                    "link": article.get("link"),
                    "published": article.get("published"),
                    "guid": article.get("guid"),
                    "ai_summary": article.get("ai_summary"),
                    "tags": article.get("tags", []),
                    "image_count": article.get("image_count", 0),
                    "images": article.get("images", [])[:3],  # Keep only first 3 images
                    "scrape_success": article.get("scrape_success", False),
                }
                storage_articles.append(storage_article)

            storage_path = r2.save_articles(storage_articles, source="archdaily")
            print(f"   ✅ Saved to: {storage_path}")

        except Exception as e:
            print(f"   ⚠️ R2 storage failed: {e}")
            print("   ℹ️ Continuing without storage...")

        # =====================================================================
        # Step 5: Send to Telegram
        # =====================================================================
        print("\n📱 Step 5: Sending Telegram digest...")

        try:
            bot = TelegramBot()
            results = await bot.send_digest(summarized_articles, source_name="ArchDaily")
            print(f"   ✅ Sent {results['sent']} messages")
            if results['failed'] > 0:
                print(f"   ⚠️ Failed: {results['failed']} messages")
        except Exception as e:
            print(f"   ❌ Telegram error: {e}")

        # =====================================================================
        # Done!
        # =====================================================================
        print(f"\n{'=' * 60}")
        print("✅ Pipeline completed successfully!")
        print(f"   📰 Articles processed: {len(summarized_articles)}")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n❌ Pipeline error: {e}")

        # Try to send error notification
        try:
            bot = TelegramBot()
            await bot.send_error_notification(f"Pipeline failed: {str(e)}")
        except:
            pass

        raise

    finally:
        # Clean up scraper
        if scraper:
            await scraper.close()


# =============================================================================
# Entry Point
# =============================================================================

async def main():
    """Main entry point - handles command line arguments."""

    # Parse arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "--test":
            # Test all connections
            success = await test_connections()
            sys.exit(0 if success else 1)

        elif arg == "--rss-only":
            # Run without scraping
            await run_pipeline(skip_scraping=True)

        elif arg == "--help":
            print("""
ArchNews Monitor - Architecture News Aggregator

Usage:
    python main.py              Run full pipeline (RSS → Scrape → AI → R2 → Telegram)
    python main.py --test       Test all service connections
    python main.py --rss-only   Run without web scraping (faster, less content)
    python main.py --help       Show this help message

Environment Variables:
    TELEGRAM_BOT_TOKEN          Telegram bot token
    TELEGRAM_CHANNEL_ID         Target channel ID
    OPENAI_API_KEY              OpenAI API key
    R2_ACCOUNT_ID               Cloudflare account ID
    R2_ACCESS_KEY_ID            R2 API access key
    R2_SECRET_ACCESS_KEY        R2 API secret key
    R2_BUCKET_NAME              R2 bucket name
    BROWSER_PLAYWRIGHT_ENDPOINT Railway Browserless URL (optional)
            """)
            sys.exit(0)

        else:
            print(f"Unknown argument: {arg}")
            print("Use --help for usage information")
            sys.exit(1)

    else:
        # Default: run full pipeline
        await run_pipeline()


if __name__ == "__main__":
    asyncio.run(main())