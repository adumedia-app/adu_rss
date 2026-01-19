# operators/custom_scrapers/identity.py
"""
Identity Magazine Custom Scraper - Visual AI Approach
Scrapes architecture news from Identity.ae (Middle East architecture magazine)

Visual Scraping Strategy:
1. Take screenshot of architecture category page
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Use AI to match headlines to links in HTML (semantic matching)
6. Click link to get publication date using AI date extraction
7. Main pipeline handles hero image and content extraction

Usage:
    scraper = IdentityScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import asyncio
import base64
from typing import Optional, List, cast
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker
from storage.scraping_stats import ScrapingStats
from prompts.homepage_analyzer import HOMEPAGE_ANALYZER_PROMPT_TEMPLATE, parse_headlines


class IdentityScraper(BaseCustomScraper):
    """
    Visual AI-powered custom scraper for Identity Magazine
    Uses GPT-4o vision to identify articles on category page.
    """

    source_id = "identity"
    source_name = "Identity Magazine"
    base_url = "https://identity.ae/category/architecture/"

    # Configuration: Maximum age of articles to process (in days)
    MAX_ARTICLE_AGE_DAYS = 2  # Today + yesterday

    def __init__(self):
        """Initialize scraper with article tracker and vision model."""
        super().__init__()
        self.tracker: Optional[ArticleTracker] = None
        self.vision_model: Optional[ChatOpenAI] = None
        self.stats = ScrapingStats(source_id=self.source_id, source_name=self.source_name, base_url=self.base_url)

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

            api_key_str = cast(str, api_key)

            self.vision_model = ChatOpenAI(
                model="gpt-4o",
                api_key=api_key_str,
                temperature=0.1
            )
            print(f"[{self.source_id}] Vision model initialized")

    async def _analyze_homepage_screenshot(self, screenshot_path: str) -> List[str]:
        """
        Analyze homepage screenshot with GPT-4o vision to extract headlines.

        Args:
            screenshot_path: Path to screenshot PNG

        Returns:
            List of article headlines
        """
        self._ensure_vision_model()

        if not self.vision_model:
            raise RuntimeError("Vision model not initialized")

        # Read and encode screenshot
        with open(screenshot_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Create vision message
        prompt = HOMEPAGE_ANALYZER_PROMPT_TEMPLATE.format(
            source_name=self.source_name
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_data}"}
                }
            ]
        )

        # Get response
        response = await asyncio.to_thread(
            self.vision_model.invoke,
            [message]
        )

        # Parse headlines
        response_text = response.content if hasattr(response, 'content') else str(response)
        if not isinstance(response_text, str):
            response_text = str(response_text)

        headlines = parse_headlines(response_text)
        return headlines

    async def _find_headline_in_html_with_ai(self, page, headline: str) -> Optional[dict]:
        """
        Find a headline in the page HTML using AI-powered matching.

        Strategy:
        1. Extract ALL meaningful article containers from the page
        2. Send them all to AI with the target headline
        3. AI matches semantically and returns the best match

        Args:
            page: Playwright page object
            headline: Headline text to search for

        Returns:
            Dict with title, link, description, image or None
        """
        self._ensure_vision_model()

        # Extract relevant HTML context around potential article links
        html_context = await page.evaluate("""
            (headline) => {
                // Find all article-like containers
                const containers = document.querySelectorAll(
                    'article, .post, [class*="post"], [class*="item"], [class*="card"], .entry'
                );

                const articleData = [];

                containers.forEach((container, index) => {
                    // Get all links in this container
                    const links = container.querySelectorAll('a[href]');

                    if (links.length === 0) return;

                    // Get the main link (usually the first or largest)
                    let mainLink = null;
                    let mainLinkText = '';

                    links.forEach(link => {
                        const text = link.textContent.trim();
                        if (text.length > mainLinkText.length) {
                            mainLink = link;
                            mainLinkText = text;
                        }
                    });

                    if (!mainLink) return;

                    // Extract data
                    const href = mainLink.href;
                    const linkText = mainLinkText;

                    // Get description
                    const descEl = container.querySelector('p, .excerpt, [class*="excerpt"], [class*="desc"]');
                    const description = descEl ? descEl.textContent.trim().substring(0, 150) : '';

                    // Get image
                    const imgEl = container.querySelector('img');
                    const imageUrl = imgEl ? imgEl.src : null;

                    // Only include if it has meaningful content
                    if (linkText.length > 5) {
                        articleData.push({
                            index: index,
                            link_text: linkText,
                            href: href,
                            description: description,
                            image_url: imageUrl
                        });
                    }
                });

                return articleData;
            }
        """, headline)

        if not html_context or len(html_context) == 0:
            print(f"      ⚠️ No article containers found on page")
            return None

        print(f"      🔍 Found {len(html_context)} article containers")

        # Format for AI
        context_text = "\n\n".join([
            f"[{item['index']}] LINK_TEXT: {item['link_text']}\n"
            f"    URL: {item['href']}\n"
            f"    EXCERPT: {item['description']}"
            for item in html_context
        ])

        # AI prompt for semantic matching
        prompt = f"""You are analyzing article containers from identity.ae to find which one matches a target headline.

