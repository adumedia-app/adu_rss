# operators/rss_fetcher.py
"""
Universal RSS Feed Fetcher
Scalable RSS fetching for multiple architecture news sources.

Handles:
- Multiple RSS feed formats (WordPress, Feedburner, custom)
- Image extraction from description HTML
- Consistent output structure across all sources
- Time-based filtering

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
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse, urljoin
from html import unescape

# Import source registry
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.sources import SOURCES, get_source_config
except ImportError:
    # Fallback for different project structures
    from sources import SOURCES, get_source_config


class RSSFetcher:
    """
    Universal RSS fetcher for architecture news sources.
    Produces consistent output structure regardless of source.
    """
    
    def __init__(self):
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
    
    def fetch_source(
        self, 
        source_id: str, 
        hours: int = 24,
        max_articles: Optional[int] = None
    ) -> list[dict]:
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
        
        print(f"[RSS] Fetching {source_name}: {rss_url}")
        
        try:
            feed = feedparser.parse(rss_url)
            
            if feed.bozo:
                print(f"[WARN] Feed warning for {source_name}: {feed.bozo_exception}")
            
            if not feed.entries:
                print(f"[WARN] No entries found for {source_name}")
                return []
            
            # Filter by time
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            articles = []
            
            for entry in feed.entries:
                article = self._parse_entry(entry, source_id, source_name)
                
                # Check if within time window
                if article["published"]:
                    try:
                        pub_date = datetime.fromisoformat(article["published"].replace('Z', '+00:00'))
                        if pub_date < cutoff_time:
                            continue
                    except:
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
    ) -> list[dict]:
        """
        Fetch articles from multiple sources.
        
        Args:
            hours: How many hours back to look
            source_ids: List of source IDs to fetch (None = all with RSS)
            max_per_source: Maximum articles per source
            
        Returns:
            Combined list of articles from all sources
        """
        all_articles = []
        
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
    
    def _parse_entry(self, entry: dict, source_id: str, source_name: str) -> dict:
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
    
    def _parse_date(self, entry: dict) -> Optional[str]:
        """Parse publication date from entry, return ISO format string."""
        # Try published_parsed first
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            try:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except:
                pass
        
        # Try updated_parsed
        if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
            try:
                dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                return dt.isoformat()
            except:
                pass
        
        # Try raw date strings
        for field in ['published', 'updated', 'pubDate']:
            raw_date = entry.get(field)
            if raw_date:
                try:
                    # Handle common formats
                    dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                    return dt.isoformat()
                except:
                    pass
        
        return None
    
    def _extract_image(
        self, 
        entry: dict, 
        description_html: str,
        base_url: str
    ) -> Optional[dict]:
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
        image_url = None
        width = None
        height = None
        
        # 1. Check media_content (common in WordPress/Feedburner)
        if hasattr(entry, 'media_content') and entry.media_content:
            for media in entry.media_content:
                if isinstance(media, dict):
                    url = media.get('url', '')
                    if self._is_image_url(url):
                        image_url = url
                        width = media.get('width')
                        height = media.get('height')
                        break
        
        # 2. Check media_thumbnail
        if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            for thumb in entry.media_thumbnail:
                if isinstance(thumb, dict):
                    url = thumb.get('url', '')
                    if url:
                        image_url = url
                        width = thumb.get('width')
                        height = thumb.get('height')
                        break
        
        # 3. Check enclosures
        if not image_url and hasattr(entry, 'enclosures') and entry.enclosures:
            for enc in entry.enclosures:
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
        if image_url and not image_url.startswith(('http://', 'https://')):
            if image_url.startswith('//'):
                image_url = 'https:' + image_url
            elif base_url:
                image_url = urljoin(base_url, image_url)
        
        # Convert width/height to int if present
        try:
            width = int(width) if width else None
        except:
            width = None
        try:
            height = int(height) if height else None
        except:
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

def fetch_rss(source_id: str, hours: int = 24) -> list[dict]:
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


def fetch_all_rss(hours: int = 24, sources: list[str] = None) -> list[dict]:
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
    test_sources = ["archdaily", "dezeen"]
    
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
        source_ids=["archdaily", "dezeen"],
        max_per_source=2
    )
    
    print(f"\nTotal articles fetched: {len(all_articles)}")
    for article in all_articles:
        print(f"  - [{article['source_name']}] {article['title'][:50]}...")
