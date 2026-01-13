# telegram_bot.py
"""
Telegram Bot Module
Handles all communication between backend and Telegram interface.

Usage:
    from telegram_bot import TelegramBot
    
    bot = TelegramBot()
    await bot.send_digest(articles)
"""

import os
import asyncio
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError


class TelegramBot:
    """Handles all Telegram bot operations."""
    
    def __init__(self, token: str = None, channel_id: str = None):
        """
        Initialize Telegram bot.
        
        Args:
            token: Bot token (defaults to TELEGRAM_BOT_TOKEN env var)
            channel_id: Channel ID (defaults to TELEGRAM_CHANNEL_ID env var)
        """
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.channel_id = channel_id or os.getenv("TELEGRAM_CHANNEL_ID")
        
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        if not self.channel_id:
            raise ValueError("TELEGRAM_CHANNEL_ID not set")
        
        self.bot = Bot(token=self.token)
    
    async def send_message(
        self, 
        text: str, 
        parse_mode: str = ParseMode.MARKDOWN,
        disable_preview: bool = False
    ) -> bool:
        """
        Send a single message to the channel.
        
        Args:
            text: Message text
            parse_mode: Telegram parse mode (Markdown/HTML)
            disable_preview: Disable link preview
            
        Returns:
            True if sent successfully
        """
        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview
            )
            return True
        except TelegramError as e:
            print(f"❌ Telegram error: {e}")
            return False
    
    async def send_digest(
        self, 
        articles: list[dict],
        source_name: str = "Architecture News"
    ) -> dict:
        """
        Send a news digest to the channel.
        
        Args:
            articles: List of article dicts with keys:
                - title: Article title
                - link: Article URL
                - ai_summary: AI-generated summary
                - tags: List of tags (optional)
            source_name: Name for the digest header
            
        Returns:
            Dict with sent/failed counts
        """
        results = {"sent": 0, "failed": 0}
        
        if not articles:
            print("📭 No articles to send")
            return results
        
        # Send header
        header = self._format_header(len(articles), source_name)
        if await self.send_message(header, disable_preview=True):
            results["sent"] += 1
        else:
            results["failed"] += 1
        
        # Send each article
        for i, article in enumerate(articles, 1):
            message = self._format_article(article, i)
            
            if await self.send_message(message, disable_preview=False):
                results["sent"] += 1
            else:
                results["failed"] += 1
            
            # Rate limiting: small delay between messages
            await asyncio.sleep(0.5)
        
        print(f"✅ Digest sent: {results['sent']} messages, {results['failed']} failed")
        return results
    
    async def send_single_article(self, article: dict) -> bool:
        """
        Send a single article notification.
        
        Args:
            article: Article dict with title, link, ai_summary
            
        Returns:
            True if sent successfully
        """
        message = self._format_article(article)
        return await self.send_message(message)
    
    async def send_error_notification(self, error_message: str) -> bool:
        """
        Send an error notification to the channel (for monitoring).
        
        Args:
            error_message: Error description
            
        Returns:
            True if sent successfully
        """
        text = f"⚠️ *System Alert*\n\n{error_message}"
        return await self.send_message(text, disable_preview=True)
    
    async def send_status_update(self, status: str) -> bool:
        """
        Send a status update (e.g., "Monitoring started").
        
        Args:
            status: Status message
            
        Returns:
            True if sent successfully
        """
        text = f"ℹ️ {status}"
        return await self.send_message(text, disable_preview=True)
    
    def _format_header(self, article_count: int, source_name: str) -> str:
        """Format digest header message."""
        today = datetime.now().strftime("%B %d, %Y")
        return (
            f"🏛️ *{source_name} Digest*\n"
            f"📅 {today}\n\n"
            f"_{article_count} new stories_"
        )
    
    def _format_article(self, article: dict, index: int = None) -> str:
        """Format single article message."""
        title = article.get("title", "Untitled")
        url = article.get("link", "")
        summary = article.get("ai_summary", "No summary available.")
        tags = article.get("tags", [])
        
        # Build message
        if index:
            header = f"*{index}. {title}*"
        else:
            header = f"*{title}*"
        
        message = f"{header}\n\n{summary}"
        
        # Add tags if present
        if tags:
            if isinstance(tags, list):
                tags_str = " ".join([f"#{tag.replace(' ', '_')}" for tag in tags])
            else:
                tags_str = tags
            message += f"\n\n{tags_str}"
        
        # Add link
        message += f"\n\n🔗 [Read more]({url})"
        
        return message
    
    async def test_connection(self) -> bool:
        """
        Test bot connection and permissions.
        
        Returns:
            True if bot can send to channel
        """
        try:
            bot_info = await self.bot.get_me()
            print(f"✅ Bot connected: @{bot_info.username}")
            
            # Try to get chat info
            chat = await self.bot.get_chat(self.channel_id)
            print(f"✅ Channel accessible: {chat.title}")
            
            return True
        except TelegramError as e:
            print(f"❌ Connection test failed: {e}")
            return False


# Convenience function for simple usage
async def send_to_telegram(articles: list[dict], source_name: str = "Architecture News"):
    """
    Quick function to send articles to Telegram.
    
    Args:
        articles: List of article dicts
        source_name: Digest header name
    """
    bot = TelegramBot()
    return await bot.send_digest(articles, source_name)


# CLI test
if __name__ == "__main__":
    async def test():
        print("🧪 Testing Telegram Bot...")
        try:
            bot = TelegramBot()
            if await bot.test_connection():
                print("✅ All tests passed!")
            else:
                print("❌ Connection test failed")
        except ValueError as e:
            print(f"❌ Configuration error: {e}")
    
    asyncio.run(test())
