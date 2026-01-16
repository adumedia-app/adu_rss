# operators/custom_scrapers/landezine.py
"""
Landezine Custom Scraper
Scrapes landscape architecture news from Landezine.com

Site Structure:
- Homepage: https://landezine.com/
- Article grid with clear date markers
- Categories: Featured Articles, Projects, News, Selected Articles
- Publication dates in format: "January 11, 2026"

Usage:
    from operators.custom_scrapers.landezine import LandezineScraper

    scraper = LandezineScraper()
    articles = await scraper.fetch_articles(hours=24)
    await scraper.close()
"""

import re
from typing import Optional
from datetime import datetime, timezone

from operators.custom_scraper_base import BaseCustomScraper, custom_scraper_registry


class LandezineScraper(BaseCustomScraper):
    """
    Custom scraper for Landezine.com
    Landscape architecture projects and articles.
    """

    source_id = "landezine"
    source_name = "Landezine"
    base_url = "https://landezine.com"

    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch articles from Landezine homepage.

        Args:
            hours: How many hours back to look for articles

        Returns:
            List of article dicts
        """
        print(f"[{self.source_id}] Fetching articles from last {hours} hours...")

        try:
            page = await self._create_page()

            try:
                # Navigate to homepage
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_timeout(2000)  # Wait for content to load

                # Extract articles using JavaScript
                articles_data = await page.evaluate(r"""
                    () => {
                        const articles = [];

                        // Look for article elements
                        // Landezine uses various selectors for different content types
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

                            // Extract date - look for text patterns
                            const datePatterns = [
                                /(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})/i,
                                /(\d{4})-(\d{2})-(\d{2})/
                            ];

                            let dateText = '';
                            const textContent = article.textContent;

                            for (const pattern of datePatterns) {
                                const match = textContent.match(pattern);
                                if (match) {
                                    dateText = match[0];
                                    break;
                                }
                            }

                            // Extract description/excerpt
                            const excerptEl = article.querySelector('p, .excerpt, .description, [class*="excerpt"]');
                            const description = excerptEl ? excerptEl.textContent.trim() : '';

                            // Extract image
                            const imgEl = article.querySelector('img');
                            const imageUrl = imgEl ? imgEl.src : null;
                            const imageWidth = imgEl ? imgEl.naturalWidth || imgEl.width : null;
                            const imageHeight = imgEl ? imgEl.naturalHeight || imgEl.height : null;

                            // Extract categories
                            const categoryEls = article.querySelectorAll('.category, [class*="categor"]');
                            const categories = Array.from(categoryEls).map(el => el.textContent.trim());

                            // Only include if we have essential data
                            if (title && link) {
                                articles.push({
                                    title: title,
                                    link: link,
                                    date_text: dateText,
                                    description: description,
                                    image_url: imageUrl,
                                    image_width: imageWidth,
                                    image_height: imageHeight,
                                    categories: categories
                                });
                            }
                        });

                        return articles;
                    }
                """)

                print(f"[{self.source_id}] Found {len(articles_data)} potential articles")

                # Process and filter articles
                articles = []
                for data in articles_data:
                    # Parse the date
                    published = self._parse_date(data['date_text'])

                    # Check if within timeframe
                    if published and not self._is_within_timeframe(published, hours):
                        continue

                    # Build hero image dict
                    hero_image = None
                    if data.get('image_url'):
                        hero_image = {
                            "url": data['image_url'],
                            "width": data.get('image_width'),
                            "height": data.get('image_height'),
                            "source": "scraper"
                        }

                    # Create article dict
                    article = self._create_article_dict(
                        title=data['title'],
                        link=data['link'],
                        description=data.get('description', ''),
                        published=published,
                        hero_image=hero_image
                    )

                    # Validate and add
                    if self._validate_article(article):
                        articles.append(article)

                print(f"[{self.source_id}] Extracted {len(articles)} articles from last {hours}h")
                return articles

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error fetching articles: {e}")
            return []

    async def fetch_article_content(self, url: str) -> Optional[dict]:
        """
        Fetch full content from a single article page.

        This can be used to get more detailed content if needed.

        Args:
            url: Article URL

        Returns:
            Dict with content, images, etc. or None
        """
        try:
            page = await self._create_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_timeout(1500)

                # Extract detailed content
                content_data = await page.evaluate("""
                    () => {
                        // Try to find main content area
                        const contentSelectors = [
                            'article .entry-content',
                            '.article-content',
                            'article',
                            '.post-content',
                            'main'
                        ];

                        let contentEl = null;
                        for (const selector of contentSelectors) {
                            contentEl = document.querySelector(selector);
                            if (contentEl) break;
                        }

                        if (!contentEl) return null;

                        // Get text content
                        const textContent = contentEl.textContent.trim();

                        // Get all images
                        const images = Array.from(contentEl.querySelectorAll('img')).map(img => ({
                            url: img.src,
                            alt: img.alt,
                            width: img.naturalWidth || img.width,
                            height: img.naturalHeight || img.height
                        }));

                        // Get hero image from og:image
                        const ogImage = document.querySelector('meta[property="og:image"]');
                        const heroImageUrl = ogImage ? ogImage.content : null;

                        return {
                            content: textContent,
                            images: images,
                            hero_image_url: heroImageUrl
                        };
                    }
                """)

                return content_data

            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Error fetching article content: {e}")
            return None


# Register this scraper
custom_scraper_registry.register(LandezineScraper)


# =============================================================================
# Standalone Test
# =============================================================================

async def test_landezine_scraper():
    """Test the Landezine scraper."""
    print("=" * 60)
    print("Testing Landezine Custom Scraper")
    print("=" * 60)

    scraper = LandezineScraper()

    try:
        # Test connection
        print("\n1. Testing connection...")
        connected = await scraper.test_connection()

        if not connected:
            print("   ❌ Connection failed")
            return

        # Fetch articles
        print("\n2. Fetching articles from last 7 days...")
        articles = await scraper.fetch_articles(hours=24 * 7)

        print(f"\n   ✅ Found {len(articles)} articles")

        # Display first 3 articles
        print("\n3. Sample articles:")
        for i, article in enumerate(articles[:3], 1):
            print(f"\n   --- Article {i} ---")
            print(f"   Title: {article['title'][:60]}...")
            print(f"   Link: {article['link']}")
            print(f"   Published: {article.get('published', 'No date')}")
            print(f"   Hero Image: {'Yes' if article.get('hero_image') else 'No'}")
            print(f"   Description: {article.get('description', '')[:100]}...")

        # Test fetching full content from first article
        if articles:
            print("\n4. Testing full content fetch...")
            first_url = articles[0]['link']
            content = await scraper.fetch_article_content(first_url)

            if content:
                print(f"   ✅ Content length: {len(content.get('content', ''))} chars")
                print(f"   ✅ Images: {len(content.get('images', []))}")
            else:
                print("   ⚠️ No content extracted")

        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)

    finally:
        await scraper.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_landezine_scraper())