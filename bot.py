import os
import re
import telebot
import time
import logging
import uuid
import asyncio
from shazamio import Shazam
from flask import Flask, jsonify
from threading import Thread
import yt_dlp

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

# --- ٢. ڕێکخستنی بۆت ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
TOKEN = '9140242629:AAE9V3AHtx8In5HNmHeAq8n8aIqYQUUtigY'  # لێرە تۆکێنە نوێیەکەت دابنێ
bot = telebot.TeleBot(TOKEN, num_threads=4)

shazam_loop = asyncio.new_event_loop()
def start_shazam_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

Thread(target=start_shazam_loop, args=(shazam_loop,), daemon=True).start()

# --- ٣. ناسینەوەی دەنگ بە Shazam ---
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
        return future.result(timeout=25)
    except Exception as e:
        logging.error(f"Shazam Timeout: {e}")
        return None

def extract_tiktok_url(text):
    match = re.search(r'(https?://[^\s]+)', text)
    return match.group(0).strip() if match else None

# --- ٤. داگرتن بە شێوازی فەرمی yt-dlp ---
def download_media_ytdlp(url, output_prefix):
    video_path = f"{output_prefix}.mp4"
    audio_path = f"{output_prefix}.mp3"
    
    ydl_opts = {
        'outtmpl': f"{output_prefix}.%(ext)s",
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            author = info.get('uploader') or info.get('creator') or 'تیکتۆک'
            likes = info.get('like_count', 0)
            views = info.get('view_count', 0)
            
            # دەرهێنانی دەنگ بۆ پشکنینی شەزام
            audio_opts = {
                'outtmpl': audio_path,
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
            try:
                with yt_dlp.YoutubeDL(audio_opts) as ydl_audio:
                    ydl_audio.download([url])
            except Exception:
                pass

            actual_video = None
            for ext in ['mp4', 'mkv', 'webm']:
                cand = f"{output_prefix}.{ext}"
                if os.path.exists(cand):
                    actual_video = cand
                    break

            return actual_video, (audio_path if os.path.exists(audio_path) else None), author, likes, views
    except Exception as e:
        logging.error(f"yt-dlp error: {e}")
        return None, None, None, 0, 0

# --- ٥. فەرمان و پەیامەکان ---
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
        file_prefix = f"media_{uuid.uuid4()}"
        video_file, audio_file, author, likes, views = download_media_ytdlp(raw_url, file_prefix)

        if video_file and os.path.exists(video_file):
            caption = f"👤 ناوی ئەکاونت: {author}\n❤️ ڕێژەی ڵایک: {likes} | 👀 ڕێژەی بینین: {views}\n\n⚙️ دروستکەری بۆت Ara"
            try:
                with open(video_file, 'rb') as vf:
                    bot.send_video(message.chat.id, vf, caption=caption, timeout=180)

                bot.edit_message_text("🔍 خەریکی پشکنینی ناوی گۆرانییەکەم...", message.chat.id, wait_msg.message_id)

                song_name = None
                target_audio = audio_file if (audio_file and os.path.exists(audio_file)) else video_file
                if target_audio:
                    song_name = recognize_song(target_audio)

                if audio_file and os.path.exists(audio_file):
                    audio_caption = f"🎶 ناوی گۆرانی: {song_name}\n🔊 دەنگی سەر پۆستەکە" if song_name else "🔊 دەنگی سەر پۆستەکە"
                    with open(audio_file, 'rb') as af:
                        bot.send_audio(message.chat.id, af, caption=audio_caption, timeout=120)

                bot.delete_message(message.chat.id, wait_msg.message_id)
            except Exception as e:
                logging.error(f"Telegram send error: {e}")
                bot.edit_message_text("❌ کێشەیەک ڕوویدا لە کاتی ناردنی فایلەکە.", message.chat.id, wait_msg.message_id)
            finally:
                for f in [video_file, audio_file, f"{file_prefix}.mp4", f"{file_prefix}.mp3"]:
                    if f and os.path.exists(f):
                        try:
                            os.remove(f)
                        except Exception:
                            pass
        else:
            bot.edit_message_text("❌ نەمتوانی پۆستەکە دابگرم، تکایە دڵنیابە لە بەردەستبوونی پۆستەکە.", message.chat.id, wait_msg.message_id)
    else:
        bot.reply_to(message, "❌ تکایە تەنیا لینکی دروستی تیکتۆک بنێرە.")

if __name__ == '__main__':
    keep_alive()
    try:
        bot.delete_webhook()
    except Exception:
        pass
    print("🤖 بۆتەکە دەستی بە کار کرد...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            time.sleep(5)
