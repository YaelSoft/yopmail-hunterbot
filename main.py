import os
import sys
import logging
import asyncio
import re
import json
import requests
import urllib3
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events, Button
from telethon.tl.types import Channel, Chat, User, InputMessagesFilterUrl
from telethon.errors import FloodWaitError, ChannelPrivateError
from curl_cffi import requests as cureq
from bs4 import BeautifulSoup

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
SAYFA_SAYISI = 4       
HEDEF_LINK_LIMITI = 50 
GRUP_TARAMA_LIMITI = 500 

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcode" 
ADMIN_USER = "yasin33" 
BOT_NAME = "LinkRadar V12 Final"

# Loglama
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger("LinkRadar")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return f"{BOT_NAME} Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_v12_fix", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı Dosyaları
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 
USER_STATES = {}

# ==================== VERİTABANI YÖNETİMİ (DÜZELTİLDİ) ====================

def load_config():
    if not os.path.exists(CONFIG_FILE): 
        return {"target_chat_id": None, "target_topic_id": None}
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {"target_chat_id": None, "target_topic_id": None}

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

# ==================== LİNK DOĞRULAMA & ÇÖZME ====================

async def resolve_target_link(link):
    link = link.strip().replace("https://", "").replace("t.me/", "")
    chat_id = None
    topic_id = None
    try:
        if "c/" in link:
            parts = link.split("c/")[1].split("/")
            chat_id = int("-100" + parts[0])
            if len(parts) > 1 and parts[1].isdigit(): topic_id = int(parts[1])
        else:
            parts = link.split("/")
            username = parts[0]
            try:
                entity = await client.get_entity(username)
                chat_id = int(f"-100{entity.id}") if not str(entity.id).startswith("-100") else entity.id
            except: return None, None
            if len(parts) > 1 and parts[1].isdigit(): topic_id = int(parts[1])
        return chat_id, topic_id
    except: return None, None

async def validate_link(link):
    try:
        clean_link = link.split("?")[0].strip()
        # Gizli linkleri ve joinchatleri ele (Müşteri isteği)
        if "joinchat" in clean_link or "+" in clean_link: return False, None
        
        try: entity = await client.get_entity(clean_link)
        except: return False, None

        if isinstance(entity, User): return False, None
        if isinstance(entity, (Channel, Chat)):
            if entity.username:
                return True, f"https://t.me/{entity.username}"
            else:
                return False, None
    except: return False, None
    return False, None

# ==================== KAZIYICILAR ====================

def scrape_site_content(url):
    found = set()
    logger.info(f"🌐 Siteye Giriliyor: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        response = cureq.get(url, headers=headers, impersonate="chrome124", timeout=20)
        
        # Regex
        regex = re.compile(r'https?://(?:www\.)?t\.me/[\w\d_]{4,}')
        for m in regex.findall(response.text): found.add(m)

        # HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if "t.me" in href and "joinchat" not in href and "+" not in href:
                found.add(href)
            
    except Exception as e: logger.error(f"Site Hatası: {e}")
    return list(found)

async def scrape_from_telegram_group(source_link, limit=500):
    found_links = set()
    logger.info(f"♻️ Gruba Bağlanılıyor: {source_link}")
    try:
        entity = await client.get_entity(source_link)
        async for message in client.iter_messages(entity, limit=limit, filter=InputMessagesFilterUrl):
            if message.text:
                regex = re.compile(r'https?://(?:www\.)?t\.me/[\w\d_]{4,}')
                for m in regex.findall(message.text): found_links.add(m)
            if message.reply_markup:
                if hasattr(message.reply_markup, 'rows'):
                    for row in message.reply_markup.rows:
                        for btn in row.buttons:
                            if hasattr(btn, 'url') and btn.url and "t.me" in btn.url and "joinchat" not in btn.url:
                                found_links.add(btn.url)
    except Exception as e: logger.error(f"Grup Hatası: {e}")
    return list(found_links)

# ==================== GOOGLE API ====================

def google_search(query, page=1):
    found = []
    if not GOOG_API_KEY: return []
    start_index = ((page - 1) * 10) + 1
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOG_API_KEY, 'cx': GOOG_CX, 'q': query, 'start': start_index, 'num': 10}
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        if "items" not in data: return []
        
        # Sadece username olanları al
        regex = re.compile(r'https?://(?:www\.)?t\.me/[\w\d_]{4,}')
        for item in data['items']:
            text = f"{item.get('link')} {item.get('snippet')} {item.get('title')}"
            for m in regex.findall(text): found.append(m.rstrip('.,")\''))
    except: pass
    return list(set(found))

