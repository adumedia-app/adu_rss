# test_feeds.py
"""
RSS Feed Tester - Standalone Script
Tests all configured RSS feeds with and without browser User-Agent.

This helps identify:
- Feeds that work normally
- Feeds that need browser User-Agent (block bots)
- Feeds that are genuinely broken

Run from Replit:
    python test_feeds.py

Requirements: pip install feedparser
"""

import feedparser
import urllib.request
import urllib.error
import time
from datetime import datetime


# Browser-like User-Agent to bypass bot blocking
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 15


# =============================================================================
# ACTIVE SOURCES (in sources.py config)
# =============================================================================
SOURCES_TO_TEST = [
    # Tier 1 - Primary Sources
    ("archdaily", "https://feeds.feedburner.com/Archdaily", "ArchDaily", 1),
    ("dezeen", "http://feeds.feedburner.com/dezeen", "Dezeen", 1),
    ("designboom", "https://www.designboom.com/feed", "Designboom", 1),
    ("archpaper", "https://www.archpaper.com/feed", "The Architect's Newspaper", 1),
    ("architects_journal", "https://www.architectsjournal.co.uk/feed", "The Architects' Journal", 1),

    # Tier 2 - North America
    ("canadian_architect", "https://www.canadianarchitect.com/feed/", "Canadian Architect", 2),
    ("design_milk", "http://feeds.feedburner.com/design-milk", "Design Milk", 2),
    ("leibal", "https://leibal.com/feed/", "Leibal", 2),
    ("construction_specifier", "https://www.constructionspecifier.com/feed/", "The Construction Specifier", 2),

    # Tier 2 - Europe
    ("architectural_review", "https://www.architectural-review.com/feed", "The Architectural Review", 2),

    # Tier 2 - Asia-Pacific
    ("yellowtrace", "https://www.yellowtrace.com.au/feed", "Yellowtrace", 2),
    ("architectureau", "https://architectureau.com/rss.xml", "ArchitectureAU", 2),
    ("architecture_now", "https://architecturenow.co.nz/rss.xml", "Architecture Now", 2),
    ("architecture_update", "https://architectureupdate.in/feed", "Architecture Update", 2),
    ("spoon_tamago", "https://spoon-tamago.com/feed/", "Spoon & Tamago", 2),
    ("indesignlive_sg", "https://www.indesignlive.sg/feed", "Indesign Live Singapore", 2),

    # Tier 2 - Latin America
    ("archdaily_brasil", "https://www.archdaily.com.br/br/feed", "ArchDaily Brasil", 2),
    ("arquine", "https://arquine.com/feed/", "Arquine", 2),

    # Tier 2 - Middle East / Computational
    ("parametric_architecture", "https://parametric-architecture.com/feed/", "Parametric Architecture", 2),
]

# =============================================================================
# CANDIDATE SOURCES (removed from config, test to see if they work)
# These may work on Railway even if they fail on Replit
# =============================================================================
CANDIDATE_SOURCES = [
    # HTTP 403 on Replit (IP blocked - may work on Railway)
    ("places_journal", "https://placesjournal.org/feed/", "Places Journal", 2),
    ("aasarchitecture", "https://aasarchitecture.com/feed/", "A As Architecture", 2),

    # HTTP 404 / Discontinued (keeping for occasional re-check)
    ("architectural_record", "https://www.architecturalrecord.com/rss/headlines", "Architectural Record", 2),
    ("metropolis", "https://metropolismag.com/feed/", "Metropolis", 2),
    ("metalocus", "https://www.metalocus.es/en/feed", "Metalocus", 2),
    ("archiru", "https://archi.ru/rss", "Archi.ru", 2),
    ("archidatum", "https://www.archidatum.com/feed/", "Archidatum", 2),
    ("planetizen", "https://www.planetizen.com/rss/news", "Planetizen", 2),

    # Malformed XML
    ("domus", "https://www.domusweb.it/en.rss.xml", "Domus", 2),
    ("next_city", "https://nextcity.org/rss", "Next City", 2),
]


