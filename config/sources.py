# config/sources.py
"""
News Source Registry
Central configuration for all monitored architecture and design news sources.

Organization:
    - Tier 1: Global Primary Sources (high volume, daily monitoring)
    - Tier 2: Regional Sources (organized by geography)

Note: Sources marked with requires_user_agent=True need browser User-Agent
      to avoid 403 blocks. Some may only work from certain IP ranges (Railway vs Replit).

Usage:
    from config.sources import get_source_name, get_source_config, SOURCES
    from config.sources import get_sources_by_tier, get_sources_by_region
"""

from urllib.parse import urlparse
from typing import Optional


# =============================================================================
# Source Configuration - 19 Sources (18 confirmed + 1 Railway-only)
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
    # Archpaper: Works in browser, returns 403 from Replit IPs
    # Keep it - might work on Railway which has different IPs
    "archpaper": {
        "name": "The Architect's Newspaper",
        "domains": ["archpaper.com", "www.archpaper.com"],
        "rss_url": "https://www.archpaper.com/feed",
        "tier": 1,
        "region": "north_america",
        "scrape_timeout": 20000,
        "requires_user_agent": True,  # Blocks bot requests
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
        "requires_user_agent": True,  # Has Cloudflare protection
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
    "planetizen": {
        "name": "Planetizen",
        "domains": ["planetizen.com", "www.planetizen.com"],
        "rss_url": "https://www.planetizen.com/frontpage/feed",
        "tier": 2,
        "region": "north_america",
        "category": "urbanism",
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
    "spoon_tamago": {
        "name": "Spoon & Tamago",
        "domains": ["spoon-tamago.com", "www.spoon-tamago.com"],
        "rss_url": "https://spoon-tamago.com/feed/",
        "tier": 2,
        "region": "asia_pacific",
        "category": "japan_design",
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
# REMOVED SOURCES (for reference)
# =============================================================================
# The following sources were removed due to feed issues:
#
# HTTP 403 (IP blocked - may work on Railway):
#   - MOVE TO SCRAPING landezine: http://www.landezine.com/feed (EUROPE)
#   - PUT ON HOLD - IMAGES BROKEN aasarchitecture: https://aasarchitecture.com/feed/
#
# HTTP 404 (Feed discontinued or URL changed):
#   - architectural_record: DIFFERENT FEED https://www.architecturalrecord.com/rss/topic/305
#   - MOVE TO SCRAPING metropolis: https://metropolismag.com/projects/
#   - MOVE TO SCRAPING metalocus: https://www.metalocus.es/en (EUROPE)
#   - MOVE TO SCRAPING archiru: https://archi.ru/ (RUSSIA)
#   - MOVE TO SCRAPING archidatum: https://www.archidatum.com/f (AFRICA)
#   
#
#   - MOVE TO SCRAPING domus: https://www.domusweb.it/ (EUROPE)


#   - CORRECTED FEED, DEFINITELY HAS CLOUDFLARE next_city: https://nextcity.org/feeds/daily (US, URBANISM)
#   - CORRECTED FEED URL places_journal: http://feeds.feedburner.com/PlacesJournal
# - CORRECTED FEED URL planetizen: https://www.planetizen.com/frontpage/feed (USA, URBANISM)

# =============================================================================


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
        if config.get("tier") == tier and config.get("rss_url"):
            result.append({"id": source_id, **config})
    return result


def get_sources_by_region(region: str) -> list[dict]:
    """Get all sources for a specific region."""
    result = []
    for source_id, config in SOURCES.items():
        if config.get("region") == region and config.get("rss_url"):
            result.append({"id": source_id, **config})
    return result

def get_source_ids_by_tier(tier: int) -> list[str]:
    """Get list of source IDs for a specific tier."""
    return [
        source_id for source_id, config in SOURCES.items()
        if config.get("tier") == tier and config.get("rss_url")
    ]


def get_all_source_ids() -> list[str]:
    """Get all source IDs that have RSS feeds configured."""
    return [
        source_id for source_id, config in SOURCES.items()
        if config.get("rss_url")
    ]

def get_source_stats() -> dict:
    """Get statistics about configured sources."""
    stats = {
        "total": len(SOURCES),
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
    print("Architecture News Sources")
    print("=" * 50)

    stats = get_source_stats()
    print(f"\nTotal sources: {stats['total']}")

    print("\nBy Tier:")
    for tier, count in sorted(stats["by_tier"].items()):
        print(f"  Tier {tier}: {count} sources")

    print("\nBy Region:")
    for region, count in sorted(stats["by_region"].items()):
        print(f"  {region}: {count}")

    print("\nAll Sources:")
    for source in get_all_rss_sources():
        print(f"  {source['id']:25} [{source['tier']}] {source['name']}")