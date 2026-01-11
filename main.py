import os
import logging
import asyncio
import re
import time
import json
import requests
import urllib3
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

# 🔥 SAHİP AYARLARI
env_admin = os.environ.get("ADMIN_ID", os.environ.get("OWNER_ID", "0"))
ADMIN_ID = int(env_admin)

# LİMİTLER
DENEME_HAKKI = 3       
SAYFA_SAYISI = 5       # Daha derin arama için 5 yaptık
HEDEF_LINK_LIMITI = 50 

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcode" 
ADMIN_USER = "yasin33" 

# Loglama & Susturma
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("ProBotV3")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Bot V3 Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_v3", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı
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
    """Dizin sitelerinden temiz link çeker"""
    if "t.me/" in url: return url
    username = ""
    # Hottg, Tgstat vb. temizleme
    if "hottg.com" in url: username = url.split("/")[-1]
    elif "tgstat" in url and "@" in url: username = url.split("@")[-1]
    elif "telemetr.io" in url:
        parts = url.split("/")[-1]
        username = parts.split("-", 1)[1] if "-" in parts else parts
    
    username = username.split("?")[0].strip()
    if re.match(r'^[a-zA-Z0-9_]{4,}$', username):
        return f"https://t.me/{username}"
    return None

# ==================== LİNK ÇÖZÜCÜ (ID + TOPIC) ====================

async def resolve_target_link(link):
    link = link.strip().replace("https://", "").replace("http://", "").replace("t.me/", "")
    chat_id = None
    topic_id = None
    
    try:
        if "c/" in link:
            parts = link.split("c/")[1].split("/")
            chat_id = int("-100" + parts[0])
            if len(parts) > 1 and parts[1].isdigit():
                topic_id = int(parts[1])
        else:
            parts = link.split("/")
            username = parts[0]
            try:
                entity = await client.get_entity(username)
                chat_id = entity.id
                if not str(chat_id).startswith("-100"): 
                    chat_id = int(f"-100{str(chat_id).replace('-','')}")
            except: return None, None
            
            if len(parts) > 1 and parts[1].isdigit():
                topic_id = int(parts[1])
                
        return chat_id, topic_id
    except: return None, None

# ==================== GOOGLE API (GELİŞMİŞ) ====================

def google_search(query, page=1):
    found = []
    # Her sayfa 10 sonuç. 1->1, 2->11, 3->21...
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
        
        # Regex: Sadece geçerli Telegram linklerini al
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+|s/)?[\w\d_\-]+')
        
        for item in data['items']:
            link = item.get('link', '')
            snippet = item.get('snippet', '')
            title = item.get('title', '')
            
            # 1. Link Analizi
            if "t.me/" in link:
                found.append(link.split("?")[0])
            
            # 2. Dizin Sitesi Analizi
            converted = extract_username_from_url(link)
            if converted and "t.me/" in converted:
                found.append(converted)

            # 3. Metin İçi Analizi (Snippet)
            text_block = f"{title} {snippet}"
            matches = regex.findall(text_block)
            for m in matches:
                # /s/ (preview) linklerini normale çevir
                clean = m.rstrip('.,")\'').replace("/s/", "/")
                found.append(clean)
                
    except Exception as e:
        logger.error(f"Hata: {e}")
        
    return list(set(found))

