import os
import logging
import asyncio
import random
import re
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from telethon.errors import MessageNotModifiedError # CRASH ÇÖZÜMÜ İÇİN GEREKLİ
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# HEDEF LİMİT
HEDEF_LINK_SAYISI = 50 

# Log Ayarları
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

# Botu Başlat
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

# ==================== GELİŞMİŞ ARAMA (BACKEND: HTML) ====================

def search_web(keyword):
    links = []
    found_urls = set()
    
    # Regex: Hem t.me/xxx hem de telegram.me/xxx formatını yakalar
    telegram_regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([\w\d_]+)')

    # Sorguları basitleştirdik ki Bing engellemesin
    queries = [
        f'"{keyword}" t.me',
        f'"{keyword}" telegram grubu',
        f'site:t.me "{keyword}"',
        f'"{keyword}" t.me joinchat',
        f'"{keyword}" "t.me/+"'
    ]

    try:
        # backend='html' botlara karşı daha az hassastır, daha çok veri verir
        with DDGS() as ddgs:
            for q in queries:
                logger.info(f"🔎 Sorgulanıyor: {q}")
                try:
                    # max_results düşürdük ama backend değiştirdik
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='html', max_results=20))
                except Exception as e:
                    logger.warning(f"Sorgu hatası ({q}): {e}")
                    continue

                if not results:
                    logger.warning(f"⚠️ Boş sonuç: {q}")
                    continue

                for res in results:
                    # Başlık, Link ve İçeriği birleştirip tarıyoruz
                    combined_text = f"{res.get('href', '')} {res.get('title', '')} {res.get('body', '')}"
                    matches = telegram_regex.findall(combined_text)
                    
                    for match in matches:
                        clean_link = f"https://t.me/{match}"
                        
                        # Gereksiz sistem linklerini filtrele
                        ignore_list = ["s", "share", "addstickers", "proxy", "socks", "contact", "iv"]
                        if match.lower() in ignore_list or len(match) < 4: 
                            continue

                        if clean_link not in found_urls:
                            found_urls.add(clean_link)
                            links.append({"url": clean_link, "title": res.get('title', 'Bulunan Grup')})
                            
        random.shuffle(links)
        return links
        
    except Exception as e:
        logger.error(f"Genel Arama Hatası: {e}")
        return []

# ==================== GÖREV YÖNETİCİSİ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    hatali_deneme = 0
    
    while CONFIG["is_running"]:
        # 1. Hedef Kontrolü
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 **Görev Tamamlandı!**\nToplam {toplanan} link bulundu.")
            CONFIG["is_running"] = False
            break

        # 2. Durum Güncelleme (HATA ÖNLEYİCİ MOD)
        try:
            await status_msg.edit(f"🔍 **{keyword}** aranıyor... (Bulunan: {toplanan}/{HEDEF_LINK_SAYISI})")
        except MessageNotModifiedError:
            pass # Mesaj aynıysa hata verme, devam et
        except Exception as e:
            logger.error(f"Mesaj edit hatası: {e}")

        # 3. Arama Yap
        new_links = search_web(keyword)
        
        gonderilecekler = []
        for item in new_links:
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        # 4. Sonuç Yoksa Bekle
        if not gonderilecekler:
            hatali_deneme += 1
            logger.info(f"Bu turda sonuç yok. ({hatali_deneme}. deneme)")
            
            # Eğer 5 kere üst üste bulamazsa, arama motorunu dinlendir
            wait_time = 10 if hatali_deneme < 5 else 60
            await asyncio.sleep(wait_time)
            continue
        
        # Sonuç bulduysa hata sayacını sıfırla
        hatali_deneme = 0 

        # 5. Linkleri Gönder
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
                logger.info(f"✅ Gönderildi: {item['url']}")
                await asyncio.sleep(3) # Flood yememek için bekle
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")

    await status_msg.respond("🛑 İşlem durduruldu.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Online. /hedef ve /basla komutlarını kullan.")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond(f"✅ Hedef: `{c}` Topic: `{t}`")
        else: await event.respond("❌ Link Hatalı.")
    except: await event.respond("❌ Link gir.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
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
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
