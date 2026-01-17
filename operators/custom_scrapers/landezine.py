# operators/custom_scrapers/landezine.py
"""
Landezine Custom Scraper - Simple HTTP Approach
Scrapes landscape architecture news from Landezine.com

Key Finding: Landezine BLOCKS requests with User-Agent headers but
ALLOWS plain HTTP requests without headers. This scraper uses the
simplest possible approach: basic requests library with no headers.

Strategy:
1. Fetch homepage HTML via basic HTTP (NO User-Agent)
2. Parse HTML with BeautifulSoup to extract article links
3. Track seen URLs in PostgreSQL database
4. Only process NEW articles (not in database)
5. Fetch each article page to get publication date
6. Filter by date: only articles from today/yesterday

Usage:
    scraper = LandezineScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import re
import asyncio
from typing import Optional, List
from datetime import datetime, timezone, timedelta

try:
    import requests
    from bs4 import BeautifulSoup
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    print("⚠️  requests or beautifulsoup4 not installed")
    print("Install with: pip install requests beautifulsoup4")

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker


class LandezineScraper(BaseCustomScraper):
    """
    Simple HTTP scraper for Landezine.com
    Uses basic requests without User-Agent (site blocks User-Agent headers).
    """

    source_id = "landezine"
    source_name = "Landezine"
    base_url = "https://landezine.com"

    # Configuration
    MAX_ARTICLE_AGE_DAYS = 2  # Today + yesterday
    REQUEST_TIMEOUT = 15  # Seconds

    def __init__(self):
        """Initialize scraper with article tracker."""
        # Don't call super().__init__() as we don't need browser
        if not all([self.source_id, self.source_name, self.base_url]):
            raise ValueError(
                f"{self.__class__.__name__} must define source_id, source_name, and base_url"
            )

        if not HTTP_AVAILABLE:
            raise ImportError(
                "requests and beautifulsoup4 required. "
                "Install with: pip install requests beautifulsoup4"
            )

        self.tracker: Optional[ArticleTracker] = None

        print(f"[{self.source_id}] Simple HTTP scraper initialized")

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _fetch_page(self, url: str) -> str:
        """
        Fetch page HTML using basic requests (NO User-Agent).

        CRITICAL: Do NOT add User-Agent header - Landezine blocks it!

        Args:
            url: URL to fetch

        Returns:
            HTML content as string
        """
        print(f"[{self.source_id}] Fetching: {url[:60]}...")

        # NO headers - Landezine blocks User-Agent!
        response = requests.get(url, timeout=self.REQUEST_TIMEOUT)
        response.raise_for_status()

        print(f"[{self.source_id}] ✅ Got {len(response.content)} bytes (status {response.status_code})")
        return response.text

    def _parse_homepage(self, html: str) -> List[dict]:
        """
        Parse homepage HTML to extract article data.

        Args:
            html: Homepage HTML

        Returns:
            List of dicts with title, link, description, image_url
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles = []

        # Landezine uses WordPress - typical selectors
        article_selectors = [
            'article',
            '.post',
            '[class*="post-"]',
            '.entry',
            '[class*="entry"]'
        ]

        article_elements = []
        for selector in article_selectors:
            elements = soup.select(selector)
            if elements:
                print(f"[{self.source_id}] Found {len(elements)} articles with selector: {selector}")
                article_elements = elements
                break

        if not article_elements:
            print(f"[{self.source_id}] ⚠️  No articles found with standard selectors")
            return []

        for article_el in article_elements:
            try:
                # Extract title and link
                title_el = article_el.select_one('h1, h2, h3, .entry-title, [class*="title"]')
                if not title_el:
                    continue

                link_el = title_el.find('a') or article_el.select_one('a[href*="/"]')
                if not link_el:
                    continue

                title = title_el.get_text(strip=True)
                link = link_el.get('href', '')

                # Make URL absolute
                if link and not link.startswith('http'):
                    link = self.base_url.rstrip('/') + '/' + link.lstrip('/')

                # Extract description
                desc_el = article_el.select_one('.entry-content, .excerpt, p')
                description = desc_el.get_text(strip=True) if desc_el else ''

                # Extract image
                img_el = article_el.select_one('img')
                image_url = img_el.get('src', '') if img_el else None

                # Make image URL absolute
                if image_url and not image_url.startswith('http'):
                    image_url = self.base_url.rstrip('/') + '/' + image_url.lstrip('/')

                if title and link:
                    articles.append({
                        'title': title,
                        'link': link,
                        'description': description[:500],  # Limit length
                        'image_url': image_url
                    })

            except Exception as e:
                print(f"[{self.source_id}] ⚠️  Error parsing article: {e}")
                continue

        print(f"[{self.source_id}] Extracted {len(articles)} articles from homepage")
        return articles

    def _parse_article_page(self, html: str, url: str) -> dict:
        """
        Parse individual article page to extract metadata.

        Args:
            html: Article page HTML
            url: Article URL

        Returns:
            Dict with date_text, hero_image_url
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Look for publication date
        date_text = ''

        # Try meta tags first
        date_meta = (
            soup.select_one('meta[property="article:published_time"]') or
            soup.select_one('meta[name="publication_date"]') or
            soup.select_one('time[datetime]')
        )

        if date_meta:
            date_text = date_meta.get('content') or date_meta.get('datetime', '')

        # Try text patterns if meta tags didn't work
        if not date_text:
            body_text = soup.get_text()

            # Pattern: "16 January 2026" or "January 16, 2026"
            pattern = r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})'
            match = re.search(pattern, body_text, re.IGNORECASE)

            if match:
                date_text = match.group(0)

        # Get og:image (hero image)
        hero_image_url = None
        og_image = soup.select_one('meta[property="og:image"]')

        if og_image:
            hero_image_url = og_image.get('content', '')
            # Make absolute
            if hero_image_url and not hero_image_url.startswith('http'):
                hero_image_url = self.base_url.rstrip('/') + '/' + hero_image_url.lstrip('/')

        return {
            'date_text': date_text,
            'hero_image_url': hero_image_url
        }

    async def fetch_articles(self, hours: int = 24) -> List[dict]:
        """
        Fetch new articles using simple HTTP scraping.

        Args:
            hours: Not used (kept for compatibility)

        Workflow:
        1. Fetch homepage HTML (no User-Agent header!)
        2. Parse to extract article links
        3. Filter to NEW URLs only (database)
        4. For each new article:
           - Fetch article page
           - Extract publication date
           - Filter by date (today/yesterday only)
           - Build article dict
        5. Mark URLs as seen in database

        Returns:
            List of article dicts (only new articles from today/yesterday)
        """
        max_new = 10
        print(f"[{self.source_id}] Starting simple HTTP scraping...")

        await self._ensure_tracker()

        try:
            # ============================================================
            # Step 1: Fetch Homepage
            # ============================================================

            html = self._fetch_page(self.base_url)

            if not html:
                print(f"[{self.source_id}] Failed to fetch homepage")
                return []

            # ============================================================
            # Step 2: Parse Homepage
            # ============================================================

            homepage_articles = self._parse_homepage(html)

            if not homepage_articles:
                print(f"[{self.source_id}] No articles found on homepage")
                return []

            # ============================================================
            # Step 3: Filter to NEW URLs
            # ============================================================

            all_urls = [a['link'] for a in homepage_articles]

            if not self.tracker:
                raise RuntimeError("Article tracker not initialized")

            new_urls = await self.tracker.filter_new_articles(self.source_id, all_urls)

            if not new_urls:
                print(f"[{self.source_id}] No new articles (all URLs seen before)")
                return []

            # Limit to max_new
            if len(new_urls) > max_new:
                print(f"[{self.source_id}] Limiting to {max_new} articles (found {len(new_urls)} new)")
                new_urls = new_urls[:max_new]

            print(f"[{self.source_id}] Processing {len(new_urls)} new articles")

            # ============================================================
            # Step 4: Fetch Each Article
            # ============================================================

            new_articles = []
            skipped_old = 0
            skipped_error = 0

            for i, url in enumerate(new_urls, 1):
                homepage_data = next((a for a in homepage_articles if a['link'] == url), None)

                if not homepage_data:
                    continue

                print(f"   [{i}/{len(new_urls)}] {homepage_data['title'][:50]}...")

                try:
                    # Fetch article page
                    article_html = self._fetch_page(url)

                    # Parse metadata
                    metadata = self._parse_article_page(article_html, url)

                    # Parse date
                    published = self._parse_date(metadata['date_text'])

                    # ============================================================
                    # DATE FILTERING
                    # ============================================================

                    if published:
                        article_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                        current_date = datetime.now(timezone.utc)
                        days_old = (current_date - article_date).days

                        if days_old > self.MAX_ARTICLE_AGE_DAYS:
                            print(f"      ⏭️  Skipping old article ({days_old} days old)")
                            skipped_old += 1
                            continue

                        print(f"      ✅ Fresh article ({days_old} day(s) old)")
                    else:
                        print(f"      ⚠️  No date found - including anyway")

                    # Build hero image
                    hero_image = None
                    if metadata.get('hero_image_url'):
                        hero_image = {
                            "url": metadata['hero_image_url'],
                            "width": None,
                            "height": None,
                            "source": "scraper"
                        }
                    elif homepage_data.get('image_url'):
                        hero_image = {
                            "url": homepage_data['image_url'],
                            "width": None,
                            "height": None,
                            "source": "scraper"
                        }

                    # Create article dict
                    article = self._create_article_dict(
                        title=homepage_data['title'],
                        link=url,
                        description=homepage_data.get('description', ''),
                        published=published,
                        hero_image=hero_image
                    )

                    if self._validate_article(article):
                        new_articles.append(article)

                    # Small delay to be polite
                    await asyncio.sleep(0.5)

                except Exception as e:
                    print(f"      ⚠️  Error: {e}")
                    skipped_error += 1
                    continue

            # ============================================================
            # Step 5: Mark as Seen
            # ============================================================

            if not self.tracker:
                raise RuntimeError("Article tracker not initialized")

            await self.tracker.mark_as_seen(self.source_id, new_urls)

            # ============================================================
            # Summary
            # ============================================================

            print(f"\n[{self.source_id}] 📊 Processing Summary:")
            print(f"   Articles on homepage: {len(homepage_articles)}")
            print(f"   New URLs: {len(new_urls)}")
            print(f"   Skipped (too old): {skipped_old}")
            print(f"   Skipped (errors): {skipped_error}")
            print(f"   ✅ Successfully scraped: {len(new_articles)}")

            return new_articles

        except Exception as e:
            print(f"[{self.source_id}] Error in HTTP scraping: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def test_connection(self) -> bool:
        """Test if we can access the site via HTTP."""
        try:
            html = self._fetch_page(self.base_url)
            if html and len(html) > 1000:
                print(f"[{self.source_id}] ✅ HTTP connection test: OK")
                return True
            else:
                print(f"[{self.source_id}] ⚠️  HTTP connection test: content too short")
                return False
        except Exception as e:
            print(f"[{self.source_id}] ❌ HTTP connection test failed: {e}")
            return False

    async def close(self):
        """Close tracker connection."""
        if self.tracker:
            await self.tracker.close()
            self.tracker = None

        print(f"[{self.source_id}] HTTP scraper closed")


# Register this scraper
custom_scraper_registry.register(LandezineScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_landezine_scraper():
    """Test the simple HTTP scraper."""
    print("=" * 60)
    print("Testing Landezine Simple HTTP Scraper")
    print("=" * 60)

    scraper = LandezineScraper()

    try:
        # Test connection
        print("\n1. Testing HTTP connection...")
        connected = await scraper.test_connection()

        if not connected:
            print("   ❌ Connection failed")
            return

        # Show tracker stats
        print("\n2. Checking tracker stats...")
        await scraper._ensure_tracker()

        if not scraper.tracker:
            print("   ⚠️  Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="landezine")

        print(f"   Total articles in database: {stats['total_articles']}")
        if stats['oldest_seen']:
            print(f"   Oldest: {stats['oldest_seen']}")
        if stats['newest_seen']:
            print(f"   Newest: {stats['newest_seen']}")

        # Fetch new articles
        print("\n3. Running HTTP scraping...")
        articles = await scraper.fetch_articles(hours=24)

        print(f"\n   ✅ Found {len(articles)} NEW articles")

        # Display articles
        if articles:
            print("\n4. New articles:")
            for i, article in enumerate(articles, 1):
                print(f"\n   --- Article {i} ---")
                print(f"   Title: {article['title'][:60]}...")
                print(f"   Link: {article['link']}")
                print(f"   Published: {article.get('published', 'No date')}")
                print(f"   Hero Image: {'Yes' if article.get('hero_image') else 'No'}")
                print(f"   Description: {article.get('description', '')[:100]}...")
        else:
            print("\n4. No new articles (all previously seen)")

        # Show updated stats
        print("\n5. Updated tracker stats...")
        if not scraper.tracker:
            print("   ⚠️  Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="landezine")
        print(f"   Total articles in database: {stats['total_articles']}")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_landezine_scraper())