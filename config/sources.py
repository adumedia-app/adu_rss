# config/sources.py
"""
News Source Registry
Central configuration for all monitored news sources.

Usage:
    from config.sources import get_source_name, get_source_config, SOURCES
"""

from urllib.parse import urlparse
from typing import Optional


# =============================================================================
# Source Configuration
# Each source has: name, domains, rss_url (optional), scrape_config (optional)
# =============================================================================

SOURCES = {
    "archdaily": {
        "name": "ArchDaily",
        "domains": ["archdaily.com", "www.archdaily.com"],
        "rss_url": "https://feeds.feedburner.com/Archdaily",
        "scrape_timeout": 25000,
    },
    "dezeen": {
        "name": "Dezeen",
        "domains": ["dezeen.com", "www.dezeen.com"],
        # Using Feedburner URL - dezeen.com/feed/ returns 403
        "rss_url": "http://feeds.feedburner.com/dezeen",
        "scrape_timeout": 25000,
    },
    "designboom": {
        "name": "Designboom",
        "domains": ["designboom.com", "www.designboom.com"],
        "rss_url": "https://www.designboom.com/feed/",
        "scrape_timeout": 20000,
    },
    "domus": {
        "name": "Domus",
        "domains": ["domusweb.it", "www.domusweb.it"],
        "rss_url": "https://www.domusweb.it/en.rss.xml",
        "scrape_timeout": 20000,
    },
    "architizer": {
        "name": "Architizer",
        "domains": ["architizer.com", "www.architizer.com"],
        "rss_url": None,  # No RSS available
        "scrape_timeout": 20000,
    },
    "archpaper": {
        "name": "The Architect's Newspaper",
        "domains": ["archpaper.com", "www.archpaper.com"],
        "rss_url": "https://www.archpaper.com/feed/",
        "scrape_timeout": 18000,
    },
    "architectural_digest": {
        "name": "Architectural Digest",
        "domains": ["architecturaldigest.com", "www.architecturaldigest.com"],
        "rss_url": "https://www.architecturaldigest.com/feed/rss",
        "scrape_timeout": 20000,
    },
    "architect_magazine": {
        "name": "Architect Magazine",
        "domains": ["architectmagazine.com", "www.architectmagazine.com"],
        "rss_url": "https://www.architectmagazine.com/rss",
        "scrape_timeout": 20000,
    },
    "wallpaper": {
        "name": "Wallpaper",
        "domains": ["wallpaper.com", "www.wallpaper.com"],
        "rss_url": "https://www.wallpaper.com/rss",
        "scrape_timeout": 20000,
    },
    "afasia": {
        "name": "Afasia",
        "domains": ["afasiaarchzine.com", "www.afasiaarchzine.com"],
        "rss_url": "https://afasiaarchzine.com/feed/",
        "scrape_timeout": 15000,
    },
    "divisare": {
        "name": "Divisare",
        "domains": ["divisare.com", "www.divisare.com"],
        "rss_url": "https://divisare.com/feed",
        "scrape_timeout": 20000,
    },
    "curbed": {
        "name": "Curbed",
        "domains": ["curbed.com", "www.curbed.com"],
        "rss_url": "https://www.curbed.com/rss/index.xml",
        "scrape_timeout": 20000,
    },
    "dwell": {
        "name": "Dwell",
        "domains": ["dwell.com", "www.dwell.com"],
        "rss_url": "https://www.dwell.com/rss",
        "scrape_timeout": 20000,
    },
}


# Build domain-to-source lookup table
_DOMAIN_TO_SOURCE = {}
for source_id, config in SOURCES.items():
    for domain in config["domains"]:
        _DOMAIN_TO_SOURCE[domain.lower()] = source_id


def get_source_id(url: str) -> Optional[str]:
    """
    Get source ID from URL.

    Args:
        url: Article URL

    Returns:
        Source ID (e.g., 'archdaily') or None if not recognized
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return _DOMAIN_TO_SOURCE.get(domain)
    except:
        return None


def get_source_name(url: str) -> str:
    """
    Get display name for a source URL.

    Args:
        url: Article URL

    Returns:
        Human-readable source name (e.g., 'ArchDaily')
    """
    if not url:
        return "Source"

    source_id = get_source_id(url)

    if source_id and source_id in SOURCES:
        return SOURCES[source_id]["name"]

    # Fallback: clean up domain name
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        parts = domain.split(".")
        if parts:
            return parts[0].capitalize()
    except:
        pass

    return "Source"


def get_source_config(source_id: str) -> Optional[dict]:
    """
    Get full configuration for a source.

    Args:
        source_id: Source ID (e.g., 'archdaily')

    Returns:
        Source config dict or None
    """
    return SOURCES.get(source_id)


def get_source_rss(source_id: str) -> Optional[str]:
    """
    Get RSS URL for a source.

    Args:
        source_id: Source ID

    Returns:
        RSS feed URL or None
    """
    config = SOURCES.get(source_id)
    if config:
        return config.get("rss_url")
    return None


def get_all_rss_sources() -> list[dict]:
    """
    Get all sources that have RSS feeds.

    Returns:
        List of dicts with 'id', 'name', 'rss_url'
    """
    result = []
    for source_id, config in SOURCES.items():
        if config.get("rss_url"):
            result.append({
                "id": source_id,
                "name": config["name"],
                "rss_url": config["rss_url"],
            })
    return result


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    # Test source lookup
    test_urls = [
        "https://www.archdaily.com/123456/some-article",
        "https://dezeen.com/2024/01/15/building-project",
        "https://www.domusweb.it/en/architecture/2024/project.html",
        "https://unknown-site.com/article",
    ]

    print("Source Registry Test")
    print("=" * 50)

    for url in test_urls:
        name = get_source_name(url)
        source_id = get_source_id(url)
        print(f"{url[:40]}...")
        print(f"  -> Name: {name}, ID: {source_id}")
        print()

    print("RSS Sources:")
    print("=" * 50)
    for source in get_all_rss_sources():
        print(f"  {source['name']}: {source['rss_url'][:50]}...")