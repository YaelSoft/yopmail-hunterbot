import os
import logging
import asyncio
import random
import time
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events

# ARAMA MOTORU KÜTÜPHANESİ
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
# Burayı doldur, gerisine karışma.
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Loglama
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SearchBot")

# Web Server (Render İçin)
app = Flask(__name__)
@app.route('/')
def home(): return "Search Bot Online 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
bot = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# ==================== GLOBAL HAFIZA ====================
# Bot ayarları burada tutulur (Restart atınca sıfırlanır, tekrar ayarlarsın)
CONFIG = {
    "target_chat_id": None,  # Hedef Grup ID
    "target_topic_id": None, # Hedef Konu ID
    "is_running": False,
    "current_keyword": ""
}

HISTORY_FILE = "sent_links.txt"

# ==================== YARDIMCI FONKSİYONLAR ====================

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(f"{link}\n")

def make_progress_bar(current, total, length=12):
    """Görsel çubuk oluşturur: [████░░░░] %50"""
    if total == 0: total = 1
    percent = current / total
    filled = int(length * percent)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] %{int(percent * 100)}"

def parse_topic_link(link):
    """Kullanıcının attığı linkten ID'leri süzer"""
    # Link tipleri: 
    # https://t.me/c/123456789/100 (Özel grup)
    # https://t.me/username/100 (Genel grup)
    link = link.strip().replace("https://", "").replace("t.me/", "")
    parts = link.split("/")
    
    try:
        if "c/" in link: # Private: c/123456/100
            chat_id = int("-100" + link.split("c/")[1].split("/")[0])
            topic_id = int(parts[-1])
            return chat_id, topic_id
        else: # Public: username/100
            # Public gruplarda username'i ID olarak kullanamayız, resolve gerekir.
            # Ancak kullanıcıya "Botu gruba ekle" dediğimiz için chat_id'yi eventten alabiliriz.
            # Şimdilik sadece Private link desteği (en garantisi) veya username.
            username = parts[0]
            topic_id = int(parts[1])
            return username, topic_id
    except:
        return None, None

# ==================== ARAMA MOTORU (TÜRKİYE MODU) ====================

def search_web(keyword):
    """Web'de DuckDuckGo ile Türkiye odaklı arama yapar"""
    links = []
    
    # Dorking Sorguları
    queries = [
        f'site:t.me joinchat "{keyword}"',
        f'"t.me/+" "{keyword}"',
        f'site:facebook.com "t.me/joinchat" "{keyword}"',
        f'site:twitter.com "t.me/+" "{keyword}"'
    ]
    
    try:
        # region='tr-tr' ekleyerek Türk sonuçlarını zorluyoruz
        # safesearch='off' ile +18 dahil her şeyi açıyoruz
        with DDGS() as ddgs:
            for q in queries:
                # timelimit='m' (Son 1 ay) ekleyerek TAZE linkleri bulabilirsin
                # ya da timelimit=None yapıp hepsini alabilirsin.
                results = list(ddgs.text(q, region='tr-tr', safesearch='off', max_results=40))
                
                for res in results:
                    url = res.get('href', '')
                    title = res.get('title', 'Başlık Yok')
                    
                    if "t.me/" in url:
                        clean = url.split("?")[0].strip()
                        if clean.count("/") <= 4:
                            links.append({"url": clean, "title": title})
                            
        random.shuffle(links)
        return links
        
    except Exception as e:
        logger.error(f"Arama hatası: {e}")
        return []

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    global CONFIG
    
    # Başlangıç Bilgisi
    await status_msg.edit(
        f"🔎 **Arama Başlatıldı: {keyword}**\n\n"
        f"🎯 Hedef Grup ID: `{CONFIG['target_chat_id']}`\n"
        f"📂 Hedef Konu ID: `{CONFIG['target_topic_id']}`\n\n"
        f"_İnternet taranıyor, lütfen bekleyin..._"
    )
    
    while CONFIG["is_running"]:
        try:
            # 1. ARAMA YAP
            found_items = search_web(keyword)
            history = load_history()
            
            # Yeni olanları ayıkla
            new_items = [i for i in found_items if i['url'] not in history]
            
            if not new_items:
                await status_msg.edit(f"💤 **{keyword}** için yeni link bulunamadı.\n2 dakika mola veriliyor...")
                await asyncio.sleep(120)
                continue
            
            # 2. GÖNDERİM SÜRECİ
            total = len(new_items)
            sent_count = 0
            
            await status_msg.edit(f"✅ **{total} Link Bulundu!**\nGruba aktarım başlıyor...")
            
            for i, item in enumerate(new_items, 1):
                if not CONFIG["is_running"]: break
                
                link = item['url']
                title = item['title']
                
                # Mesaj Şablonu
                msg_text = (
                    f"🌐 **Web'den Bulundu**\n"
                    f"🔍 Kelime: `#{keyword}`\n"
                    f"📝 Başlık: {title}\n"
                    f"🔗 **Link:** {link}"
                )
                
                try:
                    # HEDEFE GÖNDER
                    await bot.send_message(
                        CONFIG["target_chat_id"],
                        msg_text,
                        reply_to=CONFIG["target_topic_id"], # Topic içine atar
                        link_preview=False # Önizleme kapalı (Hızlı olsun)
                    )
                    save_history(link)
                    sent_count += 1
                    
                except Exception as e:
                    logger.error(f"Gönderim hatası: {e}")
                    # Eğer bot gruba erişemiyorsa durdur
                    if "CHAT_WRITE_FORBIDDEN" in str(e):
                        await status_msg.edit("❌ **HATA:** Botun o grupta mesaj atma yetkisi yok!")
                        CONFIG["is_running"] = False
                        return

                # Durum Çubuğunu Güncelle (Her 3 mesajda bir)
                if i % 3 == 0 or i == total:
                    bar = make_progress_bar(i, total)
                    await status_msg.edit(
                        f"🚀 **Aktarılıyor: {keyword}**\n\n"
                        f"{bar}\n"
                        f"📦 Durum: `{i}/{total}`\n"
                        f"✅ Başarılı: `{sent_count}`"
                    )
                
                # Spam koruması (10-20 sn bekle)
                await asyncio.sleep(random.randint(10, 20))
            
            await status_msg.edit(f"🏁 **Tur Bitti!**\nToplam `{sent_count}` link atıldı.\n5 dakika dinlenip tekrar arayacağım...")
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Task hatası: {e}")
            await asyncio.sleep(60)
            
    await status_msg.edit("🛑 **İşlem Durduruldu.**")

