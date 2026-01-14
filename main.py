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
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat, User, InputMessagesFilterUrl
from curl_cffi import requests as cureq
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "") # Opsiyonel Userbot

# GOOGLE API
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "")
GOOG_CX = os.environ.get("GOOG_CX", "")

# SAHİP AYARLARI
env_admin = os.environ.get("ADMIN_ID", os.environ.get("OWNER_ID", "0"))
ADMIN_ID = int(env_admin)

# LİMİTLER
DENEME_HAKKI = 3       
SAYFA_SAYISI = 7       
HEDEF_LINK_LIMITI = 200 
GRUP_TARAMA_LIMITI = 1000 

# Markalama
BOT_NAME = "Yael Tg Grup Bulma Botu"
KANAL_LINKI = "https://t.me/yaelcodetr" 
ADMIN_USER = "yasin33" 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("LinkRadar_V21")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return f"{BOT_NAME} Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# 1. NORMAL BOT (Arayüz ve Gönderim İçin)
bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# 2. USERBOT (Tarama İçin - Varsa)
userbot = None
if SESSION_STRING:
    try:
        userbot = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        logger.info("✅ Userbot Aktif: Grup tarama tam güç çalışacak.")
    except Exception as e:
        logger.warning(f"⚠️ Userbot Başlatılamadı: {e}")

# Veritabanı
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 
USER_STATES = {}
RUNTIME_HISTORY = set() # Anlık hafıza

# ==================== YARDIMCI FONKSİYONLAR ====================

def load_config():
    if not os.path.exists(CONFIG_FILE): return {"target_chat_id": None, "target_topic_id": None}
    try: with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"target_chat_id": None, "target_topic_id": None}

def save_config(data):
    with open(CONFIG_FILE, "w") as f: json.dump(data, f)

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

# HAFIZA SENKRONİZASYONU
async def sync_history_from_group():
    target = BOT_CONFIG.get("target_chat_id")
    if not target: return
    try:
        # Bot kendi attığı mesajları okur
        async for message in bot.iter_messages(target, limit=1000):
            if message.text:
                regex = re.compile(r'(?:https?://)?t\.me/[\w\d_+\-]+')
                for m in regex.findall(message.text): RUNTIME_HISTORY.add(m)
    except: pass

async def resolve_target_link(link):
    link = link.strip().replace("https://", "").replace("t.me/", "")
    chat_id = None; topic_id = None
    try:
        if "c/" in link:
            parts = link.split("c/")[1].split("/")
            chat_id = int("-100" + parts[0])
            if len(parts) > 1 and parts[1].isdigit(): topic_id = int(parts[1])
        else:
            parts = link.split("/")
            username = parts[0]
            try:
                # Botun gördüğü entity'i al
                entity = await bot.get_entity(username)
                chat_id = int(f"-100{entity.id}") if not str(entity.id).startswith("-100") else entity.id
            except: return None, None
            if len(parts) > 1 and parts[1].isdigit(): topic_id = int(parts[1])
        return chat_id, topic_id
    except: return None, None

def clean_and_format_link(link):
    try:
        link = link.strip().split("?")[0].rstrip(".,'\"")
        ignore = ["setlanguage", "iv?", "share/url", "socks", "proxy", "contact"]
        if any(x in link for x in ignore): return None
        if not link.startswith("http"):
            if "t.me" not in link: link = f"https://t.me/{link}"
            else: link = f"https://{link}"
        if "t.me/" in link and len(link) > 10: return link
    except: pass
    return None

# ==================== 🔥 GRUP TARAMA (FİXLENDİ) ====================

