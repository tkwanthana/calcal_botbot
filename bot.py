import os
import json
import logging
from datetime import datetime, date
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import google.generativeai as genai
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash-exp")

DATA_FILE = "user_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data:
        data[uid] = {"profile": {}, "days": {}, "weeks": {}}
    return data[uid]

def today_str():
    return date.today().isoformat()

def week_str():
    d = date.today()
    return f"{d.year}-W{d.isocalendar()[1]:02d}"

def get_today(user):
    t = today_str()
    if t not in user["days"]:
        user["days"][t] = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "sodium": 0, "sugar": 0, "burned": 0, "steps": 0, "logs": []}
    return user["days"][t]

def calc_tdee(profile):
    g = profile.get("gender", "male")
    age = profile.get("age", 25)
    w = profile.get("weight", 65)
    h = profile.get("height", 170)
    act = profile.get("activity", 1.375)
    if g == "male":
        bmr = 10 * w + 6.25 * h - 5 * age + 5
    else:
        bmr = 10 * w + 6.25 * h - 5 * age - 161
    return round(bmr * act)

def calc_targets(profile):
    tdee = calc_tdee(profile)
    w = profile.get("weight", 65)
    return {
        "calories": tdee,
        "protein": round(w * 1.8),
        "carbs": round(tdee * 0.45 / 4),
        "fat": round(tdee * 0.25 / 9),
        "sodium": 2300,
        "sugar": 50
    }

def make_prompt(profile=None, today_log=None):
    lines = [
        "คุณคือเทรนเนอร์ส่วนตัวและผู้ช่วยด้านโภชนาการ",
        "ตอบเป็นภาษาที่ผู้ใช้พิมพ์มา (ไทยหรืออังกฤษ)",
        "ใช้ภาษาสุภาพ เป็นมืออาชีพ ให้กำลังใจ ใช้ emoji ประกอบพอเหมาะ",
        "",
        "เมื่อผู้ใช้บอกชื่ออาหารหรือส่งรูปอาหาร ให้ตอบเป็น JSON เท่านั้น รูปแบบ:",
        '{"food":"ชื่อ","serving":"หน่วย","calories":0,"protein":0,"carbs":0,"fat":0,"sodium":0,"sugar":0,"advice":"คำแนะนำ"}',
        "",
        "เมื่อผู้ใช้ส่งรูปหน้าจอนาฬิกา/แอพออกกำลังกาย ให้ตอบเป็น JSON รูปแบบ:",
        '{"type":"exercise","activity":"ชื่อ","burned":0,"steps":0,"duration":"เวลา","advice":"คำแนะนำ"}',
        "",
        "ถ้าผู้ใช้ถามคำถาม ขอคำแนะนำ หรือคุยทั่วไปเกี่ยวกับสุขภาพและโภชนาการ ให้ตอบเป็นข้อความปกติ ห้ามตอบ JSON เด็ดขาด",
    ]

    if profile:
        tdee = calc_tdee(profile)
        targets = calc_targets(profile)
        lines.append("")
        lines.append("ข้อมูลผู้ใช้: เพศ " + str(profile.get("gender")) + " อายุ " + str(profile.get("age")) + " ปี น้ำหนัก " + str(profile.get("weight")) + " กก. ส่วนสูง " + str(profile.get("height")) + " ซม.")
        lines.append("TDEE: " + str(tdee) + " kcal/วัน | เป้าโปรตีน: " + str(targets["protein"]) + "g | คาร์บ: " + str(targets["carbs"]) + "g | ไขมัน: " + str(targets["fat"]) + "g")

    if today_log:
        lines.append("")
        lines.append("บันทึกวันนี้แล้ว: " + str(today_log["calories"]) + " kcal | โปรตีน " + str(today_log["protein"]) + "g | คาร์บ " + str(today_log["carbs"]) + "g | ไขมัน " + str(today_log["fat"]) + "g | โซเดียม " + str(today_log["sodium"]) + "mg | น้ำตาล " + str(today_log["sugar"]) + "g | เผาผลาญ " + str(today_log["burned"]) + " kcal")

    return "\n".join(lines)

