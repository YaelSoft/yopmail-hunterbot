import os
import logging
import asyncio
import random
import re
import time
import requests
import urllib3
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

HEDEF_LINK_SAYISI = 50 

# ==================== FİLTRELER (PASAPORT KONTROLÜ) ====================

# Bu kelimeler linkte veya başlıkta geçerse DİREKT ÇÖPE ATILIR
YASAKLI_KELIMELER = [
    "crypto", "forex", "bitcoin", "invest", "trading", "finance", "bet", 
    "casino", "pump", "signal", "binance", "coin", "stock", "market", 
    "global", "english", "usa", "russia", "china", "indian", "iran"
]

# Susturucu
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

app = Flask(__name__)
@app.route('/')
def home(): return "Bot Turkce Modda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

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

def extract_telegram_links(text):
    found = set()
    regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([a-zA-Z0-9_]{4,})')
    matches = regex.findall(text)
    for match in matches:
        ignore = ["share", "addstickers", "proxy", "socks", "contact", "iv", "setlanguage", "telegram", "settings", "status"]
        if match.lower() in ignore: continue
        
        # Ekstra Güvenlik: Username içinde yasaklı kelime var mı?
        if any(bad in match.lower() for bad in YASAKLI_KELIMELER):
            continue

        full_link = f"https://t.me/{match}"
        found.add(full_link)
    return list(found)

def dig_for_links(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=8, verify=False)
        # Sitedeki tüm metni al ve filtrele
        return extract_telegram_links(response.text)
    except:
        return []

# ==================== TÜRKÇE ODAKLI ARAMA MOTORU ====================

def search_web(keyword):
    final_links = []
    visited_sites = set()

    # SORGULARI DEĞİŞTİRDİK: Yabancı gelmemesi için Türkçe kelimeler ekledik
    queries = [
        f'"{keyword}" "telegram grubu" -crypto -forex',  # "Grubu" kelimesi Türkçe zorunluluğu katar
        f'site:t.me "{keyword}" "sohbet"',               # "Sohbet" kelimesi Türkçe zorunluluğu katar
        f'"{keyword}" "t.me" türkiye',
        f'"{keyword}" "whatsapp" "telegram" link'        # Genelde bu ikisi bir arada aranır
    ]

    logger.info(f"🔍 '{keyword}' için TÜRKÇE kaynaklar taranıyor...")

    try:
        with DDGS() as ddgs:
            for q in queries:
                if not CONFIG["is_running"]: break

                try:
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='html', max_results=20))
                except Exception as e:
                    time.sleep(2)
                    continue

                for res in results:
                    if not CONFIG["is_running"]: break

                    title = res.get('title', '').lower()
                    body = res.get('body', '').lower()
                    site_url = res.get('href', '')

                    # --- PASAPORT KONTROLÜ ---
                    # Başlıkta veya açıklamada yasaklı kelime varsa DİREKT GEÇ
                    if any(bad in title or bad in body for bad in YASAKLI_KELIMELER):
                        logger.info(f"🚫 YASAKLI İÇERİK ENGELLENDİ: {title}")
                        continue
                    
                    # --- 1. SNIPPET TARAMA ---
                    snippet_text = f"{title} {body} {site_url}"
                    snippet_links = extract_telegram_links(snippet_text)
                    
                    if snippet_links:
                        for l in snippet_links:
                            final_links.append({"url": l, "title": f"Hızlı: {res.get('title')}"})
                        continue 

                    # --- 2. SİTEYE GİRME ---
                    if site_url and site_url not in visited_sites:
                        
                        # Site adresi bile yasaklı kelime içeriyorsa girme (örn: investing.com)
                        if any(bad in site_url.lower() for bad in YASAKLI_KELIMELER):
                            continue

                        visited_sites.add(site_url)
                        
                        if "t.me/" in site_url:
                            # Direkt Telegram linki
                            l_clean = site_url.split("?")[0]
                            # Son bir kontrol
                            if not any(bad in l_clean.lower() for bad in YASAKLI_KELIMELER):
                                final_links.append({"url": l_clean, "title": "Direkt Link"})
                            continue

                        if not CONFIG["is_running"]: break

                        extracted = dig_for_links(site_url)
                        for ex_link in extracted:
                            # Linkin kendisinde yasaklı kelime var mı?
                            if not any(bad in ex_link.lower() for bad in YASAKLI_KELIMELER):
                                final_links.append({"url": ex_link, "title": f"Web: {res.get('title')}"})
                        
                        time.sleep(0.5)

        return final_links
        
    except Exception as e:
        logger.error(f"Hata: {e}")
        return []

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    fail_count = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Bitti! {toplanan} temiz link bulundu.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🇹🇷 **{keyword}** taranıyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
        except: pass

        new_links = search_web(keyword)
        
        if not CONFIG["is_running"]: break

        gonderilecekler = []
        for item in new_links:
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            logger.info(f"Temiz link yok. ({fail_count}. deneme)")
            await asyncio.sleep(5)
            continue
        
        fail_count = 0 

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
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

# ==================== KOMUTLAR AYNI ====================
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
        else: await event.respond("❌ Hatalı Link.")
    except: await event.respond("❌ Link yok.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond(f"🚀 **{kw}** için Türkçe kaynaklar taranıyor...")
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
