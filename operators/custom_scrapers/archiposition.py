# operators/custom_scrapers/archiposition.py
"""
Archiposition Custom Scraper - HTML Pattern Approach with Hero Image Extraction
Scrapes architecture news from Archiposition (Chinese architecture magazine)

Site: https://www.archiposition.com/category/1675
Strategy: Extract links matching /items/ pattern, filter out section URLs

Key Features:
- HTML pattern extraction (no AI needed for URL discovery)
- Hero image extraction from article pages (site lacks og:image)
- Direct R2 upload of hero images
- Date extraction from Chinese date formats

Pattern Analysis:
- Article links: /items/[short-hex-id] (e.g., /items/131941b2fa)
- Section links to exclude: /items/competition, /items/spaceresearch, etc.
- Hero images: First large image in .detail-content

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
from storage.r2 import R2Storage


class ArchipositionScraper(BaseCustomScraper):
    """
    HTML pattern-based custom scraper for Archiposition.
    Extracts article links from HTML, filters out section URLs.
    Handles hero image extraction since site lacks og:image meta tags.
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
        self.r2: Optional[R2Storage] = None

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _ensure_r2(self):
        """Ensure R2 storage is initialized."""
        if not self.r2:
            self.r2 = R2Storage()
            print(f"[{self.source_id}] R2 storage initialized")

    def _is_valid_article_slug(self, slug: str) -> bool:
        """
        Check if a slug represents a real article (not a section).

        Valid articles have short alphanumeric IDs like '131941b2fa'.
        Sections have word-based paths or old date-based IDs.

        Args:
            slug: The URL slug after /items/

        Returns:
            True if it's a valid article, False if it's a section
        """
        # Check against known section slugs
        if slug in self.EXCLUDED_SLUGS:
            return False

        # Valid article IDs are short hex-like strings (8-12 chars)
        # Section URLs tend to be longer or contain words
        if len(slug) > 20:
            return False

        # Check if it looks like a hex ID (alphanumeric, mostly lowercase)
        if re.match(r'^[a-f0-9]{8,12}$', slug):
            return True

        # Check for date-based IDs (old format: 20180525080701)
        if re.match(r'^\d{14}$', slug):
            # These are section pages, not articles
            return False

        # Allow other short alphanumeric slugs
        if re.match(r'^[a-zA-Z0-9]{6,15}$', slug):
            return True

        return False

    def _extract_articles_from_html(self, html: str) -> List[Tuple[str, str]]:
        """
        Extract article URLs and titles from category page HTML.

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

    async def _get_article_metadata(self, page, url: str) -> dict:
        """
        Visit article page and extract date + hero image.

        Archiposition doesn't have og:image, so we extract the first
        large image from the article content.

        Args:
            page: Playwright page object
            url: Article URL

        Returns:
            Dict with 'date' (ISO string or None) and 'hero_image' (dict or None)
        """
        result = {
            'date': None,
            'hero_image': None,
            'title': None
        }

        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)  # Wait for images to load

            # Extract metadata using JavaScript
            metadata = await page.evaluate("""
                () => {
                    const result = {
                        date_text: null,
                        hero_image_url: null,
                        title: null
                    };

                    // Extract title from detail-title or h1
                    const titleEl = document.querySelector('.detail-title') ||
                                    document.querySelector('h1.user-content-item') ||
                                    document.querySelector('h1');
                    if (titleEl) {
                        result.title = titleEl.textContent.trim();
                    }

                    // Extract date from detail-tip (format: "编辑：xxx | 校对：xxx | 2026.01.16 09:53")
                    const tipEl = document.querySelector('.detail-tip');
                    if (tipEl) {
                        result.date_text = tipEl.textContent.trim();
                    }

                    // Extract hero image - first large image in detail-content
                    // Archiposition doesn't have og:image, images are in article body
                    const selectors = [
                        '.detail-content img',
                        '.detail-content figure img',
                        'article img',
                        '.post-content img'
                    ];

                    for (const selector of selectors) {
                        const imgs = document.querySelectorAll(selector);
                        for (const img of imgs) {
                            // Get src from various attributes
                            let src = img.src || img.dataset.src || img.getAttribute('data-src');
                            if (!src) continue;

                            // Skip small images (icons, logos)
                            const width = img.naturalWidth || img.width || 0;
                            const height = img.naturalHeight || img.height || 0;

                            // Skip if dimensions are known and too small
                            if (width > 0 && width < 300) continue;
                            if (height > 0 && height < 200) continue;

                            // Skip common non-content patterns
                            const srcLower = src.toLowerCase();
                            if (srcLower.includes('logo') ||
                                srcLower.includes('icon') ||
                                srcLower.includes('avatar') ||
                                srcLower.includes('qrcode') ||
                                srcLower.includes('weixin') ||
                                srcLower.includes('wechat')) continue;

                            // Found a valid hero image
                            result.hero_image_url = src;
                            break;
                        }
                        if (result.hero_image_url) break;
                    }

                    return result;
                }
            """)

            # Parse title
            if metadata.get('title'):
                result['title'] = metadata['title']

            # Parse date from Chinese format
            if metadata.get('date_text'):
                result['date'] = self._parse_chinese_date(metadata['date_text'])

            # Build hero image dict
            if metadata.get('hero_image_url'):
                result['hero_image'] = {
                    'url': metadata['hero_image_url'],
                    'width': None,
                    'height': None,
                    'source': 'article-content'
                }

            return result

        except Exception as e:
            print(f"[{self.source_id}] Metadata extraction error for {url}: {e}")
            return result

    def _parse_chinese_date(self, text: str) -> Optional[str]:
        """
        Parse date from Chinese text.

        Handles formats like:
        - "2026.01.16 09:53"
        - "2026-01-16"
        - "2026/01/16"
        - "2026年01月16日"

        Args:
            text: Text containing date

        Returns:
            ISO format date string or None
        """
        if not text:
            return None

        # Date patterns to try
        patterns = [
            # YYYY.MM.DD HH:MM or YYYY.MM.DD
            (r'(\d{4})\.(\d{1,2})\.(\d{1,2})', lambda m: (m.group(1), m.group(2), m.group(3))),
            # YYYY-MM-DD or YYYY/MM/DD
            (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda m: (m.group(1), m.group(2), m.group(3))),
            # YYYY年MM月DD日
            (r'(\d{4})年(\d{1,2})月(\d{1,2})日', lambda m: (m.group(1), m.group(2), m.group(3))),
        ]

        for pattern, extractor in patterns:
            match = re.search(pattern, text)
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
                        return date_obj.isoformat()
                except ValueError:
                    continue

        return None

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

    async def _download_and_upload_hero_image(
        self,
        page,
        hero_image: dict,
        article: dict
    ) -> Optional[dict]:
        """
        Download hero image and upload to R2.

        Uses multiple strategies:
        1. HTTP request with User-Agent headers (fastest)
        2. Cloudscraper for Cloudflare-protected images (fallback)
        3. Playwright page navigation (last resort)

        Args:
            page: Playwright page for downloading
            hero_image: Dict with 'url' key
            article: Article dict for building R2 path

        Returns:
            Updated hero_image dict with r2_path and r2_url, or None if failed
        """
        if not hero_image or not hero_image.get('url'):
            return None

        url = hero_image['url']
        image_bytes = None

        try:
            # Ensure R2 is initialized
            self._ensure_r2()

            print(f"      Downloading hero image...")

            # Strategy 1: Simple HTTP request with User-Agent
            try:
                import aiohttp
                headers = {
                    "User-Agent": self.user_agent,
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://www.archiposition.com/",
                }

                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                        if response.status == 200:
                            image_bytes = await response.read()
                            print(f"      Downloaded (aiohttp): {len(image_bytes)} bytes")
            except Exception as e:
                print(f"      aiohttp failed: {e}")

            # Strategy 2: Cloudscraper fallback for Cloudflare protection
            if not image_bytes:
                try:
                    import cloudscraper
                    print(f"      Trying cloudscraper...")

                    scraper = cloudscraper.create_scraper(
                        browser={'browser': 'chrome', 'platform': 'darwin', 'mobile': False}
                    )
                    response = scraper.get(url, timeout=15)

                    if response.status_code == 200:
                        image_bytes = response.content
                        print(f"      Downloaded (cloudscraper): {len(image_bytes)} bytes")
                    else:
                        print(f"      Cloudscraper failed: HTTP {response.status_code}")
                except ImportError:
                    print(f"      Cloudscraper not available")
                except Exception as e:
                    print(f"      Cloudscraper failed: {e}")

            # Strategy 3: Playwright page navigation (last resort)
            if not image_bytes:
                try:
                    print(f"      Trying Playwright...")
                    # Set referer header
                    await page.set_extra_http_headers({
                        "User-Agent": self.user_agent,
                        "Referer": "https://www.archiposition.com/",
                    })
                    response = await page.goto(url, timeout=15000)

                    if response and response.ok:
                        image_bytes = await response.body()
                        print(f"      Downloaded (Playwright): {len(image_bytes)} bytes")
                    else:
                        print(f"      Playwright failed: HTTP {response.status if response else 'no response'}")
                except Exception as e:
                    print(f"      Playwright failed: {e}")

            # Upload to R2 if we got image bytes
            if image_bytes and self.r2:
                updated_hero = self.r2.save_hero_image(
                    image_bytes=image_bytes,
                    article=article,
                    source=self.source_id
                )

                if updated_hero and updated_hero.get('r2_path'):
                    print(f"      Uploaded to R2: {updated_hero['r2_path']}")
                    return updated_hero

            if not image_bytes:
                print(f"      All download methods failed")

            return hero_image

        except Exception as e:
            print(f"      Hero image error: {e}")
            return hero_image

    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch new articles from Archiposition.

        Workflow:
        1. Load category page with User-Agent header
        2. Extract all /items/ links from HTML
        3. Filter out known section URLs
        4. Check database for new URLs
        5. For new articles: visit page to get date + hero image
        6. Filter by date (within MAX_ARTICLE_AGE_DAYS)
        7. Download and upload hero images to R2
        8. Return article dicts for main pipeline

        Args:
            hours: Ignored (we use database tracking instead)

        Returns:
            List of article dicts for main pipeline
        """
        # Initialize statistics tracking
        self._init_stats()

        print(f"\n[{self.source_id}] Starting HTML pattern scraping...")
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
                # Step 1: Load Category Page
                # ============================================================
                print(f"[{self.source_id}] Loading category page...")
                await page.goto(self.base_url, timeout=self.timeout, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Get page HTML
                html = await page.content()

                # ============================================================
                # Step 2: Extract Articles from HTML
                # ============================================================
                print(f"[{self.source_id}] Extracting articles from HTML...")
                extracted = self._extract_articles_from_html(html)

                print(f"[{self.source_id}] Found {len(extracted)} article links")

                if not extracted:
                    print(f"[{self.source_id}] No articles found on page")
                    if self.stats:
                        self.stats.log_final_count(0)
                        self.stats.print_summary()
                        await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 3: Check Database for New Articles
                # ============================================================
                all_urls = [url for url, _ in extracted]

                if self.tracker:
                    # Filter to only new URLs (not seen before)
                    new_urls = await self.tracker.filter_new_articles(
                        self.source_id,
                        all_urls
                    )
                    # Keep only extracted tuples with new URLs
                    new_url_set = set(new_urls)
                    new_articles_data = [(url, title) for url, title in extracted if url in new_url_set]
                else:
                    new_articles_data = extracted
                    new_urls = all_urls

                print(f"[{self.source_id}] New articles: {len(new_articles_data)}")

                if self.stats:
                    self.stats.log_new_headlines(new_urls, len(extracted))

                if not new_articles_data:
                    print(f"[{self.source_id}] No new articles to process")
                    # Store all URLs as seen
                    if self.tracker:
                        await self.tracker.mark_as_seen(self.source_id, all_urls)
                    if self.stats:
                        self.stats.log_final_count(0)
                        self.stats.print_summary()
                        await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 4: Get Metadata, Hero Images, and Build Results
                # ============================================================
                new_articles: list[dict] = []
                skipped_old = 0
                hero_images_found = 0

                for url, title in new_articles_data[:self.MAX_NEW_ARTICLES]:
                    print(f"\n   Processing: {title[:50]}...")

                    # Get metadata from article page (date + hero image)
                    metadata = await self._get_article_metadata(page, url)

                    # Use extracted title if better than URL-based title
                    if metadata.get('title') and len(metadata['title']) > len(title):
                        title = metadata['title']

                    date_iso = metadata.get('date')
                    if date_iso:
                        print(f"      Date: {date_iso[:10]}")

                    # Check date limit
                    if not self._is_within_age_limit(date_iso):
                        print(f"      Skipped (too old)")
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
                    }

                    if date_iso:
                        article['published'] = date_iso

                    # Handle hero image
                    hero_image = metadata.get('hero_image')
                    if hero_image:
                        print(f"      Hero image found: {hero_image['url'][:60]}...")
                        hero_images_found += 1

                        # Download and upload to R2
                        updated_hero = await self._download_and_upload_hero_image(
                            page, hero_image, article
                        )

                        if updated_hero:
                            article['hero_image'] = updated_hero
                    else:
                        print(f"      No hero image found")

                    new_articles.append(article)

                    if self.stats:
                        self.stats.log_article_found(url)

                    print(f"      Added")

                    # Small delay between article page visits
                    await asyncio.sleep(0.5)

                # ============================================================
                # Step 5: Store All URLs and Finalize
                # ============================================================
                if self.tracker:
                    await self.tracker.mark_as_seen(self.source_id, all_urls)

                # Final Summary
                print(f"\n[{self.source_id}] Processing Summary:")
                print(f"   Articles found: {len(extracted)}")
                print(f"   New articles: {len(new_articles_data)}")
                print(f"   Skipped (too old): {skipped_old}")
                print(f"   Hero images found: {hero_images_found}")
                print(f"   Successfully scraped: {len(new_articles)}")

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
    """Test the HTML pattern scraper with hero image extraction."""
    print("=" * 60)
    print("Testing Archiposition Scraper (with Hero Image Extraction)")
    print("=" * 60)

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
        print("\n3. Running scraping with hero image extraction...")
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
                    print(f"   Hero Image URL: {hero.get('url', 'N/A')[:60]}...")
                    if hero.get('r2_path'):
                        print(f"   R2 Path: {hero['r2_path']}")
                    if hero.get('r2_url'):
                        print(f"   R2 URL: {hero['r2_url'][:60]}...")
                else:
                    print(f"   Hero Image: None")
        else:
            print("\n4. No new articles (all previously seen)")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(test_archiposition_scraper())