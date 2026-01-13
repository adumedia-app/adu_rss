# test_dezeen_rss.py
"""
Test script for Dezeen RSS feed.
Run this on Railway to see the feed structure.

Usage:
    python test_dezeen_rss.py
"""

import feedparser
import json
from datetime import datetime, timezone, timedelta


def test_dezeen_feed():
    """Test Dezeen RSS feed and display structure."""
    
    # Feedburner URL for Dezeen (dezeen.com/feed returns 403)
    url = "http://feeds.feedburner.com/dezeen"
    
    print("=" * 60)
    print("Dezeen RSS Feed Test")
    print("=" * 60)
    print(f"\nFetching: {url}\n")
    
    feed = feedparser.parse(url)
    
    # Check for errors
    if feed.bozo:
        print(f"[WARN] Feed warning: {feed.bozo_exception}")
    
    # Feed metadata
    print("--- Feed Metadata ---")
    print(f"Title: {feed.feed.get('title', 'N/A')}")
    print(f"Link: {feed.feed.get('link', 'N/A')}")
    print(f"Description: {feed.feed.get('description', 'N/A')[:100]}...")
    print(f"Total entries: {len(feed.entries)}")
    
    if not feed.entries:
        print("\n[ERROR] No entries found!")
        return
    
    # Analyze first entry in detail
    print("\n--- First Entry Structure ---")
    entry = feed.entries[0]
    
    print("\nAll available fields:")
    for key in sorted(entry.keys()):
        value = entry.get(key)
        if isinstance(value, str) and len(value) > 80:
            value = value[:80] + "..."
        elif isinstance(value, list):
            value = f"[list: {len(value)} items]"
        elif hasattr(value, '__len__') and not isinstance(value, str):
            value = f"[{type(value).__name__}: {len(value)} items]"
        print(f"  {key}: {value}")
    
    # Publication date analysis
    print("\n--- Publication Date Analysis ---")
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        print(f"published_parsed: {pub_date.isoformat()}")
    if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        upd_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        print(f"updated_parsed: {upd_date.isoformat()}")
    if entry.get('published'):
        print(f"published (raw): {entry.get('published')}")
    if entry.get('updated'):
        print(f"updated (raw): {entry.get('updated')}")
    
    # Media/Image analysis
    print("\n--- Media/Image Analysis ---")
    if 'media_content' in entry:
        print(f"media_content found: {len(entry.media_content)} items")
        for i, mc in enumerate(entry.media_content[:2]):
            print(f"  [{i}] {mc}")
    if 'media_thumbnail' in entry:
        print(f"media_thumbnail: {entry.media_thumbnail}")
    if 'enclosures' in entry:
        print(f"enclosures: {entry.enclosures}")
    if 'links' in entry:
        img_links = [l for l in entry.links if l.get('type', '').startswith('image')]
        print(f"image links: {len(img_links)}")
        for link in img_links[:2]:
            print(f"  {link}")
    
    # Summary/content analysis
    print("\n--- Content Analysis ---")
    if entry.get('summary'):
        print(f"summary length: {len(entry.get('summary'))} chars")
        print(f"summary preview: {entry.get('summary')[:200]}...")
    if entry.get('content'):
        print(f"content: {len(entry.content)} items")
    
    # Show last 24 hours entries
    print("\n--- Articles from last 24 hours ---")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = 0
    
    for i, e in enumerate(feed.entries[:20]):
        pub_date = None
        if hasattr(e, 'published_parsed') and e.published_parsed:
            pub_date = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
        elif hasattr(e, 'updated_parsed') and e.updated_parsed:
            pub_date = datetime(*e.updated_parsed[:6], tzinfo=timezone.utc)
        
        if pub_date and pub_date >= cutoff:
            recent_count += 1
            print(f"\n{recent_count}. {e.get('title', 'No title')}")
            print(f"   Link: {e.get('link', 'N/A')}")
            print(f"   Published: {pub_date.isoformat()}")
            print(f"   GUID: {e.get('id', e.get('link', 'N/A'))}")
    
    print(f"\n[INFO] Found {recent_count} articles from last 24 hours")
    
    # JSON structure comparison with ArchDaily
    print("\n--- JSON Structure for First Article ---")
    print("(Compare with ArchDaily structure)")
    
    article = {
        "title": entry.get("title", "No title"),
        "link": entry.get("link", ""),
        "description": entry.get("summary", ""),
        "published": None,
        "guid": entry.get("id", entry.get("link", "")),
    }
    
    # Parse date
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        article["published"] = pub_date.isoformat()
    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        article["published"] = pub_date.isoformat()
    
    print(json.dumps(article, indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    test_dezeen_feed()
