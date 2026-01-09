import os
import logging
import asyncio
import random
import re
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import MessageNotModifiedError
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Hedef
HEDEF_LINK_SAYISI = 50 

# Loglama Ayarları
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger("SearchBot")

# Web Server (Render İçin)
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Calisiyor 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Hafıza
CONFIG = {"target_chat_id": None, "target_topic_id": None, "is_running": False, "current_keyword": ""}
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

# ==================== ARAMA MOTORU (ÇİFT MOTORLU) ====================

def search_web(keyword):
    links = []
    found_urls = set()
    
    # REGEX: Metnin içindeki her türlü t.me linkini çeker
    telegram_regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([\w\d_]+)')

    # Sorgular (Daha sade tutuyoruz ki ban yemesin)
    queries = [
        f'"{keyword}" t.me',
        f'"{keyword}" telegram',
        f'site:t.me "{keyword}"'
    ]

    # Backend Listesi: Biri çalışmazsa ötekini deneyecek
    backends = ['api', 'lite', 'html']

    for backend in backends:
        if len(links) >= 10: break # Yeterince bulduysak diğer motora gerek yok
        
        try:
            logger.info(f"⚙️ Motor deneniyor: {backend.upper()}")
            
            with DDGS() as ddgs:
                for q in queries:
                    # Rastgele bekleme (Anti-Ban)
                    time.sleep(random.uniform(3, 6))
                    
                    try:
                        # Backend'i dinamik olarak değiştiriyoruz
                        results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend=backend, max_results=20))
                    except Exception as e:
                        logger.warning(f"⚠️ {backend} motoru hata verdi: {e}")
                        continue

                    if not results:
                        continue

                    for res in results:
                        # Gelen veriyi komple metne çevirip tarıyoruz
                        combined_text = f"{res.get('href', '')} {res.get('title', '')} {res.get('body', '')}"
                        matches = telegram_regex.findall(combined_text)
                        
                        for match in matches:
                            clean_link = f"https://t.me/{match}"
                            
                            # Filtreler (Gereksizleri at)
                            ignore = ["s", "share", "addstickers", "proxy", "socks", "contact", "iv", "setlanguage"]
                            if match.lower() in ignore or len(match) < 4: continue

                            if clean_link not in found_urls:
                                found_urls.add(clean_link)
                                links.append({"url": clean_link, "title": res.get('title', 'Link')})
                                logger.info(f"✅ BULUNDU ({backend}): {clean_link}")
        
        except Exception as e:
            logger.error(f"Genel Hata ({backend}): {e}")

    # Listeyi karıştır
    random.shuffle(links)
    return links

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    fail_count = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Görev Tamam! {toplanan} link bulundu.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🔍 **{keyword}** aranıyor... (Bulunan: {toplanan}/{HEDEF_LINK_SAYISI})")
        except MessageNotModifiedError: pass
        except: pass

        new_links = search_web(keyword)
        
        gonderilecekler = []
        for item in new_links:
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            logger.info(f"Bu tur boş geçti. ({fail_count}. deneme)")
            # Eğer sürekli boş geliyorsa bekleme süresini artır
            await asyncio.sleep(15 if fail_count < 3 else 60)
            continue
        
        fail_count = 0 # Sonuç bulduysak sayacı sıfırla

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=f"🔗 {item['url']}\n📝 {item['title']}\n#{keyword}",
                    reply_to=CONFIG["target_topic_id"]
                )
                toplanan += 1
                await asyncio.sleep(4) # Telegram Flood yememek için
            except Exception as e:
                logger.error(f"Mesaj atılamadı: {e}")

    await status_msg.respond("🛑 Durduruldu.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır. /hedef ve /basla komutlarını bekliyor.")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Ayarlandı.")
        else: await event.respond("❌ Link geçersiz.")
    except: await event.respond("❌ Link girilmedi.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond(f"🚀 **{kw}** için motorlar çalıştırılıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime girilmedi.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
