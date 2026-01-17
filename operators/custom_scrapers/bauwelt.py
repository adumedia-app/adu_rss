# operators/custom_scrapers/bauwelt.py
"""
Bauwelt Custom Scraper - Visual AI Approach
Scrapes architecture news from Bauwelt (German architecture magazine)

Site: https://www.bauwelt.de/rubriken/bauten/standard_index_2073531.html
Challenge: None - straightforward access

Visual Scraping Strategy:
1. Take screenshot of buildings section page
2. Use GPT-4o vision to extract article headlines
3. On first run: Store all headlines in database as "seen"
4. On subsequent runs: Only process NEW headlines (not in database)
5. Find headline text in HTML coupled with link using AI
6. Click link to get publication date and metadata
7. Continue with standard scraping logic

Usage:
    scraper = BauweltScraper()
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
from prompts.homepage_analyzer import HOMEPAGE_ANALYZER_PROMPT_TEMPLATE, parse_headlines


class BauweltScraper(BaseCustomScraper):
    """
    Visual AI-powered custom scraper for Bauwelt
    Uses GPT-4o vision to identify articles on buildings section.
    """

    source_id = "bauwelt"
    source_name = "Bauwelt"
    base_url = "https://www.bauwelt.de/rubriken/bauten/standard_index_2073531.html"

    # Configuration: Maximum age of articles to process (in days)
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

        # Parse headlines
        response_text = response.content if hasattr(response, 'content') else str(response)
        if not isinstance(response_text, str):
            response_text = str(response_text)

        headlines = parse_headlines(response_text)

        print(f"[{self.source_id}] ✅ Extracted {len(headlines)} headlines from screenshot")
        return headlines

    async def _find_headline_in_html_with_ai(self, page, headline: str) -> Optional[dict]:
        """
        Use AI to find the article link for a headline by analyzing HTML context.
        
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
                    'article, .post, [class*="post"], [class*="item"], [class*="card"], [class*="teaser"]'
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
                    const descEl = container.querySelector('p, .excerpt, [class*="excerpt"], [class*="desc"], [class*="text"]');
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

        if not html_context:
            return None

        # Prepare context for AI analysis
        context_text = f"Looking for headline: '{headline}'\n\n"
        context_text += "Article containers found on page:\n"
        
        for item in html_context[:15]:  # Limit to prevent token overflow
            context_text += f"\n--- Container {item['index']} ---\n"
            context_text += f"Link text: {item['link_text']}\n"
            context_text += f"URL: {item['href']}\n"
            if item['description']:
                context_text += f"Description: {item['description']}\n"

        # Ask AI to match the headline
        prompt = f"""Given this headline: "{headline}"

Which of these article containers is the best match? Consider:
1. Semantic similarity (meaning, not just exact words)
2. Context clues (description, URL patterns)
3. Partial matches are OK if context is clear

{context_text}

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
        Fetch new articles using visual AI approach.

        Args:
            hours: Ignored (we use database tracking instead)

        Returns:
            List of article dicts
        """
        await self._ensure_tracker()
        
        try:
            page = await self._create_page()

            try:
                print(f"[{self.source_id}] Loading buildings section...")
                await page.goto(self.base_url, timeout=self.timeout, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Take screenshot
                screenshot_path = f"/tmp/{self.source_id}_homepage.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                print(f"[{self.source_id}] Screenshot saved to {screenshot_path}")

                # Step 1: Extract headlines from screenshot using AI vision
                current_headlines = await self._analyze_homepage_screenshot(screenshot_path)

                if not current_headlines:
                    print(f"[{self.source_id}] No headlines found in screenshot")
                    return []

                # Step 2: Check database for previously seen headlines
                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                seen_headlines = await self.tracker.get_seen_headlines(self.source_id)
                new_headlines = [h for h in current_headlines if h not in seen_headlines]

                print(f"[{self.source_id}] Headlines breakdown:")
                print(f"   Total extracted: {len(current_headlines)}")
                print(f"   Previously seen: {len(current_headlines) - len(new_headlines)}")
                print(f"   New to process: {len(new_headlines)}")

                if not new_headlines:
                    print(f"[{self.source_id}] No new headlines - all previously seen")
                    return []

                # Limit processing
                MAX_NEW = 10
                if len(new_headlines) > MAX_NEW:
                    print(f"[{self.source_id}] Limiting to {MAX_NEW} newest headlines")
                    new_headlines = new_headlines[:MAX_NEW]

                # Step 3: Process each new headline
                new_articles = []
                skipped_old = 0
                skipped_no_link = 0

                for i, headline in enumerate(new_headlines, 1):
                    print(f"\n[{self.source_id}] Processing headline {i}/{len(new_headlines)}")
                    print(f"   Headline: {headline[:60]}...")

                    try:
                        # Use AI to find this headline in HTML
                        homepage_data = await self._find_headline_in_html_with_ai(page, headline)

                        if not homepage_data or not homepage_data.get('link'):
                            print(f"      ⚠️  Could not find article link")
                            skipped_no_link += 1
                            continue

                        url = homepage_data['link']
                        print(f"      🔗 Found link: {url}")

                        # Navigate to article page
                        await page.goto(url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                        # Extract metadata from article page
                        article_metadata = await page.evaluate("""
                            () => {
                                // Get publication date
                                const dateEl = document.querySelector(
                                    'time[datetime], .date, [class*="date"], [class*="time"]'
                                );
                                const dateText = dateEl ? 
                                    (dateEl.getAttribute('datetime') || dateEl.textContent.trim()) : 
                                    '';

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

                        # DATE FILTERING: Only process articles from today/yesterday
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

                        # Go back to buildings section for next headline
                        await page.goto(self.base_url, timeout=self.timeout)
                        await page.wait_for_timeout(1000)

                    except Exception as e:
                        print(f"      ⚠️ Error processing headline: {e}")
                        continue

                # Store ALL current headlines (for next run)
                if not self.tracker:
                    raise RuntimeError("Article tracker not initialized")

                await self.tracker.store_headlines(self.source_id, current_headlines)

                # Final Summary
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
custom_scraper_registry.register(BauweltScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_bauwelt_scraper():
    """Test the visual AI scraper."""
    print("=" * 60)
    print("Testing Bauwelt Visual AI Scraper")
    print("=" * 60)

    scraper = BauweltScraper()

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

        stats = await scraper.tracker.get_stats(source_id="bauwelt")

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
                print(f"   Hero Image: {'Yes' if article.get('hero_image') else 'No'}")
        else:
            print("\n4. No new articles (all previously seen)")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_bauwelt_scraper())
