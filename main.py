import os
import logging
import asyncio
import random
import cloudscraper # SİHİRLİ KÜTÜPHANE BU
from fake_useragent import UserAgent # MASKEMİZ BU
from bs4 import BeautifulSoup
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, UsernameInvalidError, ChannelPrivateError

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

DEFAULT_TARGET_ID = int(os.environ.get("TARGET_GROUP_ID", -100123456789))

# Loglama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StealthScraper")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Stealth Bot Online 🥷"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Global Ayarlar
CURRENT_CONFIG = {
    "target_id": DEFAULT_TARGET_ID,
    "is_running": False,
    "current_url": None
}
HISTORY_FILE = "sent_links.txt"

# Topic Haritası (Kendi ID'lerin)
TOPIC_MAP = {
    "yazilim": 2, "ticaret": 4, "kripto": 51, 
    "haber": 8, "ifsa": 10, "random": 1
}

KEYWORDS = {
    "yazilim": ["java", "python", "kodlama", "yazılım", "hack", "script", "php", "bot", "developer"],
    "ticaret": ["satış", "fiyat", "dolap", "letgo", "indirim", "kupon", "ticaret", "pazar", "market", "toptan"],
    "kripto": ["bitcoin", "btc", "eth", "coin", "borsa", "analiz", "forex", "usdt", "mining"],
    "haber": ["sondakika", "haber", "gündem", "siyaset", "gazete"],
    "ifsa": ["link", "arsiv", "twerk", "tiktok", "onlyfans", "yetiskin", "nsfw", "18+"]
}

# Bot Tanımları
bot = TelegramClient("manager_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
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
            if key in full_text: return cat, TOPIC_MAP.get(cat)
    return "Diğer", TOPIC_MAP["random"]

# ==================== ZIRHLI SCRAPER (GÜNCELLENDİ) ====================

def scrape_site(url):
    """Cloudscraper ile korumalı sitelerden link çeker"""
    links = []
    
    # 1. Maskeleme (Rastgele User-Agent)
    ua = UserAgent()
    random_ua = ua.random
    logger.info(f"🎭 Maske Takıldı: {random_ua}")
    
    # 2. Scraper Oluştur
    # browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    # Bu ayar Cloudflare'e "Ben Windows kullanan Chrome tarayıcısıyım" der.
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

    try:
        logger.info(f"🥷 Siteye sızılıyor: {url}")
        
        # Requests yerine scraper.get kullanıyoruz
        response = scraper.get(url, timeout=20)
        
        if response.status_code != 200:
            logger.error(f"❌ Erişim engellendi! Kod: {response.status_code}")
            return []
        
        logger.info("✅ Siteye giriş başarılı! Linkler toplanıyor...")
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Telegram linklerini ayıkla
            if "t.me/" in href and "joinchat" not in href:
                clean = href.split("?")[0].strip()
                if clean not in links:
                    links.append(clean)
        
        # Ekstra: Butonların içindeki linkleri de ara (Tgram.io gibi siteler için)
        for btn in soup.select("a.btn, a.button, div.button"):
             href = btn.get("href")
             if href and "t.me/" in href:
                 clean = href.split("?")[0].strip()
                 if clean not in links:
                     links.append(clean)

        random.shuffle(links)
        return links

    except Exception as e:
        logger.error(f"❌ Scrape patladı: {e}")
        return []

async def process_link(link):
    """Userbot ile linki analiz eder ve gönderir"""
    try:
        username = link.split("t.me/")[-1].replace("@", "")
        if not username: return False

        entity = await userbot.get_entity(username)
        real_title = entity.title or "İsimsiz"
        real_bio = getattr(entity, 'about', '') or ""
        
        cat_name, topic_id = determine_topic(real_title, real_bio)
        
        msg = (
            f"🔍 **Yeni Grup Tespit Edildi**\n\n"
            f"📛 **İsim:** {real_title}\n"
            f"📂 **Kategori:** #{cat_name}\n"
            f"📝 **Bio:** {real_bio[:100]}...\n\n"
            f"🔗 **Link:** {link}"
        )
        
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
        save_history(link)
        return False
    except FloodWaitError as e:
        logger.warning(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds + 10)
        return False
    except Exception as e:
        logger.error(f"Hata: {e}")
        return False

# ==================== DÖNGÜ VE KOMUTLAR ====================

async def scraper_task(status_msg):
    global CURRENT_CONFIG
    await status_msg.edit(f"🚀 **Tarama Başladı!**\n\nHedef: `{CURRENT_CONFIG['current_url']}`\nMod: `Cloudflare Bypass`")
    
    while CURRENT_CONFIG["is_running"]:
        try:
            links = scrape_site(CURRENT_CONFIG["current_url"])
            history = load_history()
            
            new_links = [l for l in links if l not in history]
            
            if not new_links:
                logger.info("Yeni link yok, sayfa yenileniyor...")
                # Link yoksa bekleme süresini artır
                await asyncio.sleep(120) 
                continue
            
            logger.info(f"Bulunan Taze Link: {len(new_links)}")
            
            count = 0
            for link in new_links:
                if not CURRENT_CONFIG["is_running"]: break
                
                success = await process_link(link)
                
                if success:
                    count += 1
                    wait = random.randint(40, 80) # Güvenli aralık
                    await asyncio.sleep(wait)
            
            logger.info("Sayfa bitti, mola...")
            await asyncio.sleep(600)
            
        except Exception as e:
            logger.error(f"Döngü hatası: {e}")
            await asyncio.sleep(60)
    
    await bot.send_message(OWNER_ID, "🛑 **Tarama Durduruldu.**")

@bot.on(events.NewMessage(pattern='/start', from_users=OWNER_ID))
async def start_cmd(event):
    await event.respond("👋 **Stealth Link Hunter**\n\n`/basla <URL>`\n`/hedef <ID>`\n`/dur`")

@bot.on(events.NewMessage(pattern='/hedef', from_users=OWNER_ID))
async def set_target_cmd(event):
    try:
        CURRENT_CONFIG["target_id"] = int(event.message.text.split()[1])
        await event.respond("✅ Hedef ayarlandı.")
    except: await event.respond("❌ Hata.")

@bot.on(events.NewMessage(pattern='/basla', from_users=OWNER_ID))
async def start_scrape_cmd(event):
    if CURRENT_CONFIG["is_running"]: await event.respond("⚠️ Zaten çalışıyor!"); return
    try:
        url = event.message.text.split()[1]
        CURRENT_CONFIG["current_url"] = url
        CURRENT_CONFIG["is_running"] = True
        status = await event.respond("⏳ Cloudflare aşılıyor...")
        asyncio.create_task(scraper_task(status))
    except: await event.respond("❌ Link gir.")

@bot.on(events.NewMessage(pattern='/dur', from_users=OWNER_ID))
async def stop_scrape_cmd(event):
    CURRENT_CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    userbot.start()
    bot.run_until_disconnected()
