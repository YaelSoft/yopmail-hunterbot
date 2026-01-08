import os
import logging
import asyncio
import random
import time
import math
import cloudscraper 
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, UsernameInvalidError, ChannelPrivateError

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

DEFAULT_TARGET_ID = int(os.environ.get("TARGET_GROUP_ID", -1003598285370))

# Loglama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TurboScraper")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Turbo Bot Online 🚀"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Global Durum
CURRENT_CONFIG = {
    "target_id": DEFAULT_TARGET_ID,
    "is_running": False,
    "current_url": None
}

HISTORY_FILE = "sent_links.txt"

# Topic Haritası (Senin ID'ler)
TOPIC_MAP = {
    "yazilim": 2, "ticaret": 4, "kripto": 51, 
    "haber": 8, "ifsa": 10, "random": 1
}

KEYWORDS = {
    "yazilim": ["java", "python", "kodlama", "yazılım", "hack", "script", "php", "bot", "developer"],
    "ticaret": ["satış", "fiyat", "dolap", "letgo", "indirim", "kupon", "ticaret", "pazar", "market", "toptan", "2.el", "sahibinden"],
    "kripto": ["bitcoin", "btc", "eth", "coin", "borsa", "analiz", "forex", "usdt", "mining"],
    "haber": ["sondakika", "haber", "gündem", "siyaset", "gazete"],
    "ifsa": ["link", "arsiv", "twerk", "tiktok", "onlyfans", "yetiskin", "nsfw", "18+", "kız", "liseli"]
}

