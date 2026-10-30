import os
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

# --- ١. ڕێکخستنی سێرڤەر (بۆ ئەوەی هۆستەکە نەخەوێت) ---
app = Flask('')

@app.route('/')
def home():
    return jsonify({"status": "ok", "bot": "TikTok Downloader & Shazam Full Scanner Bot"}), 200

def run():
    app.run(host='0.0.0.0', port=5000, threaded=True)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- ٢. ڕێکخستنی بۆت و لۆگ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
TOKEN = os.environ.get('9140242629:AAE9V3AHtx8In5HNmHeAq8n8aIqYQUUtigY')
bot = telebot.TeleBot(TOKEN, num_threads=4)

# دروستکردنی لۆپێکی تایبەت بۆ کارە ئەسینکەکانی شەزام تا بۆتەکە بلۆک نەبێت
shazam_loop = asyncio.new_event_loop()
def start_shazam_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

Thread(target=start_shazam_loop, args=(shazam_loop,), daemon=True).start()

# --- ٣. ناسینەوەی گۆرانی بە پشکنینی تەواوی فایلەکە (لەسەرەتاوە تا کۆتایی) ---
async def _recognize_song_async(filepath):
    try:
        shazam = Shazam()
        # shazam.recognize لێرەدا تەواوی فایلەکە دەپشکێنێت. ئەگەر لە خولەکی یەکەمدا دۆزرایەوە ڕاستەوخۆ دەیگەڕێنێتەوە،
        # ئەگەر نا، بەردەوام دەبێت لە گەڕان لە ناو بەشەکانی تری فایلەکە تا کۆتایی.
        out = await shazam.recognize(filepath)
        if 'track' in out:
            title = out['track']['title']
            artist = out['track']['subtitle']
            return f"{title} - {artist}"
        return None
    except Exception as e:
        logging.error(f"Shazam Error: {e}")
        return None

def recognize_song(filepath):
    future = asyncio.run_coroutine_threadsafe(_recognize_song_async(filepath), shazam_loop)
    try:
        # کاتی چاوەڕوانیمان کردووە بە 40 چرکە بۆ ئەوەی ئەگەر فایلەکە درێژ بوو، کاتی تەواوی هەبێت بۆ پشکنینی تا کۆتایی
        return future.result(timeout=40)
    except Exception as e:
        logging.error(f"Shazam Thread Timeout/Error: {e}")
        return None

# --- ٤. فانکشنی داگرتنی تیکتۆک ---
def download_tiktok(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        api_url = f"https://www.tikwm.com/api/?url={url}"
        response = requests.get(api_url, headers=headers, timeout=15).json()

        if response.get("code") == 0:
            is_photo = "images" in response["data"]
            audio_link = response["data"].get("music")
            info = {
                "author": response["data"]["author"]["nickname"],
                "likes": response["data"]["digg_count"],
                "views": response["data"]["play_count"],
                "is_photo": is_photo
            }
            if is_photo:
                media_links = response["data"]["images"]
            else:
                media_links = response["data"].get("hdplay") or response["data"].get("play")
            return media_links, audio_link, info
        return None, None, None
    except Exception as e:
        logging.error(f"TikTok Download Error: {e}")
        return None, None, None

# --- ٥. فەرمانەکانی بۆت ---
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋🏼 من دەتوانم ڤیدیۆ و وێنەی (تیکتۆک) دابەزێنم.\n🎵 ناوی گۆرانییەکە لە سەرەتاوە تا کۆتایی پۆستەکە دەپشکێنم و دەنگی سەر پۆستەکەت بۆ دەنێرمەوە.\n\n🔗 تەنیا لینکی تیکتۆک بنێرە📥:")

@bot.message_handler(func=lambda msg: True)
def handle_links(message):
    Thread(target=process_request, args=(message,)).start()

def process_request(message):
    url = message.text.strip()

    if "tiktok.com" in url:
        wait_msg = bot.reply_to(message, "⏳ چاوەڕێ بکە خەریکم پۆستەکە دادەبەزێنم...")
        media_data, audio_url, info = download_tiktok(url)

        if media_data:
            caption = f"👤 ناوی ئەکاونت: {info['author']}\n❤️ ڕێژەی ڵایک: {info['likes']} | 👀 ڕێژەی بینین: {info['views']}\n\n⚙️ دروستکەری بۆت Ara"
            temp_audio = None
            try:
                # ١. ناردنی وێنە یان ڤیدیۆی تیکتۆکەکە
                if info["is_photo"]:
                    images = media_data
                    for i in range(0, len(images), 10):
                        chunk = images[i:i+10]
                        media_group = [InputMediaPhoto(chunk[0], caption=caption if i==0 else "")] + [InputMediaPhoto(img) for img in chunk[1:]]
                        bot.send_media_group(message.chat.id, media_group, timeout=120)
                else:
                    bot.send_video(message.chat.id, media_data, caption=caption, timeout=120)

                bot.edit_message_text("🔍 خەریکی پشکنینی تەواوی پۆستەکەم بۆ دۆزینەوەی ناوی گۆرانی (چاوەڕێ بە )...", message.chat.id, wait_msg.message_id)

                song_name = None

                # ٢. داگرتنی فایلی دەنگی ڕەسەن بە تەواوی
                if audio_url:
                    temp_audio = f"audio_{uuid.uuid4()}.mp3"

                    with requests.get(audio_url, stream=True) as r:
                        r.raise_for_status()
                        with open(temp_audio, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)

                    # لێرەدا شەزام تەواوی فایلەکە دەخوێنێتەوە بەو مەرجەی سەرەوە کە باست کردووە
                    song_name = recognize_song(temp_audio)

                # ٣. ناردنەوەی دەنگەکە وەک فایلی MP3
                if temp_audio and os.path.exists(temp_audio):
                    if song_name:
                        audio_caption = f"🎶 ناوی گۆرانی: {song_name}\n🔊 دەنگی سەر پۆستەکە"
                    else:
                        audio_caption = "🔊 دەنگی سەر پۆستەکە\n(ناوی گۆرانییەکە لە پشکنینی تەواوی پۆستەکە نەدۆزرایەوە)"

                    with open(temp_audio, 'rb') as audio_file:
                        bot.send_audio(message.chat.id, audio_file, caption=audio_caption, timeout=120)

                bot.delete_message(message.chat.id, wait_msg.message_id)
            except Exception as e:
                logging.error(f"Error in TikTok flow: {e}")
            finally:
                if temp_audio and os.path.exists(temp_audio): 
                    os.remove(temp_audio)
        else:
            bot.edit_message_text("❌ نەمتوانی پۆستەکە بنێرمەوە بکەم.", message.chat.id, wait_msg.message_id)
    else:
        bot.reply_to(message, "❌ تکایە تەنیا لینکی تیکتۆک بنێرە.")

# --- ٦. دەستپێکردن ---
if __name__ == '__main__':
    keep_alive()
    bot.delete_webhook()
    print("🤖 بۆتەکە بە سەرکەوتوویی لەسەر لۆجیکی پشکنینی تەواو کار دەکات...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)
