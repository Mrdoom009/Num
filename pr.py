import os
import re
from threading import Thread
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from flask import Flask

# Configuration
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Client initialization
bot = Client("file_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# Flask health check
health_app = Flask(__name__)
@health_app.route('/')
def health_check(): return "OK", 200
Thread(target=lambda: health_app.run(port=8000, host="0.0.0.0"), daemon=True).start()

# Caption processing: remove specific suffix and all dots
def clean_caption(text: str) -> str:
    if not text:
        return text
    
    # Step 1: Remove the exact suffix string if present
    suffix = "1080p.JIOHS.WEB-DL.Hindi.AAC.2.0.H264-Movies4u.Foo.mkv"
    if suffix in text:
        text = text.replace(suffix, "")
    
    # Step 2: Remove all dots (.) from the remaining text
    text = text.replace(".", "")
    
    # Trim extra whitespace
    return text.strip()

# Handlers
@bot.on_message(filters.media)
async def handle_media(client, message: Message):
    if message.video:
        # Get original caption or empty string
        original_caption = message.caption or ""
        new_caption = clean_caption(original_caption)
        
        try:
            await message.edit_caption(new_caption, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            print(f"Caption edit failed: {e}")
            await message.reply_video(message.video.file_id, caption=new_caption, parse_mode=enums.ParseMode.HTML)
    
    elif message.document and message.document.mime_type == "application/pdf":
        # For PDFs, remove caption entirely (keep old behavior)
        try: 
            await message.edit_caption('')
        except: 
            pass

# Command handlers
@bot.on_message(filters.command("start"))
async def start_cmd(_, message):
    await message.reply(
        "📄 <b>Caption Cleaner Bot</b>\n\n"
        "Send any video – the bot will:\n"
        "• Remove the exact suffix:\n"
        "  <code>1080p.JIOHS.WEB-DL.Hindi.AAC.2.0.H264-Movies4u.Foo.mkv</code>\n"
        "• Remove all dots (.) from the remaining caption\n\n"
        "For PDF files, the caption is completely removed.\n\n"
        "All previous formatting and numbering logic has been removed.",
        parse_mode=enums.ParseMode.HTML
    )

bot.run()
