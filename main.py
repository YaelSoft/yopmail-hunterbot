import os
import logging
import asyncio
import random
import re
import time
import requests
from bs4 import BeautifulSoup
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Kaç link bulunca dursun?
HEDEF_LINK_SAYISI = 50 

# Loglama
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")

# Web Server (Render'ın ayakta kalması için)
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Link Topluyor 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

# Bot Başlatma
client = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Hafıza
CONFIG = {"target_chat_id": None, "target_topic_id": None, "is_running": False, "current_keyword": ""}
HISTORY_FILE = "sent_links.txt"

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(line.strip() for line in f)

def save_history(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(f"{link}\n")

def parse_topic_link(link):
    link = link.strip().replace("https://", "").replace("t.me/", "")
    parts = link.split("/")
    try:
        if "c/" in link:
            chat_id = int("-100" + link.split("c/")[1].split("/")[0])
            topic_id = int(parts[-1])
            return chat_id, topic_id
        return None, None
    except: return None, None

# ==================== DERİN TARAMA (AGRESİF MOD) ====================

def dig_for_links(url):
    """
    Bir siteye girer, içindeki TÜM tıklanabilir t.me linklerini toplar.
    Sorgusuz sualsiz ne bulursa alır.
    """
    found_in_page = set()
    
    # Tarayıcı gibi görün (Yasaklanmamak için)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # 1. Siteye Bağlan (5 saniye süre veriyoruz, açılmazsa geç)
        response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        
        # Eğer site bizi direkt Telegram'a yönlendirdiyse (Redirect)
        if "t.me" in response.url:
            clean_redirect = response.url.split("?")[0]
            logger.info(f"✅ YÖNLENDİRME YAKALANDI: {clean_redirect}")
            return [clean_redirect]

        # 2. Sitenin İçini Aç (HTML Parse)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Sayfadaki TÜM <a href="..."> etiketlerini bul
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link['href']
            
            # İçinde t.me veya telegram.me geçen her şeyi al
            if "t.me/" in href or "telegram.me/" in href:
                # Linki temizle (utm_source vs temizle)
                clean_link = href.split("?")[0].strip()
                
                # Sadece http ile başlayanları al (bazen javascript: kodları olur)
                if clean_link.startswith("http"):
                    found_in_page.add(clean_link)
                    logger.info(f"⛏️ SİTE İÇİNDE BULUNDU: {clean_link}")

    except Exception as e:
        # Site açılmadıysa veya hata verdiyse sessizce geç
        pass

    return list(found_in_page)

# ==================== ARAMA MOTORU ====================

def search_web(keyword):
    candidates = [] # Aday siteler
    final_links = [] # Bulunan Telegram linkleri
    
    # Sorgular: Artık sosyal medya yok, direkt sonuca odaklı
    queries = [
        f'"{keyword}" chat link',
        f'"{keyword}" telegram grubu',
        f'"{keyword}" joinchat',
        f'site:t.me "{keyword}"' # Bunu tutuyoruz, belki direkt link çıkar
    ]

    logger.info(f"🔍 '{keyword}' için siteler taranıyor...")

    try:
        with DDGS() as ddgs:
            for q in queries:
                # Lite mod kullanıyoruz (daha hızlı, az ban)
                try:
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='lite', max_results=15))
                except:
                    time.sleep(2)
                    continue

                for res in results:
                    url = res.get('href', '')
                    if url:
                        candidates.append(url)
            
            # Bulunan siteleri tek tek ziyaret et (CRAWLING)
            # Duplicate siteleri temizle
            candidates = list(set(candidates))
            logger.info(f"🌍 Toplam {len(candidates)} adet web sitesi incelenecek...")

            for site_url in candidates:
                # Eğer link zaten t.me ise direkt ekle
                if "t.me/" in site_url:
                    final_links.append({"url": site_url, "title": "Direkt Bulundu"})
                    continue
                
                # Değilse, sitenin içine gir (Mining)
                extracted = dig_for_links(site_url)
                for ex_link in extracted:
                    # Filtre yok! Ne bulursa ekliyor.
                    final_links.append({"url": ex_link, "title": f"Kaynak: {site_url}"})
                
                # Siteler arası çok kısa bekleme (hızlanmak için)
                time.sleep(0.5)

        return final_links
        
    except Exception as e:
        logger.error(f"Genel Hata: {e}")
        return []

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    fail_count = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Görev Bitti! {toplanan} link atıldı.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🔥 **{keyword}** sitelerin içinden sökülüyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
        except: pass

        new_links = search_web(keyword)
        
        gonderilecekler = []
        for item in new_links:
            # Telegram'ın kendi paylaşım linklerini (share/url) eleyelim ki flood olmasın
            # Ama joinchat veya + linklerine dokunmuyoruz.
            if "t.me/share" in item["url"]: continue

            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            logger.info(f"Bu turda link çıkmadı. ({fail_count}. deneme)")
            await asyncio.sleep(5) # Hızlıca tekrar dene
            continue
        
        fail_count = 0 

        # Bulunanları gruba kus
        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=f"{item['url']}", # Sadece link atıyoruz, temiz olsun
                    reply_to=CONFIG["target_topic_id"],
                    link_preview=False # Önizlemeyi kapat, daha hızlı atar
                )
                toplanan += 1
                await asyncio.sleep(2) # Flood yememek için mecburi bekleme
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")

    await status_msg.respond("🛑 Durdu.")

# ==================== KOMUTLAR ====================

@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır (Agresif Mod). /hedef ve /basla kullan.")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Tamam.")
        else: await event.respond("❌ Link bozuk.")
    except: await event.respond("❌ Link yok.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond(f"💀 **{kw}** için her deliğe giriliyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    CONFIG["is_running"] = False
    await event.respond("🛑 Durdu.")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
