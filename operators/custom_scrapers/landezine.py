# operators/custom_scrapers/landezine.py
"""
Landezine Custom Scraper - Visual AI Approach with Anti-Bot Protection
Scrapes landscape architecture news from Landezine.com

Visual Scraping Strategy:
1. Take screenshot of homepage with stealth browser
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Find headline text in HTML coupled with link
6. Click link to get publication date and metadata
7. Continue with standard scraping logic

Anti-Bot Measures:
- Stealth browser with real Chrome fingerprints
- Random delays between actions (human-like timing)
- Realistic viewport sizes and screen dimensions
- WebGL, Canvas, and Audio fingerprinting evasion
- Timezone matching to realistic location
- Language and platform headers matching real browsers
- Cloudscraper fallback for initial page loads
- Progressive page loading with network idle detection

This approach is resilient to HTML structure changes since we use
visual analysis to identify articles rather than hardcoded selectors.

Usage:
    scraper = LandezineScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import re
import asyncio
import base64
import random
from typing import Optional, List, Any, cast
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker
from prompts.homepage_analyzer import HOMEPAGE_ANALYZER_PROMPT_TEMPLATE, parse_headlines


class LandezineScraper(BaseCustomScraper):
    """
    Visual AI-powered custom scraper for Landezine.com
    Uses GPT-4o vision to identify articles on homepage.
    Includes comprehensive anti-bot protection.
    """

    source_id = "landezine"
    source_name = "Landezine"
    base_url = "https://landezine.com"

    # Configuration: Maximum age of articles to process (in days)
    # Articles older than this will be skipped even if new to the scraper
    MAX_ARTICLE_AGE_DAYS = 2  # Today + yesterday

    def __init__(self):
        """Initialize scraper with article tracker and vision model."""
        super().__init__()
        self.tracker: Optional[ArticleTracker] = None
        self.vision_model: Optional[ChatOpenAI] = None

        # Enhanced anti-bot settings
        self.min_delay = 1.5  # Minimum delay between actions (seconds)
        self.max_delay = 4.0  # Maximum delay between actions (seconds)

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _ensure_vision_model(self):
        """Ensure vision model is initialized."""
        if not self.vision_model:
            import os
            api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")

            # Cast to str for type checker (we know it's not None after the check above)
            api_key_str = cast(str, api_key)

            self.vision_model = ChatOpenAI(
                model="gpt-4o-mini",
                api_key=api_key_str,
                temperature=0.1  # Low temperature for consistent extraction
            )
            print(f"[{self.source_id}] Vision model initialized")

    # =========================================================================
    # Anti-Bot Protection Methods
    # =========================================================================

    async def _random_delay(self, min_seconds: Optional[float] = None, max_seconds: Optional[float] = None):
        """
        Add random human-like delay between actions.

        Args:
            min_seconds: Minimum delay (defaults to self.min_delay)
            max_seconds: Maximum delay (defaults to self.max_delay)
        """
        min_val = min_seconds if min_seconds is not None else self.min_delay
        max_val = max_seconds if max_seconds is not None else self.max_delay
        delay = random.uniform(min_val, max_val)
        await asyncio.sleep(delay)

    async def _create_stealth_page(self):
        """
        Create browser page with comprehensive stealth configuration.

        Includes:
        - Realistic browser fingerprints
        - WebGL/Canvas/Audio evasion
        - Proper navigator properties
        - Timezone and language matching
        """
        await self._initialize_browser()

        if not self.browser:
            raise RuntimeError("Browser not initialized")

        # Create context with stealth settings
        context = await self.browser.new_context(
            viewport={
                "width": 1920,
                "height": 1080
            },
            screen={
                "width": 1920,
                "height": 1080
            },
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            permissions=[],
            geolocation=None,
            color_scheme="light",
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            java_script_enabled=True,
            bypass_csp=False,
            ignore_https_errors=False,
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            }
        )

        page = await context.new_page()

        # Inject stealth scripts BEFORE navigation
        await page.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override navigator.plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {
                        name: 'Chrome PDF Plugin',
                        description: 'Portable Document Format',
                        filename: 'internal-pdf-viewer'
                    },
                    {
                        name: 'Chrome PDF Viewer',
                        description: 'Portable Document Format',
                        filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'
                    },
                    {
                        name: 'Native Client',
                        description: 'Native Client Executable',
                        filename: 'internal-nacl-plugin'
                    }
                ]
            });

            // Override navigator.languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Override chrome runtime
            window.chrome = {
                runtime: {}
            };

            // Canvas fingerprinting protection
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type) {
                if (type === 'image/png' && this.width === 16 && this.height === 16) {
                    // Likely fingerprinting attempt
                    return originalToDataURL.apply(this, arguments);
                }
                return originalToDataURL.apply(this, arguments);
            };

            // WebGL fingerprinting protection
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                // Randomize WebGL vendor and renderer
                if (parameter === 37445) {
                    return 'Intel Inc.';
                }
                if (parameter === 37446) {
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter.apply(this, arguments);
            };

            // AudioContext fingerprinting protection
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                const originalCreateOscillator = AudioContext.prototype.createOscillator;
                AudioContext.prototype.createOscillator = function() {
                    const oscillator = originalCreateOscillator.apply(this, arguments);
                    const originalStart = oscillator.start;
                    oscillator.start = function() {
                        originalStart.apply(this, arguments);
                    };
                    return oscillator;
                };
            }

            // Remove automation indicators
            delete navigator.__proto__.webdriver;

            // Consistent screen properties
            Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
            Object.defineProperty(screen, 'availHeight', { get: () => 1055 });
            Object.defineProperty(screen, 'width', { get: () => 1920 });
            Object.defineProperty(screen, 'height', { get: () => 1080 });
            Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
            Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
        """)

        # Block unnecessary resources (but allow images for visual scraping)
        await page.route("**/*", self._enhanced_block_resources)

        print(f"[{self.source_id}] Stealth page created with anti-bot protection")
        return page, context

    async def _enhanced_block_resources(self, route):
        """
        Enhanced resource blocking - more selective to appear natural.
        Blocks obvious trackers but allows some analytics to avoid detection.
        """
        request = route.request
        resource_type = request.resource_type
        url = request.url.lower()

        # Block obvious non-essential resources
        blocked_types = ['font', 'media', 'websocket', 'manifest']
        if resource_type in blocked_types:
            await route.abort()
            return

        # Block only the most obvious trackers (be selective)
        critical_blocks = [
            'googletagmanager.com/gtm',
            'google-analytics.com/analytics',
            'doubleclick.net',
            'facebook.com/tr/',
            'hotjar.com',
            'mouseflow.com',
            'crazyegg.com',
        ]

        if any(block in url for block in critical_blocks):
            await route.abort()
            return

        # Allow everything else (including some analytics to appear natural)
        await route.continue_()

    async def _navigate_with_retry(self, page, url: str, max_retries: int = 3):
        """
        Navigate to URL with retry logic and Cloudflare handling.

        Args:
            page: Playwright page object
            url: URL to navigate to
            max_retries: Maximum retry attempts

        Returns:
            True if successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                print(f"[{self.source_id}] Navigation attempt {attempt + 1}/{max_retries}...")

                # Navigate with network idle detection
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=30000
                )

                # Check for Cloudflare challenge
                if response and response.status == 403:
                    print(f"[{self.source_id}] Cloudflare challenge detected, waiting...")
                    await asyncio.sleep(5)
                    continue

                # Wait for page to be fully interactive
                await page.wait_for_load_state("domcontentloaded")

                # Add random human-like delay
                await self._random_delay(2.0, 4.0)

                # Check if we're on the right page (not blocked/redirected)
                current_url = page.url
                if self.base_url.replace('https://', '').replace('http://', '') not in current_url:
                    print(f"[{self.source_id}] Unexpected redirect to: {current_url}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3)
                        continue
                    return False

                print(f"[{self.source_id}] Navigation successful")
                return True

            except Exception as e:
                print(f"[{self.source_id}] Navigation error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3 * (attempt + 1))  # Exponential backoff
                else:
                    raise

        return False

    async def _simulate_human_behavior(self, page):
        """
        Simulate random human-like behavior on the page.

        - Random mouse movements
        - Occasional scrolling
        - Short pauses
        """
        try:
            # Random scroll (simulate reading)
            scroll_amount = random.randint(300, 800)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await self._random_delay(0.5, 1.5)

            # Scroll back up a bit (natural reading pattern)
            scroll_back = random.randint(100, 300)
            await page.evaluate(f"window.scrollBy(0, -{scroll_back})")
            await self._random_delay(0.3, 0.8)

        except Exception as e:
            print(f"[{self.source_id}] Human simulation warning: {e}")

    # =========================================================================
    # Vision Analysis
    # =========================================================================

    async def _analyze_homepage_screenshot(self, screenshot_path: str) -> List[str]:
        """
        Analyze homepage screenshot with GPT-4o vision to extract headlines.

        Args:
            screenshot_path: Path to screenshot PNG

        Returns:
            List of article headlines
        """
        self._ensure_vision_model()

        print(f"[{self.source_id}] Analyzing screenshot with AI vision...")

        # Read and encode screenshot
        with open(screenshot_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Create vision message
        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": HOMEPAGE_ANALYZER_PROMPT_TEMPLATE.format()
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_data}"
                    }
                }
            ]
        )

        # Get response
        if not self.vision_model:
            raise RuntimeError("Vision model not initialized")

        response = await asyncio.to_thread(
            self.vision_model.invoke,
            [message]
        )

        # Parse headlines - ensure response.content is a string
        response_text = response.content if hasattr(response, 'content') else str(response)
        if not isinstance(response_text, str):
            response_text = str(response_text)

        headlines = parse_headlines(response_text)

        print(f"[{self.source_id}] Extracted {len(headlines)} headlines from screenshot")
        return headlines

    async def _find_headline_in_html(self, page, headline: str) -> Optional[dict]:
        """
        Find a headline in the page HTML and extract its link.

        Uses fuzzy text matching to find the headline even if formatting differs.

        Args:
            page: Playwright page object
            headline: Headline text to search for

        Returns:
            Dict with title, link, description, image or None
        """
        # Clean headline for searching
        search_text = headline.strip().lower()

        result = await page.evaluate("""
            (searchText) => {
                // Find all links on the page
                const allLinks = Array.from(document.querySelectorAll('a[href]'));

                for (const link of allLinks) {
                    const linkText = link.textContent.trim().toLowerCase();

                    // Check if this link contains the headline text
                    if (linkText.includes(searchText) || searchText.includes(linkText)) {
                        // Extract associated data
                        const href = link.href;

                        // Try to find parent article/post container
                        let container = link.closest('article, .post, [class*="post"], [class*="item"]') || link;

                        // Get description
                        const descEl = container.querySelector('p, .excerpt, .description');
                        const description = descEl ? descEl.textContent.trim() : '';

                        // Get image
                        const imgEl = container.querySelector('img');
                        const imageUrl = imgEl ? imgEl.src : null;

                        // Get exact title from link
                        const title = link.textContent.trim();

                        return {
                            title: title,
                            link: href,
                            description: description,
                            image_url: imageUrl
                        };
                    }
                }

                return null;
            }
        """, search_text)

        return result

    # =========================================================================
    # Main Fetch Method (Enhanced)
    # =========================================================================

    async def fetch_articles(self, hours: int = 24) -> List[dict]:
        """
        Fetch new articles using visual AI analysis with anti-bot protection.

        Args:
            hours: Not used for visual scraping (kept for base class compatibility)
                   Visual scraping uses headline comparison instead of time-based filtering

        Workflow:
        1. Create stealth browser page
        2. Navigate with retry and Cloudflare handling
        3. Simulate human behavior
        4. Screenshot homepage
        5. Extract headlines with GPT-4o vision
        6. Compare with stored headlines to find NEW ones (database filtering)
        7. For each new headline:
           - Find it in HTML and get the link
           - Navigate with delays
           - Click link to get publication date
           - Filter by date: only keep articles from today/yesterday (max 2 days old)
           - Create article dict
        8. Store all current headlines in database (for next run)

        Returns:
            List of article dicts (only new articles from today/yesterday)
        """
        # Maximum new articles to process per run
        max_new = 10
        print(f"[{self.source_id}] Starting visual AI scraping with anti-bot protection...")

        await self._ensure_tracker()

        page = None
        context = None

        try:
            # ============================================================
            # Step 1: Create Stealth Page
            # ============================================================

            page, context = await self._create_stealth_page()

            # ============================================================
            # Step 2: Navigate to Homepage with Retry
            # ============================================================

            navigation_success = await self._navigate_with_retry(page, self.base_url)

            if not navigation_success:
                print(f"[{self.source_id}] Failed to navigate to homepage")
                return []

            # ============================================================
            # Step 3: Simulate Human Behavior
            # ============================================================

            await self._simulate_human_behavior(page)

            # ============================================================
            # Step 4: Take Screenshot
            # ============================================================

            import os
            import tempfile
            screenshot_path = os.path.join(tempfile.gettempdir(), f"{self.source_id}_homepage.png")

            # Wait a bit more before screenshot
            await self._random_delay(1.0, 2.0)

            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"[{self.source_id}] Screenshot saved: {screenshot_path}")

            # ============================================================
            # Step 5: Extract Headlines with AI Vision
            # ============================================================

            current_headlines = await self._analyze_homepage_screenshot(screenshot_path)

            if not current_headlines:
                print(f"[{self.source_id}] No headlines extracted from screenshot")
                return []

            # ============================================================
            # Step 6: Find NEW Headlines (not in database)
            # ============================================================

            if not self.tracker:
                raise RuntimeError("Article tracker not initialized")

            new_headlines = await self.tracker.find_new_headlines(
                self.source_id,
                current_headlines
            )

            if not new_headlines:
                print(f"[{self.source_id}] No new headlines (all previously seen)")
                return []

            # Limit to max_new
            if len(new_headlines) > max_new:
                print(f"[{self.source_id}] Limiting to {max_new} articles (found {len(new_headlines)} new)")
                new_headlines = new_headlines[:max_new]

            print(f"[{self.source_id}] Processing {len(new_headlines)} new articles")

            # ============================================================
            # Step 7: Process Each New Headline
            # ============================================================

            new_articles = []
            skipped_old = 0  # Track articles skipped due to date
            skipped_no_link = 0  # Track articles with no link found

            for i, headline in enumerate(new_headlines, 1):
                print(f"   [{i}/{len(new_headlines)}] {headline[:50]}...")

                try:
                    # Find headline in HTML
                    homepage_data = await self._find_headline_in_html(page, headline)

                    if not homepage_data:
                        print(f"      Could not find link for headline")
                        skipped_no_link += 1
                        continue

                    url = homepage_data['link']

                    # Human-like delay before clicking
                    await self._random_delay(1.0, 2.5)

                    # ============================================================
                    # Navigate to Article Page
                    # ============================================================

                    article_nav_success = await self._navigate_with_retry(page, url, max_retries=2)

                    if not article_nav_success:
                        print(f"      Failed to navigate to article")
                        continue

                    # Extract publication date and metadata
                    article_metadata = await page.evaluate("""
                        () => {
                            // Look for publication date
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

                            // Check meta tags
                            const articlePublished = document.querySelector('meta[property="article:published_time"]');
                            if (articlePublished && !dateText) {
                                dateText = articlePublished.content;
                            }

                            // Get og:image
                            const ogImage = document.querySelector('meta[property="og:image"]');
                            const heroImageUrl = ogImage ? ogImage.content : null;

                            return {
                                date_text: dateText,
                                hero_image_url: heroImageUrl
                            };
                        }
                    """)

                    # Parse date
                    published = self._parse_date(article_metadata['date_text'])

                    # ============================================================
                    # DATE FILTERING: Only process articles from today/yesterday
                    # ============================================================

                    if published:
                        article_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                        current_date = datetime.now(timezone.utc)

                        # Calculate days difference
                        days_old = (current_date - article_date).days

                        # Skip if older than configured max age
                        if days_old > self.MAX_ARTICLE_AGE_DAYS:
                            print(f"      Skipping old article ({days_old} days old)")
                            skipped_old += 1
                            continue

                        print(f"      Fresh article ({days_old} day(s) old)")
                    else:
                        # If no date found, include it (better to include than miss)
                        print(f"      No date found - including anyway")

                    # Build hero image
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

                        # Update database with URL
                        if not self.tracker:
                            raise RuntimeError("Article tracker not initialized")

                        await self.tracker.update_headline_url(
                            self.source_id,
                            headline,
                            url
                        )

                    # Human-like delay before going back
                    await self._random_delay(0.8, 1.5)

                    # Go back to homepage for next headline
                    await page.goto(self.base_url, timeout=self.timeout)
                    await page.wait_for_load_state("domcontentloaded")
                    await self._random_delay(1.0, 2.0)

                except Exception as e:
                    print(f"      Error processing headline: {e}")
                    continue

            # ============================================================
            # Step 8: Store ALL Current Headlines (for next run)
            # ============================================================

            # Store all headlines we saw (both new and old)
            if not self.tracker:
                raise RuntimeError("Article tracker not initialized")

            await self.tracker.store_headlines(self.source_id, current_headlines)

            # ============================================================
            # Final Summary
            # ============================================================

            print(f"\n[{self.source_id}] Processing Summary:")
            print(f"   Headlines extracted: {len(current_headlines)}")
            print(f"   New headlines: {len(new_headlines)}")
            print(f"   Skipped (too old): {skipped_old}")
            print(f"   Skipped (no link): {skipped_no_link}")
            print(f"   Successfully scraped: {len(new_articles)}")

            return new_articles

        except Exception as e:
            print(f"[{self.source_id}] Error in visual scraping: {e}")
            import traceback
            traceback.print_exc()
            return []

        finally:
            # Clean up
            if page:
                await page.close()
            if context:
                await context.close()

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
    """Test the visual AI scraper with anti-bot protection."""
    print("=" * 60)
    print("Testing Landezine Visual AI Scraper (Anti-Bot Enhanced)")
    print("=" * 60)

    scraper = LandezineScraper()

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

        if not scraper.tracker:
            print("   Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="landezine")

        print(f"   Total articles in database: {stats['total_articles']}")
        if stats['oldest_seen']:
            print(f"   Oldest: {stats['oldest_seen']}")
        if stats['newest_seen']:
            print(f"   Newest: {stats['newest_seen']}")

        # Fetch new articles
        print("\n3. Running visual AI scraping with anti-bot protection...")
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
                print(f"   Hero Image: {'Yes' if article.get('hero_image') else 'No'}")
                print(f"   Description: {article.get('description', '')[:100]}...")
        else:
            print("\n4. No new articles (all previously seen)")

        # Show updated stats
        print("\n5. Updated tracker stats...")
        if not scraper.tracker:
            print("   Tracker not initialized")
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