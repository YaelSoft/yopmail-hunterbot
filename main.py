import os
import logging
import asyncio
import re
import time
import requests # curl_cffi değil, direkt requests çünkü resmi API kullanıyoruz
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# 🔥 GOOGLE API AYARLARI (BUNLARI RENDER'DA ENVIRONMENT'A EKLE)
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "BURAYA_API_KEY_GELECEK")
GOOG_CX = os.environ.get("GOOG_CX", "BURAYA_CX_ID_GELECEK")

# KAÇ SAYFA TARASIN? (Her sayfa 10 sonuç verir. 5 sayfa = 50 sonuç)
SAYFA_SAYISI = 5 
HEDEF_LINK_SAYISI = 50

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("GoogleApiBot")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Google API Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("google_api_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

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

# ==================== GOOGLE RESMİ API ARAMASI ====================

def google_search_api(query, page=1):
    """
    Google Custom Search API kullanarak arama yapar.
    Resmi yöntem olduğu için ban yemez.
    """
    found_links = []
    
    # Google API'de her sayfa 10 sonuçtur.
    # start=1 (1. sayfa), start=11 (2. sayfa), start=21 (3. sayfa)...
    start_index = ((page - 1) * 10) + 1
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOG_API_KEY,
        'cx': GOOG_CX,
        'q': query,
        'start': start_index,
        'num': 10 # Her istekte 10 sonuç (Maksimum bu)
    }
    
    try:
        logger.info(f"🌍 Google API İsteği: Sayfa {page} (Start: {start_index})")
        resp = requests.get(url, params=params)
        data = resp.json()
        
        # Hata Kontrolü (Quota bitti mi?)
        if "error" in data:
            logger.error(f"Google API Hatası: {data['error']['message']}")
            return []
            
        if "items" not in data:
            logger.warning("Bu sayfada sonuç yok.")
            return []
            
        # Sonuçları işle
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        
        for item in data['items']:
            link = item.get('link', '')
            snippet = item.get('snippet', '')
            title = item.get('title', '')
            
            # 1. Link zaten t.me ise
            if "t.me/" in link:
                found_links.append(link)
                continue
                
            # 2. Açıklamada (Snippet) t.me varsa (Regex ile sök)
            full_text = f"{title} {snippet}"
            matches = regex.findall(full_text)
            for m in matches:
                found_links.append(m)
                
    except Exception as e:
        logger.error(f"API Bağlantı Hatası: {e}")
        
    return list(set(found_links))

# ==================== GÖREV YÖNETİCİSİ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    
    # Aramayı zenginleştiriyoruz
    search_query = f'site:t.me "{keyword}"'
    
    # SAYFA DÖNGÜSÜ (PAGINATION)
    # 1'den başlayıp SAYFA_SAYISI kadar gezecek
    for page in range(1, SAYFA_SAYISI + 1):
        if not CONFIG["is_running"]: break
        if toplanan >= HEDEF_LINK_SAYISI: break
        
        try:
            await status_msg.edit(f"🔍 **Google Taranıyor...**\nSayfa: {page}/{SAYFA_SAYISI}\nBulunan: {toplanan}")
        except: pass
        
        # Google'a Sor
        new_links = google_search_api(search_query, page)
        
        if not new_links:
            logger.info(f"Sayfa {page} boş döndü. Diğer sayfaya geçiliyor...")
            # Eğer 2 sayfa üst üste boşsa durdurabiliriz ama şimdilik devam etsin
            
        gonderilecekler = []
        for link in new_links:
            # Temizlik
            clean = link.strip().rstrip('.,")\'')
            ignore = ["share", "socks", "proxy", "contact", "google", "search"]
            if any(x in clean.lower() for x in ignore): continue

            if clean not in history:
                gonderilecekler.append(clean)
                history.add(clean)
                save_history(clean)

        # Gruba At
        for link in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=link,
                    reply_to=CONFIG["target_topic_id"],
                    link_preview=False
                )
                toplanan += 1
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")
        
        # Bir sonraki sayfaya geçmeden önce azıcık bekle
        await asyncio.sleep(2)

    await status_msg.respond(f"🏁 **İşlem Tamamlandı!**\nToplam {toplanan} link bulundu.")
    CONFIG["is_running"] = False

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond("👋 **Google API Bot Hazır**\n\n1️⃣ `/hedef <LİNK>`\n2️⃣ `/basla <KELIME>`\n\nBu modda captcha veya ban yoktur.")

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
    # API KEY KONTROLÜ
    if "BURAYA" in GOOG_API_KEY or "BURAYA" in GOOG_CX:
        await event.respond("⚠️ **HATA:** API Key ve CX ID ayarlanmamış!\nRender Environment ayarlarına `GOOG_API_KEY` ve `GOOG_CX` eklemelisin.")
        return

    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Çalışıyor.")
    
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["is_running"] = True
        msg = await event.respond(f"🚀 **{kw}** için Google API çalıştırılıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    if not CONFIG["is_running"]: return await event.respond("💤 Zaten duruk.")
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