async def scrape_from_telegram_group(source_link, limit=500):
    found_links = set()
    
    # Hangi client'ı kullanacağız?
    # Userbot varsa onu kullan (Her yere girer)
    # Yoksa Bot'u kullan (Sadece olduğu grupları görür)
    if userbot and userbot.is_connected():
        client_to_use = userbot
        worker_name = "Userbot"
    else:
        client_to_use = bot
        worker_name = "Bot"

    logger.info(f"♻️ Grup Taranıyor ({worker_name}): {source_link}")
    
    try:
        # Önce linki çözümle (Invite link mi yoksa public mi?)
        if "joinchat" in source_link or "+" in source_link:
            try:
                # Private link ise katılmaya çalış (Sadece Userbot yapabilir)
                if worker_name == "Userbot":
                    entity = await client_to_use.join_chat(source_link)
                else:
                    logger.error("❌ Bot özel linklere katılamaz. Userbot (Session) ekleyin.")
                    return []
            except Exception as e:
                logger.error(f"Gruba girilemedi: {e}")
                return []
        else:
            try:
                entity = await client_to_use.get_entity(source_link)
            except Exception as e:
                logger.error(f"Grup bulunamadı ({worker_name}): {e}")
                return []

        # Mesajları Tara
        async for message in client_to_use.iter_messages(entity, limit=limit):
            # Metin içindeki linkler
            if message.text:
                regex = re.compile(r'(?:https?://)?t\.me/[\w\d_+\-]+')
                for m in regex.findall(message.text):
                    formatted = clean_and_format_link(m)
                    if formatted: found_links.add(formatted)
            
            # Butonlardaki linkler
            if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                for row in message.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'url') and btn.url and "t.me" in btn.url:
                            found_links.add(clean_and_format_link(btn.url))
            
            # Entities (Metne gömülü linkler)
            if message.entities:
                for ent in message.entities:
                    if hasattr(ent, 'url') and ent.url and "t.me" in ent.url:
                        found_links.add(clean_and_format_link(ent.url))

    except Exception as e:
        logger.error(f"Grup Tarama Hatası: {e}")
        
    logger.info(f"✅ {worker_name} {len(found_links)} link buldu.")
    return list(found_links)

# ==================== DİĞER TARAYICILAR ====================

