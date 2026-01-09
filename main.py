import os
import logging
import asyncio
import re
import urllib.parse
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Hedef Kanal Ayarları (Hafıza)
CONFIG = {"target_chat_id": None, "target_topic_id": None}

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("HtmlHunter")

# Web Server (Render İçin)
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Dosya Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("html_hunter", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ==================== YARDIMCI FONKSİYONLAR ====================

def parse_topic_link(link):
    link = link.strip().replace("https://", "").replace("t.me/", "")
    try:
        if "c/" in link:
            parts = link.split("c/")[1].split("/")
            chat_id = int("-100" + parts[0])
            topic_id = int(parts[1]) if len(parts) > 1 else None
            return chat_id, topic_id
    except: pass
    return None, None

def extract_links_from_html(file_path):
    """İndirilen HTML dosyasının içindeki t.me linklerini bulur"""
    found_links = set()
    
    # Dosyayı oku (utf-8 hatası verirse latin-1 dener)
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return []

    # Google linkleri şifreli olur (%3A%2F), onları düzelt
    decoded_content = urllib.parse.unquote(content)

    # Regex: t.me linklerini affetmez
    regex = re.compile(r'https?://(?:www\.)?t\.me/(?:joinchat/|\+)?[\w\d_\-]+')
    
    matches = regex.findall(decoded_content)
    for match in matches:
        clean = match.strip().rstrip('.,"\';<>&)')
        
        # Filtreler
        ignore = ["share", "socks", "proxy", "contact", "setlanguage", "iv", "google", "search"]
        if any(x in clean.lower() for x in ignore): continue
        
        found_links.add(clean)
        
    return list(found_links)

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond(
        "👋 **Anti-Ban Link Sökücü**\n\n"
        "Google/Bing botları engellediği için taktik değiştirdik.\n\n"
        "**Nasıl Kullanılır?**\n"
        "1️⃣ `/hedef <LİNK>` ile hedef grubu seç.\n"
        "2️⃣ Google'da aramanı yap, sayfayı aşağı kaydır.\n"
        "3️⃣ **Sağ Tık -> Farklı Kaydet** (veya Ctrl+S) yap.\n"
        "4️⃣ İnen `.html` dosyasını bana gönder.\n\n"
        "Dosyayı attığın an içindeki tüm linkleri sökerim!"
    )

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Ayarlandı. Şimdi dosyayı at.")
        else: await event.respond("❌ Link Hatalı (Özel grup linki olmalı).")
    except: await event.respond("❌ Link girmedin.")

# ==================== DOSYA YAKALAYICI ====================

@client.on(events.NewMessage)
async def file_handler(event):
    # Sadece dosya varsa ve HTML ise çalış
    if not event.document: return
    
    # Dosya ismini kontrol et (.html veya .htm)
    file_name = event.file.name or ""
    if not file_name.endswith(('.html', '.htm')): return

    if not CONFIG["target_chat_id"]:
        await event.reply("⚠️ Önce `/hedef` belirle!")
        return

    msg = await event.reply("📥 **Dosya İnceleniyor...**")
    
    try:
        # Dosyayı sunucuya indir
        path = await event.download_media()
        
        # İçini tara
        links = extract_links_from_html(path)
        
        # Dosyayı sil (yer kaplamasın)
        os.remove(path)
        
        if not links:
            await msg.edit("❌ Bu dosyada Telegram linki bulunamadı.")
            return

        await msg.edit(f"✅ **{len(links)}** link bulundu! Gönderiliyor...")
        
        count = 0
        for link in links:
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=link,
                    reply_to=CONFIG["target_topic_id"],
                    link_preview=False
                )
                count += 1
                await asyncio.sleep(2) # Flood yememek için
            except Exception as e:
                logger.error(f"Hata: {e}")

        await client.send_message(
            entity=event.chat_id,
            message=f"🏁 **Tamamlandı!** Toplam {count} link yollandı."
        )

    except Exception as e:
        await msg.edit(f"⚠️ Bir hata oldu: {e}")
        if os.path.exists(path): os.remove(path)

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
