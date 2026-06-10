import os
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai
from PIL import Image
import io

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SYSTEM_PROMPT = """คุณคือผู้ช่วยคำนวณแคลอรี่อาหาร ตอบเป็นภาษาไทยเสมอ

เมื่อผู้ใช้บอกชื่ออาหารหรือส่งรูปอาหาร ให้:
1. บอกชื่ออาหาร
2. แคลอรี่โดยประมาณ (ต่อจาน/ต่อชิ้น)
3. สารอาหารหลัก: โปรตีน คาร์โบไฮเดรต ไขมัน
4. เคล็ดลับสุขภาพสั้นๆ 1 ประโยค

ตอบสั้นกระชับ อ่านง่าย ใช้ emoji ประกอบ
ถ้าไม่ใช่เรื่องอาหาร ให้บอกว่าตอบได้เฉพาะเรื่องแคลอรี่อาหารเท่านั้น"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 *แคลบอท* พร้อมใช้งานแล้ว!\n\n"
        "📝 พิมพ์ชื่ออาหาร เช่น _ข้าวผัดหมู 1 จาน_\n"
        "📸 หรือส่งรูปอาหาร แล้วฉันจะคำนวณให้เลย!",
        parse_mode="Markdown"
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    await update.message.chat.send_action("typing")

    try:
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nผู้ใช้ถามว่า: {user_text}")
        await update.message.reply_text(response.text)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะ")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.chat.send_action("typing")

    try:
        # Download photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()

        # Convert to PIL Image
        image = Image.open(io.BytesIO(file_bytes))

        # Send to Gemini with image
        response = model.generate_content([
            f"{SYSTEM_PROMPT}\n\nผู้ใช้ส่งรูปอาหารมา กรุณาวิเคราะห์ว่าคืออาหารอะไร แล้วคำนวณแคลอรี่",
            image
        ])
        await update.message.reply_text(response.text)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะ")


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.run_polling()
