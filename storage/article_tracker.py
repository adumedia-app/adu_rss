# storage/article_tracker.py
"""
Article Tracker - PostgreSQL Database for Custom Scrapers

Tracks seen article URLs and headlines to prevent reprocessing.
Supports visual scraping workflow where headlines are extracted via AI.

Database Schema:
    - articles table: stores seen URLs and headlines per source
    - Indexed by source_id and url for fast lookups

Usage:
    tracker = ArticleTracker()
    await tracker.connect()

    # Visual scraping workflow
    await tracker.store_headlines(source_id, headlines_list)
    stored_headlines = await tracker.get_stored_headlines(source_id)

    # URL tracking workflow  
    new_urls = await tracker.filter_new_articles(source_id, url_list)
    await tracker.mark_as_seen(source_id, url_list)
"""

import os
import asyncpg
from typing import Optional, List
from datetime import datetime


class ArticleTracker:
    """PostgreSQL-based article tracking for custom scrapers."""

    # ========================================
    # TEST MODE - Set to True to ignore "seen" status
    # This makes all articles appear as "new" for testing
    # REMOVE OR SET TO FALSE FOR PRODUCTION
    # ========================================
    TEST_MODE = os.getenv("SCRAPER_TEST_MODE", "").lower() == "true"

    def __init__(self, connection_url: Optional[str] = None):
        """
        Initialize article tracker.

        Args:
            connection_url: PostgreSQL connection URL (defaults to DATABASE_URL env var)
        """
        self.connection_url = connection_url or os.getenv("DATABASE_URL")

        if not self.connection_url:
            raise ValueError("DATABASE_URL environment variable not set")

        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Connect to PostgreSQL and initialize schema."""
        if self.pool:
            return

        # Create connection pool
        self.pool = await asyncpg.create_pool(
            self.connection_url,
            min_size=1,
            max_size=5,
            command_timeout=60
        )

        # Initialize schema
        await self._init_schema()

        print("✅ Article tracker connected to PostgreSQL")

    async def _init_schema(self):
        """Create articles table if it doesn't exist."""
        if not self.pool:
            raise RuntimeError("Not connected to database")

        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(100) NOT NULL,
                    url TEXT NOT NULL,
                    headline TEXT,
                    first_seen TIMESTAMP DEFAULT NOW(),
                    last_checked TIMESTAMP DEFAULT NOW(),
                    UNIQUE(source_id, url)
                )
            """)

            # Create index for fast lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_source_url 
                ON articles(source_id, url)
            """)

            # Create index for headline searches
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_source_headline 
                ON articles(source_id, headline)
            """)

        print("✅ Article tracker schema initialized")

    # =========================================================================
    # Visual Scraping - Headline Storage
    # =========================================================================

    async def store_headlines(self, source_id: str, headlines: List[str]) -> int:
        """
        Store headlines from first visual analysis run.

        This is used on first run to mark all visible headlines as "seen"
        so subsequent runs only process new headlines.

        Args:
            source_id: Source identifier
            headlines: List of headline strings

        Returns:
            Number of headlines stored
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        stored = 0

        async with self.pool.acquire() as conn:
            for headline in headlines:
                if not headline or not headline.strip():
                    continue

                try:
                    # Use headline as URL placeholder for now
                    # Will be updated when we find the actual URL
                    await conn.execute("""
                        INSERT INTO articles (source_id, url, headline)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (source_id, url) DO NOTHING
                    """, source_id, f"headline:{headline}", headline.strip())

                    stored += 1

                except Exception as e:
                    print(f"   ⚠️ Error storing headline: {e}")
                    continue

        print(f"[{source_id}] Stored {stored} headlines in database")
        return stored


    async def get_stored_headlines(self, source_id: str) -> List[str]:
        """
        Get all stored headlines for a source.
        ...
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        # ========================================
        # TEST MODE BYPASS - Remove for production
        # ========================================
        if self.TEST_MODE:
            print("   ⚠️ TEST MODE: Returning empty list (pretending no headlines seen)")
            return []

        async with self.pool.acquire() as conn:

            rows = await conn.fetch("""
                SELECT headline FROM articles
                WHERE source_id = $1 AND headline IS NOT NULL
                ORDER BY first_seen DESC
            """, source_id)

            return [row['headline'] for row in rows if row['headline']]

    async def find_new_headlines(self, source_id: str, current_headlines: List[str]) -> List[str]:
        """
        Find headlines that haven't been seen before.

        Uses fuzzy matching to handle slight variations in headline text.

        Args:
            source_id: Source identifier
            current_headlines: List of headlines currently on the page

        Returns:
            List of headlines not in database
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        stored_headlines = await self.get_stored_headlines(source_id)

        # Simple exact match for now
        # TODO: Could add fuzzy matching later if needed
        stored_set = set(h.strip().lower() for h in stored_headlines)

        new_headlines = [
            h for h in current_headlines
            if h.strip().lower() not in stored_set
        ]

        return new_headlines

    async def update_headline_url(self, source_id: str, headline: str, url: str) -> bool:
        """
        Update a headline entry with its actual URL.

        Called after finding the link for a headline in HTML.

        Args:
            source_id: Source identifier
            headline: Article headline
            url: Actual article URL

        Returns:
            True if updated successfully
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        async with self.pool.acquire() as conn:
            try:
                # Check if URL already exists
                existing = await conn.fetchval("""
                    SELECT id FROM articles
                    WHERE source_id = $1 AND url = $2
                """, source_id, url)

                if existing:
                    # URL already tracked, just update last_checked
                    await conn.execute("""
                        UPDATE articles
                        SET last_checked = NOW()
                        WHERE source_id = $1 AND url = $2
                    """, source_id, url)
                    return True

                # Update the placeholder entry
                result = await conn.execute("""
                    UPDATE articles
                    SET url = $1, last_checked = NOW()
                    WHERE source_id = $2 AND headline = $3 AND url LIKE 'headline:%'
                """, url, source_id, headline)

                # If no placeholder found, insert new entry
                if result == "UPDATE 0":
                    await conn.execute("""
                        INSERT INTO articles (source_id, url, headline)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (source_id, url) DO UPDATE
                        SET headline = EXCLUDED.headline, last_checked = NOW()
                    """, source_id, url, headline)

                return True

            except Exception as e:
                print(f"   ⚠️ Error updating headline URL: {e}")
                return False

    # =========================================================================
    # URL Tracking (Traditional Method)
    # =========================================================================

    async def filter_new_articles(self, source_id: str, urls: List[str]) -> List[str]:
        """
        Filter list of URLs to only those not seen before.
        ...
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        if not urls:
            return []

        # ========================================
        # TEST MODE BYPASS - Remove for production
        # ========================================
        if self.TEST_MODE:
            print(f"   ⚠️ TEST MODE: Returning ALL {len(urls)} URLs as 'new' (ignoring database)")
            return urls


        async with self.pool.acquire() as conn:
            # Get all existing URLs for this source
            rows = await conn.fetch("""
                SELECT url FROM articles
                WHERE source_id = $1 AND url = ANY($2)
            """, source_id, urls)

            seen_urls = set(row['url'] for row in rows)

            # Return URLs not in database
            new_urls = [url for url in urls if url not in seen_urls]

            return new_urls

    async def mark_as_seen(self, source_id: str, urls: List[str]) -> int:
        """
        Mark URLs as seen in the database.

        Args:
            source_id: Source identifier
            urls: List of article URLs

        Returns:
            Number of URLs marked as seen
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        if not urls:
            return 0

        marked = 0

        async with self.pool.acquire() as conn:
            for url in urls:
                try:
                    await conn.execute("""
                        INSERT INTO articles (source_id, url)
                        VALUES ($1, $2)
                        ON CONFLICT (source_id, url) DO UPDATE
                        SET last_checked = NOW()
                    """, source_id, url)

                    marked += 1

                except Exception as e:
                    print(f"   ⚠️ Error marking URL as seen: {e}")
                    continue

        return marked

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self, source_id: Optional[str] = None) -> dict:
        """
        Get statistics about tracked articles.

        Args:
            source_id: Optional source to filter by

        Returns:
            Dict with statistics
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        async with self.pool.acquire() as conn:
            if source_id:
                count = await conn.fetchval("""
                    SELECT COUNT(*) FROM articles WHERE source_id = $1
                """, source_id)

                oldest = await conn.fetchval("""
                    SELECT first_seen FROM articles
                    WHERE source_id = $1
                    ORDER BY first_seen ASC LIMIT 1
                """, source_id)

                newest = await conn.fetchval("""
                    SELECT first_seen FROM articles
                    WHERE source_id = $1
                    ORDER BY first_seen DESC LIMIT 1
                """, source_id)
            else:
                count = await conn.fetchval("SELECT COUNT(*) FROM articles")
                oldest = await conn.fetchval("""
                    SELECT first_seen FROM articles
                    ORDER BY first_seen ASC LIMIT 1
                """)
                newest = await conn.fetchval("""
                    SELECT first_seen FROM articles
                    ORDER BY first_seen DESC LIMIT 1
                """)

            return {
                "total_articles": count or 0,
                "oldest_seen": oldest.isoformat() if oldest else None,
                "newest_seen": newest.isoformat() if newest else None,
            }

    async def clear_source(self, source_id: str) -> int:
        """
        Clear all tracked articles for a source.

        Args:
            source_id: Source identifier

        Returns:
            Number of articles deleted
        """
        if not self.pool:
            raise RuntimeError("Not connected to database")

        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM articles WHERE source_id = $1
            """, source_id)

            # Extract count from result
            deleted = int(result.split()[-1])
            print(f"[{source_id}] Cleared {deleted} tracked articles")
            return deleted

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            print("✅ Article tracker disconnected")