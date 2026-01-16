# storage/article_tracker.py
"""
Article Tracker - PostgreSQL-based tracking for custom scrapers
Tracks which articles have been seen to detect new content.

Database Schema:
    seen_articles:
        - id (serial primary key)
        - source_id (varchar) - e.g., 'landezine'
        - article_url (varchar, unique) - full article URL
        - article_guid (varchar) - URL or hash
        - first_seen (timestamp) - when first discovered
        - last_checked (timestamp) - last verification

Usage:
    from storage.article_tracker import ArticleTracker

    tracker = ArticleTracker()
    await tracker.connect()

    # Check if article is new
    is_new = await tracker.is_new_article("landezine", "https://landezine.com/article-123")

    # Mark articles as seen
    await tracker.mark_as_seen("landezine", ["url1", "url2", "url3"])

    # Get new articles from a list
    new_urls = await tracker.filter_new_articles("landezine", all_urls)
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Optional, List
import asyncpg
from urllib.parse import urlparse


class ArticleTracker:
    """
    Tracks seen articles for custom scrapers using PostgreSQL.

    Prevents re-processing articles when publication dates aren't available
    on listing pages.
    """

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize article tracker.

        Args:
            database_url: PostgreSQL connection URL (defaults to DATABASE_URL env var)
        """
        self.database_url = database_url or os.getenv("DATABASE_URL")

        if not self.database_url:
            raise ValueError("DATABASE_URL not set in environment")

        self.pool: Optional[asyncpg.Pool] = None
        self._initialized = False

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def connect(self):
        """Create connection pool and initialize database."""
        if self.pool:
            return

        try:
            # Create connection pool
            self.pool = await asyncpg.create_pool(
                self.database_url,
                min_size=1,
                max_size=10,
                command_timeout=60
            )

            print("✅ Article tracker connected to PostgreSQL")

            # Initialize schema
            await self._initialize_schema()

        except Exception as e:
            print(f"❌ Failed to connect to database: {e}")
            raise

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self.pool = None
            print("✅ Article tracker disconnected")

    async def _initialize_schema(self):
        """Create tables if they don't exist."""
        if self._initialized or not self.pool:
            return

        async with self.pool.acquire() as conn:
            # Create seen_articles table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_articles (
                    id SERIAL PRIMARY KEY,
                    source_id VARCHAR(100) NOT NULL,
                    article_url VARCHAR(1000) NOT NULL,
                    article_guid VARCHAR(1000) NOT NULL,
                    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    last_checked TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(source_id, article_url)
                )
            """)

            # Create index for faster lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_url 
                ON seen_articles(source_id, article_url)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_seen 
                ON seen_articles(source_id, first_seen DESC)
            """)

            print("✅ Article tracker schema initialized")
            self._initialized = True

    # =========================================================================
    # Article Tracking
    # =========================================================================

    async def is_new_article(self, source_id: str, url: str) -> bool:
        """
        Check if an article URL is new (not seen before).

        Args:
            source_id: Source identifier (e.g., 'landezine')
            url: Article URL

        Returns:
            True if article is new, False if already seen
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT COUNT(*) FROM seen_articles 
                WHERE source_id = $1 AND article_url = $2
                """,
                source_id, url
            )

            return result == 0

    async def mark_as_seen(
        self, 
        source_id: str, 
        urls: List[str],
        guids: Optional[List[str]] = None
    ) -> int:
        """
        Mark articles as seen.

        Args:
            source_id: Source identifier
            urls: List of article URLs
            guids: Optional list of GUIDs (defaults to URLs)

        Returns:
            Number of new articles added
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        if not urls:
            return 0

        # Use URLs as GUIDs if not provided
        if guids is None:
            guids = urls

        if len(urls) != len(guids):
            raise ValueError("urls and guids must have same length")

        now = datetime.now(timezone.utc)
        added = 0

        async with self.pool.acquire() as conn:
            for url, guid in zip(urls, guids):
                try:
                    # Insert or update
                    result = await conn.execute(
                        """
                        INSERT INTO seen_articles 
                            (source_id, article_url, article_guid, first_seen, last_checked)
                        VALUES ($1, $2, $3, $4, $4)
                        ON CONFLICT (source_id, article_url) 
                        DO UPDATE SET last_checked = $4
                        """,
                        source_id, url, guid, now
                    )

                    # Check if this was an insert (not update)
                    if result == "INSERT 0 1":
                        added += 1

                except Exception as e:
                    print(f"⚠️ Error marking {url} as seen: {e}")

        if added > 0:
            print(f"📝 Marked {added} new articles as seen for {source_id}")

        return added

    async def filter_new_articles(
        self, 
        source_id: str, 
        urls: List[str]
    ) -> List[str]:
        """
        Filter a list of URLs to only new (unseen) articles.

        Args:
            source_id: Source identifier
            urls: List of article URLs to check

        Returns:
            List of URLs that haven't been seen before
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        if not urls:
            return []

        async with self.pool.acquire() as conn:
            # Get all seen URLs for this source
            seen_urls = await conn.fetch(
                """
                SELECT article_url FROM seen_articles 
                WHERE source_id = $1 AND article_url = ANY($2)
                """,
                source_id, urls
            )

            seen_set = {row['article_url'] for row in seen_urls}

            # Return only URLs not in seen set
            new_urls = [url for url in urls if url not in seen_set]

            if new_urls:
                print(f"🆕 Found {len(new_urls)} new articles (out of {len(urls)} total)")

            return new_urls

    # =========================================================================
    # Statistics & Maintenance
    # =========================================================================

    async def get_stats(self, source_id: Optional[str] = None) -> dict:
        """
        Get tracking statistics.

        Args:
            source_id: Optional source to filter by

        Returns:
            Dict with stats (total_articles, sources, oldest, newest)
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        async with self.pool.acquire() as conn:
            if source_id:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM seen_articles WHERE source_id = $1",
                    source_id
                )
                oldest = await conn.fetchval(
                    "SELECT MIN(first_seen) FROM seen_articles WHERE source_id = $1",
                    source_id
                )
                newest = await conn.fetchval(
                    "SELECT MAX(first_seen) FROM seen_articles WHERE source_id = $1",
                    source_id
                )
                sources = [source_id]
            else:
                total = await conn.fetchval("SELECT COUNT(*) FROM seen_articles")
                oldest = await conn.fetchval("SELECT MIN(first_seen) FROM seen_articles")
                newest = await conn.fetchval("SELECT MAX(first_seen) FROM seen_articles")

                # Get all sources
                source_rows = await conn.fetch(
                    "SELECT DISTINCT source_id FROM seen_articles"
                )
                sources = [row['source_id'] for row in source_rows]

        return {
            "total_articles": total,
            "sources": sources,
            "oldest_seen": oldest.isoformat() if oldest else None,
            "newest_seen": newest.isoformat() if newest else None,
        }

    async def cleanup_old_articles(
        self, 
        source_id: str, 
        days: int = 90
    ) -> int:
        """
        Remove old article records to prevent database bloat.

        Args:
            source_id: Source identifier
            days: Keep articles seen in last N days

        Returns:
            Number of records deleted
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM seen_articles 
                WHERE source_id = $1 
                AND first_seen < NOW() - INTERVAL '%s days'
                """,
                source_id, days
            )

            # Parse result like "DELETE 42"
            deleted = int(result.split()[-1]) if result else 0

            if deleted > 0:
                print(f"🗑️ Cleaned up {deleted} old articles for {source_id}")

            return deleted

    async def get_recent_articles(
        self, 
        source_id: str, 
        limit: int = 20
    ) -> List[dict]:
        """
        Get recently seen articles for a source.

        Args:
            source_id: Source identifier
            limit: Maximum number to return

        Returns:
            List of article dicts with url, guid, first_seen
        """
        if not self.pool:
            await self.connect()

        if not self.pool:
            raise RuntimeError("Failed to connect to database")

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT article_url, article_guid, first_seen, last_checked
                FROM seen_articles 
                WHERE source_id = $1 
                ORDER BY first_seen DESC 
                LIMIT $2
                """,
                source_id, limit
            )

            return [
                {
                    "url": row['article_url'],
                    "guid": row['article_guid'],
                    "first_seen": row['first_seen'].isoformat(),
                    "last_checked": row['last_checked'].isoformat(),
                }
                for row in rows
            ]