def check_warnings(today, targets):
    tdee = targets.get("calories", 0)
    deficit = today["burned"] + tdee - today["calories"]
    warnings = []
    if deficit > 0:
        warnings.append("⚠️ กินเกิน TDEE แล้วครับ ระวังด้วยนะครับ")
    if deficit < -1000:
        warnings.append("⚠️ Deficit เกิน 1,000 kcal แล้วครับ น้อยเกินไปอาจอันตราย ควรกินเพิ่มนะครับ")
    if today["sodium"] > 2300:
        warnings.append("🧂 โซเดียมเกินแล้วครับ ดื่มน้ำเยอะๆ ด้วยนะครับ")
    if today["sugar"] > 50:
        warnings.append("🍬 น้ำตาลเกินแล้วครับ ระวังเครื่องดื่มหวานด้วยนะครับ")
    if today["protein"] < targets.get("protein", 0) * 0.7:
        warnings.append("💪 โปรตีนยังน้อยอยู่ครับ ลองเพิ่มไข่ขาว อกไก่ หรือปลาได้ครับ")
    return warnings, deficit

def format_summary(user):
    profile = user.get("profile", {})
    today = get_today(user)
    if not profile:
        return "⚠️ ยังไม่มีข้อมูลโปรไฟล์ครับ กรุณาพิมพ์ /start เพื่อตั้งค่าก่อนนะครับ"
    targets = calc_targets(profile)
    tdee = calc_tdee(profile)
    deficit = today["burned"] + tdee - today["calories"]
    lines = [
        "*สรุปวันนี้* (" + today_str() + ")",
        "",
        "🔥 แคลอรี่: " + str(today["calories"]) + " / " + str(targets["calories"]) + " kcal",
        "💪 โปรตีน: " + str(today["protein"]) + "g / " + str(targets["protein"]) + "g",
        "🍚 คาร์บ: " + str(today["carbs"]) + "g / " + str(targets["carbs"]) + "g",
        "🧈 ไขมัน: " + str(today["fat"]) + "g / " + str(targets["fat"]) + "g",
        "🧂 โซเดียม: " + str(today["sodium"]) + "mg / " + str(targets["sodium"]) + "mg",
        "🍬 น้ำตาล: " + str(today["sugar"]) + "g / " + str(targets["sugar"]) + "g",
        "🏃 เผาผลาญ: " + str(today["burned"]) + " kcal",
        "👟 ก้าวเดิน: " + str(today["steps"]) + " ก้าว",
        "",
        "⚡ Deficit วันนี้: " + ("+"+str(deficit) if deficit >= 0 else str(deficit)) + " kcal",
    ]
    warnings, _ = check_warnings(today, targets)
    if warnings:
        lines.append("")
        lines.append("*คำแนะนำ:*")
        lines.extend(warnings)
    return "\n".join(lines)

def format_weekly(user):
    w = week_str()
    days = user.get("days", {})
    profile = user.get("profile", {})
    if not profile:
        return "⚠️ ยังไม่มีข้อมูลโปรไฟล์ครับ กรุณาพิมพ์ /start ก่อนนะครับ"
    tdee = calc_tdee(profile)
    total_in = 0
    total_burned = 0
    day_count = 0
    for day_key, day_data in days.items():
        try:
            day_date = date.fromisoformat(day_key)
            if day_date.isocalendar()[1] == date.today().isocalendar()[1] and day_date.year == date.today().year:
                total_in += day_data.get("calories", 0)
                total_burned += day_data.get("burned", 0) + tdee
                day_count += 1
        except:
            pass
    weekly_deficit = total_burned - total_in
    checkins = user.get("checkins", [])
    latest = checkins[-1] if checkins else None
    deficit_str = ("+"+str(weekly_deficit) if weekly_deficit >= 0 else str(weekly_deficit))
    lines = [
        "*สรุปสัปดาห์นี้* (" + w + ")",
        "วันที่บันทึก: " + str(day_count) + " วัน",
        "",
        "🍽️ กินรวม: " + str(total_in) + " kcal",
        "🔥 เผาผลาญรวม: " + str(total_burned) + " kcal",
        "⚡ Deficit รวม: " + deficit_str + " kcal",
        "",
    ]
    if weekly_deficit < 0:
        lines.append("✅ สัปดาห์นี้อยู่ในช่วง deficit ดีมากครับ!")
    elif weekly_deficit > 0:
        lines.append("⚠️ สัปดาห์นี้กินเกินเผาผลาญนะครับ ลองปรับดูครับ")
    if latest:
        lines += [
            "",
            "⚖️ น้ำหนักล่าสุด: " + str(latest.get("weight", "-")) + " กก.",
            "📏 รอบเอวล่าสุด: " + str(latest.get("waist", "-")) + " ซม.",
            "📅 บันทึกเมื่อ: " + str(latest.get("date", "-")),
        ]
    return "\n".join(lines)