# ==================== MENÜLER ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.is_private:
        user = await event.get_sender()
        is_allowed, info = check_license(user.id)
        status = "👑 **Yönetici**" if info == "admin" else f"⏳ **Hak:** {DENEME_HAKKI - info}"
        
        tid = BOT_CONFIG.get("target_chat_id")
        topic = BOT_CONFIG.get("target_topic_id")
        target_info = f"✅ `{tid}`" if tid else "❌ **AYARLANMADI**"
        if topic: target_info += f" (T: {topic})"

        text = (
            f"👋 **{BOT_NAME} Paneli**\n\n"
            f"{status}\n"
            f"🎯 **Hedef:** {target_info}\n\n"
            "👇 **İşlem Seç:**"
        )
        
        buttons = [
            [Button.inline("🔍 Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
            [Button.inline("♻️ Gruptan Çek", b"scrape_group")],
            [Button.inline("⚙️ Hedef Nasıl Ayarlanır?", b"set_target_help")],
            [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
        ]
        await event.respond(text, buttons=buttons)

@client.on(events.NewMessage(pattern='/hedef'))
async def manual_target(event):
    if event.sender_id != ADMIN_ID: return
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
            await event.reply("❌ Linkten ID çözülemedi. Lütfen `t.me/c/...` veya `t.me/grup` formatında atın.")
    except:
        await event.reply("❌ **Kullanım:** `/hedef <LINK>`")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        await event.edit(
            "⚙️ **Hedef Ayarlama:**\n\n"
            "Linklerin atılacağı grubun/konunun bağlantısını kopyala ve bana şöyle at:\n\n"
            "`/hedef https://t.me/c/123456/100`\n\n"
            "Ben ID'leri otomatik kaydederim.",
            buttons=[[Button.inline("🔙", b"main_menu")]]
        )

    elif data == "search_keyword":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce /hedef ile grup ayarla", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit("🔍 **Aranacak Kelime?**", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_site":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce /hedef ayarla", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit("🌐 **Site Linki?**\n(Örn: combot.org/...)", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "scrape_group":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce /hedef ayarla", alert=True)
        USER_STATES[user_id] = "GROUP_SCRAPE"
        await event.edit("♻️ **Kaynak Grup Linki?**", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "main_menu":
        await start_handler(event)

@client.on(events.NewMessage)
async def input_handler(event):
    if event.is_group or event.message.text.startswith("/"): return
    user_id = event.sender_id
    if user_id not in USER_STATES: return
    
    text = event.message.text
    state = USER_STATES[user_id]
    del USER_STATES[user_id]
    
    is_allowed, info = check_license(user_id)
    if not is_allowed: return await event.respond("⛔ **Limit Doldu!**", buttons=[[Button.inline("🔙", b"main_menu")]])

    msg = await event.respond("🚀 **İşlem Başlatılıyor...**")
    raw_links = []
    
    if state == "KEYWORD":
        keywords = [k.strip() for k in text.split(",")]
        for kw in keywords:
            # Sadece site:t.me araması, joinchat eledik
            qs = [f'site:t.me "{kw}"']
            for q in qs:
                for page in range(1, SAYFA_SAYISI + 1):
                    try: await msg.edit(f"🔎 **Aranıyor:** `{kw}`\nSayfa: {page}")
                    except: pass
                    raw_links.extend(google_search(q, page))
                    await asyncio.sleep(1)

    elif state == "SITE":
        try: await msg.edit(f"🌐 **Site Taranıyor...**\n`{text[:30]}...`")
        except: pass
        if "http" not in text: text = "https://" + text
        raw_links = scrape_site_content(text)

    elif state == "GROUP_SCRAPE":
        try: await msg.edit(f"♻️ **Grup Analiz Ediliyor...**")
        except: pass
        raw_links = await scrape_from_telegram_group(text, limit=GRUP_TARAMA_LIMITI)

    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    target_topic = BOT_CONFIG.get("target_topic_id")
    
    if not raw_links:
        await msg.edit("❌ **Sonuç Yok.**", buttons=[[Button.inline("🔙", b"main_menu")]])
        return

    unique_links = list(set(raw_links))
    await msg.edit(f"🧐 **{len(unique_links)} Link Bulundu.**\nKalite kontrolü yapılıyor...")

    for link in unique_links:
        if toplanan >= HEDEF_LINK_LIMITI: break
        can_continue, _ = check_license(user_id)
        if not can_continue: break

        if link not in history:
            is_valid, final_link = await validate_link(link)
            if is_valid and final_link:
                try:
                    await client.send_message(target_id, final_link, reply_to=target_topic, link_preview=False)
                    history.add(final_link)
                    save_history(final_link)
                    consume_credit(user_id)
                    toplanan += 1
                    await asyncio.sleep(4)
                except Exception as e: logger.error(f"Hata: {e}")
    
    await msg.edit(f"🏁 **Tamamlandı!**\n**{toplanan}** adet temiz link atıldı.", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
