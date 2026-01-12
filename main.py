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
from telethon.tl.types import Channel, Chat, User
from telethon.errors import FloodWaitError
from curl_cffi import requests as cureq

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
SAYFA_SAYISI = 4       # Arama derinliği
HEDEF_LINK_LIMITI = 50 
GRUP_TARAMA_LIMITI = 500 #  isteğe göre düzenle

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcodetr" 
ADMIN_USER = "yasin33" 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("ProBotV5")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Link Search Bot Active 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter_v5", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
CONFIG_FILE = "config.json" 
USER_STATES = {}

# ==================== VERİTABANI YÖNETİMİ ====================

def load_config():
    if not os.path.exists(CONFIG_FILE): return {"target_chat_id": None}
    try: with open(CONFIG_FILE, "r") as f: return json.load(f)
    except: return {"target_chat_id": None}

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

# ==================== 🔥 GELİŞMİŞ DOĞRULAMA (BOT ENGELLEYİCİ) ====================

async def validate_link(link):
    """
    Linki kontrol eder:
    1. Kullanıcı (User) mı? -> ÇÖP
    2. Bot mu? -> ÇÖP
    3. Grup/Kanal mı? -> ONAY
    """
    try:
        # Joinchat linkleri kontrol edilemez, mecburen kabul ediyoruz
        if "joinchat" in link or "+" in link:
            return True, link

        # Normal Username (t.me/deneme) kontrolü
        try:
            entity = await client.get_entity(link)
        except:
            return False, None # Bulunamadı

        # KULLANICI veya BOT ise ENGELLE
        if isinstance(entity, User):
            if entity.bot: logger.info(f"🤖 Bot Engellendi: {link}")
            else: logger.info(f"👤 Kullanıcı Engellendi: {link}")
            return False, None
        
        # Sadece Kanal veya Grup ise al
        if isinstance(entity, (Channel, Chat)):
            final_link = f"https://t.me/{entity.username}" if entity.username else link
            return True, final_link
            
    except Exception as e:
        return False, None
        
    return False, None

# ==================== SİTE VE GRUP SÖMÜRÜCÜ ====================

def scrape_site_content(url):
    """
    Verilen tam URL'ye (örn: combot.org/...) girer, 
    Cloudflare'ı deler ve tüm t.me linklerini toplar.
    """
    found = set()
    try:
        # Chrome taklidi
        response = cureq.get(url, impersonate="chrome124", timeout=15)
        
        # Regex: t.me linklerini affetmez
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        matches = regex.findall(response.text)
        
        for m in matches:
            clean = m.strip().rstrip('.,")\'')
            # Gereksizleri at
            ignore = ["share/url", "socks", "proxy", "contact", "setlanguage", "iv?"]
            if any(x in clean for x in ignore): continue
            
            found.add(clean)
    except Exception as e:
        logger.error(f"Site Hatası: {e}")
    return list(found)

async def scrape_from_telegram_group(source_link, limit=500):
    """
    Gruptan 1000 mesaj okur, içindeki linkleri çeker.
    """
    found_links = set()
    try:
        entity = await client.get_entity(source_link)
        # iter_messages ile geçmişe doğru tarıyoruz
        async for message in client.iter_messages(entity, limit=limit):
            if message.text:
                regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
                matches = regex.findall(message.text)
                for m in matches: found_links.add(m)
            
            # Butonlardaki linkler
            if message.reply_markup:
                for row in message.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'url') and btn.url and "t.me" in btn.url:
                            found_links.add(btn.url)
            
            # Fren sistemi (Telegram kızmasın)
            await asyncio.sleep(0.05) 

    except Exception as e:
        logger.error(f"Grup Tarama Hatası: {e}")
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
        
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        for item in data['items']:
            text = f"{item.get('link')} {item.get('snippet')} {item.get('title')}"
            matches = regex.findall(text)
            for m in matches: found.append(m.rstrip('.,")\''))
    except: pass
    return list(set(found))

# ==================== MENÜLER ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    status = "👑 **Admin**" if info == "admin" else f"⏳ **Hak:** {DENEME_HAKKI - info}"
    
    target = BOT_CONFIG.get("target_chat_id")
    target_info = f"✅ `{target}`" if target else "❌ Ayarsız"

    text = (
        f"👋 **Selam {user.first_name}!**\n"
        f"💎 **Link Search Bot Aktif** (Ultimate)\n\n"
        f"{status}\n"
        f"🎯 **Hedef:** {target_info}\n\n"
        "**Özellikler:**\n"
        "• 500 Mesajlık Grup Taraması(Secilen Gruptaki 500 Mesajı Tarar Grup Varsa Hedefe Ceker)\n"
        "• Özel Site (Combot/Tgstat) Taraması\n"
        "• Bulunan Linkleri Secilen Hedefe Gönderir\n\n"
        "👇 **İşlem Seç:**"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime/Etiket Ara", b"search_keyword"), Button.inline("🌐 Site Linki Tara", b"search_site")],
        [Button.inline("♻️ Gruptan Çek (1000 Msj)", b"scrape_group")],
        [Button.inline("⚙️ Hedef Ayarla (Link)", b"set_target_help")],
        [Button.url("📣 Kanal", KANAL_LINKI), Button.url("👨‍💻 Admin", f"https://t.me/{ADMIN_USER}")]
    ]
    await event.respond(text, buttons=buttons)