# ==================== MENÜLER ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    
    status_msg = "👑 **Mod:** Yönetici" if info == "admin" else f"⏳ **Hak:** {DENEME_HAKKI - info}"
    
    target_id = BOT_CONFIG.get("target_chat_id")
    target_info = f"✅ `{target_id}`" if target_id else "❌ Ayarlı Değil"

    text = (
        f"👋 **Selam {user.first_name}!**\n"
        f"🤖 **Profesyonel Link Avcısı**\n\n"
        f"{status_msg}\n"
        f"🎯 **Hedef:** {target_info}\n\n"
        "Ne yapmak istersin?"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
        [Button.inline("⚙️ Hedef Seç (Liste)", b"set_target"), Button.inline("📌 Hedef (Link)", b"set_target_help")],
        [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
    ]
    await event.respond(text, buttons=buttons)

# 🔥 MANUEL HEDEF KOMUTU
@client.on(events.NewMessage(pattern='/hedef'))
async def manual_target(event):
    if event.sender_id != ADMIN_ID: return await event.reply("⛔ Sadece Admin!")
    try:
        link = event.message.text.split(" ", 1)[1]
        cid, tid = await resolve_target_link(link)
        if cid:
            BOT_CONFIG["target_chat_id"] = cid
            BOT_CONFIG["target_topic_id"] = tid
            save_config(BOT_CONFIG)
            msg = f"✅ **Hedef Ayarlandı!**\n🆔 `{cid}`"
            if tid: msg += f"\n📂 Topic: `{tid}`"
            await event.reply(msg)
        else:
            await event.reply("❌ Link geçersiz.")
    except:
        await event.reply("❌ Kullanım: `/hedef https://t.me/c/123/456`")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    is_allowed, info = check_license(user_id)
    
    if data == "set_target":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        try:
            dialogs = await client.get_dialogs(limit=None)
            buttons = []
            count = 0
            for d in dialogs:
                if (d.is_group or d.is_channel) and count < 20:
                    buttons.append([Button.inline(f"📂 {d.title}", f"target_{d.id}")])
                    count += 1
            if not buttons:
                await event.edit("⚠️ Grup bulunamadı.", buttons=[[Button.inline("🔙 Ana Menü", b"main_menu")]])
            else:
                buttons.append([Button.inline("🔙 İptal", b"main_menu")])
                await event.edit("🎯 **Listeden Seç:**", buttons=buttons)
        except: 
            await event.edit("⚠️ Hata oluştu. `/hedef` kullan.", buttons=[[Button.inline("🔙 Ana Menü", b"main_menu")]])

    elif data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        await event.edit(
            "⚙️ **Link ile Hedef:**\n\n"
            "1. Gruba git, başlığın linkini kopyala.\n"
            "2. `/hedef <LİNK>` yaz.\n\n"
            "Örn: `/hedef https://t.me/c/12345/100`",
            buttons=[[Button.inline("🔙 Ana Menü", b"main_menu")]]
        )

    elif data.startswith("target_"):
        chat_id = int(data.split("_")[1])
        BOT_CONFIG["target_chat_id"] = chat_id
        save_config(BOT_CONFIG)
        await event.edit(f"✅ Hedef: `{chat_id}`", buttons=[[Button.inline("🔙 Ana Menü", b"main_menu")]])

    elif data == "search_keyword":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        # Geri butonu eklendi
        await event.edit("🔍 **Aranacak kelimeyi yazın:**\n\nÖrn: `Yazılım`, `İfşa`, `Ticaret`", 
                         buttons=[[Button.inline("🔙 İptal", b"main_menu")]])

    elif data == "search_site":
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Önce Hedef Seçilmeli!", alert=True)
        USER_STATES[user_id] = "SITE"
        # Geri butonu eklendi
        await event.edit("🌐 **Hangi site taransın?**\n\nÖrn: `tgstat.com`", 
                         buttons=[[Button.inline("🔙 İptal", b"main_menu")]])

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
    if not is_allowed: 
        await event.respond("⛔ **Limit Doldu!**", buttons=[[Button.inline("🔙 Ana Menü", b"main_menu")]])
        return

    msg = await event.respond("🚀 **Gelişmiş Tarama Başlatılıyor...**")
    
    # GELİŞMİŞ SORGULAR (Dandik linkleri elemek için)
    queries = []
    if state == "KEYWORD":
        # 1. Joinchat (Özel davet linkleri - En kalitelisi)
        queries.append(f'site:t.me joinchat "{text}"')
        # 2. View in Telegram (Genel kanallar)
        queries.append(f'site:t.me "View in Telegram" "{text}"')
        # 3. Dizinler (Yedek güç)
        queries.append(f'(site:tgstat.com OR site:telemetr.io) "{text}"')
        log_txt = f"Kelime: {text}"
        
    elif state == "SITE":
        domain = text.replace("https://", "").split("/")[0]
        queries.append(f'site:{domain} "t.me"')
        log_txt = f"Site: {domain}"
    
    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    target_topic = BOT_CONFIG.get("target_topic_id")
    
    # TÜM SORGULARI DÖN
    for q in queries:
        if toplanan >= HEDEF_LINK_LIMITI: break
        
        for page in range(1, SAYFA_SAYISI + 1):
            if toplanan >= HEDEF_LINK_LIMITI: break
            
            can_continue, _ = check_license(user_id)
            if not can_continue:
                await client.send_message(user_id, "⛔ Deneme hakkınız bitti.")
                break

            try: await msg.edit(f"🔎 **Taranıyor ({log_txt})...**\nSorgu Tipi: {queries.index(q)+1}/{len(queries)}\nSayfa: {page}\nBulunan: {toplanan}")
            except: pass
            
            links = google_search(q, page)
            
            for link in links:
                can_send, _ = check_license(user_id)
                if not can_send: break

                # Filter: Alakasız linkleri atla
                if any(x in link for x in ["setlanguage", "stickers", "addstickers", "iv?"]): continue

                if link not in history:
                    try:
                        await client.send_message(
                            entity=target_id, 
                            message=link, 
                            reply_to=target_topic, 
                            link_preview=False
                        )
                        history.add(link)
                        save_history(link)
                        consume_credit(user_id)
                        toplanan += 1
                        await asyncio.sleep(2.5) 
                    except Exception as e: logger.error(f"Gönderim hatası: {e}")
            
            await asyncio.sleep(1)

    # İŞLEM BİTİNCE MENÜYE DÖN BUTONU
    await msg.edit(
        f"🏁 **Tamamlandı!** Toplam {toplanan} link bulundu.",
        buttons=[[Button.inline("🔙 Ana Menüye Dön", b"main_menu")]]
    )

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
