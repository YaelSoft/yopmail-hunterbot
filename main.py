import os
import logging
import asyncio
import re
import time
import json
import requests
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events, Button

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# GOOGLE API
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "")
GOOG_CX = os.environ.get("GOOG_CX", "")

# 🔥 SAHİP AYARLARI (Otomatik Algılama)
env_admin = os.environ.get("ADMIN_ID", os.environ.get("OWNER_ID", "0"))
ADMIN_ID = int(env_admin)

# LİMİTLER
DENEME_HAKKI = 3       
SAYFA_SAYISI = 2       
HEDEF_LINK_LIMITI = 50 

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcode" 
ADMIN_USER = "yasin33" 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("ProBotV2_Fix")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Fixlendi 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_v2", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı Dosyaları
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 

USER_STATES = {}

# ==================== VERİTABANI YÖNETİMİ ====================

def load_config():
    if not os.path.exists(CONFIG_FILE): 
        return {"target_chat_id": None}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"target_chat_id": None}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

# Global Config'i Yükle
BOT_CONFIG = load_config()

def load_credits():
    if not os.path.exists(CREDITS_FILE): 
        return {}
    try:
        with open(CREDITS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_credits(data):
    with open(CREDITS_FILE, "w") as f:
        json.dump(data, f)

def check_license(user_id):
    if user_id == ADMIN_ID: return True, "admin"
    data = load_credits()
    uid = str(user_id)
    if uid not in data:
        data[uid] = 0
        save_credits(data)
    used = data[uid]
    if used < DENEME_HAKKI: return True, used
    return False, used

def consume_credit(user_id):
    if user_id == ADMIN_ID: return
    data = load_credits()
    uid = str(user_id)
    if uid in data:
        data[uid] += 1
        save_credits(data)

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    except:
        return set()

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")

def extract_username_from_url(url):
    """Dizin sitelerinden kullanıcı adı çeker"""
    if "t.me/" in url: return url
    username = ""
    if "@" in url: username = url.split("@")[-1]
    elif "hottg.com" in url: username = url.split("/")[-1]
    elif "telemetr.io" in url:
        parts = url.split("/")[-1]
        username = parts.split("-", 1)[1] if "-" in parts else parts
    
    username = username.split("?")[0].strip()
    if re.match(r'^[a-zA-Z0-9_]{4,}$', username):
        return f"https://t.me/{username}"
    return None

# ==================== GOOGLE API ====================

def google_search(query, page=1):
    found = []
    start_index = ((page - 1) * 10) + 1
    
    if not GOOG_API_KEY:
        logger.error("API KEY EKSİK!")
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOG_API_KEY, 'cx': GOOG_CX, 'q': query, 'start': start_index, 'num': 10}
    
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if "error" in data:
            logger.error(f"Google API Hatası: {data['error']['message']}")
            return []
        if "items" not in data: return []
        
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        
        for item in data['items']:
            link = item.get('link', '')
            snippet = item.get('snippet', '')
            title = item.get('title', '')
            
            if "t.me/" in link:
                found.append(link.split("?")[0])
                continue

            converted = extract_username_from_url(link)
            if converted and "t.me/" in converted:
                found.append(converted)
                continue

            text_block = f"{title} {snippet}"
            matches = regex.findall(text_block)
            for m in matches:
                found.append(m.rstrip('.,")\''))
                
    except Exception as e:
        logger.error(f"Hata: {e}")
        
    return list(set(found))