# Clientlar
bot = TelegramClient("manager_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
if SESSION_STRING:
    userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    userbot = TelegramClient("worker_userbot", API_ID, API_HASH)

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

def make_progress_bar(current, total, length=10):
    """Görsel İlerleme Çubuğu Oluşturur"""
    if total == 0: total = 1
    percent = current / total
    filled_length = int(length * percent)
    bar = "█" * filled_length + "░" * (length - filled_length)
    return f"[{bar}] %{int(percent * 100)}"

# ==================== GÜÇLENDİRİLMİŞ SCRAPER (TÜRKÇE HEADER) ====================

def scrape_site(url):
    links = []
    
    # Cloudscraper ayarları
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
    )

    # TÜRKÇE HEADERLAR (403/404 Çözümü)
    headers = {
        "User-Agent": UserAgent().random,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com.tr/",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        logger.info(f"🥷 Siteye sızılıyor: {url}")
        response = scraper.get(url, headers=headers, timeout=30)
        
        if response.status_code != 200:
            logger.error(f"❌ Erişim hatası: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Link Avcısı
        found_raw = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "t.me/" in href and "joinchat" not in href:
                found_raw.append(href)
        
        # Buton Avcısı
        for btn in soup.select("a.btn, a.button, div.button, a.tg-btn"):
             href = btn.get("href")
             if href and "t.me/" in href:
                 found_raw.append(href)

        # Temizle ve Eşsizleştir
        for link in found_raw:
            clean = link.split("?")[0].strip()
            if clean not in links: links.append(clean)

        random.shuffle(links)
        return links

    except Exception as e:
        logger.error(f"❌ Scrape patladı: {e}")
        return []

async def process_link(link):
    try:
        username = link.split("t.me/")[-1].replace("@", "")
        if not username: return False

        entity = await userbot.get_entity(username)
        real_title = entity.title or "İsimsiz"
        real_bio = getattr(entity, 'about', '') or ""
        
        cat_name, topic_id = determine_topic(real_title, real_bio)
        
        msg = (
            f"🔍 **Grup Analiz Edildi**\n\n"
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
        save_history(link) # Bozuk linki kaydet ki bir daha denemesin
        return False
    except FloodWaitError as e:
        logger.warning(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds + 10)
        return False
    except Exception as e:
        logger.error(f"Hata: {e}")
        return False

# ==================== GÜVENLİ GÖREV YÖNETİCİSİ (SİGORTALI) ====================

async def scraper_task(status_msg):
    global CURRENT_CONFIG
    
    # Hata sayacı (Sigorta)
    consecutive_errors = 0 
    MAX_RETRIES = 3  # Kaç kere üst üste hata verirse dursun?

    await status_msg.edit(f"🚀 **Sistem Başlatıldı!**\nHedef: `{CURRENT_CONFIG['current_url']}`")
    
    while CURRENT_CONFIG["is_running"]:
        try:
            # 1. TARAMA AŞAMASI
            await status_msg.edit(f"🌍 **Siteye Bağlanılıyor...**\n`{CURRENT_CONFIG['current_url']}`\n\n_Deneme: {consecutive_errors + 1}/{MAX_RETRIES}_")
            
            links = scrape_site(CURRENT_CONFIG["current_url"])
            history = load_history()
            
            # --- SİGORTA KONTROLÜ ---
            if not links:
                consecutive_errors += 1
                logger.warning(f"⚠️ Hata Sayacı: {consecutive_errors}/{MAX_RETRIES}")
                
                if consecutive_errors >= MAX_RETRIES:
                    # FİŞİ ÇEKME ANI
                    CURRENT_CONFIG["is_running"] = False
                    error_msg = (
                        f"🛑 **ACİL DURDURMA!**\n\n"
                        f"Hedef site ({CURRENT_CONFIG['current_url']}) üst üste {MAX_RETRIES} kez yanıt vermedi veya link bulunamadı.\n"
                        f"Bot kendini korumaya aldı ve kapandı."
                    )
                    await status_msg.edit(error_msg)
                    await bot.send_message(OWNER_ID, error_msg)
                    return # Fonksiyondan komple çık
                
                # Henüz limit dolmadıysa bekle ve tekrar dene
                await status_msg.edit(f"⚠️ **Hata/Link Yok!**\nSite yanıt vermedi ({consecutive_errors}/{MAX_RETRIES}).\n2 dakika bekleniyor...")
                await asyncio.sleep(120) 
                continue
            
            # Eğer buraya geldiyse link bulmuştur, sayacı sıfırla
            consecutive_errors = 0
            
            new_links = [l for l in links if l not in history]
            
            if not new_links:
                await status_msg.edit(f"💤 **Taze Link Yok.**\nSite çalışıyor ama yeni grup düşmemiş.\n2 dakika mola...")
                await asyncio.sleep(120) 
                continue
            
            total_links = len(new_links)
            success_count = 0
            
            # 2. İŞLEME AŞAMASI
            for i, link in enumerate(new_links, 1):
                if not CURRENT_CONFIG["is_running"]: break
                
                if i % 3 == 1 or i == total_links:
                    bar = make_progress_bar(i, total_links)
                    await status_msg.edit(
                        f"⚙️ **İşleniyor...**\n{bar}\n"
                        f"🔢 `{i}/{total_links}` | ✅ `{success_count}`"
                    )
                
                success = await process_link(link)
                
                if success:
                    success_count += 1
                    wait = random.randint(30, 60)
                    await asyncio.sleep(wait)
                else:
                    await asyncio.sleep(5)

            await status_msg.edit(f"🏁 **Tur Tamamlandı!**\nToplam `{success_count}` grup eklendi.\n10 dakika mola...")
            await asyncio.sleep(600)
            
        except Exception as e:
            logger.error(f"Kritik Hata: {e}")
            consecutive_errors += 1 # Kritik hatayı da sayaca ekle
            await status_msg.edit(f"⚠️ **Yazılım Hatası:** {e}\nTekrar deneniyor...")
            await asyncio.sleep(60)
    
    await bot.send_message(OWNER_ID, "🛑 **Tarama Durduruldu.**")

# ==================== KOMUTLAR ====================

@bot.on(events.NewMessage(pattern='/start', from_users=OWNER_ID))
async def start_cmd(event):
    await event.respond("👋 **Turbo Link Avcısı**\n\n`/basla <URL>`\n`/hedef <ID>`\n`/dur`")

@bot.on(events.NewMessage(pattern='/hedef', from_users=OWNER_ID))
async def set_target_cmd(event):
    try:
        CURRENT_CONFIG["target_id"] = int(event.message.text.split()[1])
        await event.respond(f"✅ Hedef: `{CURRENT_CONFIG['target_id']}`")
    except: await event.respond("❌ Hata.")

@bot.on(events.NewMessage(pattern='/basla', from_users=OWNER_ID))
async def start_scrape_cmd(event):
    if CURRENT_CONFIG["is_running"]: await event.respond("⚠️ Çalışıyor zaten."); return
    try:
        url = event.message.text.split()[1]
        CURRENT_CONFIG["current_url"] = url
        CURRENT_CONFIG["is_running"] = True
        status = await event.respond("⏳ **Başlatılıyor...**")
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