async def build_food_reply(parsed, today, targets, profile):
    today["calories"] += parsed.get("calories", 0)
    today["protein"] += parsed.get("protein", 0)
    today["carbs"] += parsed.get("carbs", 0)
    today["fat"] += parsed.get("fat", 0)
    today["sodium"] += parsed.get("sodium", 0)
    today["sugar"] += parsed.get("sugar", 0)
    today["logs"].append({"time": datetime.now().strftime("%H:%M"), "food": parsed.get("food"), "calories": parsed.get("calories")})
    tdee = calc_tdee(profile) if profile else 0
    warnings, deficit = check_warnings(today, targets)
    remaining_cal = targets.get("calories", 0) - today["calories"]
    remaining_pro = targets.get("protein", 0) - today["protein"]
    deficit_str = ("+"+str(deficit) if deficit >= 0 else str(deficit))
    reply = (
        "🍽️ *" + str(parsed.get("food")) + "* (" + str(parsed.get("serving", "")) + ")\n\n"
        "🔥 " + str(parsed.get("calories")) + " kcal\n"
        "💪 โปรตีน: " + str(parsed.get("protein")) + "g\n"
        "🍚 คาร์บ: " + str(parsed.get("carbs")) + "g\n"
        "🧈 ไขมัน: " + str(parsed.get("fat")) + "g\n"
        "🧂 โซเดียม: " + str(parsed.get("sodium")) + "mg\n"
        "🍬 น้ำตาล: " + str(parsed.get("sugar")) + "g\n\n"
        "📊 *สะสมวันนี้:* " + str(today["calories"]) + " kcal\n"
        "⚡ Deficit: " + deficit_str + " kcal\n"
        "🍽️ เหลืออีก: " + str(remaining_cal) + " kcal | โปรตีน: " + str(remaining_pro) + "g\n"
    )
    if warnings:
        reply += "\n" + "\n".join(warnings)
    reply += "\n\n💬 " + str(parsed.get("advice", ""))
    return reply

async def build_exercise_reply(parsed, today, profile):
    today["burned"] += parsed.get("burned", 0)
    today["steps"] += parsed.get("steps", 0)
    tdee = calc_tdee(profile) if profile else 0
    deficit = today["burned"] + tdee - today["calories"]
    deficit_str = ("+"+str(deficit) if deficit >= 0 else str(deficit))
    return (
        "🏃 *" + str(parsed.get("activity", "ออกกำลังกาย")) + "*\n"
        "⏱️ " + str(parsed.get("duration", "-")) + "\n"
        "🔥 เผาผลาญ: " + str(parsed.get("burned", 0)) + " kcal\n"
        "👟 ก้าวเดิน: " + str(parsed.get("steps", 0)) + " ก้าว\n\n"
        "📊 วันนี้เผาผลาญรวม: " + str(today["burned"]) + " kcal\n"
        "⚡ Deficit: " + deficit_str + " kcal\n\n"
        "💬 " + str(parsed.get("advice", ""))
    )

