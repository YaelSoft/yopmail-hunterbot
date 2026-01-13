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
from telethon.tl.types import Channel, Chat, User
from curl_cffi import requests as cureq
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS # 🔥 YENİ MOTOR

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# GOOGLE API (Yedek Güç)
GOOG_API_KEY = os.environ.get("GOOG_API_KEY", "")
GOOG_CX = os.environ.get("GOOG_CX", "")

# SAHİP AYARLARI
env_admin = os.environ.get("ADMIN_ID", os.environ.get("OWNER_ID", "0"))
ADMIN_ID = int(env_admin)

# LİMİTLER
DENEME_HAKKI = 3       
SAYFA_SAYISI = 100     # Önemli değil, DuckDuckGo limitsiz basar
HEDEF_LINK_LIMITI = 200 # Limiti artırdık
GRUP_TARAMA_LIMITI = 1000 

# Markalama
BOT_NAME = "Yael Tg Link Search"
KANAL_LINKI = "https://t.me/yaelcodetr" 
ADMIN_USER = "yasin33" 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("Yael Tg Link Search")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return f"{BOT_NAME} Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_v15", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Dosyalar
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 
USER_STATES = {}

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
                entity = await client.get_entity(username)
                chat_id = int(f"-100{entity.id}") if not str(entity.id).startswith("-100") else entity.id
            except: return None, None
            if len(parts) > 1 and parts[1].isdigit(): topic_id = int(parts[1])
        return chat_id, topic_id
    except: return None, None

def clean_and_format_link(link):
    """Süpürge Modu: Ne gelirse formatla ve gönder."""
    try:
        link = link.strip().split("?")[0].rstrip(".,'\"")
        # Gereksizleri at
        ignore = ["setlanguage", "iv?", "share/url", "socks", "proxy", "contact"]
        if any(x in link for x in ignore): return None
        
        if not link.startswith("http"):
            if "t.me" not in link: link = f"https://t.me/{link}"
            else: link = f"https://{link}"
        
        if "t.me/" in link and len(link) > 10:
            return link
    except: pass
    return None

# ==================== 🔥 ÇİFT TURBO MOTOR (DUCK + GOOGLE) ====================

def duckduckgo_search(query):
    """DuckDuckGo ile Global ve Sansürsüz Arama"""
    found = []
    logger.info(f"🦆 DuckDuckGo Aranıyor: {query}")
    try:
        with DDGS() as ddgs:
            # wt-wt = Global Bölge, safesearch=off = Filtresiz
            results = ddgs.text(query, region='wt-wt', safesearch='off', max_results=50)
            
            for r in results:
                # Linkin kendisinde t.me var mı?
                if "t.me/" in r['href']:
                    formatted = clean_and_format_link(r['href'])
                    if formatted: found.append(formatted)
                
                # Açıklamada t.me var mı? (Regex ile sök)
                body_text = f"{r['title']} {r['body']}"
                regex = re.compile(r'(?:https?://)?t\.me/[\w\d_+\-]+')
                for m in regex.findall(body_text):
                    formatted = clean_and_format_link(m)
                    if formatted: found.append(formatted)
                    
    except Exception as e:
        logger.error(f"DuckDuckGo Hatası: {e}")
        
    return list(set(found))

def google_search(query):
    """Google API (Varsa kullanır)"""
    found = []
    if not GOOG_API_KEY: return []
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        # num=10 (maksimum), start=1 (ilk sayfa)
        # Google pahalı olduğu için sadece ilk 2 sayfayı tarıyoruz
        for page in range(0, 20, 10): 
            params = {'key': GOOG_API_KEY, 'cx': GOOG_CX, 'q': query, 'start': page+1, 'num': 10}
            resp = requests.get(url, params=params)
            data = resp.json()
            if "items" not in data: break
            
            regex = re.compile(r'(?:https?://)?t\.me/[\w\d_+\-]+')
            for item in data['items']:
                text = f"{item.get('link')} {item.get('snippet')} {item.get('title')}"
                for m in regex.findall(text): 
                    formatted = clean_and_format_link(m)
                    if formatted: found.append(formatted)
    except: pass
    return list(set(found))

def scrape_site_content(url):
    """Siteyi Chrome gibi açar ve tüm linkleri süpürür"""
    found = set()
    logger.info(f"🌐 Siteye Giriliyor: {url}")
    try:
        # Chrome 124 taklidi (Cloudflare geçmek için)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36'}
        response = cureq.get(url, headers=headers, impersonate="chrome124", timeout=25)
        
        # 1. Regex ile metin tarama (Sayfada yazan her t.me linki)
        regex = re.compile(r'(?:https?://)?(?:www\.)?t\.me/[\w\d_+\-]+')
        for m in regex.findall(response.text):
            formatted = clean_and_format_link(m)
            if formatted: found.add(formatted)

        # 2. HTML href tarama (Gizli butonlar)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if "t.me" in href:
                formatted = clean_and_format_link(href)
                if formatted: found.add(formatted)
            
    except Exception as e: logger.error(f"Site Hatası: {e}")
    logger.info(f"✅ Siteden {len(found)} link süpürüldü.")
    return list(found)

