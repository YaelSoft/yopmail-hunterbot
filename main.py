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
from telethon.tl.types import Channel, Chat, User, InputMessagesFilterUrl
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
SAYFA_SAYISI = 4       
HEDEF_LINK_LIMITI = 150 
GRUP_TARAMA_LIMITI = 500 

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcodetr" 
ADMIN_USER = "yasin33" 
BOT_NAME = "YaelTg-Link Searh Bot" # 🔥 Marka İsmi

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("LinkRadar")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return f"{BOT_NAME} Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("linkradar_pro", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

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

# ==================== 🔥 LİNK DOĞRULAMA ====================

async def validate_link(link):
    try:
        if "joinchat" in link or "+" in link: return True, link
        try: entity = await client.get_entity(link)
        except: return False, None

        if isinstance(entity, User): return False, None
        if isinstance(entity, (Channel, Chat)):
            final_link = f"https://t.me/{entity.username}" if entity.username else link
            return True, final_link
    except: return False, None
    return False, None

# ==================== KAZIYICILAR ====================

def scrape_site_content(url):
    found = set()
    try:
        response = cureq.get(url, impersonate="chrome124", timeout=15)
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        matches = regex.findall(response.text)
        for m in matches:
            clean = m.strip().rstrip('.,")\'')
            ignore = ["share/url", "socks", "proxy", "contact", "iv?"]
            if any(x in clean for x in ignore): continue
            found.add(clean)
    except Exception as e: logger.error(f"Site Hatası: {e}")
    return list(found)

async def scrape_from_telegram_group(source_link, limit=500):
    found_links = set()
    try:
        entity = await client.get_entity(source_link)
        async for message in client.iter_messages(entity, limit=limit, filter=InputMessagesFilterUrl):
            if message.text:
                regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
                matches = regex.findall(message.text)
                for m in matches: found_links.add(m)
            if message.reply_markup:
                for row in message.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'url') and btn.url and "t.me" in btn.url:
                            found_links.add(btn.url)
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

# ==================== MENÜLER (VİTRİN GÜNCELLEMESİ) ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    
    # Durum Göstergesi
    if info == "admin":
        status_icon = "👑"
        status_text = "Yönetici (Sınırsız)"
    else:
        kalan = DENEME_HAKKI - info
        status_icon = "💎" if kalan > 0 else "❌"
        status_text = f"Deneme Sürümü: {kalan} Hak Kaldı"
    
    target = BOT_CONFIG.get("target_chat_id")
    target_info = "✅ Sistem Hazır" if target else "⚠️ Hedef Seçilmedi"

    # PROFESYONEL KARŞILAMA MESAJI
    text = (
        f"👋 **Merhaba {user.first_name}, {BOT_NAME}'a Hoş Geldiniz!**\n\n"
        f"Telegram'ın en gelişmiş **Grup ve Kanal Arama Botu** ile tanışın.\n"
        f"Google veritabanlarını, özel dizinleri ve gizli ağları tarayarak size en alakalı sonuçları getirir.\n\n"
        f"📊 **Hesap Durumu:**\n"
        f"👤 **Kullanıcı:** `{user.id}`\n"
        f"{status_icon} **Üyelik:** {status_text}\n"
        f"📡 **Sistem:** {target_info}\n\n"
        f"🚀 **Neler Yapabilirim?**\n"
        f"• **Akıllı Arama:** Kelimeye göre en gizli grupları bulurum.\n"
        f"• **Dizin Tarama:** Combot, Tgstat gibi sitelerden link cekerim.\n"
        f"• **Grup Analizi:** Bir gruptaki paylasılan tüm linkleri çekerim.\n\n"
        f"👇 **Başlamak için bir işlem seçin:**"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime/Etiket Ara", b"search_keyword"), Button.inline("🌐 Site/Dizin Tara", b"search_site")],
        [Button.inline("♻️ Gruptan Link Çek", b"scrape_group")],
        [Button.inline("⚙️ Hedef Ayarla (Admin)", b"set_target_help")],
        [Button.url("💎 Bot/Vip Hakkında Bilgi Al", f"https://t.me/{ADMIN_USER}"), Button.url("📣 Güncellemeler", KANAL_LINKI)]
    ]
    await event.respond(text, buttons=buttons, link_preview=False)

@client.on(events.NewMessage(pattern='/hedef'))
async def manual_target(event):
    if event.sender_id != ADMIN_ID: return await event.reply("⛔ Bu komut sadece Yönetici içindir.")
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
        await event.reply(f"✅ **Hedef Başarıyla Kaydedildi!**\n🆔 Grup ID: `{cid}`\n📂 Konu ID: `{tid}`")
    except: await event.reply("❌ **Hata:** Link geçersiz veya bot o grupta değil.")

