import os
import re
import requests
import telebot
from telebot.types import InputMediaPhoto
import time
import logging
import uuid
import asyncio
from shazamio import Shazam
from flask import Flask, jsonify
from threading import Thread

# --- ١. ڕێکخستنی سێرڤەر ---
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "ok", "bot": "TikTok Downloader & Shazam Full Scanner Bot"}), 200

def run():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- ٢. ڕێکخستنی بۆت و لۆگ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
TOKEN = '9140242629:AAE9V3AHtx8In5HNmHeAq8n8aIqYQUUtigY'  # لێرە تۆکێنە تەواوەکەت دابنێ
bot = telebot.TeleBot(TOKEN, num_threads=4)

shazam_loop = asyncio.new_event_loop()
def start_shazam_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

Thread(target=start_shazam_loop, args=(shazam_loop,), daemon=True).start()

# --- ٣. ناسینەوەی گۆرانی بە شەزام ---
async def _recognize_song_async(filepath):
    try:
        shazam = Shazam()
        out = await shazam.recognize(filepath)
        if 'track' in out:
            title = out['track'].get('title', '')
            artist = out['track'].get('subtitle', '')
            return f"{title} - {artist}"
        return None
    except Exception as e:
        logging.error(f"Shazam Error: {e}")
        return None

def recognize_song(filepath):
    future = asyncio.run_coroutine_threadsafe(_recognize_song_async(filepath), shazam_loop)
    try:
        return future.result(timeout=30)
    except Exception as e:
        logging.error(f"Shazam Timeout/Error: {e}")
        return None

def extract_tiktok_url(text):
    match = re.search(r'(https?://[^\s]+)', text)
    return match.group(0).strip() if match else None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# --- ٤. سێ سیستەمی داگرتن بەیەکەوە (بۆ ئەوەی هەرگیز تووشی هەڵە نەبێت) ---
def try_lovetik(url):
    try:
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://lovetik.com/"
        }
        res = requests.post("https://lovetik.com/api/ajax/search", headers=headers, data={"query": url}, timeout=15).json()
        if res.get("status") == "ok":
            images = res.get("images", [])
            is_photo = len(images) > 0
            video_link = None
            audio_link = None
            for item in res.get("links", []):
                t = str(item.get("t", "")).lower()
                if "mp3" in t or "audio" in t:
                    audio_link = item.get("a")
                elif "mp4" in t or "no watermark" in t or "watermark" in t:
                    if not video_link:
                        video_link = item.get("a")
            info = {
                "author": res.get("author", "تیکتۆک"),
                "likes": 0,
                "views": 0,
                "is_photo": is_photo
            }
            media = images if is_photo else video_link
            if media:
                return media, audio_link, info
    except Exception as e:
        logging.error(f"Lovetik error: {e}")
    return None, None, None

def try_tikwm(url):
    try:
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://www.tikwm.com/"
        }
        res = requests.post("https://www.tikwm.com/api/", headers=headers, data={"url": url, "hd": 1}, timeout=15).json()
        if res.get("code") == 0:
            data = res.get("data", {})
            is_photo = "images" in data and len(data["images"]) > 0
            audio_link = data.get("music")
            info = {
                "author": data.get("author", {}).get("nickname", "تیکتۆک"),
                "likes": data.get("digg_count", 0),
                "views": data.get("play_count", 0),
                "is_photo": is_photo
            }
            media = data.get("images", []) if is_photo else (data.get("hdplay") or data.get("play") or data.get("wmplay"))
            if media:
                return media, audio_link, info
    except Exception as e:
        logging.error(f"TikWM error: {e}")
    return None, None, None

def try_tiklydown(url):
    try:
        res = requests.get(f"https://api.tiklydown.eu.org/api/download?url={url}", headers=HEADERS, timeout=15).json()
        if "video" in res or "images" in res:
            images = [img.get("url") for img in res.get("images", []) if img.get("url")]
            is_photo = len(images) > 0
            audio_link = res.get("music", {}).get("play_url")
            info = {
                "author": res.get("author", {}).get("nickname", "تیکتۆک"),
                "likes": res.get("stats", {}).get("likeCount", 0),
                "views": res.get("stats", {}).get("playCount", 0),
                "is_photo": is_photo
            }
            media = images if is_photo else (res.get("video", {}).get("noWatermark") or res.get("video", {}).get("watermark"))
            if media:
                return media, audio_link, info
    except Exception as e:
        logging.error(f"Tiklydown error: {e}")
    return None, None, None