def fetch_with_browser_ua(url: str) -> bytes:
    """Fetch URL content with browser User-Agent."""
    headers = {
        'User-Agent': BROWSER_USER_AGENT,
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read()


def test_feed_standard(rss_url: str) -> dict:
    """Test feed with standard feedparser (no custom UA)."""
    result = {
        "success": False,
        "entries": 0,
        "error": None,
    }

    try:
        feed = feedparser.parse(rss_url)

        if feed.bozo and not feed.entries:
            result["error"] = str(feed.bozo_exception)[:100]
            return result

        if feed.entries:
            result["success"] = True
            result["entries"] = len(feed.entries)
        else:
            result["error"] = "No entries found"

    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def test_feed_with_ua(rss_url: str) -> dict:
    """Test feed with browser User-Agent."""
    result = {
        "success": False,
        "entries": 0,
        "error": None,
    }

    try:
        content = fetch_with_browser_ua(rss_url)
        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            result["error"] = str(feed.bozo_exception)[:100]
            return result

        if feed.entries:
            result["success"] = True
            result["entries"] = len(feed.entries)
        else:
            result["error"] = "No entries found"

    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result["error"] = f"URL Error: {str(e.reason)[:60]}"
    except Exception as e:
        result["error"] = str(e)[:100]

    return result


def test_single_feed(source_id: str, rss_url: str, name: str) -> dict:
    """Test a single RSS feed with both methods."""
    result = {
        "source_id": source_id,
        "name": name,
        "url": rss_url,
        "standard_ok": False,
        "browser_ua_ok": False,
        "entries": 0,
        "needs_ua": False,
        "broken": False,
        "error": None,
    }

    # Test 1: Standard feedparser
    standard_result = test_feed_standard(rss_url)
    result["standard_ok"] = standard_result["success"]

    if standard_result["success"]:
        result["entries"] = standard_result["entries"]
        return result

    # Test 2: With browser User-Agent (only if standard failed)
    ua_result = test_feed_with_ua(rss_url)
    result["browser_ua_ok"] = ua_result["success"]

    if ua_result["success"]:
        result["entries"] = ua_result["entries"]
        result["needs_ua"] = True  # Fixed by User-Agent!
    else:
        result["broken"] = True
        result["error"] = ua_result["error"] or standard_result["error"]

    return result


def main():
    """Test all RSS feeds."""
    print("=" * 75)
    print("RSS FEED TESTER (with User-Agent detection)")
    print(f"Testing {len(SOURCES_TO_TEST)} active + {len(CANDIDATE_SOURCES)} candidate feeds")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    results = []
    candidate_results = []

    # Categorize results
    working_standard = []
    working_with_ua = []
    broken = []

    # =========================================================================
    # Test ACTIVE sources (in sources.py)
    # =========================================================================
    print("\n" + "=" * 75)
    print("ACTIVE SOURCES (in sources.py)")
    print("=" * 75)

    print("\n--- TIER 1 (Primary Sources) ---")
    for source_id, rss_url, name, tier in SOURCES_TO_TEST:
        if tier != 1:
            continue

        print(f"  {name}...", end=" ", flush=True)
        result = test_single_feed(source_id, rss_url, name)
        result["tier"] = tier
        results.append(result)

        if result["standard_ok"]:
            working_standard.append(result)
            print(f"OK ({result['entries']} articles)")
        elif result["needs_ua"]:
            working_with_ua.append(result)
            print(f"OK with User-Agent ({result['entries']} articles)")
        else:
            broken.append(result)
            print(f"BROKEN: {result['error']}")

        time.sleep(0.5)

    print("\n--- TIER 2 (Regional/Specialty) ---")
    for source_id, rss_url, name, tier in SOURCES_TO_TEST:
        if tier != 2:
            continue

        print(f"  {name}...", end=" ", flush=True)
        result = test_single_feed(source_id, rss_url, name)
        result["tier"] = tier
        results.append(result)

        if result["standard_ok"]:
            working_standard.append(result)
            print(f"OK ({result['entries']} articles)")
        elif result["needs_ua"]:
            working_with_ua.append(result)
            print(f"OK with User-Agent ({result['entries']} articles)")
        else:
            broken.append(result)
            print(f"BROKEN: {result['error']}")

        time.sleep(0.5)

    # =========================================================================
    # Test CANDIDATE sources (removed, checking if they're back)
    # =========================================================================
    print("\n" + "=" * 75)
    print("CANDIDATE SOURCES (removed from config, checking status)")
    print("=" * 75)

    candidate_working = []
    candidate_broken = []

    for source_id, rss_url, name, tier in CANDIDATE_SOURCES:
        print(f"  {name}...", end=" ", flush=True)
        result = test_single_feed(source_id, rss_url, name)
        result["tier"] = tier
        candidate_results.append(result)

        if result["standard_ok"] or result["needs_ua"]:
            candidate_working.append(result)
            ua_note = " (needs UA)" if result["needs_ua"] else ""
            print(f"RECOVERED{ua_note} ({result['entries']} articles)")
        else:
            candidate_broken.append(result)
            print(f"Still broken: {result['error']}")

        time.sleep(0.5)

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 75)
    print("SUMMARY - ACTIVE SOURCES")
    print("=" * 75)
    print(f"Working (standard):     {len(working_standard)}")
    print(f"Working (needs UA):     {len(working_with_ua)}")
    print(f"Broken:                 {len(broken)}")
    print(f"Total working:          {len(working_standard) + len(working_with_ua)}/{len(SOURCES_TO_TEST)}")

    # Working feeds (standard)
    if working_standard:
        print("\n--- WORKING (Standard) ---")
        for r in working_standard:
            tier_label = "T1" if r["tier"] == 1 else "T2"
            print(f'  "{r["source_id"]}",  # {r["name"]} [{tier_label}] - {r["entries"]} articles')

    # Working feeds (need User-Agent)
    if working_with_ua:
        print("\n--- WORKING (Need User-Agent) ---")
        print("Add 'requires_user_agent': True to these sources in sources.py:")
        for r in working_with_ua:
            tier_label = "T1" if r["tier"] == 1 else "T2"
            print(f'  "{r["source_id"]}",  # {r["name"]} [{tier_label}] - {r["entries"]} articles')

    # Broken feeds
    if broken:
        print("\n--- BROKEN (Consider removing from sources.py) ---")
        for r in broken:
            tier_label = "T1" if r["tier"] == 1 else "T2"
            print(f'  {r["name"]} [{tier_label}]: {r["error"]}')

    # Candidate sources summary
    if candidate_working:
        print("\n" + "=" * 75)
        print("RECOVERED CANDIDATES (consider adding back to sources.py)")
        print("=" * 75)
        for r in candidate_working:
            ua_note = " [needs UA]" if r.get("needs_ua") else ""
            print(f'  "{r["source_id"]}",  # {r["name"]}{ua_note} - {r["entries"]} articles')

    if candidate_broken:
        print("\n--- STILL BROKEN CANDIDATES ---")
        for r in candidate_broken:
            print(f'  {r["name"]}: {r["error"]}')

    # Generate sources.py snippet for working feeds that need UA
    if working_with_ua:
        print("\n" + "=" * 75)
        print("SOURCES.PY UPDATE - Add requires_user_agent: True")
        print("=" * 75)
        for r in working_with_ua:
            print(f'''
    "{r["source_id"]}": {{
        "name": "{r["name"]}",
        "rss_url": "{r["url"]}",
        "requires_user_agent": True,  # Blocks bot User-Agent
        ...
    }},''')

    return results


if __name__ == "__main__":
    main()