# HEDEF AYARLAMA
@client.on(events.NewMessage(pattern='/hedef'))
async def manual_target(event):
    if event.sender_id != ADMIN_ID: return await event.reply("⛔ Sadece Admin!")
    try:
        link = event.message.text.split(" ", 1)[1]
        if "c/" in link:
            cid = int("-100" + link.split("c/")[1].split("/")[0])
            tid = int(link.split("/")[-1]) if link.split("/")[-1].isdigit() else None
        else:
            ent = await client.get_entity(link)
            cid = int(f"-100{ent.id}") if not str(ent.id).startswith("-100") else ent.id
            tid = None
        BOT_CONFIG["target_chat_id"] = cid
        BOT_CONFIG["target_topic_id"] = tid
        save_config(BOT_CONFIG)
        await event.reply(f"✅ **Hedef:** `{cid}`\n📂 Topic: `{tid}`")
    except: await event.reply("❌ Hata! Linki kontrol et.")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Sadece Admin!", alert=True)
        await event.edit("⚙️ **Ayar:**\n`/hedef https://t.me/c/123/1` yaz.", buttons=[[Button.inline("🔙", b"main_menu")]])

    elif data == "search_keyword":
        # Lisans kontrolü
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        
        USER_STATES[user_id] = "KEYWORD"
        await event.edit(
            "🔍 **Aranacak Kelimeleri Yazın:**\n\n"
            "Birden fazla kelime için virgül kullanın.\n"
            "Örn: `Yazılım, Sohbet, Borsa`\n\n"
            "Bot Google'ı, Dizinleri ve Özel Davetleri tarayacaktır.", 
            buttons=[[Button.inline("🔙", b"main_menu")]]
        )

    elif data == "search_site":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        
        USER_STATES[user_id] = "SITE"
        await event.edit(
            "🌐 **Hangi Sayfa Taransın?**\n\n"
            "Tam linki yapıştırın, bot içini boşaltsın.\n"
            "Örn: `https://combot.org/top/telegram/groups?lng=tr`", 
            buttons=[[Button.inline("🔙", b"main_menu")]]
        )

    elif data == "scrape_group":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("Limit Doldu!", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("Hedef Yok!", alert=True)
        
        USER_STATES[user_id] = "GROUP_SCRAPE"
        await event.edit(
            "♻️ **Kaynak Grup Linki?**\n\n"
            "Linklerin paylaşıldığı bir grup atın.\n"
            "Bot **son 1000 mesajı** okuyup, içindeki diğer grupları bulacak.", 
            buttons=[[Button.inline("🔙", b"main_menu")]]
        )

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
    if not is_allowed: return await event.respond("⛔ **Limit Doldu!**", buttons=[[Button.inline("🔙", b"main_menu")]])

    msg = await event.respond("🚀 **Motorlar Isınıyor...**")
    raw_links = []
    
    # 1. KAYNAKTAN LİNK TOPLA
    if state == "KEYWORD":
        # Virgülle ayrılmış kelimeleri böl
        keywords = [k.strip() for k in text.split(",")]
        
        for kw in keywords:
            # 3 Aşamalı Strateji
            strategies = [
                f'site:t.me "{kw}" (chat OR group OR sohbet)', # 1. Genel
                f'(site:tgstat.com OR site:telemetr.io OR site:hottg.com) "{kw}"', # 2. Dizin
                f'"{kw}" "t.me/+" OR "t.me/joinchat"' # 3. Davet
            ]
            
            for q in strategies:
                for page in range(1, SAYFA_SAYISI + 1):
                    try: await msg.edit(f"🔎 **Aranıyor:** `{kw}`\nMod: Google\nSayfa: {page}")
                    except: pass
                    raw_links.extend(google_search(q, page))
                    await asyncio.sleep(1)

    elif state == "SITE":
        try: await msg.edit(f"🌐 **Siteye Giriliyor...**\n`{text[:30]}...`")
        except: pass
        if "http" not in text: text = "https://" + text
        raw_links = scrape_site_content(text)

    elif state == "GROUP_SCRAPE":
        try: await msg.edit(f"♻️ **Grup Taranıyor...**\nSon {GRUP_TARAMA_LIMITI} mesaj analiz ediliyor...")
        except: pass
        raw_links = await scrape_from_telegram_group(text, limit=GRUP_TARAMA_LIMITI)

    # 2. LİNKLERİ DOĞRULA VE GÖNDER
    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    target_topic = BOT_CONFIG.get("target_topic_id")
    
    if not raw_links:
        await msg.edit("❌ Hiç link bulunamadı.", buttons=[[Button.inline("🔙", b"main_menu")]])
        return

    unique_links = list(set(raw_links))
    await msg.edit(f"🧐 **{len(unique_links)} Aday Bulundu.**\nKalite kontrolü (Anti-Bot) yapılıyor...")

    for link in unique_links:
        if toplanan >= HEDEF_LINK_LIMITI: break
        
        can_continue, _ = check_license(user_id)
        if not can_continue: break

        if link not in history:
            # 🔥 VALIDATOR: Botları ve Kullanıcıları ele
            is_valid, final_link = await validate_link(link)
            
            if is_valid and final_link:
                try:
                    await client.send_message(
                        entity=target_id, 
                        message=final_link, 
                        reply_to=target_topic, 
                        link_preview=False
                    )
                    history.add(final_link)
                    save_history(final_link)
                    consume_credit(user_id)
                    toplanan += 1
                    # Spam yememek için bekleme süresi (Grup taramada çok hızlı olabilir)
                    await asyncio.sleep(3) 
                except Exception as e: logger.error(f"Hata: {e}")
            else:
                logger.info(f"🗑️ Elendi: {link}")
    
    await msg.edit(f"🏁 **Tamamlandı!**\n**{toplanan}** adet temiz Grup/Kanal paylaşıldı.", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