def download_tiktok(url):
    # پشکنینی ڕاستەوخۆ بە یەک لە دوای یەک
    media, audio, info = try_lovetik(url)
    if media:
        return media, audio, info

    media, audio, info = try_tikwm(url)
    if media:
        return media, audio, info

    media, audio, info = try_tiklydown(url)
    if media:
        return media, audio, info

    return None, None, None

# --- ٥. بەڕێوەبردنی پەیامەکان ---
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋🏼 من دەتوانم ڤیدیۆ و وێنەی (تیکتۆک) دابەزێنم.\n🎵 ناوی گۆرانییەکە لە سەرەتاوە تا کۆتایی پۆستەکە دەپشکێنم و دەنگی سەر پۆستەکەت بۆ دەنێرمەوە.\n\n🔗 تەنیا لینکی تیکتۆک بنێرە📥:")

@bot.message_handler(func=lambda msg: True)
def handle_links(message):
    Thread(target=process_request, args=(message,)).start()

def process_request(message):
    raw_url = extract_tiktok_url(message.text.strip())

    if raw_url and "tiktok.com" in raw_url:
        wait_msg = bot.reply_to(message, "⏳ چاوەڕێ بکە خەریکم پۆستەکە دادەبەزێنم...")
        media_data, audio_url, info = download_tiktok(raw_url)

        if media_data:
            caption = f"👤 ناوی ئەکاونت: {info['author']}\n❤️ ڕێژەی ڵایک: {info['likes']} | 👀 ڕێژەی بینین: {info['views']}\n\n⚙️ دروستکەری بۆت Ara"
            temp_video = None
            temp_audio = None
            try:
                # ١. ناردنی وێنە یان ڤیدیۆ
                if info["is_photo"]:
                    images = media_data
                    for i in range(0, len(images), 10):
                        chunk = images[i:i+10]
                        media_group = [InputMediaPhoto(chunk[0], caption=caption if i==0 else "")] + [InputMediaPhoto(img) for img in chunk[1:]]
                        bot.send_media_group(message.chat.id, media_group, timeout=120)
                else:
                    temp_video = f"video_{uuid.uuid4()}.mp4"
                    with requests.get(media_data, headers=HEADERS, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(temp_video, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=16384):
                                f.write(chunk)
                    
                    with open(temp_video, 'rb') as vf:
                        bot.send_video(message.chat.id, vf, caption=caption, timeout=180)

                bot.edit_message_text("🔍 خەریکی پشکنینی پۆستەکەم بۆ دۆزینەوەی ناوی گۆرانی...", message.chat.id, wait_msg.message_id)

                song_name = None

                # ٢. داگرتنی دەنگ و پشکنین بە Shazam
                if audio_url:
                    temp_audio = f"audio_{uuid.uuid4()}.mp3"
                    with requests.get(audio_url, headers=HEADERS, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(temp_audio, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)

                    song_name = recognize_song(temp_audio)

                # ٣. ناردنی فایلی دەنگ
                if temp_audio and os.path.exists(temp_audio):
                    if song_name:
                        audio_caption = f"🎶 ناوی گۆرانی: {song_name}\n🔊 دەنگی سەر پۆستەکە"
                    else:
                        audio_caption = "🔊 دەنگی سەر پۆستەکە\n(ناوی گۆرانییەکە نەدۆزرایەوە)"

                    with open(temp_audio, 'rb') as audio_file:
                        bot.send_audio(message.chat.id, audio_file, caption=audio_caption, timeout=120)

                bot.delete_message(message.chat.id, wait_msg.message_id)
            except Exception as e:
                logging.error(f"Error in sending media: {e}")
                bot.edit_message_text("❌ کێشەیەک ڕوویدا لە کاتی ناردنی فایلەکە بۆ تێلیگرام.", message.chat.id, wait_msg.message_id)
            finally:
                if temp_video and os.path.exists(temp_video):
                    os.remove(temp_video)
                if temp_audio and os.path.exists(temp_audio):
                    os.remove(temp_audio)
        else:
            bot.edit_message_text("❌ نەمتوانی پۆستەکە دابگرم، تکایە دڵنیابە لە بەردەستبوونی پۆستەکە.", message.chat.id, wait_msg.message_id)
    else:
        bot.reply_to(message, "❌ تکایە تەنیا لینکی دروستی تیکتۆک بنێرە.")

# --- ٦. دەستپێکردن ---
if __name__ == '__main__':
    keep_alive()
    try:
        bot.delete_webhook()
    except Exception:
        pass
    print("🤖 بۆتەکە بە سەرکەوتوویی کەوتە کار...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)
