# 🔥 แคลบอท - Telegram Calorie Bot

บอทคำนวณแคลอรี่อาหาร รองรับทั้งข้อความและรูปภาพ

## การติดตั้ง

### Environment Variables ที่ต้องตั้งใน Railway
```
TELEGRAM_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
```

### Deploy บน Railway
1. Push code นี้ขึ้น GitHub
2. ไปที่ railway.app → New Project → GitHub Repository
3. เลือก repo นี้
4. ไปที่ Variables แล้วใส่ TELEGRAM_TOKEN และ GEMINI_API_KEY
5. Railway จะ deploy ให้อัตโนมัติ
