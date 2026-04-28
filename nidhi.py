import os
import re
import asyncio
from threading import Thread
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from flask import Flask

# Configuration
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

bot = Client("file_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# Flask health check
health_app = Flask(__name__)
@health_app.route('/')
def health_check(): return "OK", 200
Thread(target=lambda: health_app.run(port=8000, host="0.0.0.0"), daemon=True).start()

# Numbering persistence
NUMBERING_FILE = "numbering_state.txt"
current_number = 1
number_lock = asyncio.Lock()

def load_number():
    try:
        with open(NUMBERING_FILE, "r") as f:
            return int(f.read().strip()) if os.path.exists(NUMBERING_FILE) else 1
    except: return 1

def save_number(num):
    with open(NUMBERING_FILE, "w") as f:
        f.write(str(num))

current_number = load_number()

# Font conversion for numbering
def to_math_sans_plain(text: str) -> str:
    converted = []
    for char in text:
        if 'A' <= char <= 'Z':
            converted.append(chr(ord(char) + 0x1D5A0 - ord('A')))
        elif 'a' <= char <= 'z':
            converted.append(chr(ord(char) + 0x1D5BA - ord('a')))
        elif '0' <= char <= '9':
            converted.append(chr(ord(char) + 0x1D7E2 - ord('0')))
        else:
            converted.append(char)
    return ''.join(converted)

def blockquote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"

# Clean PDF/HTML filename: remove leading number (e.g., "1. ") and trailing date (YYYY-MM-DD) before extension
def clean_document_filename(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    # Remove leading numbering: digits followed by dot or space, optionally more spaces
    name = re.sub(r'^\d+(?:\.|\s+)\s*', '', name)
    # Remove trailing date pattern YYYY-MM-DD (and any surrounding spaces/dashes)
    name = re.sub(r'[\s_-]*\d{4}-\d{2}-\d{2}[\s_-]*$', '', name)
    # Clean up any remaining multiple spaces/dashes and strip
    name = re.sub(r'[\s_-]+', ' ', name).strip()
    # If name becomes empty, keep a default
    if not name:
        name = "document"
    return name + ext

# Caption processing for videos (unchanged, works correctly)
def process_caption(text: str, numbering: str) -> str:
    if "Title:" in text:
        after_title = text.split("Title:", 1)[-1].strip()
        after_title = re.sub(r'^\d+(?:\.|\s+)?', '', after_title).lstrip()
        after_title = re.sub(r'\d{4}-\d{2}-\d{2}.*', '', after_title, flags=re.DOTALL).strip()
        title_text = ' '.join(after_title.split())
        formatted_number = to_math_sans_plain(numbering.zfill(3))
        blockquote_text = blockquote(f"[{formatted_number}]")
        return f"{blockquote_text}{title_text}" if title_text else blockquote_text
    else:
        # Old format (unchanged)
        parts = text.split('//', 1)
        before_delim = parts[0].strip()
        before_delim = re.sub(r'\b\d+\.\s*', '', before_delim)
        before_delim = ' '.join(before_delim.split())
        after_delim = parts[1].strip() if len(parts) > 1 else ''
        if after_delim:
            after_delim = re.sub(r'(?si)Batch.*', '', after_delim).strip()
        formatted_number = to_math_sans_plain(numbering.zfill(3))
        blockquote_text = blockquote(f"[{formatted_number}]")
        result = f"{blockquote_text}{before_delim}"
        if after_delim:
            result += f"\n{after_delim}"
        return result

# Main media handler
@bot.on_message(filters.media)
async def handle_media(client, message: Message):
    global current_number
    if message.video:
        async with number_lock:
            num = current_number
            current_number += 1
            save_number(current_number)
        new_caption = process_caption(message.caption or '', str(num))
        try:
            await message.edit_caption(new_caption, parse_mode=enums.ParseMode.HTML)
        except Exception as e:
            print(f"Caption edit failed: {e}")
            await message.reply_video(message.video.file_id, caption=new_caption, parse_mode=enums.ParseMode.HTML)

    elif message.document and message.document.file_name:
        fname = message.document.file_name
        if fname.lower().endswith((".pdf", ".html")):
            new_name = clean_document_filename(fname)
            # If filename changed, re-upload renamed file and delete original
            if new_name != fname:
                try:
                    file_path = await client.download_media(message)
                    if file_path:
                        dir_name = os.path.dirname(file_path)
                        new_path = os.path.join(dir_name, new_name)
                        os.rename(file_path, new_path)
                        await client.send_document(
                            chat_id=message.chat.id,
                            document=new_path,
                            caption="",
                            reply_to_message_id=message.id if message.reply_to_message else None
                        )
                        await message.delete()
                        os.remove(new_path)
                except Exception as e:
                    print(f"PDF rename/re-upload failed: {e}")
                    # Fallback: just clear caption
                    try:
                        await message.edit_caption('')
                    except:
                        pass
            else:
                # No change – just clear caption
                try:
                    await message.edit_caption('')
                except:
                    pass

# Command handlers
@bot.on_message(filters.command("start"))
async def start_cmd(_, message):
    await message.reply(
        "✅ Bot is running.\n\n"
        "• Videos: Captions are cleaned and automatically numbered.\n"
        "• PDF/HTML: Leading number and trailing date are removed from filename; caption cleared.\n"
        "Use /reset or /set <number> to control video numbering.",
        parse_mode=enums.ParseMode.HTML
    )

@bot.on_message(filters.command(["reset", "set"]))
async def number_control(_, message):
    global current_number
    async with number_lock:
        if message.command[0] == "reset":
            current_number = 1
        elif message.command[0] == "set" and len(message.command) > 1:
            try: current_number = max(1, int(message.command[1]))
            except: pass
        save_number(current_number)
        formatted = to_math_sans_plain(str(current_number).zfill(3))
        await message.reply(f"Current numbering: <blockquote>[{formatted}]</blockquote>", parse_mode=enums.ParseMode.HTML)

bot.run()
