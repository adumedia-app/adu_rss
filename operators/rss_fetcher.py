# operators/rss_fetcher.py
"""
Universal RSS Feed Fetcher
Scalable RSS fetching for multiple architecture news sources.

Handles:
- Multiple RSS feed formats (WordPress, Feedburner, custom)
- Image extraction from description HTML
- Consistent output structure across all sources
- Time-based filtering
- Browser User-Agent for sites that block bots (e.g., archpaper.com)

Usage:
    from operators.rss_fetcher import RSSFetcher

    fetcher = RSSFetcher()
    articles = fetcher.fetch_source("dezeen", hours=24)
    # Or fetch all configured sources:
    all_articles = fetcher.fetch_all_sources(hours=24)

Output Structure (consistent for all sources):
    {
        "title": str,
        "link": str,
        "description": str,
        "published": str (ISO format),
        "guid": str,
        "source_id": str,
        "source_name": str,
        "rss_image": {        # Image extracted from RSS (if available)
            "url": str,
            "width": int or None,
            "height": int or None,
        } or None
    }
"""

import re
import feedparser
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from urllib.parse import urljoin
from html import unescape

from config.sources import SOURCES, get_source_config

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False


# Browser-like User-Agent to avoid 403 blocks
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class RSSFetcher:
    """
    Universal RSS fetcher for architecture news sources.
    Produces consistent output structure regardless of source.
    """

    def __init__(self) -> None:
        """Initialize the RSS fetcher."""
        self.sources = SOURCES

        # Image extraction patterns for different RSS formats
        self._img_patterns = [
            # Standard img tag with src
            re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
            # Media content URL
            re.compile(r'url=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']', re.IGNORECASE),
        ]

        # Patterns to extract image dimensions
        self._width_pattern = re.compile(r'width=["\']?(\d+)', re.IGNORECASE)
        self._height_pattern = re.compile(r'height=["\']?(\d+)', re.IGNORECASE)

        # Default timeout for HTTP requests
        self._request_timeout = 20

    def _fetch_feed_content(self, url: str, use_browser_ua: bool = False) -> bytes:
        """
        Fetch RSS feed content with optional browser-like headers.

        Args:
            url: RSS feed URL
            use_browser_ua: Whether to use full browser headers

        Returns:
            Feed content as bytes

        Raises:
            urllib.error.URLError: If fetch fails
        """
        headers = {
            'Accept': 'application/rss+xml, application/xml, text/xml, application/atom+xml, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        if use_browser_ua:
            # Full browser-like headers to avoid detection
            headers.update({
                'User-Agent': BROWSER_USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'Connection': 'keep-alive',
            })

        request = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
            return response.read()

    def _fetch_with_cloudscraper(self, url: str) -> bytes:
        """
        Fetch URL using cloudscraper to bypass anti-bot protection.

        Args:
            url: URL to fetch

        Returns:
            Response content as bytes
        """
        if not CLOUDSCRAPER_AVAILABLE:
            raise ImportError("cloudscraper not installed")

        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'darwin',
                'desktop': True,
            }
        )
        response = scraper.get(url, timeout=self._request_timeout)
        response.raise_for_status()
        return response.content

    def fetch_source(
        self, 
        source_id: str, 
        hours: int = 24,
        max_articles: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        Fetch articles from a single source.

        Args:
            source_id: Source identifier (e.g., 'dezeen', 'archdaily')
            hours: How many hours back to look for articles
            max_articles: Maximum number of articles to return (None = all)

        Returns:
            List of article dicts with consistent structure
        """
        config = get_source_config(source_id)

        if not config:
            print(f"[WARN] Unknown source: {source_id}")
            return []

        rss_url = config.get("rss_url")
        if not rss_url:
            print(f"[WARN] No RSS URL configured for: {source_id}")
            return []

        source_name = config.get("name", source_id.capitalize())
        requires_browser_ua = config.get("requires_user_agent", False)

        print(f"[RSS] Fetching {source_name}: {rss_url}")

        try:
            # Fetch and parse the feed
            # Some sites (like archpaper.com) block default feedparser User-Agent
            # We try with browser UA first for marked sources, or as fallback

            feed = None

            if requires_browser_ua:
                # Use browser UA for sources that require it
                try:
                    content = self._fetch_feed_content(rss_url, use_browser_ua=True)
                    feed = feedparser.parse(content)
                    print("   [OK] Fetched with browser User-Agent")
                except urllib.error.URLError as e:
                    print(f"   [WARN] Browser UA fetch failed: {e}")

            if feed is None or not feed.entries:
                # Try standard feedparser (works for most sources)
                feed = feedparser.parse(rss_url)

                # If standard fails, try with browser UA as fallback
                if (feed.bozo or not feed.entries) and not requires_browser_ua:
                    try:
                        content = self._fetch_feed_content(rss_url, use_browser_ua=True)
                        feed_with_ua = feedparser.parse(content)
                        if feed_with_ua.entries:
                            feed = feed_with_ua
                            print("   [OK] Recovered with browser User-Agent")
                    except urllib.error.URLError:
                        pass  # Keep original feed result

            # If both standard and browser UA failed, try cloudscraper
            if (feed is None or not feed.entries) and CLOUDSCRAPER_AVAILABLE:
                try:
                    print("   [INFO] Trying cloudscraper...")
                    content = self._fetch_with_cloudscraper(rss_url)
                    feed = feedparser.parse(content)
                    if feed.entries:
                        print("   [OK] Success with cloudscraper")
                except Exception as e:
                    print(f"   [WARN] Cloudscraper failed: {e}")

            if feed.bozo and not feed.entries:
                print(f"[WARN] Feed error for {source_name}: {feed.bozo_exception}")
                return []

            if not feed.entries:
                print(f"[WARN] No entries found for {source_name}")
                return []

            # Filter by time
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            articles: list[dict[str, Any]] = []

            for entry in feed.entries:
                article = self._parse_entry(entry, source_id, source_name)

                # Check if within time window
                if article["published"]:
                    try:
                        pub_date = datetime.fromisoformat(
                            article["published"].replace('Z', '+00:00')
                        )
                        if pub_date < cutoff_time:
                            continue
                    except (ValueError, TypeError):
                        pass  # Include if date parsing fails

                articles.append(article)

                if max_articles and len(articles) >= max_articles:
                    break

            print(f"[OK] {source_name}: {len(articles)} articles from last {hours}h")
            return articles

        except Exception as e:
            print(f"[ERROR] Failed to fetch {source_name}: {e}")
            return []

    def fetch_all_sources(
        self, 
        hours: int = 24,
        source_ids: Optional[list[str]] = None,
        max_per_source: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """
        Fetch articles from multiple sources.

        Args:
            hours: How many hours back to look
            source_ids: List of source IDs to fetch (None = all with RSS)
            max_per_source: Maximum articles per source

        Returns:
            Combined list of articles from all sources
        """
        all_articles: list[dict[str, Any]] = []

        # Determine which sources to fetch
        if source_ids:
            sources_to_fetch = source_ids
        else:
            # Fetch all sources that have RSS URLs
            sources_to_fetch = [
                sid for sid, config in self.sources.items() 
                if config.get("rss_url")
            ]

        print(f"\n[RSS] Fetching {len(sources_to_fetch)} sources...")

        for source_id in sources_to_fetch:
            articles = self.fetch_source(
                source_id, 
                hours=hours,
                max_articles=max_per_source
            )
            all_articles.extend(articles)

        # Sort by publication date (newest first)
        all_articles.sort(
            key=lambda x: x.get("published") or "1970-01-01",
            reverse=True
        )

        print(f"\n[OK] Total: {len(all_articles)} articles from {len(sources_to_fetch)} sources")
        return all_articles


    def _parse_entry(
        self, 
        entry: Any, 
        source_id: str, 
        source_name: str
    ) -> dict[str, Any]:
        """
        Parse a single RSS entry into consistent article format.

        Args:
            entry: feedparser entry object
            source_id: Source identifier
            source_name: Human-readable source name

        Returns:
            Normalized article dict
        """
        # Extract basic fields
        title = entry.get("title", "No title")
        link = entry.get("link", "")
        guid = entry.get("id", entry.get("link", ""))

        # Get description/summary
        description_html = entry.get("summary", entry.get("description", ""))

        # Parse publication date
        published = self._parse_date(entry)

        # Extract image from various sources
        rss_image = self._extract_image(entry, description_html, link)

        # Clean description (strip HTML for storage)
        description_text = self._strip_html(description_html)

        return {
            "title": unescape(title),
            "link": link,
            "description": description_text,
            "published": published,
            "guid": guid,
            "source_id": source_id,
            "source_name": source_name,
            "rss_image": rss_image,
        }

    def _parse_date(self, entry: Any) -> Optional[str]:
        """Parse publication date from entry, return ISO format string."""
        # Try published_parsed first
        published_parsed = getattr(entry, 'published_parsed', None)
        if published_parsed:
            try:
                dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError, IndexError):
                pass

        # Try updated_parsed
        updated_parsed = getattr(entry, 'updated_parsed', None)
        if updated_parsed:
            try:
                dt = datetime(*updated_parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except (ValueError, TypeError, IndexError):
                pass

        # Try raw date strings
        for field in ['published', 'updated', 'pubDate']:
            raw_date = entry.get(field)
            if raw_date:
                try:
                    # Handle common ISO formats
                    dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                    return dt.isoformat()
                except (ValueError, TypeError):
                    pass
                
                # Handle Archi.ru non-standard format: "Wed, 28 Jan 2026 16:01:00 GMT+4"
                # Convert "GMT+N" or "GMT-N" to standard offset format "+0N00" or "-0N00"
                try:
                    if 'GMT+' in raw_date or 'GMT-' in raw_date:
                        # Extract timezone offset
                        gmt_match = re.search(r'GMT([+-])(\d+)', raw_date)
                        if gmt_match:
                            sign = gmt_match.group(1)
                            offset_hours = gmt_match.group(2)
                            # Convert to standard format: +0400, -0500, etc.
                            standard_offset = f"{sign}{offset_hours.zfill(2)}00"
                            # Replace in string
                            clean_date = re.sub(r'GMT[+-]\d+', standard_offset, raw_date)
                            
                            # Parse using strptime with timezone
                            # Format: "Wed, 28 Jan 2026 16:01:00 +0400"
                            dt = datetime.strptime(clean_date, "%a, %d %b %Y %H:%M:%S %z")
                            # Convert to UTC
                            dt_utc = dt.astimezone(timezone.utc)
                            return dt_utc.isoformat()
                except (ValueError, TypeError, AttributeError):
                    pass

        return None

    def _extract_image(
        self, 
        entry: Any, 
        description_html: str,
        base_url: str
    ) -> Optional[dict[str, Any]]:
        """
        Extract image from RSS entry.

        Checks multiple locations:
        1. media_content (common in WordPress feeds)
        2. media_thumbnail
        3. enclosures
        4. img tags in description HTML

        Args:
            entry: feedparser entry
            description_html: Raw HTML description
            base_url: Article URL for resolving relative paths

        Returns:
            Dict with url, width, height or None
        """
        image_url: Optional[str] = None
        width: Optional[int] = None
        height: Optional[int] = None

        # 1. Check media_content (common in WordPress/Feedburner)
        media_content = getattr(entry, 'media_content', None)
        if media_content:
            for media in media_content:
                if isinstance(media, dict):
                    url = media.get('url', '')
                    if self._is_image_url(url):
                        image_url = url
                        width = media.get('width')
                        height = media.get('height')
                        break

        # 2. Check media_thumbnail
        if not image_url:
            media_thumbnail = getattr(entry, 'media_thumbnail', None)
            if media_thumbnail:
                for thumb in media_thumbnail:
                    if isinstance(thumb, dict):
                        url = thumb.get('url', '')
                        if url:
                            image_url = url
                            width = thumb.get('width')
                            height = thumb.get('height')
                            break

        # 3. Check enclosures
        if not image_url:
            enclosures = getattr(entry, 'enclosures', None)
            if enclosures:
                for enc in enclosures:
                    if isinstance(enc, dict):
                        enc_type = enc.get('type', '')
                        if enc_type.startswith('image/'):
                            image_url = enc.get('href', enc.get('url', ''))
                            break

        # 4. Extract from description HTML (Dezeen style)
        if not image_url and description_html:
            for pattern in self._img_patterns:
                match = pattern.search(description_html)
                if match:
                    image_url = match.group(1)

                    # Try to get dimensions from HTML
                    w_match = self._width_pattern.search(description_html)
                    h_match = self._height_pattern.search(description_html)
                    if w_match:
                        width = int(w_match.group(1))
                    if h_match:
                        height = int(h_match.group(1))
                    break

        # Return None if no image found
        if not image_url:
            return None

        # Resolve relative URLs
        if not image_url.startswith(('http://', 'https://')):
            if image_url.startswith('//'):
                image_url = 'https:' + image_url
            elif base_url:
                image_url = urljoin(base_url, image_url)

        # Convert width/height to int if present
        try:
            width = int(width) if width else None
        except (ValueError, TypeError):
            width = None
        try:
            height = int(height) if height else None
        except (ValueError, TypeError):
            height = None

        return {
            "url": image_url,
            "width": width,
            "height": height,
        }

    def _is_image_url(self, url: str) -> bool:
        """Check if URL looks like an image."""
        if not url:
            return False
        url_lower = url.lower()
        return any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])

    def _strip_html(self, html: str) -> str:
        """
        Strip HTML tags and clean up text.

        Args:
            html: Raw HTML string

        Returns:
            Clean text string
        """
        if not html:
            return ""

        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html)

        # Decode HTML entities
        text = unescape(text)

        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Remove "Read more" links
        text = re.sub(r'\s*Read more\s*$', '', text, flags=re.IGNORECASE)

        return text


# =============================================================================
# Convenience Functions
# =============================================================================

def fetch_rss(source_id: str, hours: int = 24) -> list[dict[str, Any]]:
    """
    Quick function to fetch RSS from a single source.

    Args:
        source_id: Source identifier
        hours: Hours to look back

    Returns:
        List of article dicts
    """
    fetcher = RSSFetcher()
    return fetcher.fetch_source(source_id, hours)


def fetch_all_rss(
    hours: int = 24, 
    sources: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    """
    Quick function to fetch RSS from multiple sources.

    Args:
        hours: Hours to look back
        sources: List of source IDs (None = all)

    Returns:
        Combined list of articles
    """
    fetcher = RSSFetcher()
    return fetcher.fetch_all_sources(hours, source_ids=sources)


# =============================================================================
# Standalone Test
# =============================================================================

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("RSS Fetcher Test")
    print("=" * 60)

    fetcher = RSSFetcher()

    # Test individual sources
    test_sources = ["archdaily", "dezeen", "archpaper"]

    for source_id in test_sources:
        print(f"\n{'='*40}")
        print(f"Testing: {source_id}")
        print("=" * 40)

        articles = fetcher.fetch_source(source_id, hours=24, max_articles=3)

        for i, article in enumerate(articles, 1):
            print(f"\n--- Article {i} ---")
            print(json.dumps(article, indent=2, ensure_ascii=False, default=str))

    # Test fetching all sources
    print(f"\n{'='*60}")
    print("Testing: Fetch all sources")
    print("=" * 60)

    all_articles = fetcher.fetch_all_sources(
        hours=24, 
        source_ids=["archdaily", "dezeen", "archpaper"],
        max_per_source=2
    )

    print(f"\nTotal articles fetched: {len(all_articles)}")
    for article in all_articles:
        print(f"  - [{article['source_name']}] {article['title'][:50]}...")