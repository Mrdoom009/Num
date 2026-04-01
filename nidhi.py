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

# Client initialization
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

# Font conversion for numbering only
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

# New caption processing logic
def process_caption(text: str, numbering: str) -> str:
    # New format: contains "Title:"
    if "Title:" in text:
        # 1. Remove everything before and including "Title:"
        after_title = text.split("Title:", 1)[-1].strip()

        # 2. Remove leading number (digits, possibly followed by dot/space) – discard it
        after_title = re.sub(r'^\d+(?:\.|\s+)?', '', after_title).lstrip()

        # 3. Remove everything from the first "[" onward (including the bracket)
        if "[" in after_title:
            after_title = after_title.split("[", 1)[0].strip()

        # 4. Clean whitespace (collapse multiple spaces/newlines)
        title_text = ' '.join(after_title.split())

        # 5. Format the bot's own numbering
        formatted_number = to_math_sans_plain(numbering.zfill(3))
        blockquote_text = blockquote(f"[{formatted_number}]")

        return f"{blockquote_text}{title_text}" if title_text else blockquote_text

    # Old format handling (backward compatibility)
    else:
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

# Handlers
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
    elif message.document and message.document.file_name and message.document.file_name.lower().endswith((".pdf", ".html")):
        # For PDFs, just remove the caption entirely
        try: 
            await message.edit_caption('')
        except: 
            pass

# Command handlers
@bot.on_message(filters.command("start"))
async def start_cmd(_, message):
    await message.reply(
        "📚 <b>Caption Formatter Bot</b>\n\n"
        "Send videos with captions formatted as:\n"
        "<code>Index: 034\n"
        "Title: 6 Subject Verb - Agreement - 2\n"
        "Topic: Home -> Grammar -> Practice -> Video->\n"
        "Batch: ACHIEVERS BATCH 7.0 (3 in 1 Batch)\n"
        "Extracted By: https://tinyurl.com/allcompetitionclasses</code>\n\n"
        "• Removes everything before and including 'Title:'\n"
        "• Removes any leading number from the title text\n"
        "• Removes everything after and including the first '[' in the title\n"
        "• Numbering is formatted in sans-serif font inside blockquote\n"
        "• Format: <blockquote>[𝟶𝟹𝟺]</blockquote>Subject Verb - Agreement - 2\n\n"
        "For PDFs: Caption is completely removed",
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
