import os
import logging
import asyncio
import re
import time
import json
import requests
import itertools
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events, Button

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# 🔥 ÇOKLU API KEY SİSTEMİ (3 Motorlu)
# Render'da GOOG_API_KEYS kısmına virgülle ayırarak gir.
keys_str = os.environ.get("GOOG_API_KEYS", "")
API_KEYS_LIST = [k.strip() for k in keys_str.split(",") if k.strip()]

# Eğer tek key varsa onu kullan, yoksa hata vermesin diye boş liste
if not API_KEYS_LIST:
    single = os.environ.get("GOOG_API_KEY", "")
    if single: API_KEYS_LIST = [single]

# Anahtarları sırayla döndür
api_key_cycle = itertools.cycle(API_KEYS_LIST)

GOOG_CX = os.environ.get("GOOG_CX", "")

# 🔥 SAHİP AYARLARI
ADMIN_ID = int(os.environ.get("OWNER_ID", "0")) # Render'a OWNER_ID ekle veya buraya ID yaz
DENEME_HAKKI = 3       # Ücretsiz deneme link sayısı
SAYFA_SAYISI = 4       # Toplam kaç sayfa gezsin? (2 Genel + 2 Dizin)
HEDEF_LINK_LIMITI = 100 # Maksimum link sayısı

# Kanal Linkleri
KANAL_LINKI = "https://t.me/yaelcode" 
ADMIN_USER = "yasin33" 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("HybridHunter")

# Web Server
app = Flask(__name__)
@app.route('/')
def home(): return "Hybrid System Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("pro_hunter", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Veritabanı
CREDITS_FILE = "credits.json"
HISTORY_FILE = "sent_links.txt"
USER_STATES = {}
CONFIG = {"target_chat_id": None}

# ==================== YARDIMCI FONKSİYONLAR ====================

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
    with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(f"{link}\n")

def extract_username_from_url(url):
    """Dizin sitelerinden (tgstat vb) kullanıcı adı çeker"""
    if "t.me/" in url: return url
    username = ""
    if "@" in url: username = url.split("@")[-1]
    elif "hottg.com" in url: username = url.split("/")[-1]
    elif "telemetr.io" in url:
        parts = url.split("/")[-1]
        username = parts.split("-", 1)[1] if "-" in parts else parts
    
    username = username.split("?")[0].strip()
    # Geçerli bir username mi?
    if re.match(r'^[a-zA-Z0-9_]{4,}$', username):
        return f"https://t.me/{username}"
    return None

# ==================== HİBRİT ARAMA MOTORU ====================

def google_search_hybrid(query, page=1):
    found = []
    start_index = ((page - 1) * 10) + 1
    
    if not API_KEYS_LIST: return []
    current_key = next(api_key_cycle) # Anahtarı değiştir
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': current_key, 'cx': GOOG_CX, 'q': query, 'start': start_index, 'num': 10}
    
    try:
        resp = requests.get(url, params=params)
        data = resp.json()
        
        if "error" in data:
            logger.error(f"API Hatası: {data['error']['message']}")
            return []
        if "items" not in data: return []
        
        regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
        
        for item in data['items']:
            link = item.get('link', '')
            snippet = item.get('snippet', '')
            title = item.get('title', '')
            
            # 1. YÖNTEM: Direkt t.me linki mi?
            if "t.me/" in link:
                found.append(link.split("?")[0])
                continue

            # 2. YÖNTEM: Dizin sitesi mi? (tgstat vb.) -> Dönüştür
            converted = extract_username_from_url(link)
            if converted and "t.me/" in converted:
                found.append(converted)
                continue

            # 3. YÖNTEM: Yazının içinde t.me geçiyor mu?
            matches = regex.findall(f"{title} {snippet}")
            for m in matches:
                found.append(m.rstrip('.,")\''))
                
    except Exception as e:
        logger.error(f"Hata: {e}")
        
    return list(set(found))