async def process_ai_response(raw, today, targets, profile, update, data):
    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
        if parsed.get("type") == "exercise":
            reply = await build_exercise_reply(parsed, today, profile)
        else:
            reply = await build_food_reply(parsed, today, targets, profile)
        save_data(data)
        await update.message.reply_text(reply, parse_mode="Markdown")
    except json.JSONDecodeError:
        await update.message.reply_text(raw)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_data()
    user = get_user(data, uid)
    await update.message.reply_text(
        "👋 สวัสดีครับ! ผมคือเทรนเนอร์ส่วนตัวด้านโภชนาการของคุณครับ\n\n"
        "ก่อนเริ่มต้น ขอข้อมูลเบื้องต้นก่อนนะครับ\n\n"
        "กรุณาตอบในรูปแบบนี้เลยครับ:\n"
        "`เพศ อายุ น้ำหนัก ส่วนสูง กิจกรรม`\n\n"
        "ตัวอย่าง: `ชาย 28 70 175 ปานกลาง`\n\n"
        "ระดับกิจกรรม:\n"
        "น้อย = นั่งทำงานทั้งวัน\n"
        "ปานกลาง = ออกกำลังกาย 3-4 วัน/สัปดาห์\n"
        "มาก = ออกกำลังกายทุกวัน\n"
        "สูงมาก = งานหนักหรือนักกีฬา",
        parse_mode="Markdown"
    )
    user["state"] = "setup"
    save_data(data)

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_data()
    user = get_user(data, uid)
    await update.message.reply_text(format_summary(user), parse_mode="Markdown")

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_data()
    user = get_user(data, uid)
    await update.message.reply_text(format_weekly(user), parse_mode="Markdown")

