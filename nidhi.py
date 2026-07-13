import os
import re
import asyncio
from threading import Thread

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from flask import Flask

# =========================
# Configuration
# =========================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

bot = Client("file_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# =========================
# Flask health check
# =========================
health_app = Flask(__name__)

@health_app.route("/")
def health_check():
    return "OK", 200

Thread(
    target=lambda: health_app.run(port=8000, host="0.0.0.0"),
    daemon=True
).start()

# =========================
# Numbering persistence
# =========================
NUMBERING_FILE = "numbering_state.txt"
current_number = 1
number_lock = asyncio.Lock()

def load_number():
    try:
        if os.path.exists(NUMBERING_FILE):
            with open(NUMBERING_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip() or "1")
        return 1
    except:
        return 1

def save_number(num: int):
    with open(NUMBERING_FILE, "w", encoding="utf-8") as f:
        f.write(str(num))

current_number = load_number()

# =========================
# Sequential queue
# =========================
media_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
enqueue_seq = 0
enqueue_lock = asyncio.Lock()
worker_started = False
worker_start_lock = asyncio.Lock()

async def ensure_worker_started():
    global worker_started
    async with worker_start_lock:
        if not worker_started:
            worker_started = True
            asyncio.create_task(media_worker())

async def enqueue_media(message: Message):
    global enqueue_seq
    async with enqueue_lock:
        enqueue_seq += 1
        seq = enqueue_seq
    await media_queue.put((seq, message))
    await ensure_worker_started()

async def media_worker():
    while True:
        seq, message = await media_queue.get()
        try:
            await process_media(message)
        except Exception as e:
            print(f"[QUEUE ERROR] seq={seq} msg_id={message.id}: {e}")
        finally:
            media_queue.task_done()

# =========================
# Helpers
# =========================
def to_math_sans_plain(text: str) -> str:
    converted = []
    for char in text:
        if "A" <= char <= "Z":
            converted.append(chr(ord(char) + 0x1D5A0 - ord("A")))
        elif "a" <= char <= "z":
            converted.append(chr(ord(char) + 0x1D5BA - ord("a")))
        elif "0" <= char <= "9":
            converted.append(chr(ord(char) + 0x1D7E2 - ord("0")))
        else:
            converted.append(char)
    return "".join(converted)

def blockquote(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"

def process_caption(text: str, numbering: str) -> str:
    # Matches:
    # Title: 1
    # Title : 1
    # Title:1.
    # title : 34.
    title_pattern = r"Title\s*:\s*\d+\.?"
    match = re.search(title_pattern, text, flags=re.IGNORECASE)
    if match:
        text = text[match.end():].strip()

    # Cut everything after .mp4 only
    mp4_match = re.search(r"\.mp4", text, flags=re.IGNORECASE)
    if mp4_match:
        text = text[:mp4_match.start()].strip()

    title_text = " ".join(text.split())
    formatted_number = to_math_sans_plain(numbering.zfill(3))
    num_block = blockquote(f"[{formatted_number}]")

    return f"{num_block}{title_text}" if title_text else num_block

def remove_leading_number(filename: str) -> str:
    name, ext = os.path.splitext(filename)
    name = re.sub(r"^\d+\.\s*", "", name)
    if not name:
        name = "document"
    return name + ext

# =========================
# Main processing
# =========================
async def process_video(message: Message):
    global current_number

    async with number_lock:
        num = current_number

    new_caption = process_caption(message.caption or "", str(num))
    success = False

    # 1) Try editing the original caption
    try:
        await message.edit_caption(new_caption, parse_mode=enums.ParseMode.HTML)
        success = True
    except Exception as e:
        print(f"[EDIT FAIL] msg_id={message.id}: {e}")

    # 2) If edit fails, resend as a new video with the caption
    if not success:
        try:
            await message.reply_video(
                message.video.file_id,
                caption=new_caption,
                parse_mode=enums.ParseMode.HTML
            )
            success = True
        except Exception as e:
            print(f"[RESEND FAIL] msg_id={message.id}: {e}")

    # 3) Consume number anyway so sequence stays moving
    async with number_lock:
        current_number += 1
        save_number(current_number)

async def process_document(message: Message):
    fname = message.document.file_name or ""
    if not fname.lower().endswith((".pdf", ".html")):
        return

    # Clear caption if possible
    try:
        await message.edit_caption("")
    except:
        pass

    new_name = remove_leading_number(fname)
    if new_name == fname:
        return

    file_path = None
    new_path = None

    try:
        file_path = await bot.download_media(message)
        if not file_path:
            return

        dir_name = os.path.dirname(file_path)
        new_path = os.path.join(dir_name, new_name)

        os.replace(file_path, new_path)

        await bot.send_document(
            chat_id=message.chat.id,
            document=new_path,
            caption="",
            reply_to_message_id=message.id if message.reply_to_message else None
        )

        try:
            await message.delete()
        except:
            pass

    except Exception as e:
        print(f"[DOC FAIL] msg_id={message.id}: {e}")

    finally:
        # Cleanup temp file if present
        try:
            if new_path and os.path.exists(new_path):
                os.remove(new_path)
        except:
            pass

        try:
            if file_path and os.path.exists(file_path) and file_path != new_path:
                os.remove(file_path)
        except:
            pass

async def process_media(message: Message):
    if message.video:
        await process_video(message)
    elif message.document and message.document.file_name:
        await process_document(message)

# =========================
# Handlers
# =========================
@bot.on_message(filters.media)
async def handle_media(_, message: Message):
    await enqueue_media(message)

@bot.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    await message.reply(
        "✅ Bot is running.\n\n"
        "• Videos: detects `Title : 1`, `Title: 1`, `Title: 1.` etc.\n"
        "• Removes everything after `.mp4`.\n"
        "• Processing is sequential, so bulk uploads keep numbering in order.\n"
        "• PDF/HTML: filename leading number is removed.\n"
        "Use `/reset` or `/set <number>` to control video numbering.",
        parse_mode=enums.ParseMode.HTML
    )

@bot.on_message(filters.command(["reset", "set"]))
async def number_control(_, message: Message):
    global current_number

    async with number_lock:
        if message.command[0] == "reset":
            current_number = 1
        elif message.command[0] == "set" and len(message.command) > 1:
            try:
                current_number = max(1, int(message.command[1]))
            except:
                pass

        save_number(current_number)
        formatted = to_math_sans_plain(str(current_number).zfill(3))

    await message.reply(
        f"Current numbering: <blockquote>[{formatted}]</blockquote>",
        parse_mode=enums.ParseMode.HTML
    )

# =========================
# Run bot
# =========================
bot.run()
