# operators/custom_scrapers/identity.py
"""
Identity Magazine Custom Scraper - Visual AI Approach
Scrapes architecture news from Identity.ae (Middle East architecture magazine)

Visual Scraping Strategy:
1. Take screenshot of architecture category page
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Find headline text in HTML coupled with link
6. Click link to get publication date and metadata
7. Continue with standard scraping logic

This approach is resilient to HTML structure changes since we use
visual analysis to identify articles rather than hardcoded selectors.

Usage:
    scraper = IdentityScraper()
    articles = await scraper.fetch_articles()
    await scraper.close()
"""

import re
import asyncio
import base64
from typing import Optional, List, Any, cast
from datetime import datetime, timezone

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry
from storage.article_tracker import ArticleTracker
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

    async def _analyze_homepage_screenshot(self, screenshot_path: str) -> List[str]:
        """
        Analyze homepage screenshot with GPT-4o vision to extract headlines.

        Args:
            screenshot_path: Path to screenshot PNG

        Returns:
            List of article headlines
        """
        self._ensure_vision_model()

        print(f"[{self.source_id}] 📸 Analyzing screenshot with AI vision...")

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

        print(f"[{self.source_id}] ✅ Extracted {len(headlines)} headlines from screenshot")
        return headlines

    async def _find_headline_in_html_with_ai(self, page, headline: str) -> Optional[dict]:
        """
        Use AI to find the article link for a headline by analyzing HTML context.
        
        This is more reliable than regex because AI can understand:
        - Similar but not exact text matches
        - HTML structure and context
        - Which links are article links vs navigation
        
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
                    'article, .post, [class*="post"], [class*="item"], [class*="card"], .each'
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
                    const descEl = container.querySelector('p, .excerpt, [class*="excerpt"]');
                    const description = descEl ? descEl.textContent.trim().substring(0, 150) : '';
                    
                    // Get image
                    const imgEl = container.querySelector('img');
                    const imageUrl = imgEl ? imgEl.src : null;
                    
                    // Only include if has meaningful text
                    if (linkText.length > 5 && href.includes('/')) {
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
        
        print(f"      🔍 Found {len(html_context)} potential article containers")
        
        # Use AI to find the best match
        prompt = f"""You are analyzing HTML article links to find the one matching a specific headline.

TARGET HEADLINE: "{headline}"

AVAILABLE ARTICLE LINKS:
{self._format_articles_for_ai(html_context)}

Your task: Find which article link best matches the target headline.

Rules:
- Match based on semantic similarity, not exact text match
- The link_text might be slightly different from the headline (capitalization, punctuation, shortened)
- If multiple matches, choose the most similar one
- If no good match exists, respond with "NONE"

Respond with ONLY the index number (0, 1, 2, etc.) of the matching article, or "NONE" if no match.

Example responses:
3
NONE
0"""

        try:
            if not self.vision_model:
                raise RuntimeError("Vision model not initialized")
            
            response = await asyncio.to_thread(
                self.vision_model.invoke,
                prompt
            )
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            response_text = response_text.strip()
            
            # Parse AI response
            if response_text.upper() == "NONE":
                print(f"      ❌ AI: No matching article found")
                return None
            
            try:
                match_index = int(response_text)
                
                if match_index < 0 or match_index >= len(html_context):
                    print(f"      ⚠️ AI returned invalid index: {match_index}")
                    return None
                
                # Get the matched article
                matched = html_context[match_index]
                
                print(f"      ✅ AI matched to: '{matched['link_text'][:50]}...'")
                
                return {
                    "title": matched["link_text"],
                    "link": matched["href"],
                    "description": matched.get("description", ""),
                    "image_url": matched.get("image_url")
                }
                
            except ValueError:
                print(f"      ⚠️ AI returned non-numeric response: {response_text}")
                return None
                
        except Exception as e:
            print(f"      ❌ AI analysis error: {e}")
            return None
    
    def _format_articles_for_ai(self, articles: List[dict]) -> str:
        """Format article data for AI prompt."""
        lines = []
        for i, article in enumerate(articles):
            lines.append(f"[{i}] LINK_TEXT: {article['link_text']}")
            lines.append(f"    URL: {article['href']}")
            if article.get('description'):
                lines.append(f"    EXCERPT: {article['description'][:100]}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def _find_headline_in_html(self, page, headline: str) -> Optional[dict]:
        """
        Find a headline in the page HTML and extract its link.
        
        Uses AI-powered HTML analysis for reliable matching.
        
        Args:
            page: Playwright page object
            headline: Headline text to search for

        Returns:
            Dict with title, link, description, image or None
        """
        return await self._find_headline_in_html_with_ai(page, headline)

    async def fetch_articles(self, hours: int = 24) -> List[dict]:
        """
        Fetch new articles using visual AI analysis.

        Args:
            hours: Not used for visual scraping (kept for base class compatibility)
                   Visual scraping uses headline comparison instead of time-based filtering

        Workflow:
        1. Screenshot category page
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
                            print(f"      ⚠️ Could not find link for headline")
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
                                print(f"      ⏭️  Skipping old article ({days_old} days old)")
                                skipped_old += 1
                                continue

                            print(f"      ✅ Fresh article ({days_old} day(s) old)")
                        else:
                            # If no date found, include it (better to include than miss)
                            print(f"      ⚠️ No date found - including anyway")

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

                        # Go back to category page for next headline
                        await page.goto(self.base_url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                    except Exception as e:
                        print(f"      ⚠️ Error processing headline: {e}")
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
        articles = await scraper.fetch_articles(hours=24)  # hours parameter ignored, uses max_new=10 internally

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
