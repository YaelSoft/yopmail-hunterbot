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

# SAHİP AYARLARI
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
logger = logging.getLogger("LinkHunterPRO")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Link Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_link", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 
USER_STATES = {}

# ==================== VERİTABANI YÖNETİMİ ====================

def load_config():
    if not os.path.exists(CONFIG_FILE): return {"chat_id": None, "topic_id": None}
    try:
        with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"chat_id": None, "topic_id": None}

def save_config(data):
    with open(CONFIG_FILE, "w") as f: json.dump(data, f)

# Config Yükle
BOT_CONFIG = load_config()

def load_credits():
    if not os.path.exists(CREDITS_FILE): return {}
    try: with open(CREDITS_FILE, "r") as f: return json.load(f)
    except: return {}

def save_credits(data):
    with open(CREDITS_FILE, "w") as f: json.dump(data, f)

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
    try: with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(line.strip() for line in f)
    except: return set()

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(f"{link}\n")

def extract_username_from_url(url):
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

# ==================== LİNK ÇÖZÜCÜ (AGANIN İSTEDİĞİ ÖZELLİK) ====================

async def resolve_target_link(link):
    """
    Kullanıcının attığı linki (t.me/c/123/456) ID ve Topic ID'ye çevirir.
    """
    link = link.strip().replace("https://", "").replace("http://", "").replace("t.me/", "")
    
    chat_id = None
    topic_id = None
    
    try:
        # DURUM 1: Özel Grup Linki (t.me/c/123456789/100)
        if "c/" in link:
            parts = link.split("c/")[1].split("/")
            # İlk parça Chat ID'dir (Başında -100 olmalı)
            chat_id = int("-100" + parts[0])
            
            # İkinci parça Topic ID olabilir
            if len(parts) > 1 and parts[1].isdigit():
                topic_id = int(parts[1])
                
        # DURUM 2: Genel Grup Linki (t.me/username/100)
        else:
            parts = link.split("/")
            username = parts[0]
            
            # Username'i ID'ye çevirmemiz lazım
            try:
                entity = await client.get_entity(username)
                chat_id = entity.id
                # Telethon bazen -100 eklemez, biz ekleyelim
                if str(chat_id).startswith("-100"): pass
                else: chat_id = int(f"-100{str(chat_id).replace('-','')}")
            except:
                return None, None # Bot grubu göremiyor
            
            if len(parts) > 1 and parts[1].isdigit():
                topic_id = int(parts[1])
                
        return chat_id, topic_id
        
    except Exception as e:
        logger.error(f"Link Parse Hatası: {e}")
        return None, None

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
        if "error" in data: return []
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
                
    except: pass
    return list(set(found))