# ==================== MENÜLER ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    
    status_msg = "👑 **Mod:** Yönetici (Sınırsız)" if info == "admin" else f"⏳ **Kalan Hak:** {DENEME_HAKKI - info}"
    
    target_info = "✅ Ayarlı" if BOT_CONFIG.get("target_chat_id") else "❌ Ayarlanmadı"

    text = (
        f"👋 **Selam {user.first_name}!**\n"
        f"🤖 **Link Avcısı Bot** hizmetine hoş geldin.\n\n"
        f"{status_msg}\n"
        f"🎯 **Hedef Grup:** {target_info}\n\n"
        "Ne aramak istersin?"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
        [Button.inline("⚙️ Hedef Seç (Admin)", b"set_target")],
        [Button.url("📣 Kanalımız", KANAL_LINKI), Button.url("👨‍💻 Admin / Destek", f"https://t.me/{ADMIN_USER}")]
    ]
    await event.respond(text, buttons=buttons)

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    is_allowed, info = check_license(user_id)
    
    if data == "set_target":
        if user_id != ADMIN_ID: return await event.answer("⛔ Sadece Admin!", alert=True)
        try:
            dialogs = await client.get_dialogs(limit=15)
            buttons = []
            for d in dialogs:
                if d.is_group or d.is_channel:
                    buttons.append([Button.inline(f"📂 {d.title}", f"target_{d.id}")])
            buttons.append([Button.inline("🔙 İptal", b"main_menu")])
            await event.edit("🎯 **Hedef Grubu Seçin:**", buttons=buttons)
        except: await event.answer("Botu gruba yönetici yapın!", alert=True)

    elif data.startswith("target_"):
        chat_id = int(data.split("_")[1])
        BOT_CONFIG["target_chat_id"] = chat_id
        save_config(BOT_CONFIG) # Kalıcı kaydet
        await event.edit(f"✅ Hedef ID: `{chat_id}` kaydedildi.", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

    elif data == "search_keyword":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Önce Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit("🔍 **Aranacak kelimeyi yazın:**\n\nÖrn: `Yazılım`, `İfşa`, `Kripto`", buttons=None)

    elif data == "search_site":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Önce Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit("🌐 **Hangi site taransın?**\n\nÖrn: `tgstat.com` veya `reddit.com`", buttons=None)

    elif data == "main_menu":
        await start_handler(event)

@client.on(events.NewMessage)
async def input_handler(event):
    user_id = event.sender_id
    if user_id not in USER_STATES: return
    
    text = event.message.text
    state = USER_STATES[user_id]
    del USER_STATES[user_id]
    
    is_allowed, info = check_license(user_id)
    if not is_allowed: return await event.respond("⛔ **Limit Doldu!**\nDevamı için: @yasin33")

    msg = await event.respond("🚀 **Motorlar Çalıştırılıyor...**")
    
    # SORGULARI AYARLA
    if state == "KEYWORD":
        # Hibrit Arama
        query = f'site:t.me "{text}" (chat OR group OR sohbet)'
        log_txt = f"Kelime: {text}"
        
    elif state == "SITE":
        # Site İçi Arama
        domain = text.replace("https://", "").replace("http://", "").split("/")[0]
        query = f'site:{domain} "t.me"'
        log_txt = f"Site: {domain}"
    
    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    
    # Sayfaları gez
    for page in range(1, SAYFA_SAYISI + 1):
        if toplanan >= HEDEF_LINK_LIMITI: break
        
        can_continue, _ = check_license(user_id)
        if not can_continue:
            await client.send_message(user_id, "⛔ Deneme hakkınız bitti.")
            break

        try: await msg.edit(f"🔎 **Taranıyor ({log_txt})...**\nSayfa: {page}\nBulunan: {toplanan}")
        except: pass
        
        links = google_search(query, page)
        
        if not links:
            # Boş sayfada bekleme yapma
            pass

        for link in links:
            can_send, _ = check_license(user_id)
            if not can_send: break

            if link not in history:
                try:
                    await client.send_message(target_id, link, link_preview=False)
                    history.add(link)
                    save_history(link)
                    consume_credit(user_id)
                    toplanan += 1
                    await asyncio.sleep(2.5) # Güvenli mod
                except Exception as e: logger.error(f"Gönderim hatası: {e}")
        
        await asyncio.sleep(1)

    await msg.edit(f"🏁 **Tamamlandı!** Toplam {toplanan} link bulundu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
