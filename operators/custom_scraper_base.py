# operators/custom_scraper_base.py
"""
Base Custom Scraper Infrastructure
Provides common functionality for custom site scrapers (sites without working RSS feeds).

Architecture:
    - BaseCustomScraper: Abstract base class with common methods
    - Site-specific scrapers inherit and implement fetch_articles()
    - Consistent output format matching RSS fetcher

Usage:
    from operators.custom_scrapers.landezine import LandezineScraper

    scraper = LandezineScraper()
    articles = await scraper.fetch_articles(hours=24)
"""

import asyncio
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from urllib.parse import urljoin, urlparse
from html import unescape

from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError
)


class BaseCustomScraper(ABC):
    """
    Abstract base class for custom site scrapers.

    Each source-specific scraper inherits from this and implements:
    - source_id: str
    - source_name: str
    - base_url: str
    - fetch_articles(hours) -> list[dict]
    """

    # Subclasses must define these
    source_id: str
    source_name: str
    base_url: str

    def __init__(self):
        """Initialize the custom scraper."""
        if not all([self.source_id, self.source_name, self.base_url]):
            raise ValueError(
                f"{self.__class__.__name__} must define source_id, source_name, and base_url"
            )

        # Browser settings
        self.browser: Optional[Browser] = None
        self.playwright = None
        self.timeout = 20000  # 20 seconds

        # User-Agent to avoid blocks
        self.user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        print(f"[{self.source_id}] Custom scraper initialized")

    @abstractmethod
    async def fetch_articles(self, hours: int = 24) -> list[dict]:
        """
        Fetch articles from the last N hours.

        Must return list of dicts with structure:
        {
            "title": str,
            "link": str,
            "description": str,
            "published": str (ISO format),
            "guid": str,
            "source_id": str,
            "source_name": str,
            "custom_scraped": True,
            "hero_image": {
                "url": str,
                "width": int or None,
                "height": int or None,
                "source": "scraper"
            } or None
        }

        Args:
            hours: How many hours back to look for articles

        Returns:
            List of article dicts
        """
        pass

    # =========================================================================
    # Browser Management
    # =========================================================================

    async def _initialize_browser(self):
        """Initialize Playwright browser if needed."""
        if self.browser:
            return

        try:
            self.playwright = await async_playwright().start()

            # Railway Browserless configuration (exact pattern from scraper.py)
            browserless_endpoint = (
                os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT_PRIVATE') or
                os.getenv('BROWSER_PLAYWRIGHT_ENDPOINT') or
                os.getenv('BROWSERLESS_URL')
            )
            browserless_token = os.getenv('BROWSER_TOKEN')

            if browserless_endpoint:
                # Connect to Railway Browserless
                connect_url = browserless_endpoint
                if browserless_token and 'token=' not in connect_url:
                    separator = '&' if '?' in connect_url else '?'
                    connect_url = f"{connect_url}{separator}token={browserless_token}"

                self.browser = await self.playwright.chromium.connect(
                    connect_url,
                    timeout=25000
                )
                print(f"[{self.source_id}] Connected to Railway Browserless")
            else:
                # Local Playwright fallback
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ]
                )
                print(f"[{self.source_id}] Using local Playwright")

        except Exception as e:
            print(f"[{self.source_id}] Browser init failed: {e}")
            raise

    async def _create_page(self) -> Page:
        """Create a new browser page with proper configuration."""
        await self._initialize_browser()

        if not self.browser:
            raise RuntimeError("Browser not initialized")

        page = await self.browser.new_page(
            user_agent=self.user_agent,
            viewport={"width": 1280, "height": 800}
        )

        # Block unnecessary resources for speed
        await page.route("**/*", self._block_resources)

        return page

    async def _block_resources(self, route):
        """Block ads, trackers, and unnecessary resources."""
        request = route.request
        resource_type = request.resource_type
        url = request.url.lower()

        # Block by resource type
        blocked_types = ['font', 'media', 'websocket', 'manifest']
        if resource_type in blocked_types:
            await route.abort()
            return

        # Block known ad/tracking domains
        blocked_domains = [
            'google-analytics', 'googletagmanager', 'googlesyndication',
            'doubleclick', 'facebook.com', 'twitter.com',
            'adservice', 'advertising', 'analytics',
        ]

        if any(domain in url for domain in blocked_domains):
            await route.abort()
            return

        await route.continue_()

    async def close(self):
        """Clean shutdown of browser."""
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass

        print(f"[{self.source_id}] Browser closed")

    # =========================================================================
    # Common Helper Methods
    # =========================================================================

    def _parse_date(self, date_string: str) -> Optional[str]:
        """
        Parse various date formats into ISO format.

        Handles:
        - "January 11, 2026"
        - "11 January 2026"
        - "2026-01-16"
        - "16/01/2026"

        Args:
            date_string: Raw date string

        Returns:
            ISO format datetime string or None
        """
        if not date_string:
            return None

        date_string = date_string.strip()

        # Pattern 1: "January 11, 2026" or "11 January 2026"
        pattern1 = r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})'
        match = re.search(pattern1, date_string, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_name = match.group(2)
            year = int(match.group(3))

            month_map = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                'september': 9, 'october': 10, 'november': 11, 'december': 12
            }
            month = month_map.get(month_name.lower(), 1)

            try:
                dt = datetime(year, month, day, tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                pass

        # Pattern 2: "2026-01-16"
        pattern2 = r'(\d{4})-(\d{2})-(\d{2})'
        match = re.search(pattern2, date_string)
        if match:
            try:
                dt = datetime(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                    tzinfo=timezone.utc
                )
                return dt.isoformat()
            except ValueError:
                pass

        # Pattern 3: ISO format already
        if 'T' in date_string:
            try:
                dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
                return dt.isoformat()
            except (ValueError, AttributeError):
                pass

        return None

    def _is_within_timeframe(self, date_string: str, hours: int) -> bool:
        """
        Check if a date is within the specified timeframe.

        Args:
            date_string: ISO format date string
            hours: Hours to look back

        Returns:
            True if within timeframe, False otherwise
        """
        if not date_string:
            return True  # Include if no date (edge case)

        try:
            article_date = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            return article_date >= cutoff
        except:
            return True  # Include if parsing fails

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text content.

        Args:
            text: Raw text

        Returns:
            Cleaned text
        """
        if not text:
            return ""

        # Decode HTML entities
        text = unescape(text)

        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text

    def _resolve_url(self, url: str) -> str:
        """
        Resolve relative URLs to absolute.

        Args:
            url: URL (can be relative or absolute)

        Returns:
            Absolute URL
        """
        if not url:
            return ""

        if url.startswith('http'):
            return url

        if url.startswith('//'):
            return 'https:' + url

        return urljoin(self.base_url, url)

    def _extract_hero_image_from_html(self, html: str, base_url: str) -> Optional[dict]:
        """
        Extract hero image from HTML content.

        Looks for:
        - og:image meta tag
        - twitter:image meta tag
        - First large image

        Args:
            html: HTML content
            base_url: Base URL for resolving relative paths

        Returns:
            Dict with url, width, height or None
        """
        # Try og:image
        og_pattern = r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']'
        match = re.search(og_pattern, html, re.IGNORECASE)
        if match:
            url = self._resolve_url(match.group(1))
            return {
                "url": url,
                "width": None,
                "height": None,
                "source": "scraper"
            }

        # Try twitter:image
        twitter_pattern = r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']'
        match = re.search(twitter_pattern, html, re.IGNORECASE)
        if match:
            url = self._resolve_url(match.group(1))
            return {
                "url": url,
                "width": None,
                "height": None,
                "source": "scraper"
            }

        return None

    # =========================================================================
    # Validation
    # =========================================================================

    def _validate_article(self, article: dict) -> bool:
        """
        Validate that an article has required fields.

        Args:
            article: Article dict

        Returns:
            True if valid, False otherwise
        """
        required_fields = ['title', 'link', 'source_id', 'source_name']

        for field in required_fields:
            if not article.get(field):
                print(f"[{self.source_id}] Invalid article: missing {field}")
                return False

        return True

    def _create_article_dict(
        self,
        title: str,
        link: str,
        description: str = "",
        published: Optional[str] = None,
        hero_image: Optional[dict] = None
    ) -> dict:
        """
        Create a standardized article dict.

        Args:
            title: Article title
            link: Article URL
            description: Article description/excerpt
            published: Publication date (ISO format)
            hero_image: Hero image dict

        Returns:
            Standardized article dict
        """
        article = {
            "title": self._clean_text(title),
            "link": self._resolve_url(link),
            "description": self._clean_text(description),
            "published": published,
            "guid": self._resolve_url(link),  # Use URL as GUID
            "source_id": self.source_id,
            "source_name": self.source_name,
            "custom_scraped": True,
            "hero_image": hero_image,
        }

        return article

    # =========================================================================
    # Testing
    # =========================================================================

    async def test_connection(self) -> bool:
        """
        Test if the scraper can access the site.

        Returns:
            True if successful, False otherwise
        """
        try:
            page = await self._create_page()

            try:
                await page.goto(self.base_url, timeout=self.timeout)
                print(f"[{self.source_id}] Connection test: OK")
                return True
            finally:
                await page.close()

        except Exception as e:
            print(f"[{self.source_id}] Connection test failed: {e}")
            return False


# =============================================================================
# Custom Scraper Registry
# =============================================================================

class CustomScraperRegistry:
    """
    Registry for managing custom scrapers.

    Usage:
        registry = CustomScraperRegistry()
        registry.register(LandezineScraper)

        scraper = registry.get("landezine")
        articles = await scraper.fetch_articles()
    """

    def __init__(self):
        self._scrapers: dict[str, type[BaseCustomScraper]] = {}

    def register(self, scraper_class: type[BaseCustomScraper]):
        """Register a custom scraper class."""
        if not issubclass(scraper_class, BaseCustomScraper):
            raise ValueError(f"{scraper_class} must inherit from BaseCustomScraper")

        # Get source_id from class
        source_id = getattr(scraper_class, 'source_id', None)
        if not source_id:
            raise ValueError(f"{scraper_class} must define source_id")

        self._scrapers[source_id] = scraper_class
        print(f"[Registry] Registered custom scraper: {source_id}")

    def get(self, source_id: str) -> Optional[BaseCustomScraper]:
        """Get a scraper instance by source_id."""
        scraper_class = self._scrapers.get(source_id)
        if scraper_class:
            return scraper_class()
        return None

    def has_scraper(self, source_id: str) -> bool:
        """Check if a scraper is registered."""
        return source_id in self._scrapers

    def list_scrapers(self) -> list[str]:
        """List all registered scraper source_ids."""
        return list(self._scrapers.keys())


# Global registry instance
custom_scraper_registry = CustomScraperRegistry()