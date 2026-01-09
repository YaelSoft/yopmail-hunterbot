import re
import os
import logging
import asyncio
import random
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events

# ARAMA MOTORU KÜTÜPHANESİ
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# 🔥 TURBO AYARI: Kaç tane link bulunca dursun?
HEDEF_LINK_SAYISI = 50 

# Loglama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SearchBot")

# Web Server (Render İçin)
app = Flask(__name__)
@app.route('/')
def home(): return "Search Bot Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ==================== GLOBAL HAFIZA ====================
CONFIG = {
    "target_chat_id": None,  
    "target_topic_id": None, 
    "is_running": False,
    "current_keyword": ""
}

HISTORY_FILE = "sent_links.txt"

# ==================== YARDIMCI FONKSİYONLAR ====================

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")

def parse_topic_link(link):
    """Linkten ID'leri süzer"""
    link = link.strip().replace("https://", "").replace("t.me/", "")
    parts = link.split("/")
    
    try:
        if "c/" in link: # Private: c/123456/100
            chat_id = int("-100" + link.split("c/")[1].split("/")[0])
            topic_id = int(parts[-1])
            return chat_id, topic_id
        else: 
            return None, None
    except:
        return None, None

# ==================== GELİŞMİŞ ARAMA MOTORU (REGEX MODU) ====================

def search_web(keyword):
    """Web'de tarama yapar ve metin içindeki gizli linkleri Regex ile söker"""
    links = []
    found_urls = set() # Aynı linki tekrar eklememek için

    # Daha geniş sorgular (Facebook/Twitter yerine genel tarama daha verimli olabilir)
    queries = [
        f'site:t.me "{keyword}"',
        f'"t.me/+" "{keyword}"',
        f'"{keyword}" "t.me/joinchat"',
        f'"{keyword}" "Telegram grubu"',
        f'site:facebook.com "{keyword}" "t.me"',
        f'site:instagram.com "{keyword}" "t.me"',
        f'site:vk.com "{keyword}" "t.me"'
    ]
    
    # TELEGRAM LİNKİNİ BULAN SİHİRLİ REGEX
    # Bu kod, bir metnin içinde "t.me/blabla" gördüğü an yakalar.
    telegram_regex = re.compile(r'(https?://t\.me/(?:joinchat/|\+)?[\w\d_]+)')

    try:
        with DDGS() as ddgs:
            for q in queries:
                # Sonuçları çekiyoruz
                results = list(ddgs.text(q, region='tr-tr', safesearch='off', max_results=25))
                
                for res in results:
                    # Linki hem başlıkta, hem linkte, hem de açıklamada arayacağız
                    search_content = f"{res.get('href', '')} {res.get('title', '')} {res.get('body', '')}"
                    
                    # Regex ile metnin içindeki TÜM t.me linklerini bul
                    matches = telegram_regex.findall(search_content)
                    
                    for match in matches:
                        clean_link = match.strip()
                        
                        # Temizlik ve Filtreleme
                        if clean_link not in found_urls:
                            # Sonunda nokta, virgül varsa temizle
                            clean_link = clean_link.rstrip(".,)!?")
                            
                            # Hatalı/Gereksiz linkleri ele (Örn: t.me/s/.. kanalların web önizlemesidir)
                            if "/s/" in clean_link or clean_link.endswith("t.me"):
                                continue

                            found_urls.add(clean_link)
                            links.append({"url": clean_link, "title": res.get('title', 'Bulunan Link')})
                            
        # Karıştır ki hep aynı sırayla gitmesin
        list_links = list(links)
        random.shuffle(list_links)
        return list_links
        
    except Exception as e:
        logger.error(f"Arama hatası: {e}")
        return []
# ==================== ANA MOTOR (LEECH TASK) ====================
# Burası senin eski kodda eksik olan kısımdı, baştan yazdım.

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan_sayisi = 0 # Sayaç sıfırdan başlar
    
    while CONFIG["is_running"]:
        # 1. Limit Kontrolü
        if toplanan_sayisi >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 **HEDEF TAMAMLANDI!**\nToplam {toplanan_sayisi} yeni link bulundu ve durduruldu.")
            CONFIG["is_running"] = False
            break

        # 2. Arama Yap
        await status_msg.edit(f"🔍 **{keyword}** aranıyor... (Bulunan: {toplanan_sayisi}/{HEDEF_LINK_SAYISI})")
        new_links = search_web(keyword)
        
        yeni_bulunanlar = []
        
        # 3. Linkleri Filtrele
        for item in new_links:
            link = item["url"]
            if link not in history:
                yeni_bulunanlar.append(item)
                history.add(link)
                save_history(link)

        # 4. Sonuç Yoksa Hızlı Geç (TURBO)
        if not yeni_bulunanlar:
            await status_msg.edit(f"⚠️ Bu turda yeni link yok. Hızla tekrar deneniyor...")
            await asyncio.sleep(5) # Eskiden 120 saniyeydi, şimdi 5 saniye
            continue

        # 5. Linkleri Gruba Gönder
        for item in yeni_bulunanlar:
            if not CONFIG["is_running"]: break # Acil durdurma kontrolü
            if toplanan_sayisi >= HEDEF_LINK_SAYISI: break # Döngü içi limit kontrolü

            msg_text = (
                f"🎯 **Yeni Link Bulundu!**\n"
                f"🔗 Link: {item['url']}\n"
                f"📝 Başlık: {item['title']}\n"
                f"🔎 Kelime: #{keyword}"
            )
            
            try:
                # Hedef konuya mesaj at
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=msg_text,
                    reply_to=CONFIG["target_topic_id"]
                )
                toplanan_sayisi += 1
                await asyncio.sleep(2) # Flood yememek için 2 saniye ara
                
            except Exception as e:
                logger.error(f"Gönderme hatası: {e}")

    await status_msg.respond("🛑 İşlem sonlandırıldı.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond(
        "👋 **Turbo Link Avcısı**\n\n"
        "1️⃣ `/hedef https://t.me/c/xxxx/123` ile hedef ayarla.\n"
        "2️⃣ `/basla <kelime>` ile aramayı başlat.\n"
        f"3️⃣ Bot {HEDEF_LINK_SAYISI} link bulunca otomatik durur."
    )

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        chat_id, topic_id = parse_topic_link(link)
        
        if chat_id and topic_id:
            CONFIG["target_chat_id"] = chat_id
            CONFIG["target_topic_id"] = topic_id
            await event.respond(f"✅ Hedef Ayarlandı!\nGrup: `{chat_id}`\nKonu: `{topic_id}`")
        else:
            await event.respond("❌ Hatalı Link! Sadece `t.me/c/..` formatlı özel grup linki kabul edilir.")
    except IndexError:
        await event.respond("❌ Link girmedin.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]:
        await event.respond("⚠️ Önce `/hedef` ayarla!")
        return
        
    if CONFIG["is_running"]:
        await event.respond(f"⚠️ Zaten çalışıyor.")
        return

    try:
        keyword = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"] = keyword
        CONFIG["is_running"] = True
        
        status_msg = await event.respond(f"🚀 **{keyword}** için Turbo Mod başlatılıyor...")
        # Ana motoru burada çağırıyoruz
        asyncio.create_task(leech_task(status_msg, keyword))
        
    except IndexError:
        await event.respond("❌ Kelime girmedin. Örn: `/basla kripto`")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    if not CONFIG["is_running"]:
        await event.respond("💤 Zaten durmuş.")
        return
    
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor... (Mevcut gönderim bitince duracak)")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
