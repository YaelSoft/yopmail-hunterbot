import os
import logging
import asyncio
import random
import re
import time
import requests
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Limit
HEDEF_LINK_SAYISI = 50 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Avda 🟢"
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

# ==================== YARDIMCI: LİNK TEMİZLEME ====================
def extract_telegram_links(text):
    """
    Bir metnin içindeki (HTML, Yazı, Snippet) tüm t.me linklerini bulur.
    """
    found = set()
    # Regex: t.me/xxx veya telegram.me/xxx (HTTP olması şart değil)
    regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([a-zA-Z0-9_]{4,})')
    
    matches = regex.findall(text)
    for match in matches:
        # Yasaklı kelimeler (System linkleri)
        ignore = ["share", "addstickers", "proxy", "socks", "contact", "iv", "setlanguage", "telegram", "settings"]
        if match.lower() in ignore: continue
        
        # Linki oluştur
        full_link = f"https://t.me/{match}"
        found.add(full_link)
    
    return list(found)

# ==================== SİTE İÇİ TARAMA ====================
def dig_for_links(url):
    """Siteye girip kaynak kodunu tarar"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=8, verify=False)
        if "t.me" in response.url: return [response.url.split("?")[0]]
        return extract_telegram_links(response.text)
    except:
        return []

# ==================== ARAMA MOTORU ====================

def search_web(keyword):
    final_links = []
    visited_sites = set()

    # Dorking Sorguları
    queries = [
        f'"{keyword}" t.me',
        f'"{keyword}" chat link',
        f'"{keyword}" telegram grubu',
        f'site:t.me "{keyword}"'
    ]

    logger.info(f"🔍 '{keyword}' aranıyor...")

    try:
        with DDGS() as ddgs:
            for q in queries:
                try:
                    # backend='api' en temiz veriyi verir
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='api', max_results=25))
                except:
                    time.sleep(2)
                    continue

                for res in results:
                    # ADIM 1: GÖZÜNLE GÖRDÜĞÜN YERİ TARA (SNIPPET SCAN)
                    # Başlıkta veya açıklamada link varsa DİREKT AL, siteye gitme.
                    snippet_text = f"{res.get('title', '')} {res.get('body', '')} {res.get('href', '')}"
                    snippet_links = extract_telegram_links(snippet_text)
                    
                    if snippet_links:
                        for l in snippet_links:
                            final_links.append({"url": l, "title": f"Hızlı Bulundu: {res.get('title')}"})
                            logger.info(f"⚡ SNIPPET'TAN YAKALANDI: {l}")
                        # Snippet'ta bulduysak siteye girmekle vakit kaybetmeyelim
                        continue 

                    # ADIM 2: EĞER SNIPPET'TA YOKSA SİTEYE GİR (DEEP SCAN)
                    site_url = res.get('href', '')
                    if site_url and site_url not in visited_sites:
                        visited_sites.add(site_url)
                        
                        # Eğer link zaten t.me ise
                        if "t.me/" in site_url:
                            l_clean = site_url.split("?")[0]
                            final_links.append({"url": l_clean, "title": "Direkt Link"})
                            continue

                        # Değilse siteye gir
                        extracted = dig_for_links(site_url)
                        for ex_link in extracted:
                            final_links.append({"url": ex_link, "title": f"Kaynak: {site_url}"})
                        
                        time.sleep(0.5) # IP ban yememek için bekleme

        return final_links
        
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
            await status_msg.respond(f"🏁 Görev Bitti! {toplanan} link bulundu.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🔥 **{keyword}** taranıyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
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
            logger.info(f"Bu turda link çıkmadı. ({fail_count}. deneme)")
            await asyncio.sleep(5)
            continue
        
        fail_count = 0 

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                # Linki direkt mesaj olarak atıyoruz, buton vs yok. Sade.
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=f"{item['url']}",
                    reply_to=CONFIG["target_topic_id"],
                    link_preview=False
                )
                toplanan += 1
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")

    await status_msg.respond("🛑 Durdu.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır. /hedef ve /basla")

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
        msg = await event.respond(f"🚀 **{kw}** aranıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durdu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
