import os
import logging
import asyncio
import re
import time
import urllib.parse # Şifreli Google linklerini çözmek için
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from curl_cffi import requests as cureq

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("ScraperBot")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Google Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("scraper_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Hafıza
CONFIG = {"target_chat_id": None, "target_topic_id": None}
HISTORY_FILE = "sent_links.txt"

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(f"{link}\n")

def parse_topic_link(link):
    link = link.strip().replace("https://", "").replace("t.me/", "")
    parts = link.split("/")
    try:
        if "c/" in link:
            chat_id = int("-100" + link.split("c/")[1].split("/")[0])
            topic_id = int(parts[-1])
            return chat_id, topic_id
        return None, None
    except: return None, None

# ==================== GOOGLE & BING KAZIYICI ====================

def scrape_page_source(url):
    """
    Verilen URL'ye gider, içeriği çözer (decode) ve linkleri toplar.
    """
    found_links = set()
    
    # Regex: t.me linklerini yakalar
    regex = re.compile(r'https?://t\.me/(?:joinchat/|\+)?[\w\d_\-]+')

    try:
        logger.info(f"🌍 Sayfaya gidiliyor: {url}")
        
        # Chrome taklidi yaparak siteye gir
        # headers ekledik ki Google bizi bot sanıp "Cookie sayfası"na atmasın
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7'
        }
        
        response = cureq.get(url, impersonate="chrome110", headers=headers, timeout=20)
        
        if response.status_code == 200:
            # 1. Ham içeriği al
            raw_content = response.text
            
            # 2. KRİTİK ADIM: Google'ın şifreli linklerini (%3A %2F) normal yazıya çevir
            decoded_content = urllib.parse.unquote(raw_content)
            
            # 3. Şimdi temizlenmiş metinde arama yap
            matches = regex.findall(decoded_content)
            
            for match in matches:
                clean_link = match.strip().rstrip('.,")\'<>&;') # Google bazen linkin sonuna & koyar
                
                # Yasaklı kelime filtresi
                ignore = ["share", "socks", "proxy", "contact", "setlanguage", "iv", "google", "search"]
                if any(x in clean_link for x in ignore): continue
                
                found_links.add(clean_link)
                logger.info(f"✅ BULUNDU: {clean_link}")
        else:
            logger.warning(f"❌ Siteye girilemedi! Kod: {response.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Hata oluştu: {e}")

    return list(found_links)

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond(
        "👋 **Google & Bing Avcısı**\n\n"
        "1️⃣ `/hedef <GRUP_LINKI>`\n"
        "2️⃣ `/tara <GOOGLE_LINKI>`"
    )

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Ayarlandı.")
        else: await event.respond("❌ Link Hatalı.")
    except: await event.respond("❌ Link girmelisin.")

@client.on(events.NewMessage(pattern='/tara'))
async def manual_scan(event):
    if not CONFIG["target_chat_id"]:
        await event.respond("⚠️ Önce `/hedef` belirle!")
        return

    try:
        url_to_scrape = event.message.text.split(" ", 1)[1]
        msg = await event.respond(f"⏳ **Google taranıyor...**\nLink: {url_to_scrape[:50]}...")
        
        links = scrape_page_source(url_to_scrape)
        
        if not links:
            await msg.edit("❌ Link bulunamadı. Google 'Robot musun?' kontrolüne takılmış olabilir.")
            return

        await msg.edit(f"✅ **{len(links)}** link bulundu! Atılıyor...")
        
        history = load_history()
        count = 0
        
        for link in links:
            if link not in history:
                try:
                    await client.send_message(
                        entity=CONFIG["target_chat_id"],
                        message=link,
                        reply_to=CONFIG["target_topic_id"],
                        link_preview=False
                    )
                    history.add(link)
                    save_history(link)
                    count += 1
                    await asyncio.sleep(2) 
                except Exception as e:
                    logger.error(f"Gönderme hatası: {e}")
        
        await client.send_message(
            entity=CONFIG["target_chat_id"],
            message=f"🏁 **Bitti!** Toplam {count} yeni link.",
            reply_to=CONFIG["target_topic_id"]
        )

    except IndexError:
        await event.respond("❌ Link girmedin.")
    except Exception as e:
        await event.respond(f"⚠️ Hata: {e}")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
