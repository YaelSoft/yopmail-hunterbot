import os
import logging
import asyncio
import random
import re
import time
import requests
import urllib3
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events
from duckduckgo_search import DDGS

# ==================== AYARLAR ====================
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

HEDEF_LINK_SAYISI = 50 

# Yasaklı kelimeler (Yabancı/Gereksiz)
YASAKLI_KELIMELER = [
    "crypto", "forex", "bitcoin", "invest", "trading", "bet", 
    "casino", "stock", "market", "english", "usa", "indian"
]

# Uyarıları Sustur
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("SearchBot")
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

app = Flask(__name__)
@app.route('/')
def home(): return "Bot Takip Modunda 🟢"
def run_web(): port = int(os.environ.get("PORT", 8080)); app.run(host="0.0.0.0", port=port)
def keep_alive(): t = Thread(target=run_web); t.daemon = True; t.start()

client = TelegramClient("search_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

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

# ==================== YENİ: URL ÇÖZÜCÜ (REDIRECT FOLLOWER) ====================

def resolve_redirects(url):
    """
    Linke tıklar, yönlendirmeleri takip eder ve SON adresi getirir.
    Sayfa kaynağı boş olsa bile URL t.me ise yakalar.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        # allow_redirects=True: Bot linke tıklar ve sonuna kadar gider
        response = requests.head(url, headers=headers, allow_redirects=True, timeout=5, verify=False)
        final_url = response.url
        
        # Eğer son adres t.me ise Bingo!
        if "t.me/" in final_url:
            return final_url.split("?")[0]
            
    except:
        # head isteği yemezse get isteği atalım (biraz daha yavaş ama garanti)
        try:
            response = requests.get(url, headers=headers, timeout=5, verify=False)
            if "t.me/" in response.url:
                return response.url.split("?")[0]
        except:
            pass
            
    return None

def extract_telegram_links(text):
    """Metin içindeki linkleri bulur (Regex)"""
    found = set()
    # GÜNCELLENMİŞ REGEX: + (Plus) linklerini ve joinchat'i kesin yakalar
    regex = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)?([a-zA-Z0-9_\-]{4,})')
    
    matches = regex.findall(text)
    for match in matches:
        # Yasaklı kelime kontrolü
        if any(bad in match.lower() for bad in YASAKLI_KELIMELER): continue
        ignore = ["share", "addstickers", "proxy", "socks", "contact", "iv", "setlanguage", "telegram", "settings"]
        if match.lower() in ignore: continue

        # Linki yeniden inşa et
        # Eğer match 'joinchat' ile başlamıyorsa ve '+' yoksa, normal kullanıcı adıdır.
        # Ama regex zaten temizlediği için direkt ekleyebiliriz.
        # Düzeltme: Regex grubu sadece ID kısmını alıyor, başını biz ekleyelim.
        # Ancak + linkler için özel durum var.
        
        if text.find(f"+{match}") != -1: # Eğer orijinal metinde + varsa
            full_link = f"https://t.me/+{match}"
        elif text.find(f"joinchat/{match}") != -1:
            full_link = f"https://t.me/joinchat/{match}"
        else:
            full_link = f"https://t.me/{match}"
            
        found.add(full_link)
    return list(found)

# ==================== ARAMA MOTORU ====================

def search_web(keyword):
    final_links = []
    visited_sites = set()

    # Sen "site:t.me" dedin, o yüzden onu en başa koydum.
    queries = [
        f'site:t.me "{keyword}" "chat"', 
        f'site:t.me "{keyword}" "sohbet"',
        f'"{keyword}" "t.me/+"', 
        f'"{keyword}" "t.me/joinchat"'
    ]

    logger.info(f"🔍 '{keyword}' için link takibi yapılıyor...")

    try:
        with DDGS() as ddgs:
            for q in queries:
                if not CONFIG["is_running"]: break

                try:
                    # backend='html' en iyi sonucu veriyor şu an
                    results = list(ddgs.text(q, region='tr-tr', safesearch='off', backend='html', max_results=25))
                except:
                    time.sleep(2)
                    continue

                for res in results:
                    if not CONFIG["is_running"]: break

                    # Arama sonucundaki linki al
                    found_url = res.get('href', '')
                    title = res.get('title', '')
                    
                    # 1. YÖNTEM: Link zaten t.me ise DİREKT AL (Hiç uğraşma)
                    if "t.me/" in found_url:
                        clean = found_url.split("?")[0]
                        final_links.append({"url": clean, "title": "Direkt Bulundu"})
                        logger.info(f"✅ BULUNDU: {clean}")
                        continue
                    
                    # 2. YÖNTEM: Link t.me değilse (Google yönlendirmesi vs.), TAKİP ET
                    # "Tıklayınca o sayfa çıkıyor" dediğin olay burası.
                    resolved_link = resolve_redirects(found_url)
                    if resolved_link:
                        final_links.append({"url": resolved_link, "title": f"Yönlendirme: {title}"})
                        logger.info(f"🔀 YÖNLENDİRME ÇÖZÜLDÜ: {resolved_link}")
                        continue

                    # 3. YÖNTEM: Snippet (Özet Yazı) tarama
                    # Bazen link başlıkta yazar ama href başkadır.
                    snippet_links = extract_telegram_links(f"{title} {res.get('body', '')}")
                    for l in snippet_links:
                        final_links.append({"url": l, "title": f"Yazıdan: {title}"})

                    time.sleep(0.5)

        return final_links
        
    except Exception as e:
        logger.error(f"Hata: {e}")
        return []

# ==================== GÖREV DÖNGÜSÜ ====================

async def leech_task(status_msg, keyword):
    history = load_history()
    toplanan = 0
    fail_count = 0
    
    while CONFIG["is_running"]:
        if toplanan >= HEDEF_LINK_SAYISI:
            await status_msg.respond(f"🏁 Hedef tamam! {toplanan} link bulundu.")
            CONFIG["is_running"] = False
            break

        try:
            await status_msg.edit(f"🔗 **{keyword}** linkleri çözülüyor... ({toplanan}/{HEDEF_LINK_SAYISI})")
        except: pass

        new_links = search_web(keyword)
        
        if not CONFIG["is_running"]: break

        gonderilecekler = []
        for item in new_links:
            if item["url"] not in history:
                gonderilecekler.append(item)
                history.add(item["url"])
                save_history(item["url"])

        if not gonderilecekler:
            fail_count += 1
            logger.info(f"Link çıkmadı. ({fail_count}. deneme)")
            await asyncio.sleep(5)
            continue
        
        fail_count = 0 

        for item in gonderilecekler:
            if not CONFIG["is_running"]: break
            if toplanan >= HEDEF_LINK_SAYISI: break
            
            try:
                await client.send_message(
                    entity=CONFIG["target_chat_id"],
                    message=f"{item['url']}",
                    reply_to=CONFIG["target_topic_id"],
                    link_preview=False
                )
                toplanan += 1
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Gönderim hatası: {e}")

    await status_msg.respond("🛑 Durdu.")

# ==================== KOMUTLAR ====================
@client.on(events.NewMessage(pattern='/start'))
async def start_cmd(event): await event.respond("Bot Hazır. /hedef ve /basla")

@client.on(events.NewMessage(pattern='/hedef'))
async def set_target(event):
    try:
        link = event.message.text.split()[1]
        c, t = parse_topic_link(link)
        if c: 
            CONFIG["target_chat_id"], CONFIG["target_topic_id"] = c, t
            await event.respond("✅ Hedef Tamam.")
        else: await event.respond("❌ Hatalı Link.")
    except: await event.respond("❌ Link yok.")

@client.on(events.NewMessage(pattern='/basla'))
async def start_leech_cmd(event):
    if not CONFIG["target_chat_id"]: return await event.respond("⚠️ Hedef yok.")
    if CONFIG["is_running"]: return await event.respond("⚠️ Zaten çalışıyor.")
    try:
        kw = event.message.text.split(" ", 1)[1]
        CONFIG["current_keyword"], CONFIG["is_running"] = kw, True
        msg = await event.respond(f"🚀 **{kw}** takip ediliyor...")
        asyncio.create_task(leech_task(msg, kw))
    except: await event.respond("❌ Kelime yok.")

@client.on(events.NewMessage(pattern='/dur'))
async def stop_leech(event):
    if not CONFIG["is_running"]: return await event.respond("💤 Zaten duruk.")
    CONFIG["is_running"] = False
    await event.respond("🛑 Durduruluyor...")

if __name__ == '__main__':
    keep_alive()
    client.run_until_disconnected()
