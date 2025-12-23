import os
import requests
import asyncio
import random
import re
import time
from threading import Thread
from flask import Flask
from bs4 import BeautifulSoup
from pyrogram import Client, filters

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

bot = Client(
    "yopmail_v7",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False
)

# ==================== WEB SERVER ====================
app = Flask(__name__)
@app.route('/')
def home(): return "V7 Hunter Aktif! 🟢"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== RAM VERİTABANI ====================
USER_LIMITS = {}
def check_user_rights(user_id):
    if user_id == OWNER_ID: return True, "Sınırsız"
    if user_id not in USER_LIMITS: USER_LIMITS[user_id] = 5
    if USER_LIMITS[user_id] > 0:
        USER_LIMITS[user_id] -= 1
        return True, USER_LIMITS[user_id]
    return False, 0

# ==================== CHECKER MOTORU (V7 - COOKIE FIX) ====================
def check_yopmail_v7(email):
    username = email.split('@')[0]
    
    # Session (Oturum) Başlat
    s = requests.Session()
    
    # Bu Headerlar ÇOK ÖNEMLİ. Birebir Tarayıcı Taklidi.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://yopmail.com/en/",
        "Origin": "https://yopmail.com",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1"
    }

    # Çerezler (GDPR Engelini Geçmek İçin)
    # Yopmail'e "Ben daha önce girdim, kabul ettim" diyoruz.
    cookies = {
        "consent": "yes",
        "cw": "1", # Cookie Warning kapalı
        "ytime": str(int(time.time())) # Zaman damgası
    }
    s.cookies.update(cookies)

    try:
        # ADIM 1: Ana Sayfadan Token Çal
        r_main = s.get("https://yopmail.com/en/", headers=headers, timeout=10)
        
        # Regex ile 'yp' değerini bul (Tırnak işaretlerine duyarlı)
        # Yopmail bazen value="XXX" bazen value='XXX' yapar.
        yp_match = re.search(r'id=["\']?yp["\']?\s+value=["\']?([^"\']+)["\']?', r_main.text)
        yj_match = re.search(r'id=["\']?yj["\']?\s+value=["\']?([^"\']+)["\']?', r_main.text)
        
        if not yp_match:
            # Eğer token bulamazsa muhtemelen Captcha yedik
            if "Captcha" in r_main.text or "robot" in r_main.text:
                return "BLOCK", "Captcha Çıktı"
            return "ERROR", "Token Bulunamadı (HTML Değişti)"
            
        yp = yp_match.group(1)
        yj = yj_match.group(1) if yj_match else "V2"

        # ADIM 2: Kutuya Gir
        inbox_url = "https://yopmail.com/en/inbox"
        params = {
            "login": username,
            "p": "1",
            "d": "",
            "ctrl": "",
            "scrl": "",
            "spam": True,
            "yp": yp, # Çaldığımız token
            "yj": yj,
            "v": "3.1"
        }
        
        r_inbox = s.post(inbox_url, data=params, headers=headers, timeout=10)

        # HTML Analizi
        soup = BeautifulSoup(r_inbox.text, "html.parser")
        text_lower = r_inbox.text.lower()

        # Boş Kontrolü
        if "no mail for" in text_lower or "inbox is empty" in text_lower:
            return "EMPTY", "Boş"

        # Kategori Taraması
        tags = []
        msgs = []
        
        # Mail Başlıklarını Al
        # Yopmail masaüstünde 'lms', mobilde 'm' class kullanır.
        mail_items = soup.find_all("div", class_="lms")
        if not mail_items: mail_items = soup.find_all("div", class_="m")

        # Kelime Havuzu
        keywords = {
            "SUPERCELL": ["supercell", "brawl", "clash", "id code", "login code", "verification"],
            "SOCIAL": ["instagram", "tiktok", "facebook", "twitter", "snapchat"],
            "GAME": ["steam", "valorant", "riot", "roblox", "epic games", "pubg"],
            "CRYPTO": ["binance", "metamask", "trust wallet", "rollercoin"]
        }

        # İçerik Analizi
        for item in mail_items:
            txt = item.get_text().strip()
            txt_lower = txt.lower()
            
            # Etiketle
            for cat, words in keywords.items():
                if any(w in txt_lower for w in words):
                    if cat not in tags: tags.append(cat)
                    msgs.append(txt) # Detay ekle
        
        # Eğer sayfanın tamamında kelime geçiyorsa ama div bulamadıysak (Garanti)
        if not tags:
            for cat, words in keywords.items():
                if any(w in text_lower for w in words):
                    tags.append(cat)
                    msgs.append("Başlık Alınamadı (İçerikte Var)")

        if tags:
            return "HIT", {"tags": list(set(tags)), "msgs": msgs[:3]}
        
        # Mail var ama bizim aradığımız değil
        if mail_items or "lms" in text_lower:
            return "BAD", "Değersiz Mail"
            
        return "EMPTY", "Boş (Görünürde)"

    except Exception as e: return "ERROR", str(e)