async def scrape_from_telegram_group(source_link, limit=500):
    """Grup linklerini çeker (Filtresiz)"""
    found_links = set()
    logger.info(f"♻️ Gruba Bakılıyor: {source_link}")
    try:
        entity = await client.get_entity(source_link)
        async for message in client.iter_messages(entity, limit=limit):
            if message.text:
                regex = re.compile(r'(?:https?://)?t\.me/[\w\d_+\-]+')
                for m in regex.findall(message.text):
                    formatted = clean_and_format_link(m)
                    if formatted: found_links.add(formatted)
            
            if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                for row in message.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'url') and btn.url and "t.me" in btn.url:
                            found_links.add(btn.url)
    except Exception as e: logger.error(f"Grup Hatası: {e}")
    return list(found_links)

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
            f"👋 **{BOT_NAME}**\n"
            f"🌍 **Mod:** Global Search (Dünya Geneli)\n\n"
            f"{status}\n"
            f"🎯 **Hedef:** {target_info}\n\n"
            "👇 **Ne yapmak istersin?**"
        )
        
        buttons = [
            [Button.inline("🔍 Global Kelime Ara", b"search_keyword"), Button.inline("🌐 Site Tara", b"search_site")],
            [Button.inline("♻️ Gruptan Çek", b"scrape_group")],
            [Button.inline("⚙️ Hedef Nasıl Ayarlanır?", b"set_target_help")],
            [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
        ]
        await event.respond(text, buttons=buttons)

@client.on(events.NewMessage(pattern='/kur'))
async def setup_here(event):
    if event.sender_id != ADMIN_ID: return
    chat_id = event.chat_id
    topic_id = event.reply_to_msg_id if event.is_reply else None
    if not topic_id and event.reply_to: topic_id = event.reply_to.reply_to_msg_id
    BOT_CONFIG["target_chat_id"] = chat_id
    BOT_CONFIG["target_topic_id"] = topic_id
    save_config(BOT_CONFIG)
    await event.reply(f"✅ **BAŞARILI!**\n🆔 `{chat_id}`\n📂 `{topic_id}`")

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
        else: await event.reply("❌ Link geçersiz.")
    except: await event.reply("❌ Kullanım: `/hedef <LINK>`")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        await event.edit("⚙️ **Ayarlama:**\n\n1. Gruba/Topice gir.\n2. **/kur** yaz.", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_keyword":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce Hedef Ayarla (/kur)", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit("🔍 **Aranacak Kelime?**\n(Global arama yapılır)", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_site":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce Hedef Ayarla", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit("🌐 **Site Linki?**\n(Örn: combot.org/...)", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "scrape_group":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Önce Hedef Ayarla", alert=True)
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

    msg = await event.respond("🚀 **Motorlar Çalıştırılıyor...**")
    raw_links = []
    
    if state == "KEYWORD":
        keywords = [k.strip() for k in text.split(",")]
        for kw in keywords:
            # 1. DuckDuckGo (Global & Sansürsüz)
            try: await msg.edit(f"🦆 **DuckDuckGo Taranıyor:** `{kw}`")
            except: pass
            
            # Farklı varyasyonlar
            queries = [
                f'site:t.me "{kw}"', 
                f'"{kw}" telegram group link',
                f'site:telegra.ph "{kw}"', # Telegra.ph'de genelde arşivler olur
                f'site:pastebin.com "{kw}"' # Pastebin'de listeler olur
            ]
            
            for q in queries:
                raw_links.extend(duckduckgo_search(q))
                await asyncio.sleep(1)

            # 2. Google (Yedek)
            try: await msg.edit(f"🔎 **Google Taranıyor:** `{kw}`")
            except: pass
            raw_links.extend(google_search(f'site:t.me "{kw}"'))

    elif state == "SITE":
        try: await msg.edit(f"🌐 **Siteye Giriliyor...**\n`{text[:30]}...`")
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
    
    if not raw_links:
        await msg.edit("❌ **Sonuç Yok.**", buttons=[[Button.inline("🔙", b"main_menu")]])
        return

    unique_links = list(set(raw_links))
    await msg.edit(f"🧐 **{len(unique_links)} Link Bulundu.**\nSüpürge modu aktif, hepsi gönderiliyor...")

    for link in unique_links:
        if toplanan >= HEDEF_LINK_LIMITI: break
        can_continue, _ = check_license(user_id)
        if not can_continue: break

        if link not in history:
            try:
                # DOĞRULAMA YOK - Direkt Gönderim
                await client.send_message(target_id, link, reply_to=target_topic, link_preview=False)
                history.add(link)
                save_history(link)
                consume_credit(user_id)
                toplanan += 1
                await asyncio.sleep(1.5) # Biraz hızlandırdık
            except Exception as e: logger.error(f"Hata: {e}")
    
    await msg.edit(f"🏁 **Tamamlandı!**\n**{toplanan}** adet link atıldı.", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
