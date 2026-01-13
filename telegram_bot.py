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
import re
import asyncio
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

# Import source registry
from config.sources import get_source_name


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

    @staticmethod
    def _escape_markdown(text: str) -> str:
        """
        Escape special Markdown characters for Telegram.

        Telegram's legacy Markdown mode uses these special characters:
        - _ for italic
        - * for bold
        - ` for code
        - [ for links

        Args:
            text: Raw text to escape

        Returns:
            Text with escaped Markdown characters
        """
        if not text:
            return ""

        # Characters that need escaping in Telegram Markdown
        # Order matters: escape backslash first to avoid double-escaping
        escape_chars = ['_', '*', '[', ']', '`']

        result = text
        for char in escape_chars:
            result = result.replace(char, f'\\{char}')

        return result

    @staticmethod
    def _escape_url(url: str) -> str:
        """
        Escape special characters in URLs for Markdown links.

        Parentheses in URLs break Markdown link syntax.

        Args:
            url: URL to escape

        Returns:
            URL with escaped parentheses
        """
        if not url:
            return ""

        # Escape parentheses which break Markdown link syntax
        return url.replace('(', '%28').replace(')', '%29')

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
            print(f"[ERROR] Telegram error: {e}")
            # Try sending without parse mode as fallback
            try:
                await self.bot.send_message(
                    chat_id=self.channel_id,
                    text=text,
                    parse_mode=None,
                    disable_web_page_preview=disable_preview
                )
                print("[INFO] Sent without formatting as fallback")
                return True
            except TelegramError as e2:
                print(f"[ERROR] Fallback also failed: {e2}")
                return False

    async def send_photo(
        self,
        photo_url: str,
        caption: str = None,
        parse_mode: str = ParseMode.MARKDOWN
    ) -> bool:
        """
        Send a photo with optional caption to the channel.

        Args:
            photo_url: URL of the image to send
            caption: Optional caption text
            parse_mode: Telegram parse mode

        Returns:
            True if sent successfully
        """
        try:
            await self.bot.send_photo(
                chat_id=self.channel_id,
                photo=photo_url,
                caption=caption,
                parse_mode=parse_mode
            )
            return True
        except TelegramError as e:
            print(f"[ERROR] Telegram photo error: {e}")
            # Try sending without parse mode as fallback
            try:
                await self.bot.send_photo(
                    chat_id=self.channel_id,
                    photo=photo_url,
                    caption=caption,
                    parse_mode=None
                )
                print("[INFO] Sent photo without formatting as fallback")
                return True
            except TelegramError as e2:
                print(f"[ERROR] Photo fallback also failed: {e2}")
                return False

    async def send_digest(
        self, 
        articles: list[dict],
        include_header: bool = True
    ) -> dict:
        """
        Send a news digest to the channel.

        Args:
            articles: List of article dicts with keys:
                - link: Article URL
                - ai_summary: AI-generated summary
                - tags: List of tags (optional)
                - hero_image: Dict with 'url' or 'r2_url' (optional)
            include_header: Whether to send daily header message

        Returns:
            Dict with sent/failed counts
        """
        results = {"sent": 0, "failed": 0}

        if not articles:
            print("[INFO] No articles to send")
            return results

        # Send header (optional)
        if include_header:
            header = self._format_header(len(articles))
            if await self.send_message(header, disable_preview=True):
                results["sent"] += 1
            else:
                results["failed"] += 1

        # Send each article
        for article in articles:
            success = await self._send_article(article)

            if success:
                results["sent"] += 1
            else:
                results["failed"] += 1

            # Rate limiting: small delay between messages
            await asyncio.sleep(0.5)

        print(f"[OK] Digest sent: {results['sent']} messages, {results['failed']} failed")
        return results

    async def _send_article(self, article: dict) -> bool:
        """
        Send a single article - with image if available.

        Args:
            article: Article dict

        Returns:
            True if sent successfully
        """
        # Get hero image URL (prefer R2, fallback to original)
        hero_image = article.get("hero_image")
        image_url = None

        if hero_image:
            image_url = hero_image.get("r2_url") or hero_image.get("url")

        # Format the caption/message
        caption = self._format_article(article)

        # Send with image if available
        if image_url:
            success = await self.send_photo(image_url, caption)
            if success:
                return True
            # Fallback to text-only if image fails
            print("[WARN] Image failed, sending text only")

        # Send as text message
        return await self.send_message(caption, disable_preview=False)

    async def send_single_article(self, article: dict) -> bool:
        """
        Send a single article notification.

        Args:
            article: Article dict with link, ai_summary, tags

        Returns:
            True if sent successfully
        """
        return await self._send_article(article)

    async def send_error_notification(self, error_message: str) -> bool:
        """
        Send an error notification to the channel (for monitoring).

        Args:
            error_message: Error description

        Returns:
            True if sent successfully
        """
        # Escape the error message to prevent Markdown issues
        escaped_message = self._escape_markdown(error_message)
        text = f"*System Alert*\n\n{escaped_message}"
        return await self.send_message(text, disable_preview=True)

    async def send_status_update(self, status: str) -> bool:
        """
        Send a status update (e.g., "Monitoring started").

        Args:
            status: Status message

        Returns:
            True if sent successfully
        """
        # Escape status message
        escaped_status = self._escape_markdown(status)
        return await self.send_message(escaped_status, disable_preview=True)

    def _format_header(self, article_count: int) -> str:
        """Format digest header message."""
        today = datetime.now().strftime("%d %B %Y")
        return (
            f"{today}\n"
            f"Our editorial selection for today."
        )

    def _format_article(self, article: dict) -> str:
        """
        Format single article message with proper Markdown escaping.

        Format:
            Summary text here.

            #tag1 #tag2

            SourceName (linked)
        """
        url = article.get("link", "")
        summary = article.get("ai_summary", "No summary available.")
        tags = article.get("tags", [])

        # Get source display name
        source_name = get_source_name(url)

        # Escape special Markdown characters in summary
        escaped_summary = self._escape_markdown(summary)

        # Build message - start with escaped summary
        message = escaped_summary

        # Add tags if present
        if tags:
            if isinstance(tags, list):
                # Clean tags: lowercase, replace spaces with underscores
                # Tags with # don't need escaping as # is not a Markdown char
                cleaned_tags = []
                for tag in tags:
                    if tag:
                        # Remove any special characters from tags
                        clean_tag = tag.strip().lower()
                        # Replace spaces with underscores
                        clean_tag = clean_tag.replace(" ", "_")
                        # Remove any remaining Markdown special chars from tag
                        clean_tag = re.sub(r'[_*\[\]`]', '', clean_tag)
                        if clean_tag:
                            cleaned_tags.append(f"#{clean_tag}")
                tags_str = " ".join(cleaned_tags)
            else:
                tags_str = str(tags)

            if tags_str:
                message += f"\n\n{tags_str}"

        # Add source link with escaped source name and URL
        if url:
            escaped_source = self._escape_markdown(source_name)
            escaped_url = self._escape_url(url)
            message += f"\n\n[{escaped_source}]({escaped_url})"

        return message

    async def test_connection(self) -> bool:
        """
        Test bot connection and permissions.

        Returns:
            True if bot can send to channel
        """
        try:
            bot_info = await self.bot.get_me()
            print(f"[OK] Bot connected: @{bot_info.username}")

            # Try to get chat info
            chat = await self.bot.get_chat(self.channel_id)
            print(f"[OK] Channel accessible: {chat.title}")

            return True
        except TelegramError as e:
            print(f"[ERROR] Connection test failed: {e}")
            return False


# Convenience function for simple usage
async def send_to_telegram(articles: list[dict], include_header: bool = True):
    """
    Quick function to send articles to Telegram.

    Args:
        articles: List of article dicts
        include_header: Whether to include daily header
    """
    bot = TelegramBot()
    return await bot.send_digest(articles, include_header)


# CLI test
if __name__ == "__main__":
    async def test():
        print("Testing Telegram Bot...")
        try:
            bot = TelegramBot()
            if await bot.test_connection():
                print("[OK] All tests passed!")
            else:
                print("[ERROR] Connection test failed")
        except ValueError as e:
            print(f"[ERROR] Configuration error: {e}")

    asyncio.run(test())