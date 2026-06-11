import os
import re
import json
import asyncio
import aiohttp
from html import unescape
from bs4 import BeautifulSoup
from threading import Thread
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import Message

# ---------- CONFIG ----------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID, API_HASH or BOT_TOKEN environment variables.")

bot = Client("quiz_converter_bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# Flask health check (for hosting)
health_app = Flask(__name__)

@health_app.route('/')
def health_check():
    return "OK", 200

Thread(target=lambda: health_app.run(port=8000, host="0.0.0.0"), daemon=True).start()


# ---------- HELPERS ----------
def extract_json_url_from_html(html_content: str) -> str | None:
    """Find the first occurrence of var JSON_URL = '...' in the HTML."""
    # Pattern matches: var JSON_URL = 'http...' or var JSON_URL = "http..."
    match = re.search(r"var\s+JSON_URL\s*=\s*['\"]([^'\"]+)['\"]", html_content)
    return match.group(1) if match else None


def clean_html_text(html_text: str) -> str:
    """Convert HTML to plain text, remove extra whitespace."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    # Unescape HTML entities like &amp; etc.
    text = unescape(text)
    return " ".join(text.split())


def convert_question(q: dict) -> dict:
    """
    Convert a single question from the source JSON to target format.
    Expected source fields:
        - question (HTML string)
        - option_1, option_2, ... up to option_10 (HTML)
        - answer (string, e.g. "1", "2", ...)
        - solution_text (HTML) – optional
    """
    # Clean question text
    question_text = clean_html_text(q.get("question", ""))

    # Collect options (max 10, but we stop when empty)
    options = []
    option_ids = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]
    for i in range(1, 11):
        opt_html = q.get(f"option_{i}")
        if not opt_html or not opt_html.strip():
            continue
        opt_text = clean_html_text(opt_html)
        if opt_text:
            options.append({"id": option_ids[len(options)], "text": opt_text})

    # Map answer to option id (answer is string like "1", "2", ...)
    raw_answer = str(q.get("answer", "")).strip()
    correct_option_id = ""
    if raw_answer.isdigit():
        idx = int(raw_answer) - 1
        if 0 <= idx < len(options):
            correct_option_id = options[idx]["id"]

    # Clean explanation
    explanation = clean_html_text(q.get("solution_text", ""))

    return {
        "question_text": question_text,
        "options": options,
        "correct_option_id": correct_option_id,
        "explanation": explanation
    }


def convert_questions_batch(questions_data: list) -> list:
    """Convert the whole list of source questions."""
    converted = []
    for q in questions_data:
        try:
            converted.append(convert_question(q))
        except Exception as e:
            print(f"Error converting a question: {e}")
            # Skip broken question
            continue
    return converted


async def download_json_from_url(url: str) -> dict | None:
    """Download JSON from URL and return parsed data."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data
    except Exception as e:
        print(f"JSON download failed: {e}")
        return None


# ---------- BOT HANDLERS ----------
@bot.on_message(filters.command("start"))
async def start_cmd(_, message: Message):
    await message.reply(
        "📚 **Quiz Converter Bot**\n\n"
        "Send me an **HTML file** that contains a `var JSON_URL = '...'` (like the Mewar dynasty file).\n"
        "I will:\n"
        "1. Extract the JSON URL\n"
        "2. Download the questions\n"
        "3. Convert them into your required format\n"
        "4. Send you back a clean **JSON file**.\n\n"
        "You can also send me a **JSON file** directly (the one from the URL) – I'll convert it immediately.\n\n"
        "Made with ❤️ for easy question extraction.",
        parse_mode=enums.ParseMode.MARKDOWN
    )


@bot.on_message(filters.document)
async def handle_document(client: Client, message: Message):
    doc = message.document
    file_name = doc.file_name or ""

    # Download the file
    temp_path = await client.download_media(message)
    if not temp_path:
        await message.reply("❌ Failed to download the file.")
        return

    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        await message.reply("❌ Could not read file (not UTF-8 text).")
        os.remove(temp_path)
        return

    json_data = None
    source_desc = ""

    # Case 1: HTML file
    if file_name.lower().endswith(".html"):
        json_url = extract_json_url_from_html(content)
        if not json_url:
            await message.reply("❌ No `var JSON_URL = '...'` found in the HTML file.")
            os.remove(temp_path)
            return
        await message.reply(f"🔍 Found JSON URL:\n`{json_url}`\nDownloading...", parse_mode=enums.ParseMode.MARKDOWN)
        json_data = await download_json_from_url(json_url)
        source_desc = f"from URL: {json_url}"
        if not json_data:
            await message.reply("❌ Failed to download or parse the JSON from that URL.")
            os.remove(temp_path)
            return

    # Case 2: JSON file directly
    elif file_name.lower().endswith(".json"):
        try:
            json_data = json.loads(content)
            source_desc = "from uploaded JSON file"
        except json.JSONDecodeError:
            await message.reply("❌ Invalid JSON file.")
            os.remove(temp_path)
            return
    else:
        await message.reply("❌ Unsupported file type. Send an **.html** or **.json** file.")
        os.remove(temp_path)
        return

    # At this point, json_data should be a list of questions
    if not isinstance(json_data, list):
        await message.reply("❌ JSON data is not an array of questions.")
        os.remove(temp_path)
        return

    # Convert questions
    await message.reply(f"✅ Loaded {len(json_data)} questions. Converting... {source_desc}")
    converted_questions = convert_questions_batch(json_data)

    # Prepare final output
    output = {"questions": converted_questions}
    output_json_str = json.dumps(output, ensure_ascii=False, indent=2)

    # Save to temporary file
    output_path = temp_path + ".converted.json"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_json_str)

    # Send back the JSON file
    try:
        await client.send_document(
            chat_id=message.chat.id,
            document=output_path,
            caption=f"✅ Conversion complete!\n\n📊 {len(converted_questions)} questions extracted.\n📁 Format: your requested structure.",
            reply_to_message_id=message.id
        )
    except Exception as e:
        await message.reply(f"❌ Failed to send the output file: {e}")

    # Cleanup
    os.remove(temp_path)
    if os.path.exists(output_path):
        os.remove(output_path)


# ---------- RUN ----------
if __name__ == "__main__":
    print("Bot started. Waiting for HTML/JSON files...")
    bot.run()