@client.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "set_target_help":
        if user_id != ADMIN_ID: return await event.answer("Bu menü sadece Yönetici içindir!", alert=True)
        await event.edit(
            "⚙️ **Hedef Kurulumu:**\n\n"
            "Linklerin otomatik gönderileceği grubu ayarlamak için:\n"
            "1. Hedef gruba gidin.\n"
            "2. (Varsa) Konu başlığına sağ tıklayıp linki kopyalayın.\n"
            "3. Buraya gelip şu komutu yazın:\n\n"
            "`/hedef https://t.me/c/123456/1`",
            buttons=[[Button.inline("🔙 Ana Menüye Dön", b"main_menu")]]
        )

    elif data == "search_keyword":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("⚠️ Deneme süreniz doldu! Premium alın.", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Sistem bakımda (Hedef Ayarlanmadı).", alert=True)
        USER_STATES[user_id] = "KEYWORD"
        await event.edit(
            "🔍 **Kelime ile Arama Modu**\n\n"
            "Aradığınız içeriği tanımlayan anahtar kelimeleri yazın.\n"
            "Birden fazla kelime için virgül (,) kullanabilirsiniz.\n\n"
            "📝 *Örnek:* `Yazılım, Sohbet, İkinci El`", 
            buttons=[[Button.inline("🔙 İptal", b"main_menu")]]
        )

    elif data == "search_site":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("⚠️ Deneme süreniz doldu! Premium alın.", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Sistem bakımda.", alert=True)
        USER_STATES[user_id] = "SITE"
        await event.edit(
            "🌐 **Site/Dizin Tarama Modu**\n\n"
            "Telegram linklerinin bulunduğu bir web sitesi adresi gönderin.\n"
            "Bot siteye girip tüm linkleri sömürecektir.\n\n"
            "📝 *Örnek:* `https://combot.org/top/telegram/groups?lng=tr`", 
            buttons=[[Button.inline("🔙 İptal", b"main_menu")]]
        )

    elif data == "scrape_group":
        is_allowed, info = check_license(user_id)
        if not is_allowed: return await event.answer("⚠️ Deneme süreniz doldu! Premium alın.", alert=True)
        if not BOT_CONFIG.get("target_chat_id"): return await event.answer("⚠️ Sistem bakımda.", alert=True)
        USER_STATES[user_id] = "GROUP_SCRAPE"
        await event.edit(
            "♻️ **Grup İçi Link Toplama Modu**\n\n"
            "İçinde bolca link paylaşılan bir grubun linkini gönderin.\n"
            "Bot 'Bağlantılar' kısmını tarayıp diğer grupları bulur.\n\n"
            "📝 *Örnek:* `https://t.me/linkpaylasimgrubu`", 
            buttons=[[Button.inline("🔙 İptal", b"main_menu")]]
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
    if not is_allowed: return await event.respond("⛔ **Deneme Süreniz Bitti!**\nSınırsız erişim ve daha fazlası için yönetici ile iletişime geçin.", buttons=[[Button.url("💎 Satın Al", f"https://t.me/{ADMIN_USER}")], [Button.inline("🔙 Menü", b"main_menu")]])

    msg = await event.respond("🚀 **Tarama Başlatılıyor...**\nVeritabanlarına bağlanılıyor, lütfen bekleyin.")
    raw_links = []
    
    # 1. TARAMA İŞLEMİ
    if state == "KEYWORD":
        keywords = [k.strip() for k in text.split(",")]
        for kw in keywords:
            qs = [
                f'site:t.me joinchat "{kw}"',
                f'site:t.me "View in Telegram" "{kw}"',
                f'(site:tgstat.com OR site:telemetr.io) "{kw}"'
            ]
            for q in qs:
                for page in range(1, SAYFA_SAYISI + 1):
                    try: await msg.edit(f"🔎 **Aranıyor:** `{kw}`\nDerinlik: {page}/{SAYFA_SAYISI}")
                    except: pass
                    raw_links.extend(google_search(q, page))
                    await asyncio.sleep(1)

    elif state == "SITE":
        try: await msg.edit(f"🌐 **Siteye Giriliyor...**\nBulut koruması aşılıyor...")
        except: pass
        if "http" not in text: text = "https://" + text
        raw_links = scrape_site_content(text)

    elif state == "GROUP_SCRAPE":
        try: await msg.edit(f"♻️ **Grup Analiz Ediliyor...**\nSon {GRUP_TARAMA_LIMITI} bağlantı taranıyor...")
        except: pass
        raw_links = await scrape_from_telegram_group(text, limit=GRUP_TARAMA_LIMITI)

    # 2. DOĞRULAMA VE GÖNDERİM
    history = load_history()
    toplanan = 0
    target_id = BOT_CONFIG.get("target_chat_id")
    target_topic = BOT_CONFIG.get("target_topic_id")
    
    if not raw_links:
        await msg.edit("❌ **Sonuç Bulunamadı.**\nFarklı kelimeler veya kaynaklar deneyin.", buttons=[[Button.inline("🔙 Ana Menüye Dön", b"main_menu")]])
        return

    unique_links = list(set(raw_links))
    await msg.edit(f"🧐 **{len(unique_links)} Bağlantı İnceleniyor...**\nBotlar, kullanıcılar ve kırık linkler temizleniyor.")

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
    
    await msg.edit(
        f"🏁 **İşlem Tamamlandı!**\n\n"
        f"✅ **{toplanan}** adet temiz Grup/Kanal hedef klasöre gönderildi.\n"
        f"🗑️ {len(unique_links) - toplanan} adet geçersiz/tekrarlı link elendi.",
        buttons=[[Button.inline("🔙 Ana Menüye Dön", b"main_menu")]]
    )

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
