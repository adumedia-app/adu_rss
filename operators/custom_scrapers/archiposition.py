# operators/custom_scrapers/archiposition.py
"""
Archiposition Custom Scraper - HTML Pattern Approach (Simplified)
Scrapes architecture news from Archiposition (Chinese architecture magazine)

Site: https://www.archiposition.com/category/1675
Strategy: Extract links matching /items/ pattern, filter out section URLs

Pattern Analysis:
- Article links: /items/[short-hex-id] (e.g., /items/131941b2fa)
- Section links to exclude: /items/competition, /items/spaceresearch, etc.

Section URLs (hardcoded exclusions):
- /items/competition - 招标竞赛组织
- /items/spaceresearch - 空间研究
- /items/customize - 旅行定制
- /items/20180525080701 - 策划
- /items/20180530191342 - 策展
- /items/20180527092142 - 图书出版
- /items/jobservice - 招聘投放
- /items/20180528083806 - 媒体推广
- /items/20180527092602 - 场地租赁

Requirements:
- User-Agent header required to avoid 403

Usage:
    scraper = ArchipositionScraper()
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


class ArchipositionScraper(BaseCustomScraper):
    """
    HTML pattern-based custom scraper for Archiposition.
    Extracts article links from HTML, filters out section URLs - no AI needed.
    """

    source_id = "archiposition"
    source_name = "Archiposition"
    base_url = "https://www.archiposition.com/category/1675"

    # Configuration
    MAX_ARTICLE_AGE_DAYS = 14
    MAX_NEW_ARTICLES = 15

    # URL pattern for items
    ARTICLE_PATTERN = re.compile(r'/items/([^"\'>\s/]+)')

    # Section URLs to exclude (not real articles)
    EXCLUDED_SLUGS = {
        'competition',      # 招标竞赛组织
        'spaceresearch',    # 空间研究
        'customize',        # 旅行定制
        '20180525080701',   # 策划
        '20180530191342',   # 策展
        '20180527092142',   # 图书出版
        'jobservice',       # 招聘投放
        '20180528083806',   # 媒体推广
        '20180527092602',   # 场地租赁
    }

    def __init__(self):
        """Initialize scraper with article tracker."""
        super().__init__()
        self.tracker: Optional[ArticleTracker] = None

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _is_valid_article_slug(self, slug: str) -> bool:
        """
        Check if a slug represents a real article (not a section).

        Valid articles have short alphanumeric IDs like '131941b2fa'.
        Sections have word-based paths or old date-based IDs.

        Args:
            slug: The URL slug to check

        Returns:
            True if valid article slug
        """
        # Check excluded list
        if slug in self.EXCLUDED_SLUGS:
            return False

        # Check if it's an old date-based ID (14 digits like 20180525080701)
        if re.match(r'^\d{14}$', slug):
            return False

        # Check if it contains only letters (likely a section name)
        if re.match(r'^[a-z]+$', slug.lower()):
            return False

        # Valid articles usually have alphanumeric IDs
        return True

    def _extract_articles_from_html(self, html: str) -> List[Tuple[str, str]]:
        """
        Extract article URLs and titles from HTML.

        Finds all /items/ links and filters out section URLs.

        Args:
            html: Page HTML content

        Returns:
            List of tuples: (url, title)
        """
        soup = BeautifulSoup(html, 'html.parser')
        articles: List[Tuple[str, str]] = []
        seen_urls: set[str] = set()

        # Find all links with /items/ pattern
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            match = self.ARTICLE_PATTERN.search(href)

            if not match:
                continue

            slug = match.group(1)

            # Skip section URLs
            if not self._is_valid_article_slug(slug):
                continue

            # Build full URL
            if href.startswith('/'):
                full_url = urljoin("https://www.archiposition.com", href)
            else:
                full_url = href

            # Skip duplicates
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Get title from link text or nearby elements
            title = link.get_text(strip=True)

            # If link text is empty (image link), look for title in parent
            if not title or len(title) < 3:
                parent = link.find_parent(['div', 'article', 'li'])
                if parent:
                    # Look for heading or title class
                    title_elem = parent.find(['h1', 'h2', 'h3', 'h4', '.title', '.name'])
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                    else:
                        # Get first substantial text
                        title = parent.get_text(strip=True)[:100]

            # Fallback: use slug as title
            if not title or len(title) < 3:
                title = slug

            # Clean up title (remove extra whitespace)
            title = ' '.join(title.split())[:150]

            articles.append((full_url, title))

        return articles

    async def _get_article_data(self, page, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Visit article page and extract publication date and hero image.

        Looks for common date patterns in Chinese sites and extracts hero image.

        Args:
            page: Playwright page object
            url: Article URL

        Returns:
            Tuple of (ISO format date string or None, hero_image_url or None)
        """
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(1000)

            # Get page content
            html = await page.content()

            # Extract date
            date_iso = None
            date_patterns = [
                # YYYY-MM-DD or YYYY/MM/DD
                (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda m: (m.group(1), m.group(2), m.group(3))),
                # YYYY年MM月DD日
                (r'(\d{4})年(\d{1,2})月(\d{1,2})日', lambda m: (m.group(1), m.group(2), m.group(3))),
            ]

            for pattern, extractor in date_patterns:
                match = re.search(pattern, html)
                if match:
                    try:
                        year, month, day = extractor(match)
                        date_obj = datetime(
                            year=int(year),
                            month=int(month),
                            day=int(day),
                            tzinfo=timezone.utc
                        )
                        # Sanity check: not in the future, not too old
                        now = datetime.now(timezone.utc)
                        if date_obj <= now and date_obj > now - timedelta(days=365):
                            date_iso = date_obj.isoformat()
                            break
                    except ValueError:
                        continue

            # Extract hero image - try og:image first, then first large image
            hero_image_url = await page.evaluate("""
                () => {
                    // Try og:image first
                    const ogImage = document.querySelector('meta[property="og:image"]');
                    if (ogImage && ogImage.content) {
                        return ogImage.content;
                    }

                    // Try twitter:image
                    const twitterImage = document.querySelector('meta[name="twitter:image"]');
                    if (twitterImage && twitterImage.content) {
                        return twitterImage.content;
                    }

                    // Fallback: find first large image in article content
                    const contentSelectors = [
                        'article img',
                        '.article-content img',
                        '.content img',
                        'main img',
                        '.post img'
                    ];

                    for (const selector of contentSelectors) {
                        const imgs = document.querySelectorAll(selector);
                        for (const img of imgs) {
                            const src = img.src || img.dataset.src || img.dataset.lazySrc;
                            if (!src) continue;

                            // Skip small images, icons, logos
                            const width = img.naturalWidth || img.width || 0;
                            const height = img.naturalHeight || img.height || 0;

                            // If dimensions known, check size
                            if (width > 0 && height > 0) {
                                if (width >= 300 && height >= 200) {
                                    return src;
                                }
                            } else {
                                // If dimensions unknown, check URL doesn't look like icon/logo
                                const srcLower = src.toLowerCase();
                                if (!srcLower.includes('logo') && 
                                    !srcLower.includes('icon') && 
                                    !srcLower.includes('avatar') &&
                                    !srcLower.includes('placeholder')) {
                                    return src;
                                }
                            }
                        }
                    }

                    return null;
                }
            """)

            return date_iso, hero_image_url

        except Exception as e:
            print(f"[{self.source_id}] Article data extraction error for {url}: {e}")
            return None, None

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
        Fetch new articles from Archiposition.

        Workflow:
        1. Load category page with User-Agent header
        2. Extract all /items/ links from HTML
        3. Filter out known section URLs
        4. Check database for new URLs
        5. For new articles: visit page to get date and hero image
        6. Filter by date (within MAX_ARTICLE_AGE_DAYS)
        7. Download and save hero images to R2
        8. Return article dicts

        Args:
            hours: Ignored (we use database tracking instead)

        Returns:
            List of article dicts
        """
        # Initialize statistics tracking
        self._init_stats()

        print(f"[{self.source_id}] Starting HTML pattern scraping...")

        await self._ensure_tracker()

        try:
            page = await self._create_page()

            try:
                # ============================================================
                # Step 1: Load Category Page
                # ============================================================
                print(f"[{self.source_id}] Loading category page...")
                await page.goto(self.base_url, timeout=self.timeout, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Get page HTML
                html = await page.content()

                # ============================================================
                # Step 2: Extract Article Links
                # ============================================================
                extracted = self._extract_articles_from_html(html)
                print(f"[{self.source_id}] Found {len(extracted)} article links (after filtering sections)")

                if not extracted:
                    print(f"[{self.source_id}] No articles found")
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

                all_urls = [url for url, _ in extracted]

                # Use filter_new_articles to get only new URLs
                new_urls = await self.tracker.filter_new_articles(self.source_id, all_urls)

                # Build new_articles_data with titles for the new URLs
                url_to_title = {url: title for url, title in extracted}
                new_articles_data = [(url, url_to_title[url]) for url in new_urls]

                print(f"[{self.source_id}] Database check:")
                print(f"   Total extracted: {len(extracted)}")
                print(f"   Already seen: {len(extracted) - len(new_articles_data)}")
                print(f"   New articles: {len(new_articles_data)}")

                if not new_articles_data:
                    print(f"[{self.source_id}] No new articles to process")
                    # Mark all as seen
                    await self.tracker.mark_as_seen(self.source_id, all_urls)
                    if self.stats:
                        self.stats.log_final_count(0)
                        self.stats.print_summary()
                        await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 4: Get Dates, Hero Images, and Build Results
                # ============================================================
                new_articles: list[dict] = []
                skipped_old = 0
                images_saved = 0

                for url, title in new_articles_data[:self.MAX_NEW_ARTICLES]:
                    print(f"\n[{self.source_id}] Processing: {title[:50]}...")

                    # Get publication date and hero image from article page
                    date_iso, hero_image_url = await self._get_article_data(page, url)

                    if date_iso:
                        print(f"[{self.source_id}]    Date: {date_iso[:10]}")

                    # Check date limit
                    if not self._is_within_age_limit(date_iso):
                        print(f"[{self.source_id}]    Skipped (too old)")
                        skipped_old += 1
                        if self.stats:
                            self.stats.log_skipped("too_old")
                        continue

                    # Build article dict
                    article = {
                        'title': title,
                        'link': url,
                        'guid': url,
                        'source_id': self.source_id,
                        'source_name': self.source_name,
                        'custom_scraped': True,
                        'description': '',
                        'full_content': '',
                        'hero_image': None,
                    }

                    if date_iso:
                        article['published'] = date_iso

                    # Download and save hero image to R2
                    if hero_image_url:
                        print(f"[{self.source_id}]    Hero image found: {hero_image_url[:60]}...")
                        hero_image = await self._download_and_save_hero_image(
                            page=page,
                            image_url=hero_image_url,
                            article=article
                        )
                        if hero_image:
                            article['hero_image'] = hero_image
                            if hero_image.get('r2_path'):
                                images_saved += 1
                    else:
                        print(f"[{self.source_id}]    No hero image found")

                    new_articles.append(article)

                    if self.stats:
                        self.stats.log_article_found(url)

                    print(f"[{self.source_id}]    Added to results")

                    # Small delay between article page visits
                    await asyncio.sleep(0.5)

                # ============================================================
                # Step 5: Store All URLs and Finalize
                # ============================================================
                await self.tracker.mark_as_seen(self.source_id, all_urls)

                # Final Summary
                print(f"\n[{self.source_id}] Processing Summary:")
                print(f"   Articles found: {len(extracted)}")
                print(f"   New articles: {len(new_articles_data)}")
                print(f"   Skipped (too old): {skipped_old}")
                print(f"   Hero images saved to R2: {images_saved}")
                print(f"   Returning to pipeline: {len(new_articles)}")

                # Log final count and upload stats
                if self.stats:
                    self.stats.log_final_count(len(new_articles))
                    self.stats.print_summary()
                    await self._upload_stats_to_r2()

                return new_articles

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error in scraping: {e}")
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
custom_scraper_registry.register(ArchipositionScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_archiposition_scraper():
    """Test the HTML pattern scraper."""
    print("=" * 60)
    print("Testing Archiposition HTML Pattern Scraper")
    print("=" * 60)

    # Show TEST_MODE status
    from storage.article_tracker import ArticleTracker
    print(f"\nTEST_MODE: {ArticleTracker.TEST_MODE}")
    if ArticleTracker.TEST_MODE:
        print("   All articles will appear as 'new' (ignoring database)")
    else:
        print("   Normal mode - filtering seen articles")

    scraper = ArchipositionScraper()

    try:
        # Test connection
        print("\n1. Testing connection...")
        connected = await scraper.test_connection()

        if not connected:
            print("   Connection failed")
            return

        # Show tracker stats
        print("\n2. Checking tracker stats...")
        await scraper._ensure_tracker()

        if scraper.tracker:
            stats = await scraper.tracker.get_stats(source_id="archiposition")
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
                hero = article.get('hero_image')
                if hero:
                    print(f"   Hero Image: {hero.get('r2_path', hero.get('url', 'No'))[:50]}...")
                else:
                    print(f"   Hero Image: No")
        else:
            print("\n4. No new articles (all previously seen)")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(test_archiposition_scraper())