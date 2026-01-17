# operators/custom_scrapers/landezine.py
"""
Landezine Custom Scraper - Visual AI Approach
Scrapes landscape architecture news from Landezine.com

Visual Scraping Strategy:
1. Take screenshot of homepage
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Find headline text in HTML coupled with link
6. Click link to get publication date and metadata
7. Continue with standard scraping logic

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
import os
from typing import Optional, List, Any, cast
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker


def parse_headlines(response_text: str) -> list[str]:
    """
    Parse AI response into list of headlines.

    Args:
        response_text: Raw AI response (headlines separated by newlines)

    Returns:
        List of headline strings
    """
    lines = response_text.strip().split('\n')

    headlines = []
    for line in lines:
        line = line.strip()
        # Skip empty lines, numbered lists, explanations
        if not line:
            continue
        if line.startswith('#'):
            continue
        if line.lower().startswith('here'):
            continue
        if line.lower().startswith("i'm unable"):
            continue
        if line.lower().startswith("i cannot"):
            continue
        if "screenshot" in line.lower() and len(line) > 100:
            continue

        # Remove numbered list markers (1. 2. etc)
        if len(line) > 2 and line[0].isdigit() and '. ' in line[:4]:
            line = line.split('. ', 1)[1].strip()

        # Remove bullet points
        if line.startswith('- '):
            line = line[2:].strip()
        if line.startswith('• '):
            line = line[2:].strip()

        if line and len(line) > 5:  # Minimum headline length
            headlines.append(line)

    return headlines[:20]  # Limit to 20


class LandezineScraper(BaseCustomScraper):
    """
    Visual AI-powered custom scraper for Landezine.com
    Uses GPT-4o vision to identify articles on homepage.
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

    async def _ensure_tracker(self):
        """Ensure article tracker is connected."""
        if not self.tracker:
            self.tracker = ArticleTracker()
            await self.tracker.connect()

    def _ensure_vision_model(self):
        """Ensure vision model is initialized."""
        if not self.vision_model:
            api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")

            # Use GPT-4o (not mini) for better vision capabilities
            # GPT-4o-mini has limited vision and may fail on complex screenshots
            self.vision_model = ChatOpenAI(
                model="gpt-4o",  # Changed from gpt-4o-mini
                api_key=api_key,
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=1000,  # Enough for headline list
            )
            print(f"[{self.source_id}] Vision model initialized (gpt-4o)")

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

        # Check file size
        file_size = os.path.getsize(screenshot_path)
        print(f"[{self.source_id}] Screenshot size: {file_size / 1024:.1f} KB")

        # Create vision message with PROPER format
        # The prompt is embedded directly in the message, not using template
        prompt_text = """You are analyzing a homepage screenshot to extract article headlines.

TASK: Extract all visible article headlines from this webpage screenshot.

RULES:
- Look for text that appears to be article headlines (larger font, prominent placement)
- Ignore navigation menus, footer links, sidebar content, ads
- Focus on the main content area where articles are listed
- Return ONLY the headlines, one per line
- Copy headlines EXACTLY as they appear - do not paraphrase
- Return headlines in the order they appear (top to bottom)
- Maximum 20 headlines
- Do not include any explanation or commentary
- Do not use emoji

OUTPUT FORMAT:
Just the headlines, one per line. Example:
New Park Design in Amsterdam
Sustainable Landscape Project Wins Award
Interview with Studio XYZ"""

        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": prompt_text
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_data}",
                        "detail": "high"  # Use high detail for text extraction
                    }
                }
            ]
        )

        # Get response
        if not self.vision_model:
            raise RuntimeError("Vision model not initialized")

        try:
            response = await asyncio.to_thread(
                self.vision_model.invoke,
                [message]
            )

            # Parse headlines - ensure response.content is a string
            response_text = response.content if hasattr(response, 'content') else str(response)
            if not isinstance(response_text, str):
                response_text = str(response_text)

            print(f"[{self.source_id}] Raw AI response: {response_text[:200]}...")

            headlines = parse_headlines(response_text)

            print(f"[{self.source_id}] Extracted {len(headlines)} headlines from screenshot")
            return headlines

        except Exception as e:
            print(f"[{self.source_id}] Vision API error: {e}")
            import traceback
            traceback.print_exc()
            return []

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
                // Normalize text for comparison
                function normalize(text) {
                    return text.trim().toLowerCase().replace(/\\s+/g, ' ');
                }

                // Find all links on the page
                const allLinks = Array.from(document.querySelectorAll('a[href]'));

                for (const link of allLinks) {
                    const linkText = normalize(link.textContent || '');
                    const searchNormalized = normalize(searchText);

                    // Check if this link contains the headline text (or vice versa)
                    if (linkText.includes(searchNormalized) || searchNormalized.includes(linkText)) {
                        // Make sure it's a substantial match (not just a word)
                        if (linkText.length > 10 || searchNormalized.length > 10) {
                            const href = link.href;

                            // Skip if not an article link
                            if (href.includes('#') || href.includes('category') || href.includes('tag')) {
                                continue;
                            }

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
                }

                return null;
            }
        """, search_text)

        return result

    async def fetch_articles(self, hours: int = 24) -> List[dict]:
        """
        Fetch new articles using visual AI analysis.

        Args:
            hours: Not used for visual scraping (kept for base class compatibility)
                   Visual scraping uses headline comparison instead of time-based filtering

        Workflow:
        1. Screenshot homepage
        2. Extract headlines with GPT-4o vision
        3. Compare with stored headlines to find NEW ones (database filtering)
        4. For each new headline:
           - Find it in HTML and get the link
           - Click link to get publication date
           - Filter by date: only keep articles from today/yesterday (max 2 days old)
           - Create article dict
        5. Store all current headlines in database (for next run)

        Date Filtering:
        - Articles older than MAX_ARTICLE_AGE_DAYS are skipped (handles archive content)
        - Articles without dates are included (better to include than miss)
        - Uses article publication date, not homepage appearance date

        Returns:
            List of article dicts (only new articles from today/yesterday)
        """
        # Maximum new articles to process per run
        max_new = 10
        print(f"[{self.source_id}] Starting visual AI scraping...")

        await self._ensure_tracker()

        try:
            page = await self._create_page()

            try:
                # ============================================================
                # Step 1: Take Screenshot of Homepage
                # ============================================================

                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_timeout(3000)  # Let page fully render (increased wait)

                # Scroll down slightly to trigger any lazy loading
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(1000)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)

                # Save screenshot with higher quality settings
                import tempfile
                screenshot_path = os.path.join(tempfile.gettempdir(), f"{self.source_id}_homepage.png")

                # Take screenshot of just viewport (not full page - more reliable)
                await page.screenshot(
                    path=screenshot_path,
                    full_page=False,  # Just viewport, not full page
                    type="png"
                )
                print(f"[{self.source_id}] Screenshot saved: {screenshot_path}")

                # ============================================================
                # Step 2: Extract Headlines with AI Vision
                # ============================================================

                current_headlines = await self._analyze_homepage_screenshot(screenshot_path)

                if not current_headlines:
                    print(f"[{self.source_id}] No headlines extracted from screenshot")
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

                if not new_headlines:
                    print(f"[{self.source_id}] No new headlines (all previously seen)")
                    # Still store headlines to update timestamps
                    await self.tracker.store_headlines(self.source_id, current_headlines)
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
                    print(f"   [{i}/{len(new_headlines)}] {headline[:50]}...")

                    try:
                        # Find headline in HTML
                        homepage_data = await self._find_headline_in_html(page, headline)

                        if not homepage_data:
                            print("      Could not find link for headline")
                            skipped_no_link += 1
                            continue

                        url = homepage_data['link']

                        # ============================================================
                        # Step 5: Click Into Article to Get Publication Date
                        # ============================================================

                        await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                        await page.wait_for_timeout(1500)

                        # Extract publication date and metadata
                        article_metadata = await page.evaluate(r"""
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

                        # Small delay
                        await asyncio.sleep(0.5)

                        # Go back to homepage for next headline
                        await page.goto(self.base_url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                    except Exception as e:
                        print(f"      Error processing headline: {e}")
                        continue

                # ============================================================
                # Step 6: Store ALL Current Headlines (for next run)
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

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error in visual scraping: {e}")
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
custom_scraper_registry.register(LandezineScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_landezine_scraper():
    """Test the visual AI scraper."""
    print("=" * 60)
    print("Testing Landezine Visual AI Scraper")
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
        print("\n3. Running visual AI scraping...")
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
    asyncio.run(test_landezine_scraper())