TARGET HEADLINE: "{headline}"

AVAILABLE ARTICLE CONTAINERS:
{context_text}

Your task: Find which container index best matches the target headline.

Consider:
1. Semantic similarity (meaning, not just exact words)
2. Context clues (description, URL patterns)
3. Partial matches are OK if context is clear

Respond with ONLY the container index number (e.g., "3") or "NONE" if no good match.
Do not include any explanation."""

        if not self.vision_model:
            raise RuntimeError("Vision model not initialized")

        ai_response = await asyncio.to_thread(
            self.vision_model.invoke,
            [HumanMessage(content=prompt)]
        )

        response_text = ai_response.content if hasattr(ai_response, 'content') else str(ai_response)
        if not isinstance(response_text, str):
            response_text = str(response_text)

        response_clean = response_text.strip().upper()

        if response_clean == "NONE":
            return None

        # Extract index number
        import re
        match = re.search(r'\d+', response_clean)
        if not match:
            return None

        selected_index = int(match.group(0))

        # Find the matching container
        for item in html_context:
            if item['index'] == selected_index:
                return {
                    'title': item['link_text'],
                    'link': item['href'],
                    'description': item['description'],
                    'image_url': item['image_url']
                }

        return None

    async def fetch_articles(self, hours: int = 24) -> List[dict]:
        """
        Fetch new articles using visual AI analysis.

        Args:
            hours: Not used for visual scraping (kept for base class compatibility)

        Workflow:
        1. Screenshot category page
        2. Extract headlines with GPT-4o vision
        3. Compare with stored headlines to find NEW ones (database filtering)
        4. For each new headline:
           - Find it in HTML and get the link (AI matching)
           - Click link to get publication date (AI extraction)
           - Filter by date: only keep articles within MAX_ARTICLE_AGE_DAYS
           - Create minimal article dict
        5. Store all current headlines in database (for next run)
        6. Upload statistics to R2

        Date Filtering:
        - Articles older than MAX_ARTICLE_AGE_DAYS are skipped
        - Articles without dates are included (better to include than miss)
        - Uses article publication date, not homepage appearance date

        Returns:
            List of article dicts (only new articles from recent days)
        """
        # Maximum new articles to process per run
        max_new = 10
        print(f"[{self.source_id}] 📸 Starting visual AI scraping...")

        await self._ensure_tracker()

        try:
            page = await self._create_page()

            try:
                # ============================================================
                # Step 1: Take Screenshot of Category Page
                # ============================================================

                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_timeout(2000)  # Let page fully render

                # Save screenshot
                import os
                import tempfile
                screenshot_path = os.path.join(tempfile.gettempdir(), f"{self.source_id}_homepage.png")

                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"[{self.source_id}] 📸 Screenshot saved: {screenshot_path}")

                # ============================================================
                # Step 2: Extract Headlines with AI Vision
                # ============================================================

                print(f"[{self.source_id}] 🤖 Analyzing screenshot with GPT-4o vision...")
                current_headlines = await self._analyze_homepage_screenshot(screenshot_path)
                print(f"[{self.source_id}] ✅ Extracted {len(current_headlines)} headlines from screenshot")

                if not current_headlines:
                    print(f"[{self.source_id}] No headlines extracted from screenshot")
                    await self._upload_stats_to_r2()
                    return []

                # ============================================================
                # Step 3: Find NEW Headlines (not in database)
                # ============================================================

                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                new_headlines = await self.tracker.find_new_headlines(
                    self.source_id,
                    current_headlines
                )

                print(f"\n[{self.source_id}] 📊 Status:")
                print(f"   Total headlines: {len(current_headlines)}")
                print(f"   Already seen: {len(current_headlines) - len(new_headlines)}")
                print(f"   NEW headlines: {len(new_headlines)}")

                if not new_headlines:
                    print(f"[{self.source_id}] No new headlines (all previously seen)")
                    await self._upload_stats_to_r2()
                    return []

                # Limit to max_new
                if len(new_headlines) > max_new:
                    print(f"[{self.source_id}] Limiting to {max_new} articles (found {len(new_headlines)} new)")
                    new_headlines = new_headlines[:max_new]

                print(f"[{self.source_id}] Processing {len(new_headlines)} new articles")

                # ============================================================
                # Step 4: Find Each Headline in HTML and Extract Link
                # ============================================================

                new_articles = []
                skipped_old = 0  # Track articles skipped due to date
                skipped_no_link = 0  # Track articles with no link found

                for i, headline in enumerate(new_headlines, 1):
                    print(f"\n   [{i}/{len(new_headlines)}] {headline[:50]}...")

                    try:
                        # Find headline in HTML using AI
                        homepage_data = await self._find_headline_in_html_with_ai(page, headline)

                        if not homepage_data or not homepage_data.get('link'):
                            print(f"      ⚠️ Could not find link for headline")
                            skipped_no_link += 1
                            continue

                        url = homepage_data['link']
                        print(f"      🔗 Found URL: {url}")

                        # ============================================================
                        # Step 5: Click Into Article to Get Publication Date
                        # ============================================================

                        await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                        await page.wait_for_timeout(1500)

                        # Extract article text for AI date extraction
                        article_text = await page.evaluate("""
                            () => {
                                // Get text from common date locations
                                const article = document.querySelector('article, main, .content, .post');
                                if (article) {
                                    return article.textContent.substring(0, 2000);
                                }
                                return document.body.textContent.substring(0, 2000);
                            }
                        """)

                        # Use AI to extract date
                        published = self._parse_date_with_ai(article_text)

                        # ============================================================
                        # DATE FILTERING: Only process recent articles
                        # ============================================================

                        if published:
                            article_date = datetime.fromisoformat(published.replace('Z', '+00:00'))
                            current_date = datetime.now(timezone.utc)

                            # Calculate days difference
                            days_old = (current_date - article_date).days

                            # Skip if older than configured max age
                            if days_old > self.MAX_ARTICLE_AGE_DAYS:
                                print(f"      ⏭️  Skipping old article ({days_old} days old)")
                                skipped_old += 1
                                continue

                            print(f"      ✅ Fresh article ({days_old} day(s) old)")
                        else:
                            # If no date found, include it (better to include than miss)
                            print(f"      ⚠️ No date found - including anyway")

                        # ============================================================
                        # Create MINIMAL article dict
                        # Hero image and content will be extracted by scraper.py
                        # ============================================================

                        article = self._create_minimal_article_dict(
                            title=homepage_data['title'],
                            link=url,
                            published=published
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

                        # Small delay
                        await asyncio.sleep(0.5)

                        # Go back to category page for next headline
                        await page.goto(self.base_url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                    except Exception as e:
                        print(f"      ⚠️ Error processing headline: {e}")
                        continue

                # ============================================================
                # Step 6: Store ALL Current Headlines (for next run)
                # ============================================================

                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                await self.tracker.store_headlines(self.source_id, current_headlines)

                # ============================================================
                # Step 7: Upload Statistics to R2
                # ============================================================

                await self._upload_stats_to_r2()

                # ============================================================
                # Final Summary
                # ============================================================

                print(f"\n[{self.source_id}] 📊 Processing Summary:")
                print(f"   Headlines extracted: {len(current_headlines)}")
                print(f"   New headlines: {len(new_headlines)}")
                print(f"   Skipped (too old): {skipped_old}")
                print(f"   Skipped (no link): {skipped_no_link}")
                print(f"   ✅ Successfully scraped: {len(new_articles)}")

                return new_articles

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error in visual scraping: {e}")
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
custom_scraper_registry.register(IdentityScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_identity_scraper():
    """Test the visual AI scraper."""
    print("=" * 60)
    print("Testing Identity Magazine Visual AI Scraper")
    print("=" * 60)

    scraper = IdentityScraper()

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

        if not scraper.tracker:
            print("   ⚠️ Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="identity")

        print(f"   Total articles in database: {stats['total_articles']}")
        if stats['oldest_seen']:
            print(f"   Oldest: {stats['oldest_seen']}")
        if stats['newest_seen']:
            print(f"   Newest: {stats['newest_seen']}")

        # Fetch new articles
        print("\n3. Running visual AI scraping (max 10 new articles)...")
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
                print(f"   Custom scraped: {article.get('custom_scraped', False)}")
        else:
            print("\n4. No new articles (all previously seen)")

        # Show updated stats
        print("\n5. Updated tracker stats...")
        if not scraper.tracker:
            print("   ⚠️ Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="identity")
        print(f"   Total articles in database: {stats['total_articles']}")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_identity_scraper())