# ==================== KOMUTLAR ====================

@bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    await event.respond(
        "👋 **Link Avcısı Bot**\n\n"
        "**Nasıl Kullanılır?**\n"
        "1️⃣ Botu grubuna ekle ve yönetici yap.\n"
        "2️⃣ Linklerin atılacağı **Konunun (Topic)** bağlantısını kopyala.\n"
        "3️⃣ Bana özelden: `/hedef https://t.me/c/xxxx/123` yaz.\n"
        "4️⃣ Sonra: `/basla <kelime>` yaz.\n\n"
        "Bu kadar! Gerisini ben hallederim."
    )

@bot.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        chat_id, topic_id = parse_topic_link(link)
        
        if chat_id and topic_id:
            CONFIG["target_chat_id"] = chat_id
            CONFIG["target_topic_id"] = topic_id
            await event.respond(
                f"✅ **Hedef Ayarlandı!**\n\n"
                f"📂 Grup ID: `{chat_id}`\n"
                f"📌 Topic ID: `{topic_id}`\n\n"
                f"Şimdi `/basla <kelime>` komutunu kullanabilirsin."
            )
        else:
            await event.respond("❌ Linkten ID çözülemedi. Lütfen `t.me/c/..` formatında (özel grup) topic linki atın.\nBotun grupta olduğundan emin olun.")
    except IndexError:
        await event.respond("❌ Link girmelisin.\nÖrn: `/hedef https://t.me/c/123456/101`")

@bot.on(events.NewMessage(pattern='/basla'))
async def start_leech(event):
    if not CONFIG["target_chat_id"]:
        await event.respond("⚠️ Önce hedef belirlemelisin!\n`/hedef <TOPIC_LINKI>` komutunu kullan.")
        return
        
    if CONFIG["is_running"]:
        await event.respond(f"⚠️ Zaten çalışıyor: `{CONFIG['current_keyword']}`")
        return

    try:
        keyword = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"] = keyword
        CONFIG["is_running"] = True
        
        status_msg = await event.respond(f"⏳ **{keyword}** için motorlar ısınıyor...")
        asyncio.create_task(leech_task(status_msg, keyword))
        
    except IndexError:
        await event.respond("❌ Kelime girmedin.\nÖrn: `/basla ifsa` veya `/basla kripto`")

@bot.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    if not CONFIG["is_running"]:
        await event.respond("💤 Zaten çalışmıyor.")
        return
    
    CONFIG["is_running"] = False
    await event.respond("🛑 Durdurma emri verildi. Mevcut işlem bitince duracak.")

if __name__ == '__main__':
    keep_alive()
    bot.run_until_disconnected()
