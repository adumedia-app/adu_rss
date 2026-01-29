# config/sources.py
"""
News Source Registry - RSS Pipeline
Configuration for RSS feed sources only.

This is the RSS-only version for the dedicated RSS service.
Custom scrapers are handled by a separate service.

Organization:
    - Tier 1: Global Primary Sources (high volume, daily monitoring)
    - Tier 2: Regional Sources (organized by geography)

Usage:
    from config.sources import get_source_name, get_source_config, SOURCES
    from config.sources import get_sources_by_tier, get_all_source_ids
"""

from urllib.parse import urlparse
from typing import Optional


# =============================================================================
# RSS Source Configuration
# =============================================================================

SOURCES = {
    # =========================================================================
    # TIER 1 - Global Primary Sources
    # =========================================================================

    "archdaily": {
        "name": "ArchDaily",
        "domains": ["archdaily.com", "www.archdaily.com"],
        "rss_url": "https://feeds.feedburner.com/Archdaily",
        "tier": 1,
        "region": "global",
        "scrape_timeout": 25000,
    },
    "dezeen": {
        "name": "Dezeen",
        "domains": ["dezeen.com", "www.dezeen.com"],
        "rss_url": "http://feeds.feedburner.com/dezeen",
        "tier": 1,
        "region": "uk",
        "scrape_timeout": 25000,
    },
    "designboom": {
        "name": "Designboom",
        "domains": ["designboom.com", "www.designboom.com"],
        "rss_url": "https://www.designboom.com/feed",
        "tier": 1,
        "region": "italy",
        "scrape_timeout": 20000,
    },
    "architects_journal": {
        "name": "The Architects' Journal",
        "domains": ["architectsjournal.co.uk", "www.architectsjournal.co.uk"],
        "rss_url": "https://www.architectsjournal.co.uk/feed",
        "tier": 1,
        "region": "uk",
        "scrape_timeout": 20000,
    },
    "archpaper": {
        "name": "The Architect's Newspaper",
        "domains": ["archpaper.com", "www.archpaper.com"],
        "rss_url": "https://www.archpaper.com/feed",
        "tier": 1,
        "region": "north_america",
        "scrape_timeout": 20000,
        "requires_user_agent": True,
    },

    # =========================================================================
    # TIER 2 - North America
    # =========================================================================

    "canadian_architect": {
        "name": "Canadian Architect",
        "domains": ["canadianarchitect.com", "www.canadianarchitect.com"],
        "rss_url": "https://www.canadianarchitect.com/feed/",
        "tier": 2,
        "region": "north_america",
        "scrape_timeout": 20000,
    },
    "design_milk": {
        "name": "Design Milk",
        "domains": ["design-milk.com", "www.design-milk.com"],
        "rss_url": "http://feeds.feedburner.com/design-milk",
        "tier": 2,
        "region": "north_america",
        "category": "design_culture",
        "scrape_timeout": 20000,
    },
    "leibal": {
        "name": "Leibal",
        "domains": ["leibal.com", "www.leibal.com"],
        "rss_url": "https://leibal.com/feed/",
        "tier": 2,
        "region": "north_america",
        "category": "minimalism",
        "scrape_timeout": 20000,
    },
    "construction_specifier": {
        "name": "The Construction Specifier",
        "domains": ["constructionspecifier.com", "www.constructionspecifier.com"],
        "rss_url": "https://www.constructionspecifier.com/feed/",
        "tier": 2,
        "region": "north_america",
        "category": "technical",
        "scrape_timeout": 20000,
    },
    "architectural_record": {
        "name": "Architectural Record",
        "domains": ["architecturalrecord.com", "www.architecturalrecord.com"],
        "rss_url": "https://www.architecturalrecord.com/rss/topic/305",
        "tier": 2,
        "region": "north_america",
        "category": "technical",
        "scrape_timeout": 20000,
    },
    "next_city": {
        "name": "Next City",
        "domains": ["nextcity.org", "www.nextcity.org"],
        "rss_url": "https://nextcity.org/feeds/daily",
        "tier": 2,
        "region": "north_america",
        "category": "urbanism",
        "scrape_timeout": 20000,
        "requires_user_agent": True,
    },
    "places_journal": {
        "name": "Places Journal",
        "domains": ["placesjournal.org", "www.placesjournal.org"],
        "rss_url": "http://feeds.feedburner.com/PlacesJournal",
        "tier": 2,
        "region": "north_america",
        "category": "critical_theory",
        "scrape_timeout": 20000,
    },

    # =========================================================================
    # TIER 2 - Europe
    # =========================================================================

    "architectural_review": {
        "name": "The Architectural Review",
        "domains": ["architectural-review.com", "www.architectural-review.com"],
        "rss_url": "https://www.architectural-review.com/feed",
        "tier": 2,
        "region": "europe",
        "category": "critique",
        "scrape_timeout": 20000,
    },
    "archiru": {
        "name": "Archi.ru",
        "domains": ["archi.ru", "www.archi.ru"],
        "rss_url": "https://archi.ru/rss.xml",
        "tier": 2,
        "region": "europe",
        "category": "russia",
        "scrape_timeout": 20000,
    },

    # =========================================================================
    # TIER 2 - Asia-Pacific
    # =========================================================================

    "yellowtrace": {
        "name": "Yellowtrace",
        "domains": ["yellowtrace.com.au", "www.yellowtrace.com.au"],
        "rss_url": "https://www.yellowtrace.com.au/feed",
        "tier": 2,
        "region": "asia_pacific",
        "scrape_timeout": 20000,
    },
    "architectureau": {
        "name": "ArchitectureAU",
        "domains": ["architectureau.com", "www.architectureau.com"],
        "rss_url": "https://architectureau.com/rss.xml",
        "tier": 2,
        "region": "asia_pacific",
        "scrape_timeout": 20000,
    },
    "architecture_now": {
        "name": "Architecture Now",
        "domains": ["architecturenow.co.nz", "www.architecturenow.co.nz"],
        "rss_url": "https://architecturenow.co.nz/rss.xml",
        "tier": 2,
        "region": "asia_pacific",
        "scrape_timeout": 20000,
    },
    "architecture_update": {
        "name": "Architecture Update",
        "domains": ["architectureupdate.in", "www.architectureupdate.in"],
        "rss_url": "https://architectureupdate.in/feed",
        "tier": 2,
        "region": "asia_pacific",
        "scrape_timeout": 20000,
    },
    "indesignlive_sg": {
        "name": "Indesign Live Singapore",
        "domains": ["indesignlive.sg", "www.indesignlive.sg"],
        "rss_url": "https://www.indesignlive.sg/feed",
        "tier": 2,
        "region": "asia_pacific",
        "scrape_timeout": 20000,
    },

    # =========================================================================
    # TIER 2 - Latin America
    # =========================================================================

    "archdaily_brasil": {
        "name": "ArchDaily Brasil",
        "domains": ["archdaily.com.br", "www.archdaily.com.br"],
        "rss_url": "https://www.archdaily.com.br/br/feed",
        "tier": 2,
        "region": "latin_america",
        "scrape_timeout": 25000,
    },
    "arquine": {
        "name": "Arquine",
        "domains": ["arquine.com", "www.arquine.com"],
        "rss_url": "https://arquine.com/feed/",
        "tier": 2,
        "region": "latin_america",
        "scrape_timeout": 20000,
    },

    # =========================================================================
    # TIER 2 - Middle East / Computational
    # =========================================================================

    "parametric_architecture": {
        "name": "Parametric Architecture",
        "domains": ["parametric-architecture.com", "www.parametric-architecture.com"],
        "rss_url": "https://parametric-architecture.com/feed/",
        "tier": 2,
        "region": "middle_east",
        "category": "computational",
        "scrape_timeout": 20000,
    },
}


