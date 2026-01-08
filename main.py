import os
import logging
import asyncio
import requests
import random
from bs4 import BeautifulSoup
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UsernameInvalidError, ChannelPrivateError

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
# BotFather'dan aldığın Token (Seninle konuşacak olan)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Userbot Session (İşi yapacak olan)
SESSION_STRING = os.environ.get("SESSION_STRING", "")
# Bu botu sadece sen yönet (Senin ID'n)
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# Varsayılan Hedef (Değiştirilebilir)
DEFAULT_TARGET_ID = int(os.environ.get("TARGET_GROUP_ID", -100123456789))

# Loglama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ScraperManager")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Manager Bot Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# ==================== GLOBAL DEĞİŞKENLER ====================
# Bot çalışırken bu ayarları hafızada tutar
CURRENT_CONFIG = {
    "target_id": DEFAULT_TARGET_ID,
    "is_running": False,
    "current_url": None
}

HISTORY_FILE = "sent_links.txt"

# Topic Haritası (Senin grubunun topic ID'leri)
# Burayı kendi grubuna göre bir kez ayarla, rahat et.
TOPIC_MAP = {
    "yazilim": 2,      
    "ticaret": 4,      
    "kripto": 51,      
    "haber": 8,        
    "ifsa": 10,        
    "random": 1  # Hiçbiri uymazsa buraya       
}

KEYWORDS = {
    "yazilim": ["java", "python", "kodlama", "yazılım", "hack", "script", "php", "bot", "developer"],
    "ticaret": ["satış", "fiyat", "dolap", "letgo", "indirim", "kupon", "ticaret", "pazar", "market", "toptan"],
    "kripto": ["bitcoin", "btc", "eth", "coin", "borsa", "analiz", "forex", "usdt", "mining"],
    "haber": ["sondakika", "haber", "gündem", "siyaset", "gazete"],
    "ifsa": ["link", "arsiv", "twerk", "tiktok", "onlyfans", "yetiskin", "nsfw", "18+"]
}

