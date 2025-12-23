import os
import requests
import asyncio
import random
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
    "ram_hunter",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False
)

# ==================== WEB SERVER (7/24 İçin) ====================
app = Flask(__name__)
@app.route('/')
def home(): return "RAM Hunter Aktif! 🟢"

def run_web():
    # Pella/Render/Replit uyumlu port ayarı
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# ==================== RAM VERİTABANI (GEÇİCİ HAFIZA) ====================
# Bot kapanıp açılınca burası sıfırlanır. Bedava sunucularda bu işimize gelir.
# Format: {user_id: kalan_hak}
USER_LIMITS = {}

def check_user_rights(user_id):
    """Kullanıcının hakkı var mı RAM'den kontrol eder."""
    if user_id == OWNER_ID:
        return True, "Sınırsız (Admin)"
    
    # Kullanıcı ilk kez geldiyse veya bot resetlendiyse 5 hak ver
    if user_id not in USER_LIMITS:
        USER_LIMITS[user_id] = 5
        return True, 5
    
    current_rights = USER_LIMITS[user_id]
    
    if current_rights > 0:
        USER_LIMITS[user_id] -= 1
        return True, (current_rights - 1)
    else:
        return False, 0

# ==================== RANDOM MAİL ====================
def generate_random_emails(count=10):
    names = ["ahmet", "mehmet", "ayse", "fatma", "ali", "veli", "can", "cem", "kaan", "emir", "pro", "king", "baba", "oyuncu", "pubg", "brawl"]
    generated = []
    for _ in range(count):
        name = random.choice(names)
        num = random.randint(100, 2025)
        email = f"{name}{num}@yopmail.com"
        generated.append(email)
    return generated

# ==================== CHECKER (Hızlı & Proxy Yok) ====================
def check_yopmail_v3(email):
    username = email.split('@')[0]
    url = "https://yopmail.com/en/inbox"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"login": username, "p": "1", "d": "", "ctrl": "", "scrl": "", "spam": True, "v": "3.1", "yj": "V2"}
    
    try:
        with requests.Session() as s:
            r = s.post(url, data=data, headers=headers, timeout=8)
            if "To protect our service" in r.text: return "BLOCK", "IP Ban"
            if r.status_code != 200: return "ERROR", "Hata"

            soup = BeautifulSoup(r.text, "html.parser")
            subjects = soup.find_all("div", class_="lms")
            
            if not subjects: return "EMPTY", "Boş"

            tags = []
            details = []
            
            for s in subjects:
                txt = s.get_text().lower()
                
                # GENİŞ KATEGORİ LİSTESİ
                if any(x in txt for x in ["supercell", "brawl", "clash", "login code"]):
                    if "SUPERCELL" not in tags: tags.append("SUPERCELL")
                    details.append(s.get_text().strip())

                elif any(x in txt for x in ["instagram", "facebook", "tiktok", "twitter", "snapchat"]):
                    if "SOCIAL" not in tags: tags.append("SOCIAL")
                    details.append(s.get_text().strip())

                elif any(x in txt for x in ["steam", "valorant", "riot", "epic", "roblox", "minecraft"]):
                    if "GAME" not in tags: tags.append("GAME")
                    details.append(s.get_text().strip())
                
                elif any(x in txt for x in ["binance", "rollercoin", "metamask"]):
                    if "CRYPTO" not in tags: tags.append("CRYPTO")
                    details.append(s.get_text().strip())

            if tags:
                return "HIT", {"tags": tags, "msgs": list(set(details))}
            
            return "BAD", "Değersiz"

    except Exception as e: return "ERROR", str(e)

# ==================== BOT KOMUTLARI ====================
@bot.on_message(filters.command("start"))
async def start(c, m):
    uid = m.from_user.id
    role = "👑 Admin" if uid == OWNER_ID else "👤 Kullanıcı"
    limit_msg = "\n(Bot her yeniden başladığında hakların yenilenir)" if uid != OWNER_ID else ""
    
    await m.reply(
        f"💎 **Yopmail Hunter V5 (RAM)**\n"
        f"Rol: {role}\n"
        f"🎲 `/random` yaz, şansını dene!{limit_msg}"
    )

@bot.on_message(filters.command("random"))
async def random_scan(client, message):
    user_id = message.from_user.id
    
    # RAM'den limit kontrolü
    allowed, remaining = check_user_rights(user_id)
    
    if not allowed:
        await message.reply("⛔ **Hakkın Bitti!**\nAdmin ile görüş veya botun resetlenmesini bekle.")
        return

    msg_txt = "🎲 **Şansına Bakılıyor...**"
    if user_id != OWNER_ID: msg_txt += f"\n(Kalan: {remaining})"
    
    status_msg = await message.reply(msg_txt)
    
    emails = generate_random_emails(10)
    hits = 0
    
    for email in emails:
        status, result = check_yopmail_v3(email)
        
        if status == "HIT":
            hits += 1
            tags_str = " ".join([f"#{t}" for t in result['tags']])
            msgs_str = "\n".join([f"🔹 {msg[:40]}..." for msg in result['msgs'][:2]])
            
            hit_msg = (
                f"🚨 **ŞANSINA HIT!**\n"
                f"🏷️ {tags_str}\n"
                f"📧 `{email}`\n"
                f"{msgs_str}\n"
                f"🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})"
            )
            
            await message.reply(hit_msg, disable_web_page_preview=True)
            
            # ADMİNE VERGİ (Sessizce gönder)
            if user_id != OWNER_ID:
                try:
                    await client.send_message(OWNER_ID, f"🕵️ **VERGİ GELDİ!**\n👤 {message.from_user.first_name}\n{hit_msg}", disable_web_page_preview=True)
                except: pass
        
        elif status == "BLOCK":
            await message.reply("⛔ IP Ban, 10sn mola...")
            await asyncio.sleep(10)
            
        await asyncio.sleep(1.5)
        
    await status_msg.edit(f"🏁 **Bitti!**\nHit: {hits}")

@bot.on_message(filters.document)
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID:
        await message.reply("🔒 **Dosya Yasak!** Sadece Admin atabilir.")
        return

    status_msg = await message.reply("📥 **Admin Dosyası Taranıyor...**")
    file_path = await message.download()
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        emails = [line.strip() for line in f.readlines() if "@yopmail.com" in line]
    
    if not emails: await status_msg.edit("❌ Mail yok."); return

    hits = 0
    checked = 0
    
    for email in emails:
        status, result = check_yopmail_v3(email)
        
        if status == "HIT":
            hits += 1
            tags_str = " ".join([f"#{t}" for t in result['tags']])
            msgs_str = "\n".join([f"🔹 {msg[:40]}..." for msg in result['msgs'][:2]])
            await message.reply(
                f"🚨 **ADMİN HIT!**\n🏷️ {tags_str}\n📧 `{email}`\n{msgs_str}\n🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})",
                disable_web_page_preview=True
            )
        
        elif status == "BLOCK":
            await status_msg.edit(f"⚠️ Engel! 15sn Mola... Hit: {hits}")
            await asyncio.sleep(15)

        checked += 1
        if checked % 20 == 0:
            try: await status_msg.edit(f"⏳ {checked}/{len(emails)} | Hit: {hits}")
            except: pass
        await asyncio.sleep(1.5)

    os.remove(file_path)
    await message.reply(f"🏁 **Bitti!** Toplam: {checked} | Hit: {hits}")

if __name__ == '__main__':
    keep_alive()
    bot.run()
