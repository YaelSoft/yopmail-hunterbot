import os
import logging
import asyncio
import random
import time
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

# Loglama (Gözümüzle görelim ne buluyor)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")
# Gereksizleri sustur
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
urllib3.disable_warnings()

app = Flask(__name__)
@app.route('/')
def home(): return "Bot Basit Modda 🟢"
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

# ==================== ARAMA MOTORU (DİREKT ADRES OKUMA) ====================

def search_web(keyword):
    final_links = []
    
    # SENİN DEDİĞİN GİBİ: Direkt t.me linklerini hedefliyoruz.
    # site:t.me demek "Bana sadece Telegram linklerini getir" demektir.
    queries = [
        f'site:t.me "{keyword}"',          # Direkt telegram linkleri
        f'site:t.me "{keyword}" chat',     # Sohbetler
        f'"{keyword}" t.me joinchat',      # Katılma linkleri
        f'"{keyword}" t.me/+'              # Özel linkler
    ]

    logger.info(f"👀 '{keyword}' için linkler toplanıyor...")

    try:
        with DDGS() as ddgs:
            for q in queries:
                if not CONFIG["is_running"]: break

                try:
                    # max_results'ı 50 yaptık, tek seferde çok alsın
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='html', max_results=50))
                except Exception as e:
                    logger.warning(f"⚠️ Arama hatası: {e}")
                    time.sleep(3)
                    continue
                
                if not results:
                    logger.warning(f"⚠️ BU SORGU BOŞ DÖNDÜ (Ban Riski): {q}")

                for res in results:
                    # BURASI SENİN DEDİĞİN YER
                    # Linkin kendisine (href) bakıyoruz.
                    link = res.get('href', '')
                    title = res.get('title', '')
                    
                    # LOG: Botun tam olarak ne bulduğunu yazdıralım
                    # logger.info(f"BULUNAN HAM LİNK: {link}") 

                    # 1. Linkin kendisi t.me ise AL
                    if "t.me/" in link:
                        clean_link = link.split("?")[0] # Soru işaretinden sonrasını at
                        final_links.append({"url": clean_link, "title": title})
                        logger.info(f"✅ HEDEF VURULDU: {clean_link}")
                    
                    # 2. Başlıkta veya açıklamada link geçiyor mu?
                    # Bazen link 'google.com/...' olur ama açıklamasında 't.me/grup' yazar.
                    else:
                        snippet = f"{title} {res.get('body', '')}"
                        if "t.me/" in snippet:
                            # Basitçe metnin içinden t.me... kısmını kesip alalım
                            import re
                            found = re.findall(r'(https?://t\.me/[\w\d_\+]+)', snippet)
                            for f in found:
                                final_links.append({"url": f, "title": f"Yazıdan: {title}"})
                                logger.info(f"✅ YAZIDAN ALINDI: {f}")

                time.sleep(1)

        return final_links
        
    except Exception as e:
        logger.error(f"Genel Hata: {e}")
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
            await status_msg.edit(f"🔍 **{keyword}** taranıyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
        except: pass

        new_links = search_web(keyword)
        
        if not CONFIG["is_running"]: break

        gonderilecekler = []
        for item in new_links:
            # Filtreler (Gereksiz sistem linkleri)
            ignore = ["share", "socks", "proxy", "contact", "setlanguage", "iv"]
            if any(x in item["url"] for x in ignore): continue

            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            logger.info(f"Taze link yok. ({fail_count}. deneme)")
            await asyncio.sleep(5)
            continue
        
        fail_count = 0 

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                # Linki at
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
        else: await event.respond("❌ Hatalı Link.")
    except: await event.respond("❌ Link yok.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond(f"🚀 **{kw}** için linkler toplanıyor...")
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
