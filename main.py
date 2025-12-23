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

# ==================== DÜZELTİLMİŞ CHECKER (Cookies Fix) ====================
def check_yopmail_v3(email):
    username = email.split('@')[0]
    
    # 1. Adım: Önce Ana Sayfaya Gir (Çerezleri Al)
    main_url = "https://yopmail.com/en/"
    inbox_url = "https://yopmail.com/en/inbox"
    
    # Masaüstü Chrome Taklidi (En Sağlamı)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://yopmail.com/en/",
        "Origin": "https://yopmail.com",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    try:
        # Session açıyoruz (Çerezleri hafızada tutsun diye)
        with requests.Session() as s:
            # A) Önce Ana Sayfaya "Selam" ver
            s.get(main_url, headers=headers, timeout=5)
            
            # B) Şimdi Kutuya Gir
            data = {
                "login": username,
                "p": "1", # Sayfa 1
                "d": "",
                "ctrl": "",
                "scrl": "",
                "spam": True, # Spamları da göster
                "yj": "V2",   # Yopmail versiyonu
                "v": "3.1"
            }
            
            r = s.post(inbox_url, data=data, headers=headers, timeout=8)
            
            # Engel Kontrolü
            if r.status_code != 200: return "ERROR", f"Kod: {r.status_code}"
            if "To protect our service" in r.text or "Captcha" in r.text:
                return "BLOCK", "IP Ban"

            # HTML Analizi
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Yopmail Masaüstü sürümünde mailler 'm' veya 'lms' class'ında olur
            # İkisini de kontrol edelim garanti olsun
            subjects = soup.find_all("div", class_="lms") # Konu Başlığı
            senders = soup.find_all("span", class_="lmf") # Gönderen
            
            if not subjects:
                # Belki yapı farklıdır, 'm' classına bakalım (Mobil görünüm için)
                subjects = soup.find_all("div", class_="m")

            if not subjects:
                if "No mail for" in r.text or "is empty" in r.text:
                    return "EMPTY", "Boş"
                # Eğer 'Boş' yazmıyorsa ama mail de bulamadıysa, HTML yüklenemedi demektir.
                # Debug için html'in bir kısmını yazdırabilirsin: print(r.text[:500])
                return "EMPTY", "Görünürde Boş"

            # KATEGORİ TARAMASI
            tags = []
            details = []
            
            # Hem başlıkları hem gönderenleri birleştirip tarayalım (Daha garanti)
            all_text = r.text.lower()
            
            # 1. SUPERCELL (Brawl Stars, Clash)
            if "supercell" in all_text or "brawl" in all_text or "clash" in all_text or "id code" in all_text:
                tags.append("SUPERCELL")

            # 2. SOCIAL (Instagram, TikTok)
            if "instagram" in all_text or "tiktok" in all_text or "facebook" in all_text or "twitter" in all_text:
                tags.append("SOCIAL")

            # 3. GAMES (Steam, Valorant)
            if "steam" in all_text or "riot" in all_text or "valorant" in all_text or "epic games" in all_text:
                tags.append("GAME")

            # Detayları çek (İlk 3 mail başlığı)
            for s in subjects[:3]:
                details.append(s.get_text().strip())

            if tags:
                return "HIT", {"tags": list(set(tags)), "msgs": details}
            
            # Eğer etiket yoksa ama mail varsa
            return "BAD", "Mail Var Ama Değersiz"

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
