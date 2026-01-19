# operators/custom_scrapers/japan_architects.py
"""
Japan Architects Custom Scraper - HTML Pattern Approach (Simplified)
Scrapes architecture news from Japan-Architects.com

Site: https://www.japan-architects.com/ja
Strategy: Extract links matching /ja/architecture-news/ pattern + dates from HTML

Pattern Analysis:
- Article links: /ja/architecture-news/category/article-name
- Date format in HTML: DD.MM.YYYY (e.g., "28.12.2025")
- Each article block contains: image, category tag, title, description, author + date

HTML Structure:
<div class="grid-item ... news-panel">
    ...
    <a href="/ja/architecture-news/...">...</a>
    ...
    <span> Author Name | DD.MM.YYYY </span>
</div>

Requirements:
- User-Agent header required to avoid 403

Usage:
    scraper = JapanArchitectsScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import asyncio
import re
from typing import Optional, List, Tuple
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker


class JapanArchitectsScraper(BaseCustomScraper):
    """
    HTML pattern-based custom scraper for Japan Architects.
    Extracts article links and dates directly from HTML - no AI needed.
    """

    source_id = "japan_architects"
    source_name = "Japan Architects"
    base_url = "https://www.japan-architects.com/ja"

    # Configuration
    MAX_ARTICLE_AGE_DAYS = 30
    MAX_NEW_ARTICLES = 15

    # URL pattern for architecture news
    ARTICLE_PATTERN = re.compile(r'/ja/architecture-news/[^"\'>\s]+')

    # Date pattern: DD.MM.YYYY
    DATE_PATTERN = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')

    def __init__(self):
        """Initialize scraper with article tracker."""
        super().__init__()
        self.tracker: Optional[ArticleTracker] = None

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _extract_articles_from_html(self, html: str) -> List[Tuple[str, str, Optional[str]]]:
        """
        Extract article URLs, titles and dates from HTML.

        Parses the news-panel blocks to get:
        - URL from href="/ja/architecture-news/..."
        - Title from the link text
        - Date from the span containing "| DD.MM.YYYY"

        Args:
            html: Page HTML content

        Returns:
            List of tuples: (url, title, date_iso) - date may be None
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles: List[Tuple[str, str, Optional[str]]] = []
        seen_urls: set[str] = set()

        # Find all news panel blocks
        news_panels = soup.find_all('div', class_='news-panel')

        if not news_panels:
            # Fallback: look for grid-item blocks
            news_panels = soup.find_all('div', class_='grid-item')

        print(f"[{self.source_id}] Found {len(news_panels)} news panels")

        for panel in news_panels:
            try:
                # Find article link (href starting with /ja/architecture-news/)
                article_link = None
                title = None

                # Look for links in the title div first
                title_div = panel.find('div', class_='title')
                if title_div:
                    link = title_div.find('a', href=self.ARTICLE_PATTERN)
                    if link:
                        article_link = link.get('href')
                        title = link.get_text(strip=True)

                # Fallback: find any matching link
                if not article_link:
                    for link in panel.find_all('a', href=True):
                        href = link.get('href', '')
                        if self.ARTICLE_PATTERN.match(href):
                            article_link = href
                            # Get title from link text if it's not just an image
                            link_text = link.get_text(strip=True)
                            if link_text and not title:
                                title = link_text
                            break

                if not article_link:
                    continue

                # Make URL absolute
                full_url = urljoin("https://www.japan-architects.com", article_link)

                # Skip if already seen
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                # Extract date from the span (format: "Author | DD.MM.YYYY")
                date_iso = None
                panel_text = panel.get_text()
                date_match = self.DATE_PATTERN.search(panel_text)

                if date_match:
                    day, month, year = date_match.groups()
                    try:
                        date_obj = datetime(
                            year=int(year),
                            month=int(month),
                            day=int(day),
                            tzinfo=timezone.utc
                        )
                        date_iso = date_obj.isoformat()
                    except ValueError as e:
                        print(f"[{self.source_id}] Invalid date: {day}.{month}.{year} - {e}")

                # Use URL slug as title if no title found
                if not title:
                    # Extract from URL: /ja/architecture-news/category/article-name -> article-name
                    slug = article_link.rstrip('/').split('/')[-1]
                    title = slug.replace('-', ' ').title()

                articles.append((full_url, title, date_iso))

            except Exception as e:
                print(f"[{self.source_id}] Error parsing panel: {e}")
                continue

        return articles

    def _is_within_age_limit(self, date_iso: Optional[str]) -> bool:
        """Check if article date is within MAX_ARTICLE_AGE_DAYS."""
        if not date_iso:
            # If no date, assume it's recent enough
            return True

        try:
            article_date = datetime.fromisoformat(date_iso.replace('Z', '+00:00'))
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.MAX_ARTICLE_AGE_DAYS)
            return article_date >= cutoff
        except Exception:
            return True

    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch new articles from Japan Architects.

        Workflow:
        1. Load homepage with User-Agent header
        2. Extract all /ja/architecture-news/ links + dates from HTML
        3. Check database for new URLs
        4. Filter by date (within MAX_ARTICLE_AGE_DAYS)
        5. Return minimal article dicts for main pipeline

        Args:
            hours: Ignored (we use database tracking instead)

        Returns:
            List of article dicts for main pipeline
        """
        # Initialize statistics tracking
        self._init_stats()

        print(f"\n[{self.source_id}] 🔍 Starting HTML pattern scraping...")
        print(f"   URL: {self.base_url}")

        await self._ensure_tracker()

        try:
            page = await self._create_page()

            # Set User-Agent header (required for this site)
            await page.set_extra_http_headers({
                "User-Agent": self.user_agent
            })

            try:
                # ============================================================
                # Step 1: Load Homepage
                # ============================================================
                print(f"[{self.source_id}] Loading homepage...")
                await page.goto(self.base_url, timeout=self.timeout, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Get page HTML
                html = await page.content()

                # ============================================================
                # Step 2: Extract Articles from HTML
                # ============================================================
                print(f"[{self.source_id}] Extracting articles from HTML...")
                extracted = self._extract_articles_from_html(html)

                print(f"[{self.source_id}] Found {len(extracted)} articles matching /ja/architecture-news/ pattern")

                if not extracted:
                    print(f"[{self.source_id}] ⚠️ No articles found")
                    if self.stats:
                        self.stats.log_final_count(0)
                        self.stats.print_summary()
                        await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 3: Check Database for New URLs
                # ============================================================
                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                all_urls = [url for url, _, _ in extracted]
                seen_urls = await self.tracker.get_stored_headlines(self.source_id)

                # Find new articles
                new_articles_data = [
                    (url, title, date)
                    for url, title, date in extracted
                    if url not in seen_urls
                ]

                print(f"[{self.source_id}] Database check:")
                print(f"   Total extracted: {len(extracted)}")
                print(f"   Already seen: {len(extracted) - len(new_articles_data)}")
                print(f"   New articles: {len(new_articles_data)}")

                if not new_articles_data:
                    print(f"[{self.source_id}] ✅ No new articles to process")
                    # Still store all URLs
                    await self.tracker.store_headlines(self.source_id, all_urls)
                    if self.stats:
                        self.stats.log_final_count(0)
                        self.stats.print_summary()
                        await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 4: Filter by Date and Build Results
                # ============================================================
                new_articles: list[dict] = []
                skipped_old = 0

                for url, title, date_iso in new_articles_data[:self.MAX_NEW_ARTICLES]:
                    # Check date limit
                    if not self._is_within_age_limit(date_iso):
                        skipped_old += 1
                        if self.stats:
                            self.stats.log_skipped("too_old")
                        continue

                    # Build article dict
                    article = {
                        'title': title,
                        'link': url,
                        'source_id': self.source_id,
                    }

                    if date_iso:
                        article['published'] = date_iso

                    new_articles.append(article)

                    if self.stats:
                        self.stats.log_article_found(url)

                    print(f"   ✅ {title[:50]}...")
                    if date_iso:
                        print(f"      Date: {date_iso[:10]}")

                # ============================================================
                # Step 5: Store All URLs and Finalize
                # ============================================================
                await self.tracker.store_headlines(self.source_id, all_urls)

                # Final Summary
                print(f"\n[{self.source_id}] 📊 Processing Summary:")
                print(f"   Articles found: {len(extracted)}")
                print(f"   New articles: {len(new_articles_data)}")
                print(f"   Skipped (too old): {skipped_old}")
                print(f"   ✅ Successfully scraped: {len(new_articles)}")

                # Log final count and upload stats
                if self.stats:
                    self.stats.log_final_count(len(new_articles))
                    self.stats.print_summary()
                    await self._upload_stats_to_r2()

                return new_articles

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] ❌ Error in scraping: {e}")
            if self.stats:
                self.stats.log_error(f"Critical error: {str(e)}")
                self.stats.print_summary()
                await self._upload_stats_to_r2()
            import traceback
            traceback.print_exc()
            return []

    async def close(self):
        """Close browser and tracker connections."""
        await super().close()

        if self.tracker:
            await self.tracker.close()
            self.tracker = None


# Register this scraper
custom_scraper_registry.register(JapanArchitectsScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_japan_architects_scraper():
    """Test the HTML pattern scraper."""
    print("=" * 60)
    print("Testing Japan Architects HTML Pattern Scraper")
    print("=" * 60)

    scraper = JapanArchitectsScraper()

    try:
        # Test connection
        print("\n1. Testing connection...")
        connected = await scraper.test_connection()

        if not connected:
            print("   ❌ Connection failed")
            return

        # Show tracker stats
        print("\n2. Checking tracker stats...")
        await scraper._ensure_tracker()

        if scraper.tracker:
            stats = await scraper.tracker.get_stats(source_id="japan_architects")
            print(f"   Total articles in database: {stats['total_articles']}")
            if stats['oldest_seen']:
                print(f"   Oldest: {stats['oldest_seen']}")
            if stats['newest_seen']:
                print(f"   Newest: {stats['newest_seen']}")

        # Fetch new articles
        print("\n3. Running HTML pattern scraping...")
        articles = await scraper.fetch_articles(hours=24)

        print(f"\n   Found {len(articles)} NEW articles")

        # Display articles
        if articles:
            print("\n4. New articles:")
            for i, article in enumerate(articles, 1):
                print(f"\n   --- Article {i} ---")
                print(f"   Title: {article['title'][:60]}...")
                print(f"   Link: {article['link']}")
                print(f"   Published: {article.get('published', 'No date')}")
        else:
            print("\n4. No new articles (all previously seen)")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(test_japan_architects_scraper())