async def cmd_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚖️ บันทึกข้อมูลประจำสัปดาห์ครับ\n\n"
        "กรุณาพิมพ์: `น้ำหนัก รอบเอว`\n"
        "ตัวอย่าง: `68.5 82`\n\n"
        "(น้ำหนักหน่วย กก. รอบเอวหน่วย ซม.)",
        parse_mode="Markdown"
    )
    data = load_data()
    user = get_user(data, str(update.effective_user.id))
    user["state"] = "checkin"
    save_data(data)

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_data()
    user = get_user(data, uid)
    profile = user.get("profile", {})
    if not profile:
        await update.message.reply_text("ยังไม่มีโปรไฟล์ครับ พิมพ์ /start เพื่อตั้งค่าได้เลยครับ")
        return
    targets = calc_targets(profile)
    tdee = calc_tdee(profile)
    act_map = {1.2: "น้อย", 1.375: "ปานกลาง", 1.55: "มาก", 1.725: "สูงมาก"}
    act_label = act_map.get(profile.get("activity"), "ปานกลาง")
    text = (
        "👤 *โปรไฟล์ของคุณ*\n\n"
        "เพศ: " + str(profile.get("gender", "-")) + "\n"
        "อายุ: " + str(profile.get("age", "-")) + " ปี\n"
        "น้ำหนัก: " + str(profile.get("weight", "-")) + " กก.\n"
        "ส่วนสูง: " + str(profile.get("height", "-")) + " ซม.\n"
        "ระดับกิจกรรม: " + act_label + "\n\n"
        "📊 *เป้าหมายต่อวัน*\n"
        "TDEE: " + str(tdee) + " kcal\n"
        "โปรตีน: " + str(targets["protein"]) + "g\n"
        "คาร์บ: " + str(targets["carbs"]) + "g\n"
        "ไขมัน: " + str(targets["fat"]) + "g\n\n"
        "พิมพ์ /start เพื่อแก้ไขข้อมูลได้เลยครับ"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    data = load_data()
    user = get_user(data, uid)
    t = today_str()
    user["days"][t] = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "sodium": 0, "sugar": 0, "burned": 0, "steps": 0, "logs": []}
    save_data(data)
    await update.message.reply_text("✅ ล้างข้อมูลวันนี้เรียบร้อยแล้วครับ")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    text = update.message.text.strip()
    data = load_data()
    user = get_user(data, uid)
    state = user.get("state", "")

    if state == "setup":
        try:
            parts = text.split()
            gender_map = {"ชาย": "male", "หญิง": "female", "male": "male", "female": "female"}
            act_map = {"น้อย": 1.2, "ปานกลาง": 1.375, "มาก": 1.55, "สูงมาก": 1.725}
            gender = gender_map.get(parts[0].lower(), "male")
            age = int(parts[1])
            weight = float(parts[2])
            height = float(parts[3])
            activity = act_map.get(parts[4], 1.375) if len(parts) > 4 else 1.375
            user["profile"] = {"gender": gender, "age": age, "weight": weight, "height": height, "activity": activity}
            user["state"] = ""
            targets = calc_targets(user["profile"])
            tdee = calc_tdee(user["profile"])
            save_data(data)
            await update.message.reply_text(
                "✅ *บันทึกโปรไฟล์เรียบร้อยแล้วครับ!*\n\n"
                "📊 TDEE ของคุณ: *" + str(tdee) + " kcal/วัน*\n\n"
                "*เป้าหมายสารอาหารต่อวัน:*\n"
                "💪 โปรตีน: " + str(targets["protein"]) + "g\n"
                "🍚 คาร์บ: " + str(targets["carbs"]) + "g\n"
                "🧈 ไขมัน: " + str(targets["fat"]) + "g\n\n"
                "พร้อมแล้วครับ! ส่งชื่ออาหารหรือรูปมาได้เลย",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text("❌ รูปแบบไม่ถูกต้องครับ ลองใหม่นะครับ\nตัวอย่าง: `ชาย 28 70 175 ปานกลาง`", parse_mode="Markdown")
        return

    if state == "checkin":
        try:
            parts = text.split()
            weight = float(parts[0])
            waist = float(parts[1]) if len(parts) > 1 else None
            if "checkins" not in user:
                user["checkins"] = []
            entry = {"date": today_str(), "weight": weight}
            if waist:
                entry["waist"] = waist
            user["checkins"].append(entry)
            user["state"] = ""
            save_data(data)
            msg = "✅ บันทึกแล้วครับ! น้ำหนัก " + str(weight) + " กก."
            if waist:
                msg += " รอบเอว " + str(waist) + " ซม."
            await update.message.reply_text(msg)
        except:
            await update.message.reply_text("❌ รูปแบบไม่ถูกต้องครับ ตัวอย่าง: `68.5 82`", parse_mode="Markdown")
        return

    await update.message.chat.send_action("typing")
    profile = user.get("profile", {})
    today = get_today(user)
    targets = calc_targets(profile) if profile else {}
    prompt = make_prompt(profile, today)

    try:
        response = model.generate_content(prompt + "\n\nผู้ใช้: " + text)
        raw = response.text.strip()
        await process_ai_response(raw, today, targets, profile, update, data)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ เกิดข้อผิดพลาดครับ ลองใหม่อีกครั้งนะครับ")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    await update.message.chat.send_action("typing")
    data = load_data()
    user = get_user(data, uid)
    profile = user.get("profile", {})
    today = get_today(user)
    targets = calc_targets(profile) if profile else {}
    prompt = make_prompt(profile, today)

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        image = Image.open(io.BytesIO(file_bytes))
        response = model.generate_content([prompt + "\n\nผู้ใช้ส่งรูปมาครับ วิเคราะห์ว่าเป็นอาหารหรือหน้าจอออกกำลังกาย แล้วตอบ JSON ตามรูปแบบที่กำหนดครับ", image])
        raw = response.text.strip()
        await process_ai_response(raw, today, targets, profile, update, data)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ เกิดข้อผิดพลาดครับ ลองใหม่อีกครั้งนะครับ")

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "ตั้งค่าโปรไฟล์"),
        BotCommand("summary", "ดูยอดสะสมวันนี้"),
        BotCommand("weekly", "สรุปรายสัปดาห์ + deficit"),
        BotCommand("checkin", "บันทึกน้ำหนัก + รอบเอว"),
        BotCommand("profile", "ดู/แก้ไขโปรไฟล์"),
        BotCommand("reset", "ล้างข้อมูลวันนี้"),
    ])

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("weekly", cmd_weekly))
    app.add_handler(CommandHandler("checkin", cmd_checkin))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.run_polling()