# ==================== BOT ====================
@bot.on_message(filters.command("start"))
async def start(c, m):
    uid = m.from_user.id
    role = "👑 Admin" if uid == OWNER_ID else "👤 Kullanıcı"
    await m.reply(f"🔥 **V7 Final Hunter**\nRol: {role}\n\n`/random` veya Dosya at.")

@bot.on_message(filters.command("random"))
async def random_scan(client, message):
    user_id = message.from_user.id
    allowed, remaining = check_user_rights(user_id)
    
    if not allowed: await message.reply("⛔ Hakkın bitti."); return

    msg = await message.reply("🎲 **Aranıyor...**")
    names = ["ahmet", "mehmet", "ali", "veli", "can", "emir", "pro", "king"]
    emails = [f"{random.choice(names)}{random.randint(100, 2025)}@yopmail.com" for _ in range(10)]
    
    hits = 0
    for email in emails:
        status, res = check_yopmail_v7(email)
        
        if status == "HIT":
            hits += 1
            tags = " ".join([f"#{t}" for t in res['tags']])
            msgs = "\n".join([f"🔹 {m}" for m in res['msgs']])
            txt = f"🚨 **HIT!**\n🏷️ {tags}\n📧 `{email}`\n{msgs}\n🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})"
            await message.reply(txt, disable_web_page_preview=True)
            if user_id != OWNER_ID:
                try: await client.send_message(OWNER_ID, f"VERGİ:\n{txt}")
                except: pass
        
        elif status == "BLOCK":
            await message.reply("⛔ Captcha çıktı, 15sn bekle...")
            await asyncio.sleep(15)
        
        await asyncio.sleep(1.5)
    await msg.edit(f"🏁 Bitti. Hit: {hits}")

@bot.on_message(filters.document)
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID: await message.reply("🔒 Yasak."); return
    status_msg = await message.reply("📥 **Admin Dosyası...**")
    file_path = await message.download()
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        emails = [l.strip() for l in f if "@yopmail.com" in l]
    
    if not emails: await status_msg.edit("❌ Mail yok."); return
    hits = 0
    checked = 0
    
    for email in emails:
        status, res = check_yopmail_v7(email)
        if status == "HIT":
            hits += 1
            tags = " ".join([f"#{t}" for t in res['tags']])
            msgs = "\n".join([f"🔹 {m}" for m in res['msgs']])
            await message.reply(f"🚨 **HIT!**\n🏷️ {tags}\n📧 `{email}`\n{msgs}\n🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})", disable_web_page_preview=True)
        elif status == "BLOCK":
            await status_msg.edit(f"⚠️ Captcha! 15sn Mola...")
            await asyncio.sleep(15)
        
        checked += 1
        if checked % 20 == 0:
            try: await status_msg.edit(f"⏳ {checked}/{len(emails)} | Hit: {hits}")
            except: pass
        await asyncio.sleep(1.5)
    os.remove(file_path)
    await message.reply(f"🏁 Bitti! Toplam: {checked} | Hit: {hits}")

if __name__ == '__main__':
    keep_alive()
    bot.run()
