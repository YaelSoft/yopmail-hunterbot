import os
import logging
import asyncio
import random
import re
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
HEDEF_LINK_SAYISI = 50 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")

app = Flask(__name__)
@app.route('/')
def home(): return "Bot Calisiyor"
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

# ==================== YENİ ARAMA MOTORU ====================

def search_web(keyword):
    links = []
    found_urls = set()
    
    # "t.me" içeren her şeyi bulmaya çalışacağız
    # Regex Güncellemesi: http zorunluluğunu kaldırdık, (?:https?://)? yaptık.
    telegram_regex = re.compile(r'(?:https?://)?(?:www\.)?t\.me/(?:joinchat/|\+)?([\w\d_]+)')

    queries = [
        f'"{keyword}" site:t.me',
        f'"{keyword}" "t.me/joinchat"',
        f'"{keyword}" "t.me/+"',
        f'"{keyword}" "Telegram kanalı"',
        f'site:facebook.com "{keyword}" "t.me"',
        f'site:instagram.com "{keyword}" "t.me"'
    ]

    try:
        # max_results=50 yaptık, daha çok veri çeksin
        with DDGS() as ddgs:
            for q in queries:
                logger.info(f"Sorgu yapılıyor: {q}")
                results = list(ddgs.text(q, region='tr-tr', safesearch='off', max_results=30))
                
                if not results:
                    logger.warning(f"Sorgu boş döndü: {q}")

                for res in results:
                    # Hata ayıklama için botun ne gördüğünü yazdırıyoruz
                    # logger.info(f"HAM VERİ: {res.get('href')} - {res.get('title')}")

                    combined_text = f"{res.get('href', '')} {res.get('title', '')} {res.get('body', '')}"
                    matches = telegram_regex.findall(combined_text)
                    
                    for match in matches:
                        # Regex sadece username'i yakalayabilir, linki biz tamamlayalım
                        clean_link = f"https://t.me/{match}"
                        
                        # Filtreleme (Botlar, stickeler vb. hariç)
                        if match.lower() in ["s", "share", "addstickers", "proxy", "socks"]: continue
                        if len(match) < 4: continue # Çok kısa isimler genelde çöp olur

                        if clean_link not in found_urls:
                            found_urls.add(clean_link)
                            links.append({"url": clean_link, "title": res.get('title', 'Bulunan Link')})
                            logger.info(f"✅ BULUNDU VE EKLENDİ: {clean_link}")

        random.shuffle(links)
        return links
        
    except Exception as e:
        logger.error(f"Arama Motoru Hatası: {e}")
        return []

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Hedef ({HEDEF_LINK_SAYISI}) tamamlandı.")
            CONFIG["is_running"] = False
            break

        await status_msg.edit(f"🔍 **{keyword}** aranıyor... (Bulunan: {toplanan}/{HEDEF_LINK_SAYISI})")
        new_links = search_web(keyword)
        
        gonderilecekler = []
        for item in new_links:
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            logger.info("Bu turda yeni link bulunamadı, 10sn bekleniyor...")
            await asyncio.sleep(10)
            continue

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=f"🔗 {item['url']}\n📝 {item['title']}\n#{keyword}",
                    reply_to=CONFIG["target_topic_id"]
                )
                toplanan += 1
                logger.info(f"Mesaj gönderildi: {item['url']}")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")

    await status_msg.respond("🛑 Durduruldu.")

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır.\n/hedef ve /basla komutlarını kullan.")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Tamam.")
        else: await event.respond("❌ Hatalı link.")
    except: await event.respond("❌ Link gir.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef seç.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond("🚀 Başlıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime gir.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
