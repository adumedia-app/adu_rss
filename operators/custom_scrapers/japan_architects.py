# operators/custom_scrapers/japan_architects.py
"""
Japan Architects Custom Scraper - Visual AI Approach
Scrapes architecture news from Japan-Architects.com

Site: https://www.japan-architects.com/en
Challenge: Requires User-Agent header

Visual Scraping Strategy:
1. Take screenshot of homepage
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Use AI to match headlines to links in HTML (semantic matching)
6. Click link to get publication date using AI date extraction
7. Main pipeline handles hero image and content extraction

Usage:
    scraper = JapanArchitectsScraper()
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


class JapanArchitectsScraper(BaseCustomScraper):
    """
    Visual AI-powered custom scraper for Japan Architects
    Uses GPT-4o vision to identify articles on homepage.
    """

    source_id = "japan_architects"
    source_name = "Japan Architects"
    base_url = "https://www.japan-architects.com/en"

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
            screenshot_path: Path to screenshot file

        Returns:
            List of headline strings
        """
        self._ensure_vision_model()

        if not self.vision_model:
            raise RuntimeError("Vision model not initialized")

        with open(screenshot_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        prompt = HOMEPAGE_ANALYZER_PROMPT_TEMPLATE.format(
            source_name=self.source_name
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_data}"},
                },
            ]
        )

        response = await self.vision_model.ainvoke([message])
        headlines = parse_headlines(response.content)

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
        prompt = f"""You are analyzing article containers from japan-architects.com to find which one matches a target headline.

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

    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch NEW articles using visual AI approach.

        Returns only articles not previously seen by this scraper.
        Filters to articles from last MAX_ARTICLE_AGE_DAYS days.
        """
        await self._ensure_tracker()
        await self._initialize_browser()

        if not self.browser:
            return []

        try:
            page = await self.browser.new_page()

            # Set User-Agent header (required for this site)
            await page.set_extra_http_headers({
                "User-Agent": self.user_agent
            })

            try:
                print(f"\n[{self.source_id}] 🔍 Starting Visual AI Scraping")
                print(f"   URL: {self.base_url}")

                # Navigate to homepage
                await page.goto(self.base_url, timeout=self.timeout)
                await page.wait_for_timeout(2000)

                # Take screenshot
                screenshot_path = f"/tmp/{self.source_id}_homepage.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"   📸 Screenshot saved: {screenshot_path}")

                # Extract headlines with AI
                print(f"   🤖 Analyzing with GPT-4o vision...")
                current_headlines = await self._analyze_homepage_screenshot(screenshot_path)
                print(f"   ✅ Extracted {len(current_headlines)} headlines")

                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                # Check which headlines are NEW
                seen_headlines = await self.tracker.get_stored_headlines(self.source_id)
                new_headlines = [h for h in current_headlines if h not in seen_headlines]

                print(f"\n   📊 Status:")
                print(f"      Total headlines: {len(current_headlines)}")
                print(f"      Already seen: {len(current_headlines) - len(new_headlines)}")
                print(f"      NEW headlines: {len(new_headlines)}")

                if not new_headlines:
                    print(f"   ✅ No new articles to process")
                    await self.tracker.store_headlines(self.source_id, current_headlines)
                    await self._upload_stats_to_r2()
                    return []

                # Process each NEW headline
                print(f"\n   🔄 Processing {len(new_headlines)} new articles...")
                new_articles = []
                skipped_old = 0
                skipped_no_link = 0

                for idx, headline in enumerate(new_headlines, 1):
                    print(f"\n   [{idx}/{len(new_headlines)}] {headline[:60]}...")

                    try:
                        # Use AI to find matching link in HTML
                        homepage_data = await self._find_headline_in_html_with_ai(page, headline)

                        if not homepage_data or not homepage_data.get('link'):
                            print(f"      ⚠️ No link found for headline")
                            skipped_no_link += 1
                            continue

                        url = homepage_data['link']
                        print(f"      🔗 Found URL: {url}")

                        # Navigate to article to get date
                        await page.goto(url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                        # Extract date using AI
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

                        published = self._parse_date_with_ai(article_text)

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
                            print(f"      ⚠️ No date found - including anyway")

                        # Create minimal article dict (main pipeline will handle hero image)
                        article = self._create_minimal_article_dict(
                            title=homepage_data['title'],
                            link=url,
                            published=published
                        )

                        if self._validate_article(article):
                            new_articles.append(article)

                            await self.tracker.update_headline_url(
                                self.source_id,
                                headline,
                                url
                            )

                        # Navigate back to homepage
                        await page.goto(self.base_url, timeout=self.timeout)
                        await page.wait_for_timeout(500)

                    except Exception as e:
                        print(f"      ⚠️ Error processing headline: {e}")
                        continue

                # Store all current headlines
                await self.tracker.store_headlines(self.source_id, current_headlines)

                # Upload statistics
                await self._upload_stats_to_r2()

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
custom_scraper_registry.register(JapanArchitectsScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_japan_architects_scraper():
    """Test the visual AI scraper."""
    print("=" * 60)
    print("Testing Japan Architects Visual AI Scraper")
    print("=" * 60)

    scraper = JapanArchitectsScraper()

    try:
        print("\n1. Testing connection...")
        connected = await scraper.test_connection()

        if not connected:
            print("   ❌ Connection failed")
            return

        print("\n2. Checking tracker stats...")
        await scraper._ensure_tracker()

        if not scraper.tracker:
            print("   ⚠️ Tracker not initialized")
            return

        stats = await scraper.tracker.get_stats(source_id="japan_architects")

        print(f"   Total articles in database: {stats['total_articles']}")
        if stats['oldest_seen']:
            print(f"   Oldest: {stats['oldest_seen']}")
        if stats['newest_seen']:
            print(f"   Newest: {stats['newest_seen']}")

        print("\n3. Running visual AI scraping...")
        articles = await scraper.fetch_articles(hours=24)

        print(f"\n   ✅ Found {len(articles)} NEW articles")

        if articles:
            print("\n4. Sample articles:")
            for i, article in enumerate(articles[:3], 1):
                print(f"\n   Article {i}:")
                print(f"      Title: {article['title'][:60]}...")
                print(f"      URL: {article['link']}")
                print(f"      Published: {article.get('published', 'N/A')}")

    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(test_japan_architects_scraper())