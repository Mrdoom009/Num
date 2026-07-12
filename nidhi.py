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

# Video caption processing (no bracket detection)
def process_caption(text: str, numbering: str) -> str:
    # Find all numbers in the caption
    all_numbers = re.findall(r'\d+', text)
    target_number = None

    # Check for the exact pattern: 3-digit, then 1-3 digit, then 1-3 digit (the target)
    if len(all_numbers) >= 3:
        if (len(all_numbers[0]) == 3 and
            1 <= len(all_numbers[1]) <= 3 and
            1 <= len(all_numbers[2]) <= 3):
            target_number = all_numbers[2]   # third number is the one to remove
            # Locate the third number occurrence in the original text
            matches = list(re.finditer(r'\d+', text))
            if len(matches) >= 3:
                third_match = matches[2]
                # Remove everything before the start of the third number, and the number itself
                text = text[third_match.end():].strip()

    # If the pattern didn't match, leave the caption untouched (no removal)

    # Detect "├" and remove everything after including it
    if '├' in text:
        text = text.split('├', 1)[0].strip()

    # Remove any leftover leading dot or spaces
    text = text.lstrip('. ')
    # Clean up multiple spaces/newlines
    title_text = ' '.join(text.split())

    # Format bot's automatic numbering
    formatted_number = to_math_sans_plain(numbering.zfill(3))
    blockquote_text = blockquote(f"[{formatted_number}]")
    return f"{blockquote_text}{title_text}" if title_text else blockquote_text

# PDF/HTML renaming: remove everything up to and including the first number + following spaces
def remove_leading_number(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = re.sub(r'^.*?\d+\s*', '', name)
    if not name:
        name = "document"
    return name + ext

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
            try:
                await message.edit_caption('')
            except:
                pass
            new_name = remove_leading_number(fname)
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

# Command handlers
@bot.on_message(filters.command("start"))
async def start_cmd(_, message):
    await message.reply("✅ Bot is alive.", parse_mode=enums.ParseMode.HTML)

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