# ==================== MENÜLER ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    status_msg = "👑 **Mod:** Yönetici" if info == "admin" else f"⏳ **Hak:** {DENEME_HAKKI - info}"
    
    cid = BOT_CONFIG.get("chat_id")
    tid = BOT_CONFIG.get("topic_id")
    target_info = "❌ Ayarsız"
    if cid:
        target_info = f"✅ Grup: `{cid}`"
        if tid: target_info += f"\n📂 Konu: `{tid}`"

    text = (
        f"👋 **Selam {user.first_name}!**\n"
        f"🤖 **Link Avcısı Bot** hizmetine hoş geldin.\n\n"
        f"{status_msg}\n"
        f"🎯 **Hedef:**\n{target_info}\n\n"
        "👇 **Ne yapmak istersin?**"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
        [Button.inline("⚙️ Hedef Ayarla (Link ile)", b"set_target_help")],
        [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
    ]
    await event.respond(text, buttons=buttons)

# 🔥 YENİ HEDEF SİSTEMİ (LİNK İLE)
@client.on(events.NewMessage(pattern='/hedef'))
async def manual_target(event):
    if event.sender_id != ADMIN_ID: return await event.reply("⛔ Sadece Admin!")
    
    try:
        link = event.message.text.split(" ", 1)[1]
        cid, tid = await resolve_target_link(link)
        
        if cid:
            BOT_CONFIG["chat_id"] = cid
            BOT_CONFIG["topic_id"] = tid
            save_config(BOT_CONFIG)
            
            msg = f"✅ **Hedef Başarıyla Ayarlandı!**\n🆔 Grup ID: `{cid}`"
            if tid: msg += f"\n📂 Topic ID: `{tid}`"
            await event.reply(msg)
        else:
            await event.reply("❌ Linkten ID çözülemedi. Botun o grupta olduğundan emin ol veya özel grup (t.me/c/..) linki kullan.")
            
    except IndexError:
        await event.reply("❌ **Kullanım:** `/hedef <LINK>`\nÖrn: `/hedef https://t.me/c/123456/100`")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    is_allowed, info = check_license(user_id)
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        await event.edit(
            "⚙️ **Hedef Nasıl Ayarlanır?**\n\n"
            "1️⃣ Linklerin atılacağı gruba/konuya git.\n"
            "2️⃣ Başlığa sağ tıkla -> **Link'i Kopyala** de.\n"
            "3️⃣ Buraya gelip şunu yaz:\n\n"
            "`/hedef https://t.me/c/123456/99`\n\n"
            "Ben ID'yi otomatik bulurum.",
            buttons=[[Button.inline("🔙 Menü", b"main_menu")]]
        )

    elif data == "search_keyword":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("chat_id"): return await event.answer("Önce Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit("🔍 **Aranacak kelimeyi yazın:**\n\nÖrn: `Yazılım`, `İfşa`, `Kripto`", buttons=None)

    elif data == "search_site":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("chat_id"): return await event.answer("Önce Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit("🌐 **Hangi site taransın?**\n\nÖrn: `tgstat.com` veya `reddit.com`", buttons=None)

    elif data == "main_menu":
        await start_handler(event)

@client.on(events.NewMessage)
async def input_handler(event):
    user_id = event.sender_id
    if event.message.text.startswith("/"): return
    if user_id not in USER_STATES: return
    
    text = event.message.text
    state = USER_STATES[user_id]
    del USER_STATES[user_id]
    
    is_allowed, info = check_license(user_id)
    if not is_allowed: return await event.respond("⛔ **Limit Doldu!**")

    msg = await event.respond("🚀 **Motorlar Çalıştırılıyor...**")
    
    if state == "KEYWORD":
        query = f'site:t.me "{text}" (chat OR group OR sohbet)'
        log_txt = f"Kelime: {text}"
    elif state == "SITE":
        domain = text.replace("https://", "").replace("http://", "").split("/")[0]
        query = f'site:{domain} "t.me"'
        log_txt = f"Site: {domain}"
    
    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("chat_id")
    target_topic = BOT_CONFIG.get("topic_id")
    
    for page in range(1, SAYFA_SAYISI + 1):
        if toplanan >= HEDEF_LINK_LIMITI: break
        
        can_continue, _ = check_license(user_id)
        if not can_continue:
            await client.send_message(user_id, "⛔ Deneme hakkınız bitti.")
            break

        try: await msg.edit(f"🔎 **Taranıyor ({log_txt})...**\nSayfa: {page}\nBulunan: {toplanan}")
        except: pass
        
        links = google_search(query, page)
        
        for link in links:
            can_send, _ = check_license(user_id)
            if not can_send: break

            if link not in history:
                try:
                    # TOPIC DESTEĞİ EKLENDİ
                    await client.send_message(
                        entity=target_id, 
                        message=link, 
                        reply_to=target_topic, # Topic ID varsa oraya atar
                        link_preview=False
                    )
                    history.add(link)
                    save_history(link)
                    consume_credit(user_id)
                    toplanan += 1
                    await asyncio.sleep(2.5) 
                except Exception as e: logger.error(f"Gönderim hatası: {e}")
        
        await asyncio.sleep(1)

    await msg.edit(f"🏁 **Tamamlandı!** Toplam {toplanan} link bulundu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
