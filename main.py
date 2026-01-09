import os
import logging
import asyncio
import re
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from curl_cffi import requests as cureq # Bot engeli aşan özel kütüphane

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
def home(): return "Bot Manuel Modda 🟢"
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

# ==================== SAYFA KAZIYICI (SADECE AL VE GİT) ====================

def scrape_page_source(url):
    """
    Verilen URL'ye gider, HTML kodunu indirir ve t.me linklerini Regex ile çeker.
    """
    found_links = set()
    
    # Regex: t.me ile başlayan her şeyi yakalar (joinchat, +, normal username)
    # En agresif regex budur.
    regex = re.compile(r'https?://t\.me/(?:joinchat/|\+)?[\w\d_\-]+')

    try:
        logger.info(f"🌍 Sayfaya gidiliyor: {url}")
        
        # Chrome taklidi yaparak siteye gir (Bing Engelini Aşmak İçin)
        response = cureq.get(url, impersonate="chrome110", timeout=15)
        
        if response.status_code == 200:
            content = response.text
            # Sayfanın tamamında "t.me" ara
            matches = regex.findall(content)
            
            for match in matches:
                # Temizlik
                clean_link = match.strip().rstrip('.,")\'')
                
                # Yasaklı kelime filtresi (İsteğe bağlı, şimdilik kapattım her şeyi alsın)
                ignore = ["share", "socks", "proxy", "contact", "setlanguage", "iv"]
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
        "👋 **Manuel Link Toplayıcı**\n\n"
        "1️⃣ `/hedef <GRUP_LINKI>` -> Önce linklerin atılacağı yeri seç.\n"
        "2️⃣ `/tara <URL>` -> Bing veya Google arama linkini yapıştır, ben içini boşaltayım."
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
        # Linki al (Mesajdaki 2. parça ve sonrası, bazen link uzun olabilir)
        url_to_scrape = event.message.text.split(" ", 1)[1]
        
        msg = await event.respond(f"⏳ **Bağlanılıyor:** {url_to_scrape}\nLütfen bekle...")
        
        # İşlemi başlat
        links = scrape_page_source(url_to_scrape)
        
        if not links:
            await msg.edit("❌ Bu sayfadan link çıkarılamadı.\nYa sayfa bot korumalı ya da link yok.")
            return

        await msg.edit(f"✅ **{len(links)}** adet link bulundu! Gönderiliyor...")
        
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
                    await asyncio.sleep(2) # Flood yememek için 2 saniye bekle
                except Exception as e:
                    logger.error(f"Gönderme hatası: {e}")
        
        await client.send_message(
            entity=CONFIG["target_chat_id"],
            message=f"🏁 **İşlem Tamamlandı!**\nToplam {count} yeni link eklendi.",
            reply_to=CONFIG["target_topic_id"]
        )

    except IndexError:
        await event.respond("❌ Link girmedin.\nÖrnek: `/tara https://www.bing.com/search?q=...`")
    except Exception as e:
        await event.respond(f"⚠️ Hata: {e}")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
