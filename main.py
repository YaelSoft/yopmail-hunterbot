import os
import logging
import asyncio
import re
import time
import requests
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "")
GOOG_CX = os.environ.get("GOOG_CX", "")

# BURAYA DİKKAT: Admin ID'ni gir ki limit sana işlemesin
ADMIN_ID = 000000000 # <-- ID'ni buraya yaz

# Kaç sayfa tarasın? (Daha çok sonuç için artırabilirsin ama Google kotanı yer)
SAYFA_SAYISI = 5 
HEDEF_LINK_SAYISI = 100 # Hedefi yükselttik

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("DirectoryHunter")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Dizin Avcisi Modu 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("dir_hunter", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Hafıza
CONFIG = {"target_chat_id": None, "target_topic_id": None, "is_running": False}
HISTORY_FILE = "sent_links.txt"
CREDITS_FILE = "user_credits.json"

# ==================== YARDIMCI FONKSİYONLAR ====================

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

def extract_username_from_url(url):
    """
    Tgstat, Telemetr gibi sitelerin linklerinden @username çeker ve t.me linkine çevirir.
    """
    # Örnek Linkler:
    # https://tgstat.com/channel/@ticaretgrubu -> ticaretgrubu
    # https://telemetr.io/en/channels/12345-grupismi -> grupismi
    # https://hottg.com/grupismi -> grupismi
    
    clean_url = url.rstrip("/")
    username = ""

    if "t.me/" in url:
        return url # Zaten t.me linki
    
    elif "@" in url: 
        # Linkin içinde @ varsa (Örn: tgstat.com/.../@ahmet)
        username = url.split("@")[-1]
    
    elif "hottg.com" in url:
        username = url.split("/")[-1]
        
    elif "telemetr.io" in url:
        parts = url.split("/")[-1]
        # Bazen "1234-isim" formatında olur
        if "-" in parts:
            username = parts.split("-", 1)[1]
        else:
            username = parts

    # Temizlik ve Kontrol
    username = username.split("?")[0].strip()
    
    # Eğer geçerli bir kullanıcı adıysa linke çevir
    if re.match(r'^[a-zA-Z0-9_]{4,}$', username):
        return f"https://t.me/{username}"
    
    return None

# ==================== GOOGLE API (DİZİN TARAMA) ====================

def google_search_directories(keyword, page=1):
    found_links = []
    start_index = ((page - 1) * 10) + 1
    
    # HEDEF SİTELER: Bu siteler Telegram gruplarını listeler.
    # Resmi bakanlık kanalları buralarda pek olmaz.
    target_sites = [
        "site:tgstat.com",
        "site:telemetr.io",
        "site:hottg.com",
        "site:telegramchannels.me",
        "site:best-telegram-groups.com",
        "site:telegramindex.com"
    ]
    
    # Sorguyu oluştur: (site:A OR site:B OR site:C) "keyword" "chat" -kanal
    # "chat" veya "group" kelimelerini ekliyoruz ki sadece sohbet grupları gelsin.
    sites_query = " OR ".join(target_sites)
    
    # Negatif kelimelerle resmiyeti azaltıyoruz
    final_query = f'({sites_query}) "{keyword}" (chat OR group OR sohbet) -channel -kanal -haber'
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOG_API_KEY,
        'cx': GOOG_CX,
        'q': final_query,
        'start': start_index,
        'num': 10
    }
    
    try:
        logger.info(f"🌍 Google'da Dizinler Taranıyor: Sayfa {page}")
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if "items" not in data: return []
            
        for item in data['items']:
            link = item.get('link', '')
            
            # Linki analiz et ve t.me formatına çevir
            tg_link = extract_username_from_url(link)
            
            if tg_link:
                found_links.append(tg_link)
                
    except Exception as e:
        logger.error(f"API Hatası: {e}")
        
    return list(set(found_links))

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    
    # Sayfa Sayısı kadar dön
    for page in range(1, SAYFA_SAYISI + 1):
        if not CONFIG["is_running"]: break
        if toplanan >= HEDEF_LINK_SAYISI: break
        
        try:
            await status_msg.edit(f"🔍 **Dizinler Taranıyor...**\nKelime: {keyword}\nSayfa: {page}\nBulunan: {toplanan}")
        except: pass
        
        new_links = google_search_directories(keyword, page)
        
        if not new_links:
            logger.info("Bu sayfadan verimli link çıkmadı.")
            
        gonderilecekler = []
        for link in new_links:
            # Yasaklı kelime kontrolü
            ignore = ["bot", "news", "support", "admin"]
            if any(x in link.lower() for x in ignore): continue
            
            if link not in history:
                gonderilecekler.append(link)
                history.add(link)
                save_history(link)

        # Hepsini birden değil, tek tek at (Flood yememek için)
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
                # Biraz hızlı atabiliriz
                await asyncio.sleep(1.5) 
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")
        
        # Sayfa geçişinde bekle
        await asyncio.sleep(2)

    await status_msg.respond(f"🏁 **Tarama Bitti!**\nToplam {toplanan} adet grup/kanal bulundu.")
    CONFIG["is_running"] = False

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond("👋 **Dizin Avcısı (Directory Hunter)**\n\nBu mod Tgstat, Telemetr gibi sitelerden grup toplar.\n\n1️⃣ `/hedef <LİNK>`\n2️⃣ `/basla <KELIME>`")

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
        msg = await event.respond(f"🚀 **{kw}** için veritabanları taranıyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
