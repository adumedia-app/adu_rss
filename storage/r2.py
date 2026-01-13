# storage/r2.py
"""
Cloudflare R2 Storage Module
Handles all interactions with Cloudflare R2 for storing scraped news data.

Folder Structure:
    bucket/
    └── 2026/
        └── January/
            └── Week-1/
                └── 2026-01-04/
                    ├── archdaily.json
                    └── dezeen.json

Usage:
    from storage import R2Storage
    
    r2 = R2Storage()
    r2.save_articles(articles, source="archdaily")
    articles = r2.get_articles("archdaily", date="2026-01-04")
"""

import os
import json
from datetime import datetime, date
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class R2Storage:
    """Handles Cloudflare R2 storage operations."""
    
    def __init__(
        self,
        account_id: str = None,
        access_key_id: str = None,
        secret_access_key: str = None,
        bucket_name: str = None
    ):
        """
        Initialize R2 storage client.
        
        Args:
            account_id: Cloudflare account ID (defaults to R2_ACCOUNT_ID env var)
            access_key_id: R2 access key (defaults to R2_ACCESS_KEY_ID env var)
            secret_access_key: R2 secret key (defaults to R2_SECRET_ACCESS_KEY env var)
            bucket_name: R2 bucket name (defaults to R2_BUCKET_NAME env var)
        """
        self.account_id = account_id or os.getenv("R2_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME")
        
        # Validate required credentials
        if not all([self.account_id, self.access_key_id, self.secret_access_key, self.bucket_name]):
            missing = []
            if not self.account_id: missing.append("R2_ACCOUNT_ID")
            if not self.access_key_id: missing.append("R2_ACCESS_KEY_ID")
            if not self.secret_access_key: missing.append("R2_SECRET_ACCESS_KEY")
            if not self.bucket_name: missing.append("R2_BUCKET_NAME")
            raise ValueError(f"Missing R2 credentials: {', '.join(missing)}")
        
        # Create S3 client configured for R2
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"}
            )
        )
    
    def _get_week_number(self, dt: date) -> int:
        """
        Get the week number within the month (1-5).
        
        Args:
            dt: Date to check
            
        Returns:
            Week number (1-5)
        """
        first_day = dt.replace(day=1)
        # Calculate which week of the month this date falls in
        day_of_month = dt.day
        first_weekday = first_day.weekday()  # 0=Monday, 6=Sunday
        
        # Adjust to start week on Monday
        adjusted_day = day_of_month + first_weekday
        week_number = (adjusted_day - 1) // 7 + 1
        
        return week_number
    
    def _build_path(self, source: str, target_date: date = None) -> str:
        """
        Build the storage path based on date.
        
        Format: YYYY/MonthName/Week-N/YYYY-MM-DD/source.json
        Example: 2026/January/Week-1/2026-01-04/archdaily.json
        
        Args:
            source: News source name (e.g., "archdaily", "dezeen")
            target_date: Date for the path (defaults to today)
            
        Returns:
            Full storage path
        """
        if target_date is None:
            target_date = date.today()
        
        year = target_date.year
        month_name = target_date.strftime("%B")  # Full month name
        week_num = self._get_week_number(target_date)
        date_str = target_date.strftime("%Y-%m-%d")
        
        return f"{year}/{month_name}/Week-{week_num}/{date_str}/{source}.json"
    
    def save_articles(
        self, 
        articles: list[dict], 
        source: str,
        target_date: date = None,
        metadata: dict = None
    ) -> str:
        """
        Save articles to R2 storage.
        
        Args:
            articles: List of article dictionaries
            source: News source name (e.g., "archdaily")
            target_date: Date for storage path (defaults to today)
            metadata: Optional metadata to include
            
        Returns:
            Storage path where file was saved
        """
        path = self._build_path(source, target_date)
        
        # Build the data structure
        data = {
            "source": source,
            "date": (target_date or date.today()).isoformat(),
            "fetched_at": datetime.now().isoformat(),
            "article_count": len(articles),
            "articles": articles
        }
        
        if metadata:
            data["metadata"] = metadata
        
        # Upload to R2
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=path,
            Body=json.dumps(data, indent=2, ensure_ascii=False),
            ContentType="application/json"
        )
        
        print(f"   📁 Saved {len(articles)} articles to: {path}")
        return path
    
    def get_articles(
        self, 
        source: str, 
        target_date: date = None
    ) -> Optional[dict]:
        """
        Retrieve articles from R2 storage.
        
        Args:
            source: News source name
            target_date: Date to retrieve (defaults to today)
            
        Returns:
            Dict with articles data, or None if not found
        """
        path = self._build_path(source, target_date)
        
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=path
            )
            content = response["Body"].read().decode("utf-8")
            return json.loads(content)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise
    
    def list_dates(
        self, 
        source: str = None,
        year: int = None, 
        month: str = None
    ) -> list[str]:
        """
        List available dates in storage.
        
        Args:
            source: Filter by source (optional)
            year: Filter by year (optional)
            month: Filter by month name (optional)
            
        Returns:
            List of available date paths
        """
        prefix = ""
        if year:
            prefix = f"{year}/"
            if month:
                prefix = f"{year}/{month}/"
        
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                Delimiter="/"
            )
            
            # Get all keys
            dates = []
            if "Contents" in response:
                for obj in response["Contents"]:
                    key = obj["Key"]
                    if source is None or key.endswith(f"/{source}.json"):
                        dates.append(key)
            
            return dates
        except ClientError as e:
            print(f"Error listing dates: {e}")
            return []
    
    def file_exists(self, source: str, target_date: date = None) -> bool:
        """
        Check if a file exists for the given source and date.
        
        Args:
            source: News source name
            target_date: Date to check (defaults to today)
            
        Returns:
            True if file exists
        """
        path = self._build_path(source, target_date)
        
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=path)
            return True
        except ClientError:
            return False
    
    def delete_file(self, source: str, target_date: date = None) -> bool:
        """
        Delete a file from storage.
        
        Args:
            source: News source name
            target_date: Date of file to delete
            
        Returns:
            True if deleted successfully
        """
        path = self._build_path(source, target_date)
        
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=path)
            print(f"   🗑️ Deleted: {path}")
            return True
        except ClientError as e:
            print(f"   ❌ Delete failed: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        Test R2 connection and bucket access.
        
        Returns:
            True if connection successful
        """
        try:
            # Try to list objects (even if empty)
            self.client.list_objects_v2(
                Bucket=self.bucket_name,
                MaxKeys=1
            )
            print(f"   ✅ R2 connected: bucket '{self.bucket_name}'")
            return True
        except ClientError as e:
            print(f"   ❌ R2 connection failed: {e}")
            return False


# CLI test
if __name__ == "__main__":
    print("🧪 Testing R2 Storage...")
    
    try:
        r2 = R2Storage()
        
        if r2.test_connection():
            # Test path building
            test_date = date(2026, 1, 4)
            path = r2._build_path("archdaily", test_date)
            print(f"   📁 Example path: {path}")
            
            print("✅ R2 Storage ready!")
        else:
            print("❌ R2 connection failed")
            
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
