# operators/custom_scrapers/landezine.py
"""
Landezine Custom Scraper
Scrapes landscape architecture news from Landezine.com

Site Strategy:
- Homepage doesn't show publication dates
- Solution: Track seen article URLs in PostgreSQL database
- On first run: Mark all visible articles as seen
- On subsequent runs: Only process articles with new URLs
- Click into new articles to get publication date from article page

Database Tracking:
- Uses ArticleTracker to store seen URLs
- Prevents re-processing old articles
- Enables incremental monitoring

Usage:
    from operators.custom_scrapers.landezine import LandezineScraper

    scraper = LandezineScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import re
import asyncio
from typing import Optional, List
from datetime import datetime, timezone

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker


class LandezineScraper(BaseCustomScraper):
    """
    Custom scraper for Landezine.com
    Landscape architecture projects and articles.

    Uses URL tracking to detect new articles since dates aren't on homepage.
    """

    source_id = "landezine"
    source_name = "Landezine"
    base_url = "https://landezine.com"

    def __init__(self):
        """Initialize scraper with article tracker."""
        super().__init__()
        self.tracker: Optional[ArticleTracker] = None

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch new articles from Landezine homepage.

        Strategy:
        1. Get all article URLs from homepage
        2. Filter to only URLs not seen before (using database)
        3. Click into each new article to get publication date
        4. Mark new URLs as seen in database

        Args:
            hours: Not used (kept for compatibility with base class)

        Returns:
            List of article dicts (only new articles)
        """
        max_new = 10  # Process up to 10 new articles per run

        print(f"[{self.source_id}] Fetching new articles...")

        await self._ensure_tracker()

        try:
            page = await self._create_page()

            try:
                # ============================================================
                # Step 1: Get all article URLs from homepage
                # ============================================================

                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_timeout(2000)

                # Extract all article URLs and basic info
                homepage_articles = await page.evaluate(r"""
                    () => {
                        const articles = [];

                        // Look for article elements
                        const selectors = [
                            'article',
                            '.post',
                            '[class*="article"]',
                            '.entry'
                        ];

                        let articleElements = [];
                        for (const selector of selectors) {
                            const elements = document.querySelectorAll(selector);
                            if (elements.length > 0) {
                                articleElements = Array.from(elements);
                                break;
                            }
                        }

                        articleElements.forEach(article => {
                            // Extract title
                            const titleEl = article.querySelector('h1, h2, h3, .title, [class*="title"]');
                            const title = titleEl ? titleEl.textContent.trim() : '';

                            // Extract link
                            const linkEl = article.querySelector('a[href]');
                            const link = linkEl ? linkEl.href : '';

                            // Extract description/excerpt
                            const excerptEl = article.querySelector('p, .excerpt, .description, [class*="excerpt"]');
                            const description = excerptEl ? excerptEl.textContent.trim() : '';

                            // Extract image
                            const imgEl = article.querySelector('img');
                            const imageUrl = imgEl ? imgEl.src : null;
                            const imageWidth = imgEl ? imgEl.naturalWidth || imgEl.width : null;
                            const imageHeight = imgEl ? imgEl.naturalHeight || imgEl.height : null;

                            // Only include if we have essential data
                            if (title && link) {
                                articles.push({
                                    title: title,
                                    link: link,
                                    description: description,
                                    image_url: imageUrl,
                                    image_width: imageWidth,
                                    image_height: imageHeight,
                                });
                            }
                        });

                        return articles;
                    }
                """)

                print(f"[{self.source_id}] Found {len(homepage_articles)} articles on homepage")

                if not homepage_articles:
                    print(f"[{self.source_id}] No articles found on homepage")
                    return []

                # ============================================================
                # Step 2: Filter to only NEW article URLs
                # ============================================================

                all_urls = [a['link'] for a in homepage_articles]

                # Ensure tracker is initialized
                if not self.tracker:
                    await self._ensure_tracker()

                new_urls = await self.tracker.filter_new_articles(self.source_id, all_urls)

                if not new_urls:
                    print(f"[{self.source_id}] No new articles found (all URLs seen before)")
                    return []

                # Limit to max_new
                if len(new_urls) > max_new:
                    print(f"[{self.source_id}] Limiting to {max_new} newest articles (found {len(new_urls)})")
                    new_urls = new_urls[:max_new]

                print(f"[{self.source_id}] Processing {len(new_urls)} new articles")

                # ============================================================
                # Step 3: Click into each NEW article to get publication date
                # ============================================================

                new_articles = []

                for i, url in enumerate(new_urls, 1):
                    # Find the homepage article data
                    homepage_data = next((a for a in homepage_articles if a['link'] == url), None)

                    if not homepage_data:
                        continue

                    print(f"   [{i}/{len(new_urls)}] {homepage_data['title'][:50]}...")

                    try:
                        # Navigate to article page
                        await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                        await page.wait_for_timeout(1500)

                        # Extract publication date and other metadata from article page
                        # Use raw string for regex patterns to avoid escape sequence warnings
                        article_metadata = await page.evaluate(r"""
                            () => {
                                // Look for publication date - using proper regex escaping
                                const datePatterns = [
                                    /(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})/i,
                                    /(\d{4})-(\d{2})-(\d{2})/
                                ];

                                let dateText = '';
                                const bodyText = document.body.textContent;

                                for (const pattern of datePatterns) {
                                    const match = bodyText.match(pattern);
                                    if (match) {
                                        dateText = match[0];
                                        break;
                                    }
                                }

                                // Also check meta tags for date
                                const articlePublished = document.querySelector('meta[property="article:published_time"]');
                                if (articlePublished && !dateText) {
                                    dateText = articlePublished.content;
                                }

                                // Get og:image (hero image)
                                const ogImage = document.querySelector('meta[property="og:image"]');
                                const heroImageUrl = ogImage ? ogImage.content : null;

                                return {
                                    date_text: dateText,
                                    hero_image_url: heroImageUrl
                                };
                            }
                        """)

                        # Parse the date
                        published = self._parse_date(article_metadata['date_text'])

                        # Build hero image dict (prefer og:image from article page)
                        hero_image = None
                        if article_metadata.get('hero_image_url'):
                            hero_image = {
                                "url": article_metadata['hero_image_url'],
                                "width": None,
                                "height": None,
                                "source": "scraper"
                            }
                        elif homepage_data.get('image_url'):
                            hero_image = {
                                "url": homepage_data['image_url'],
                                "width": homepage_data.get('image_width'),
                                "height": homepage_data.get('image_height'),
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

                        # Validate and add
                        if self._validate_article(article):
                            new_articles.append(article)

                        # Small delay between article page loads
                        await asyncio.sleep(0.5)

                    except Exception as e:
                        print(f"      ⚠️ Error processing article: {e}")
                        continue

                # ============================================================
                # Step 4: Mark all new URLs as seen (even if some failed)
                # ============================================================

                if self.tracker:
                    await self.tracker.mark_as_seen(self.source_id, new_urls)

                print(f"[{self.source_id}] Successfully extracted {len(new_articles)} new articles")
                return new_articles

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error fetching articles: {e}")
            return []

    async def close(self):
        """Close browser and tracker connections."""
        await super().close()

        if self.tracker:
            await self.tracker.close()
            self.tracker = None


# Register this scraper
custom_scraper_registry.register(LandezineScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_landezine_scraper():
    """Test the Landezine scraper with URL tracking."""
    print("=" * 60)
    print("Testing Landezine Custom Scraper (with URL tracking)")
    print("=" * 60)

    scraper = LandezineScraper()

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
            stats = await scraper.tracker.get_stats(source_id="landezine")

            print(f"   Total articles in database: {stats['total_articles']}")
            if stats['oldest_seen']:
                print(f"   Oldest: {stats['oldest_seen']}")
            if stats['newest_seen']:
                print(f"   Newest: {stats['newest_seen']}")

        # Fetch new articles (limit to 5 for testing)
        print("\n3. Fetching new articles (max 5)...")
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
        if scraper.tracker:
            print("\n5. Updated tracker stats...")
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