# ==================== CLIENT TANIMLAMA ====================
# 1. Yönetici Bot (BotFather)
bot = TelegramClient("manager_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# 2. İşçi Userbot (Session)
userbot = TelegramClient("worker_userbot", API_ID, API_HASH, session_string=SESSION_STRING)

# ==================== YARDIMCI FONKSİYONLAR ====================

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")

def determine_topic(title, bio):
    full_text = f"{title} {bio}".lower()
    for cat, keys in KEYWORDS.items():
        for key in keys:
            if key in full_text:
                return cat, TOPIC_MAP.get(cat)
    return "Diğer", TOPIC_MAP["random"]

# ==================== SCRAPER MOTORU ====================

def scrape_site(url):
    """Verilen URL'deki telegram linklerini çeker"""
    links = []
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        logger.info(f"Site taranıyor: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "t.me/" in href and "joinchat" not in href:
                clean = href.split("?")[0].strip()
                if clean not in links:
                    links.append(clean)
        
        random.shuffle(links)
        return links
    except Exception as e:
        logger.error(f"Scrape hatası: {e}")
        return []

async def process_link(link):
    """Userbot ile linki analiz eder ve gönderir"""
    try:
        username = link.split("t.me/")[-1].replace("@", "")
        if not username: return False

        # Telegram'dan bilgi çek
        entity = await userbot.get_entity(username)
        
        real_title = entity.title or "İsimsiz"
        real_bio = getattr(entity, 'about', '') or ""
        
        # Kategori belirle
        cat_name, topic_id = determine_topic(real_title, real_bio)
        
        msg = (
            f"🔍 **Yeni Grup Bulundu!**\n\n"
            f"📛 **İsim:** {real_title}\n"
            f"📂 **Kategori:** #{cat_name}\n"
            f"📝 **Bio:** {real_bio[:100]}...\n\n"
            f"🔗 **Link:** {link}"
        )
        
        # Hedefe gönder
        await userbot.send_message(
            CURRENT_CONFIG["target_id"],
            msg,
            reply_to=topic_id,
            link_preview=False
        )
        
        save_history(link)
        logger.info(f"Gönderildi: {real_title}")
        return True

    except (UsernameInvalidError, ChannelPrivateError):
        save_history(link) # Bozuk linki bir daha deneme
        return False
    except FloodWaitError as e:
        logger.warning(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds + 10)
        return False
    except Exception as e:
        logger.error(f"Hata: {e}")
        return False

# ==================== ANA İŞ DÖNGÜSÜ ====================

async def scraper_task(status_msg):
    """Arka planda sürekli çalışacak görev"""
    global CURRENT_CONFIG
    
    await status_msg.edit(f"🚀 **Tarama Başladı!**\n\n🎯 Hedef Site: `{CURRENT_CONFIG['current_url']}`\n📂 Hedef Grup ID: `{CURRENT_CONFIG['target_id']}`")
    
    while CURRENT_CONFIG["is_running"]:
        try:
            links = scrape_site(CURRENT_CONFIG["current_url"])
            history = load_history()
            
            new_links = [l for l in links if l not in history]
            
            if not new_links:
                logger.info("Yeni link yok, bekleniyor...")
                await asyncio.sleep(60) # 1 dk bekle tekrar dene
                continue
            
            count = 0
            for link in new_links:
                if not CURRENT_CONFIG["is_running"]: break
                
                success = await process_link(link)
                
                if success:
                    count += 1
                    wait = random.randint(30, 60)
                    await asyncio.sleep(wait)
                    
                    # 10 linkte bir rapor ver (Opsiyonel, log kirliliği olmasın diye kapattım)
                    # await bot.send_message(OWNER_ID, f"✅ {count} adet link işlendi.")

            logger.info("Liste bitti, 10 dk mola...")
            await asyncio.sleep(600)
            
        except Exception as e:
            logger.error(f"Döngü hatası: {e}")
            await asyncio.sleep(60)
    
    await bot.send_message(OWNER_ID, "🛑 **Tarama İşlemi Durduruldu.**")

# ==================== BOT KOMUTLARI (CONTROLLER) ====================

@bot.on(events.NewMessage(pattern='/start', from_users=OWNER_ID))
async def start_cmd(event):
    await event.respond(
        "👋 **Link Scraper Manager**\n\n"
        "Komutlar:\n"
        "🔹 `/hedef -100xxxx` -> Hedef grubu değiştir.\n"
        "🔹 `/basla https://site.com` -> Taramayı başlat.\n"
        "🔹 `/dur` -> Taramayı durdur.\n"
        "🔹 `/durum` -> Şu anki ayarları gör."
    )

@bot.on(events.NewMessage(pattern='/hedef', from_users=OWNER_ID))
async def set_target_cmd(event):
    try:
        new_id = int(event.message.text.split()[1])
        CURRENT_CONFIG["target_id"] = new_id
        await event.respond(f"✅ Hedef grup ayarlandı: `{new_id}`")
    except:
        await event.respond("❌ Hatalı format. Örn: `/hedef -100123456789`")

@bot.on(events.NewMessage(pattern='/basla', from_users=OWNER_ID))
async def start_scrape_cmd(event):
    if CURRENT_CONFIG["is_running"]:
        await event.respond("⚠️ Zaten çalışıyor!")
        return
        
    try:
        url = event.message.text.split()[1]
        CURRENT_CONFIG["current_url"] = url
        CURRENT_CONFIG["is_running"] = True
        
        status_msg = await event.respond("⏳ Başlatılıyor...")
        
        # Görevi arka plana at
        asyncio.create_task(scraper_task(status_msg))
        
    except IndexError:
        await event.respond("❌ Link girmelisin. Örn: `/basla https://tgram.io/tr/groups`")

@bot.on(events.NewMessage(pattern='/dur', from_users=OWNER_ID))
async def stop_scrape_cmd(event):
    if not CURRENT_CONFIG["is_running"]:
        await event.respond("⚠️ Zaten durmuş.")
        return
    
    CURRENT_CONFIG["is_running"] = False
    await event.respond("🛑 Durdurma sinyali gönderildi. Mevcut işlem bitince duracak.")

@bot.on(events.NewMessage(pattern='/durum', from_users=OWNER_ID))
async def status_cmd(event):
    status = "Çalışıyor 🟢" if CURRENT_CONFIG["is_running"] else "Durdu 🔴"
    await event.respond(
        f"📊 **Sistem Durumu**\n\n"
        f"Durum: {status}\n"
        f"Hedef Grup: `{CURRENT_CONFIG['target_id']}`\n"
        f"Hedef Site: `{CURRENT_CONFIG['current_url']}`"
    )

# ==================== BAŞLATMA ====================
if __name__ == '__main__':
    keep_alive()
    logger.info("Sistem başlatılıyor...")
    
    # Userbot'u başlat
    userbot.start()
    
    # Yönetici Bot'u başlat (Loop kilitler, en sonda olmalı)
    bot.run_until_disconnected()