# ==================== MENÜ SİSTEMİ ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    is_allowed, info = check_license(user.id)
    
    status_msg = "👑 **Mod:** Yönetici (Sınırsız)" if info == "admin" else f"⏳ **Kalan Hak:** {DENEME_HAKKI - info}"
    
    text = (
        f"👋 **Selam {user.first_name}!**\n"
        f"🤖 **Hibrit Link Avcısı** (Google + Dizinler)\n\n"
        f"{status_msg}\n"
        f"🎯 **Hedef:** {CONFIG.get('target_chat_id', 'Ayarlanmadı')}\n\n"
        "Ne yapmak istersin?"
    )
    
    buttons = [
        [Button.inline("🔍 Kelime Tara", b"search_hybrid")],
        [Button.inline("⚙️ Hedef Seç (Admin)", b"set_target")],
        [Button.url("📣 Kanalımız", KANAL_LINKI), Button.url("👨‍💻 Admin / Satın Al", f"https://t.me/{ADMIN_USER}")]
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
        CONFIG["target_chat_id"] = chat_id
        await event.edit(f"✅ Hedef: `{chat_id}`", buttons=[[Button.inline("🔙 Menü", b"main_menu")]])

    elif data == "search_hybrid":
        if not is_allowed: return await event.answer("Limit Doldu! Admine Yazın.", alert=True)
        if not CONFIG["target_chat_id"]: return await event.answer("Hedef Seçilmedi!", alert=True)
        USER_STATES[user_id] = "HYBRID"
        await event.edit("🔍 **Aranacak kelimeyi yazın:**\n\nÖrn: `Yazılım`, `Borsa`, `Sohbet`\nBot hem Google'ı hem Telegram sitelerini tarayacaktır.", buttons=None)

    elif data == "main_menu":
        await start_handler(event)

@client.on(events.NewMessage)
async def input_handler(event):
    user_id = event.sender_id
    if user_id not in USER_STATES: return
    
    text = event.message.text
    del USER_STATES[user_id]
    
    is_allowed, info = check_license(user_id)
    if not is_allowed: return await event.respond("⛔ **Limit Doldu!**\nDevamı için: @yasin33")

    msg = await event.respond("🚀 **Hibrit Motorlar Çalıştırılıyor...**")
    
    # --- STRATEJİ: 2 AŞAMALI ARAMA ---
    # 1. Aşama: Direkt Google'daki t.me linkleri (Senin sevdiğin yöntem)
    query_general = f'site:t.me "{text}" (chat OR group OR sohbet)'
    
    # 2. Aşama: Dizin sitelerindeki linkler (Tgstat vb.)
    dizinler = "site:tgstat.com OR site:telemetr.io OR site:hottg.com OR site:telegramindex.com"
    query_directories = f'({dizinler}) "{text}"'

    queries = [query_general, query_directories] # Sırayla bunları yapacak
    
    history = load_history()
    toplanan = 0
    
    # Her sorgu türü için (Önce Genel, Sonra Dizin)
    for q_type in queries:
        if toplanan >= HEDEF_LINK_LIMITI: break
        
        # Sayfaları gez
        for page in range(1, 3): # Her sorgu türü için 2 sayfa gez (Toplam 4-5 sayfa eder)
            if toplanan >= HEDEF_LINK_LIMITI: break
            
            can_continue, _ = check_license(user_id)
            if not can_continue:
                await client.send_message(user_id, "⛔ Deneme hakkınız bitti.")
                return

            try: await msg.edit(f"🔎 **Taranıyor...**\nMod: {'Genel' if 'site:t.me' in q_type else 'Dizin'}\nBulunan: {toplanan}")
            except: pass
            
            links = google_search_hybrid(q_type, page)
            
            for link in links:
                can_send, _ = check_license(user_id)
                if not can_send: break

                # Yasaklı kelime / Temizlik
                ignore = ["share", "socks", "proxy", "google", "telegram", "status", "joinchat"] 
                # joinchat'i eleme, o lazım olabilir ama bazen bozuk oluyor.
                # Şimdilik temiz kalsın.
                
                if link not in history:
                    try:
                        await client.send_message(CONFIG["target_chat_id"], link, link_preview=False)
                        history.add(link)
                        save_history(link)
                        consume_credit(user_id)
                        toplanan += 1
                        await asyncio.sleep(2.5) # Güvenli bekleme
                    except Exception as e: logger.error(f"Hata: {e}")
            
            await asyncio.sleep(1)

    await msg.edit(f"🏁 **Tamamlandı!** Toplam {toplanan} link bulundu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