# =============================================================================
# Build Lookup Tables
# =============================================================================

_DOMAIN_TO_SOURCE = {}
for source_id, config in SOURCES.items():
    for domain in config["domains"]:
        _DOMAIN_TO_SOURCE[domain.lower()] = source_id


# =============================================================================
# Core Functions
# =============================================================================

def get_source_id(url: str) -> Optional[str]:
    """Get source ID from URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        return _DOMAIN_TO_SOURCE.get(domain)
    except Exception:
        return None


def get_source_name(url: str) -> str:
    """Get display name for a source URL."""
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
    except Exception:
        pass

    return "Source"


def get_source_config(source_id: str) -> Optional[dict]:
    """Get full configuration for a source."""
    return SOURCES.get(source_id)


def get_source_rss(source_id: str) -> Optional[str]:
    """Get RSS URL for a source."""
    config = SOURCES.get(source_id)
    if config:
        return config.get("rss_url")
    return None


# =============================================================================
# Filtering Functions
# =============================================================================

def get_all_rss_sources() -> list[dict]:
    """Get all sources that have RSS feeds."""
    result = []
    for source_id, config in SOURCES.items():
        if config.get("rss_url"):
            result.append({
                "id": source_id,
                "name": config["name"],
                "rss_url": config["rss_url"],
                "tier": config.get("tier", 2),
                "region": config.get("region", "global"),
            })
    return result


def get_sources_by_tier(tier: int) -> list[dict]:
    """Get all sources for a specific tier."""
    result = []
    for source_id, config in SOURCES.items():
        if config.get("tier") == tier:
            result.append({"id": source_id, **config})
    return result


def get_sources_by_region(region: str) -> list[dict]:
    """Get all sources for a specific region."""
    result = []
    for source_id, config in SOURCES.items():
        if config.get("region") == region:
            result.append({"id": source_id, **config})
    return result


def get_source_ids_by_tier(tier: int) -> list[str]:
    """Get list of source IDs for a specific tier."""
    return [
        source_id for source_id, config in SOURCES.items()
        if config.get("tier") == tier
    ]


def get_all_source_ids() -> list[str]:
    """Get all source IDs."""
    return list(SOURCES.keys())


def is_custom_scraper(source_id: str) -> bool:
    """Check if a source uses custom scraper. Always False for RSS-only service."""
    return False


def get_source_stats() -> dict:
    """Get statistics about configured sources."""
    stats = {
        "total": len(SOURCES),
        "rss_sources": len(SOURCES),
        "custom_scrapers": 0,
        "by_tier": {},
        "by_region": {},
    }

    for config in SOURCES.values():
        tier = config.get("tier", 2)
        region = config.get("region", "unknown")

        stats["by_tier"][tier] = stats["by_tier"].get(tier, 0) + 1
        stats["by_region"][region] = stats["by_region"].get(region, 0) + 1

    return stats


# =============================================================================
# Test
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("ADUmedia RSS Sources")
    print("=" * 50)

    stats = get_source_stats()
    print(f"\nTotal RSS sources: {stats['total']}")

    print("\nBy Tier:")
    for tier, count in sorted(stats["by_tier"].items()):
        print(f"  Tier {tier}: {count} sources")

    print("\nBy Region:")
    for region, count in sorted(stats["by_region"].items()):
        print(f"  {region}: {count}")

    print("\nAll RSS Sources:")
    for source in get_all_rss_sources():
        print(f"  {source['id']:25} [{source['tier']}] {source['name']}")