def fetch_combot_api(url):
    found = []
    logger.info("🔓 Combot API...")
    lang = "tr"
    if "lng=" in url:
        try: lang = url.split("lng=")[1].split("&")[0]
        except: pass
    
    api_url = f"https://combot.org/api/chart/all?limit=100&offset=0&lang={lang}"
    try:
        resp = requests.get(api_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        if resp.status_code == 200:
            for item in resp.json():
                if 'u' in item: found.append(f"https://t.me/{item['u']}")
    except: pass
    return found

def scrape_site_content(url):
    if "combot.org" in url: return fetch_combot_api(url)
    found = set()
    logger.info(f"🌐 Site: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = cureq.get(url, headers=headers, impersonate="chrome124", timeout=25)
        regex = re.compile(r'(?:https?://)?(?:www\.)?t\.me/[\w\d_+\-]+')
        for m in regex.findall(response.text):
            formatted = clean_and_format_link(m)
            if formatted: found.add(formatted)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            if "t.me" in a['href']: found.add(clean_and_format_link(a['href']))
    except: pass
    return list(found)

def google_search(query):
    found = []
    if not GOOG_API_KEY: return []
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        for page in range(0, 20, 10):
            params = {'key': GOOG_API_KEY, 'cx': GOOG_CX, 'q': query, 'start': page+1, 'num': 10}
            resp = requests.get(url, params=params).json()
            if "items" not in resp: break
            for item in resp['items']:
                text = f"{item['link']} {item['snippet']}"
                regex = re.compile(r't\.me/[\w\d_+\-]+')
                for m in regex.findall(text): found.append(clean_and_format_link(m))
    except: pass
    return list(set([f for f in found if f]))

def duckduckgo_search(query):
    found = []
    try:
        with DDGS() as ddgs:
            for region in ['tr-tr', 'wt-wt']:
                results = ddgs.text(query, region=region, safesearch='off', max_results=50)
                for r in results:
                    text = f"{r['href']} {r['body']}"
                    regex = re.compile(r't\.me/[\w\d_+\-]+')
                    for m in regex.findall(text): found.append(clean_and_format_link(m))
    except: pass
    return list(set([f for f in found if f]))

# ==================== MENÜLER ====================

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    if event.is_private:
        asyncio.create_task(sync_history_from_group())
        user = await event.get_sender()
        is_allowed, info = check_license(user.id)
        status = "👑 **Yönetici**" if info == "admin" else f"⏳ **Hak:** {DENEME_HAKKI - info}"
        tid = BOT_CONFIG.get("target_chat_id")
        t_info = f"✅ `{tid}`" if tid else "❌ **AYARSIZ**"
        
        # Userbot Bilgisi
        ub_txt = "✅ Userbot Aktif" if userbot and userbot.is_connected() else "⚠️ Userbot Yok (Kısıtlı)"

        text = (
            f"👋 **{BOT_NAME}**\n\n"
            f"{status}\n"
            f"🎯 **Hedef:** {t_info}\n"
            f"🤖 **Mod:** {ub_txt}\n\n"
            "👇 **Ne Lazım?**"
        )
        
        buttons = [
            [Button.inline("🔍 Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
            [Button.inline("♻️ Gruptan Çek", b"scrape_group")],
            [Button.inline("⚙️ Hedef Ayarla", b"set_target_help")],
            [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
        ]
        await event.respond(text, buttons=buttons)

@bot.on(events.NewMessage(pattern='/kur'))
async def setup_here(event):
    if event.sender_id != ADMIN_ID: return
    BOT_CONFIG["target_chat_id"] = event.chat_id
    BOT_CONFIG["target_topic_id"] = event.reply_to_msg_id if event.is_reply else None
    save_config(BOT_CONFIG)
    asyncio.create_task(sync_history_from_group())
    await event.reply(f"✅ **BAŞARILI!**\n🆔 `{event.chat_id}`")

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Admin Only!", alert=True)
        await event.edit("⚙️ **Kurulum:**\nHedef topic'e gir, **/kur** yaz.", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_keyword":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Bitti!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit("🔍 **Hangi Kelime?**", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_site":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Bitti!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit("🌐 **Hangi Site?**\n(Örn: combot.org)", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "scrape_group":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Bitti!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        USER_STATES[user_id] = "GROUP_SCRAPE"
        
        # Uyarı metni
        warning = "\n⚠️ **Uyarı:** Userbot yoksa sadece botun olduğu gruplar çalışır." if not userbot else ""
        await event.edit(f"♻️ **Kaynak Grup Linki?**{warning}", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "main_menu":
        await start_handler(event)

@bot.on(events.NewMessage)
async def input_handler(event):
    if event.is_group or event.message.text.startswith("/"): return
    user_id = event.sender_id
    if user_id not in USER_STATES: return
    
    text = event.message.text
    state = USER_STATES[user_id]
    del USER_STATES[user_id]
    
    is_allowed, info = check_license(user_id)
    if not is_allowed: return await event.respond("⛔ **Bitti.**")

    msg = await event.respond("🚀 **Başlıyoruz...**")
    raw_links = []
    
    if state == "KEYWORD":
        keywords = [k.strip() for k in text.split(",")]
        for kw in keywords:
            qs = [
                f'site:t.me "{kw}"', 
                f'(site:tgstat.com OR site:telemetr.io) "{kw}"'
            ]
            for q in qs:
                try: await msg.edit(f"🔎 **Aranıyor:** `{kw}`")
                except: pass
                raw_links.extend(google_search(q))
                raw_links.extend(duckduckgo_search(q))
                await asyncio.sleep(1)

    elif state == "SITE":
        try: await msg.edit(f"🌐 **Site Kazılıyor...**")
        except: pass
        if "http" not in text: text = "https://" + text
        raw_links = scrape_site_content(text)

    elif state == "GROUP_SCRAPE":
        try: await msg.edit(f"♻️ **Grup Taranıyor...**")
        except: pass
        raw_links = await scrape_from_telegram_group(text, limit=GRUP_TARAMA_LIMITI)

    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    target_topic = BOT_CONFIG.get("target_topic_id")
    
    unique_links = list(set([l for l in raw_links if l])) # Temizle
    
    if not unique_links:
        await msg.edit("❌ **Sonuç Yok.**", buttons=[[Button.inline("🔙", b"main_menu")]])
        return

    await msg.edit(f"🧐 **{len(unique_links)} Link Bulundu.**\nAyıklanıyor ve atılıyor...")

    for link in unique_links:
        if toplanan >= HEDEF_LINK_LIMITI: break
        can_continue, _ = check_license(user_id)
        if not can_continue: break

        # Hafıza Kontrolü
        if link not in history and link not in RUNTIME_HISTORY:
            try:
                await bot.send_message(target_id, link, reply_to=target_topic, link_preview=False)
                history.add(link)
                save_history(link)
                RUNTIME_HISTORY.add(link)
                consume_credit(user_id)
                toplanan += 1
                await asyncio.sleep(1.5)
            except Exception as e: logger.error(f"Hata: {e}")
    
    await msg.edit(f"🏁 **Tamamlandı!**\n**{toplanan}** yeni link atıldı.", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

# ==================== ANA DÖNGÜ ====================
async def main():
    if userbot:
        logger.info("✅ Userbot Başlatılıyor...")
        await userbot.start()
    
    logger.info("✅ Bot Başlatılıyor...")
    await bot.start()
    await bot.run_until_disconnected()

if __name__ == '__main__':
    keep_alive()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
