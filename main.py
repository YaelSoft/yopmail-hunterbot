import os
import logging
import asyncio
import random
import re
import time
import requests 
from bs4 import BeautifulSoup
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

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")

# Web Server
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

# ==================== SİTE İÇİ LİNK ÇIKARICI ====================

def extract_links_from_page(url, regex):
    """Verilen web sitesine girer ve içindeki t.me linklerini çeker"""
    extracted = set()
    try:
        # Siteye tarayıcı gibi git
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            # HTML içeriğini tara
            content = response.text
            matches = regex.findall(content)
            for match in matches:
                full_link = f"https://t.me/{match}"
                extracted.add(full_link)
                logger.info(f"⛏️ Siteden link çıkarıldı: {full_link}")
    except Exception as e:
        # Hata verirse (timeout vs) geç, önemli değil
        pass
    return list(extracted)

# ==================== ARAMA MOTORU ====================

def search_web(keyword):
    links = []
    found_urls = set()
    
    # Regex: Telegram linklerini yakalar
    telegram_regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([\w\d_]+)')

    queries = [
        f'"{keyword}" t.me',
        f'site:facebook.com "{keyword}" t.me',
        f'site:instagram.com "{keyword}" t.me',
        f'"{keyword}" telegram grubu'
    ]

    try:
        with DDGS() as ddgs:
            for q in queries:
                logger.info(f"🔎 Aranan: {q}")
                # backend='lite' en hızlısıdır
                try:
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='lite', max_results=15))
                except: 
                    time.sleep(5)
                    continue

                for res in results:
                    url = res.get('href', '')
                    
                    # 1. Durum: Link zaten bir Telegram linkiyse direkt al
                    if "t.me/" in url:
                        matches = telegram_regex.findall(url)
                        for match in matches:
                            clean = f"https://t.me/{match}"
                            if clean not in found_urls:
                                found_urls.add(clean)
                                links.append({"url": clean, "title": res.get('title')})
                    
                    # 2. Durum: Link bir websitesi ise (Facebook vb.) İÇİNE GİR
                    else:
                        # Bu siteye gir ve tara
                        extracted = extract_links_from_page(url, telegram_regex)
                        for ext_link in extracted:
                            if ext_link not in found_urls:
                                found_urls.add(ext_link)
                                links.append({"url": ext_link, "title": f"Web: {res.get('title')}"})
                
                # Her sorgu arası azıcık bekle
                time.sleep(2)

        random.shuffle(links)
        return links
        
    except Exception as e:
        logger.error(f"Arama Hatası: {e}")
        return []

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    fail_count = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Tamamlandı! {toplanan} link bulundu.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🔍 **{keyword}** derinlemesine taranıyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
        except: pass

        new_links = search_web(keyword)
        
        gonderilecekler = []
        for item in new_links:
            # Filtreler (proxy, share, vb.)
            if "socks" in item["url"] or "proxy" in item["url"] or "share" in item["url"]: continue
            
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            await asyncio.sleep(10)
            continue
        
        fail_count = 0 

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
                await asyncio.sleep(3) 
            except Exception as e:
                logger.error(f"Mesaj hatası: {e}")

    await status_msg.respond("🛑 Bitti.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır.\n1. /hedef link\n2. /basla kelime")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Tamam.")
        else: await event.respond("❌ Link bozuk.")
    except: await event.respond("❌ Link yok.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond("🚀 Derin tarama başlıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durdu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