# =============================================================================
# Convenience Functions
# =============================================================================

async def test_tracker():
    """Test the article tracker."""
    print("=" * 60)
    print("Testing Article Tracker")
    print("=" * 60)

    tracker = ArticleTracker()

    try:
        await tracker.connect()

        # Test data
        test_source = "test_source"
        test_urls = [
            "https://example.com/article-1",
            "https://example.com/article-2",
            "https://example.com/article-3",
        ]

        # Mark articles as seen
        print("\n1. Marking test articles as seen...")
        added = await tracker.mark_as_seen(test_source, test_urls)
        print(f"   Added {added} new articles")

        # Check if articles are new
        print("\n2. Checking if articles are new...")
        for url in test_urls:
            is_new = await tracker.is_new_article(test_source, url)
            print(f"   {url}: {'NEW' if is_new else 'SEEN'}")

        # Filter new articles
        print("\n3. Filtering new articles...")
        all_urls = test_urls + ["https://example.com/article-4"]
        new_urls = await tracker.filter_new_articles(test_source, all_urls)
        print(f"   New URLs: {new_urls}")

        # Get stats
        print("\n4. Getting stats...")
        stats = await tracker.get_stats(test_source)
        print(f"   Total articles: {stats['total_articles']}")
        print(f"   Sources: {stats['sources']}")

        # Get recent articles
        print("\n5. Getting recent articles...")
        recent = await tracker.get_recent_articles(test_source, limit=5)
        for article in recent:
            print(f"   - {article['url']} (seen: {article['first_seen']})")

        print("\n" + "=" * 60)
        print("✅ Test complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await tracker.close()


if __name__ == "__main__":
    asyncio.run(test_tracker())