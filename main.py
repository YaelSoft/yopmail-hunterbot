import os
import requests
import asyncio
import random
import re
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
    "token_hunter",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
    ipv6=False
)

# ==================== WEB SERVER (7/24) ====================
app = Flask(__name__)
@app.route('/')
def home(): return "Token Hunter Aktif! 🟢"

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

# ==================== YENİ TOKENLI CHECKER ====================
def check_yopmail_v6(email):
    username = email.split('@')[0]
    
    # 1. Oturum Aç
    s = requests.Session()
    
    # Headerlar (Birebir Chrome Taklidi)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://yopmail.com/en/",
    }

    try:
        # ADIM 1: Ana Sayfaya Git ve Gizli 'yp' Kodunu Çal
        r_main = s.get("https://yopmail.com/en/", headers=headers, timeout=10)
        
        # HTML içinden 'yp' değerini bul (Regex ile)
        # Yopmail bunu <input type="hidden" id="yp" value="XXX"> diye saklar
        match = re.search(r'id="yp" value="([^"]+)"', r_main.text)
        if not match:
            return "ERROR", "Token Bulunamadı (Site Yapısı Değişmiş)"
        
        yp_token = match.group(1)
        
        # Ayrıca 'yj' versiyonunu da bulalım
        match_yj = re.search(r'id="yj" value="([^"]+)"', r_main.text)
        yj_token = match_yj.group(1) if match_yj else "V2"

        # ADIM 2: Token ile Kutuya Gir
        inbox_url = "https://yopmail.com/en/inbox"
        
        params = {
            "login": username,
            "p": "1",
            "d": "",
            "ctrl": "",
            "scrl": "",
            "spam": True,
            "yp": yp_token, # <--- İŞTE BU EKSİKTİ!
            "yj": yj_token,
            "v": "3.1"
        }
        
        # Cookie'leri ve Token'i kullanarak isteği at
        r_inbox = s.post(inbox_url, data=params, headers=headers, timeout=10)
        
        # Engel Kontrolü
        if "To protect our service" in r_inbox.text: return "BLOCK", "IP Ban"

        # HTML Analizi
        soup = BeautifulSoup(r_inbox.text, "html.parser")
        
        # Tüm metni küçük harfe çevirip tarayalım (Garanti olsun)
        page_text = r_inbox.text.lower()
        
        # Eğer sayfada "No mail for" yazıyorsa boştur
        if "no mail for" in page_text or "inbox is empty" in page_text:
            return "EMPTY", "Boş"

        # KATEGORİLER
        tags = []
        
        # 1. SUPERCELL
        if any(x in page_text for x in ["supercell", "brawl", "clash", "id code", "login code"]):
            tags.append("SUPERCELL")

        # 2. SOCIAL
        if any(x in page_text for x in ["instagram", "tiktok", "facebook", "twitter", "snapchat"]):
            tags.append("SOCIAL")

        # 3. GAME
        if any(x in page_text for x in ["steam", "valorant", "riot", "roblox", "epic games"]):
            tags.append("GAME")

        # 4. CRYPTO
        if any(x in page_text for x in ["binance", "metamask", "rollercoin"]):
            tags.append("CRYPTO")

        # Hit Kontrolü
        if tags:
            # Mail başlıklarını çekmeye çalış (Görsellik için)
            subjects = []
            for div in soup.find_all("div", class_="lms"):
                subjects.append(div.get_text().strip())
            
            return "HIT", {"tags": list(set(tags)), "msgs": subjects[:3]}
        
        # Eğer tag yok ama 'Boş' da değilse, önemsiz mail vardır
        # Bunu kullanıcıya "Boş" dememek için BAD olarak işaretliyoruz
        if "lms" in r_inbox.text or "mname" in r_inbox.text:
             return "BAD", "Değersiz Mail"
             
        # Hiçbir şey bulamadıysa
        return "EMPTY", "Boş"

    except Exception as e: return "ERROR", str(e)

# ==================== BOT ====================
@bot.on_message(filters.command("start"))
async def start(c, m):
    uid = m.from_user.id
    role = "👑 Admin" if uid == OWNER_ID else "👤 Kullanıcı"
    await m.reply(f"🔥 **Token Hunter V6**\nRol: {role}\n\n`/random` ile dene veya dosya at.")

@bot.on_message(filters.command("random"))
async def random_scan(client, message):
    user_id = message.from_user.id
    allowed, remaining = check_user_rights(user_id)
    
    if not allowed:
        await message.reply("⛔ Hakkın bitti.")
        return

    msg = await message.reply("🎲 **Aranıyor...**")
    
    # Rastgele İsim Listesi
    names = ["ahmet", "mehmet", "ali", "veli", "can", "emir", "pro", "king", "baba", "oyun"]
    emails = [f"{random.choice(names)}{random.randint(100, 2025)}@yopmail.com" for _ in range(10)]
    
    hits = 0
    
    for email in emails:
        status, res = check_yopmail_v6(email)
        
        if status == "HIT":
            hits += 1
            tags = " ".join([f"#{t}" for t in res['tags']])
            msgs = "\n".join([f"🔹 {m}" for m in res['msgs']])
            text = f"🚨 **HIT!**\n🏷️ {tags}\n📧 `{email}`\n{msgs}\n🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})"
            await message.reply(text, disable_web_page_preview=True)
            
            if user_id != OWNER_ID:
                try: await client.send_message(OWNER_ID, f"VERGİ:\n{text}")
                except: pass
                
        elif status == "BLOCK":
            await message.reply("⛔ IP Ban, bekliyorum...")
            await asyncio.sleep(15)
            
        await asyncio.sleep(1.5)
        
    await msg.edit(f"🏁 Bitti. Hit: {hits}")

@bot.on_message(filters.document)
async def handle_file(client, message):
    if message.from_user.id != OWNER_ID:
        await message.reply("🔒 Yasak.")
        return

    status_msg = await message.reply("📥 **Admin Dosyası...**")
    file_path = await message.download()
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        emails = [l.strip() for l in f if "@yopmail.com" in l]
    
    if not emails: await status_msg.edit("❌ Mail yok."); return

    hits = 0
    checked = 0
    
    for email in emails:
        status, res = check_yopmail_v6(email)
        
        if status == "HIT":
            hits += 1
            tags = " ".join([f"#{t}" for t in res['tags']])
            msgs = "\n".join([f"🔹 {m}" for m in res['msgs']])
            await message.reply(f"🚨 **HIT!**\n🏷️ {tags}\n📧 `{email}`\n{msgs}\n🔗 [Giriş](https://yopmail.com/en?login={email.split('@')[0]})", disable_web_page_preview=True)
        
        elif status == "BLOCK":
            await status_msg.edit(f"⚠️ Engel! 15sn Mola...")
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
