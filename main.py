import os
import logging
import asyncio
import re
import time
import requests
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from curl_cffi import requests as cureq # Cloudflare Delici

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "")
GOOG_CX = os.environ.get("GOOG_CX", "")

# Google'dan kaç sayfa sonuç çeksin? (Her sayfa 10 site demek)
SAYFA_SAYISI = 8 
HEDEF_LINK_SAYISI = 150

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("DeepHunter")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Balyoz Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("deep_hunter", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Hafıza
CONFIG = {"target_chat_id": None, "target_topic_id": None, "is_running": False}
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

# ==================== SİTE İÇİ KAZIYICI (CLOUDFLARE GEÇER) ====================

def dig_inside_page(url):
    """
    Tgstat, Telemetr gibi sitelere Chrome taklidi yaparak girer,
    sayfa kaynağındaki TÜM t.me linklerini söküp alır.
    """
    found = set()
    # Regex: t.me/xxx, t.me/joinchat/xxx, t.me/+xxx hepsini alır
    regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
    
    try:
        # Chrome 124 taklidi yapıyoruz (En güncel tarayıcı gibi)
        response = cureq.get(url, impersonate="chrome124", timeout=10)
        
        if response.status_code == 200:
            content = response.text
            matches = regex.findall(content)
            
            for match in matches:
                clean = match.strip().rstrip('.,"\';<>&)')
                # Gereksiz sistem linklerini ele
                ignore = ["share", "socks", "proxy", "contact", "setlanguage", "iv", "telegram"]
                if any(x in clean.lower() for x in ignore): continue
                
                found.add(clean)
                logger.info(f"⛏️ SİTE İÇİNDEN ALINDI: {clean}")
        else:
            logger.warning(f"❌ Siteye girilemedi ({response.status_code}): {url}")
            
    except Exception as e:
        logger.error(f"❌ Kazı Hatası ({url}): {e}")
        
    return list(found)

# ==================== GOOGLE API + DERİN KAZI ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    
    # Sadece büyük veritabanlarını hedefliyoruz
    target_sites = "site:tgstat.com OR site:telemetr.io OR site:hottg.com OR site:telegramindex.com"
    query = f"({target_sites}) {keyword}"
    
    for page in range(1, SAYFA_SAYISI + 1):
        if not CONFIG["is_running"]: break
        if toplanan >= HEDEF_LINK_SAYISI: break
        
        try:
            await status_msg.edit(f"🔍 **Google'da Dizinler Bulunuyor...**\nSayfa: {page}\nLinkler Toplanıyor: {toplanan}")
        except: pass
        
        # 1. Google'dan Site Listesini Al
        start_index = ((page - 1) * 10) + 1
        api_url = "https://www.googleapis.com/customsearch/v1"
        params = {'key': GOOG_API_KEY, 'cx': GOOG_CX, 'q': query, 'start': start_index, 'num': 10}
        
        candidate_urls = []
        try:
            resp = requests.get(api_url, params=params)
            data = resp.json()
            if "items" in data:
                for item in data['items']:
                    candidate_urls.append(item['link'])
        except Exception as e:
            logger.error(f"Google API Hatası: {e}")
            
        if not candidate_urls:
            logger.info("Bu sayfada site bulunamadı.")
            await asyncio.sleep(2)
            continue
            
        # 2. Bulunan Sitelere TEK TEK GİR (Deep Digging)
        for site_url in candidate_urls:
            if not CONFIG["is_running"]: break
            
            # Siteye gir ve içini boşalt
            extracted_links = dig_inside_page(site_url)
            
            if not extracted_links:
                logger.info(f"⚠️ Boş çıktı: {site_url}")
            
            for link in extracted_links:
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
                        toplanan += 1
                        await asyncio.sleep(1.5) # Flood yememek için
                    except Exception as e:
                        logger.error(f"Gönderim hatası: {e}")
            
            # Diğer siteye geçmeden az bekle (Cloudflare kill switch yememek için)
            await asyncio.sleep(2)

    await status_msg.respond(f"🏁 **Operasyon Bitti!**\nToplam {toplanan} link söküldü.")
    CONFIG["is_running"] = False

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond("👋 **Derin Dizin Avcısı**\n\nGoogle'dan site bulur -> İçine girer -> Linkleri söker.\n\n1️⃣ `/hedef <LİNK>`\n2️⃣ `/basla <KELIME>`")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Tamam.")
        else: await event.respond("❌ Hatalı Link.")
    except: await event.respond("❌ Link girmelisin.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["is_running"] = True
        msg = await event.respond(f"🚀 **{kw}** için dizinlere giriliyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
