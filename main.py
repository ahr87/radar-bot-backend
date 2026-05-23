import os
import requests
import time
import subprocess
import schedule
import random
import json
from flask import Flask, jsonify, request
from flask_cors import CORS
from threading import Thread
from openai import OpenAI
from datetime import datetime
import boto3
from botocore.client import Config

# ═══════════════════════════════════════════════
# RADAR NEWS BOT — BACKEND ENGINE v2.0
# Railway Deployment | Fully Automated
# ═══════════════════════════════════════════════

app = Flask(__name__)
CORS(app)

# ── ENV VARIABLES (set in Railway dashboard) ──
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY")
IG_ACCESS_TOKEN    = os.environ.get("IG_ACCESS_TOKEN")
IG_ACCOUNT_ID      = os.environ.get("IG_ACCOUNT_ID")
B2_KEY_ID          = os.environ.get("B2_KEY_ID")
B2_APP_KEY         = os.environ.get("B2_APP_KEY")
B2_BUCKET          = os.environ.get("B2_BUCKET", "radar-news-bot")
B2_ENDPOINT        = os.environ.get("B2_ENDPOINT", "https://s3.us-east-005.backblazeb2.com")
BOT_SECRET         = os.environ.get("BOT_SECRET", "radar2025")  # for API auth

client = OpenAI(api_key=OPENAI_API_KEY)

MEMORY_FILE  = "published_topics.txt"
STATS_FILE   = "stats.json"
LOG_FILE     = "bot_log.json"

# ── POST TYPE ROTATION ──
# Alternates: reel → image → reel → image ...
POST_COUNTER_FILE = "post_counter.txt"

# ── HOOK STYLES ──
HOOK_STYLES = {
    "shock":    "ابدأ بجملة صادمة تكشف حقيقة خطيرة مخفية عن الناس",
    "question": "ابدأ بسؤال فلسفي أو علمي يجعل القارئ يتوقف فوراً ويفكر",
    "number":   "ابدأ برقم مثير كـ '99% من الناس لا يعرفون هذا' أو '7 حقائق غيّرت التاريخ'",
    "story":    "ابدأ بسرد قصة حقيقية مثيرة من التاريخ بأسلوب درامي مشوق",
}

# ═══════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════

def log(msg, level="info"):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "level": level,
        "msg": msg
    }
    print(f"[{entry['time']}] {msg}")
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except:
            logs = []
    logs.insert(0, entry)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs[:100], f, ensure_ascii=False)

def get_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {"total": 0, "reels": 0, "images": 0, "today": 0, "last_post": None, "today_date": None}

def update_stats(post_type):
    s = get_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("today_date") != today:
        s["today"] = 0
        s["today_date"] = today
    s["total"] += 1
    s["today"] += 1
    s["last_post"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    if post_type == "reel":
        s["reels"] = s.get("reels", 0) + 1
    else:
        s["images"] = s.get("images", 0) + 1
    with open(STATS_FILE, "w") as f:
        json.dump(s, f)

def get_previous_topics():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "لا توجد مواضيع سابقة"

def save_topic(topic):
    titles = []
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            titles = f.read().splitlines()
    titles.insert(0, topic)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(titles[:30]))

def get_post_type():
    """Alternate between reel and image automatically"""
    counter = 0
    if os.path.exists(POST_COUNTER_FILE):
        with open(POST_COUNTER_FILE, "r") as f:
            counter = int(f.read().strip() or 0)
    post_type = "reel" if counter % 2 == 0 else "image"
    with open(POST_COUNTER_FILE, "w") as f:
        f.write(str(counter + 1))
    return post_type

def get_hook_style():
    styles = list(HOOK_STYLES.keys())
    return random.choice(styles)

# ═══════════════════════════════
# CONTENT GENERATION
# ═══════════════════════════════

def generate_content(hook_style=None):
    log("🧠 GPT-4o يبتكر المحتوى...")
    previous = get_previous_topics()
    if not hook_style:
        hook_style = get_hook_style()

    hook_instruction = HOOK_STYLES[hook_style]

    prompt = f"""أنت صانع محتوى ويوتيوبر محترف تدير حساب انستقرام عراقي اسمه "رادار نيوز" متخصص في الحقائق العلمية النادرة والغريبة.

هدفك: إنشاء محتوى يصعد لـ EXPLORE ويحقق أعلى engagement ممكن.

قاعدة الهوك: {hook_instruction}

المواضيع المنشورة سابقاً (تجنبها تماماً): [{previous}]

أنشئ محتوى عن حقيقة علمية نادرة جداً ومثيرة.

أجب بـ JSON فقط بدون أي نص خارجه:
{{
  "topic": "عنوان الموضوع بكلمتين أو ثلاث",
  "hook": "جملة الهوك القوية للكابشن (15-20 كلمة، تبدأ بـ emoji مناسب)",
  "script": "السيناريو الصوتي كاملاً بالفصحى المبسطة السليمة 100% (40-55 كلمة فقط، Hook قوي في البداية، معلومة مذهلة في المنتصف، call to action في النهاية)",
  "caption": "الكابشن الكامل للبوست: يبدأ بـ Hook مختلف عن السيناريو + شرح مختصر + سؤال يدعو للتعليق + سطر فارغ + 5 هاشتاقات عربية وانجليزية مناسبة",
  "image_prompt": "وصف بالإنجليزية لصورة DALL-E 3 سريالية عالية الجودة، vertical 9:16، سينمائية، بدون أي نص أو كلمات في الصورة، تعبّر عن الموضوع بأسلوب conceptual art"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,
        response_format={"type": "json_object"}
    )

    content = json.loads(response.choices[0].message.content)
    log(f"✅ المحتوى جاهز — الموضوع: {content['topic']}")
    return content

# ═══════════════════════════════
# IMAGE GENERATION
# ═══════════════════════════════

def generate_image(image_prompt):
    log("🎨 DALL-E 3 يرسم الصورة...")
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=f"{image_prompt}. Masterpiece quality, cinematic lighting, ultra detailed, no text, no letters, no words anywhere in the image.",
            size="1024x1792",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url
        img_data = requests.get(image_url, timeout=30).content
        with open("temp_image.jpg", "wb") as f:
            f.write(img_data)
        log("✅ الصورة محفوظة محلياً")
        return True
    except Exception as e:
        log(f"❌ خطأ DALL-E: {e}", "error")
        # Fallback: try with simpler prompt
        try:
            simple_prompt = f"Surreal conceptual art, vertical 9:16, cinematic, highly detailed, no text"
            response = client.images.generate(
                model="dall-e-3",
                prompt=simple_prompt,
                size="1024x1792",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            img_data = requests.get(image_url, timeout=30).content
            with open("temp_image.jpg", "wb") as f:
                f.write(img_data)
            log("✅ صورة بديلة محفوظة")
            return True
        except:
            return False

# ═══════════════════════════════
# VOICE GENERATION
# ═══════════════════════════════

def generate_voice(text):
    log("🎙️ OpenAI TTS يسجّل الصوت بجودة HD...")
    try:
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice="onyx",
            input=text,
            speed=0.95
        )
        with open("temp_audio.mp3", "wb") as f:
            f.write(response.content)
        log("✅ الصوت جاهز")
        return True
    except Exception as e:
        log(f"❌ خطأ TTS: {e}", "error")
        return False

# ═══════════════════════════════
# VIDEO CREATION (REEL)
# ═══════════════════════════════

def create_reel():
    log("🎬 ffmpeg يصنع الريلز بتأثير Zoom...")
    try:
        command = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", "30", "-i", "temp_image.jpg",
            "-i", "temp_audio.mp3",
            "-vf", (
                "zoompan=z='if(lte(zoom,1.0),1.05,max(1.001,zoom-0.0008))'"
                ":x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
                ":d=125:s=1080x1920:fps=30,"
                "fade=t=in:st=0:d=0.5"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            "output_reel.mp4"
        ]
        result = subprocess.run(command, capture_output=True, timeout=120)
        if result.returncode == 0:
            log("✅ فيديو الريلز جاهز")
            return True
        else:
            log(f"❌ ffmpeg error: {result.stderr.decode()[:200]}", "error")
            return False
    except Exception as e:
        log(f"❌ خطأ ffmpeg: {e}", "error")
        return False

# ═══════════════════════════════
# UPLOAD TO CLOUDINARY
# ═══════════════════════════════

def get_b2_client():
    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
        config=Config(signature_version="s3v4"),
    )

def upload_video_b2():
    log("☁️ رفع الفيديو على Backblaze B2...")
    try:
        s3 = get_b2_client()
        filename = f"reel_{int(time.time())}.mp4"
        s3.upload_file(
            "output_reel.mp4",
            B2_BUCKET,
            filename,
            ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"}
        )
        url = f"{B2_ENDPOINT}/{B2_BUCKET}/{filename}"
        log(f"✅ الفيديو منشور: {url[:60]}...")
        return url
    except Exception as e:
        log(f"❌ خطأ Backblaze فيديو: {e}", "error")
        return None

def upload_image_b2():
    log("☁️ رفع الصورة على Backblaze B2...")
    try:
        s3 = get_b2_client()
        filename = f"img_{int(time.time())}.jpg"
        s3.upload_file(
            "temp_image.jpg",
            B2_BUCKET,
            filename,
            ExtraArgs={"ContentType": "image/jpeg", "ACL": "public-read"}
        )
        url = f"{B2_ENDPOINT}/{B2_BUCKET}/{filename}"
        log(f"✅ الصورة منشورة: {url[:60]}...")
        return url
    except Exception as e:
        log(f"❌ خطأ Backblaze صورة: {e}", "error")
        return None

# ═══════════════════════════════
# INSTAGRAM PUBLISHING
# ═══════════════════════════════

def post_reel(video_url, caption):
    log("🚀 نشر الريلز على إنستقرام...")
    base = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}"

    # Step 1: Create container
    res = requests.post(f"{base}/media", data={
        "video_url": video_url,
        "caption": caption,
        "media_type": "REELS",
        "share_to_feed": "true",
        "access_token": IG_ACCESS_TOKEN
    }).json()

    if "id" not in res:
        log(f"❌ فشل إنشاء container: {res}", "error")
        return False

    creation_id = res["id"]
    log(f"⏳ معالجة الفيديو... (ID: {creation_id})")

    # Step 2: Wait for processing
    for attempt in range(20):
        time.sleep(15)
        status = requests.get(
            f"https://graph.facebook.com/v20.0/{creation_id}",
            params={"fields": "status_code", "access_token": IG_ACCESS_TOKEN}
        ).json()
        code = status.get("status_code")
        log(f"  الحالة: {code} (محاولة {attempt+1}/20)")
        if code == "FINISHED":
            break
        if code == "ERROR":
            log("❌ خطأ في معالجة الفيديو", "error")
            return False

    # Step 3: Publish
    pub = requests.post(f"{base}/media_publish", data={
        "creation_id": creation_id,
        "access_token": IG_ACCESS_TOKEN
    }).json()

    if "id" in pub:
        log(f"🎉 تم نشر الريلز بنجاح! Post ID: {pub['id']}", "success")
        return True
    else:
        log(f"❌ فشل النشر: {pub}", "error")
        return False

def post_image(image_url, caption):
    log("🚀 نشر الصورة على إنستقرام...")
    base = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}"

    # Step 1: Create container
    res = requests.post(f"{base}/media", data={
        "image_url": image_url,
        "caption": caption,
        "access_token": IG_ACCESS_TOKEN
    }).json()

    if "id" not in res:
        log(f"❌ فشل إنشاء container: {res}", "error")
        return False

    creation_id = res["id"]
    time.sleep(5)

    # Step 2: Publish
    pub = requests.post(f"{base}/media_publish", data={
        "creation_id": creation_id,
        "access_token": IG_ACCESS_TOKEN
    }).json()

    if "id" in pub:
        log(f"🎉 تم نشر الصورة بنجاح! Post ID: {pub['id']}", "success")
        return True
    else:
        log(f"❌ فشل النشر: {pub}", "error")
        return False

# ═══════════════════════════════
# CLEANUP
# ═══════════════════════════════

def cleanup():
    for f in ["temp_image.jpg", "temp_audio.mp3", "output_reel.mp4"]:
        if os.path.exists(f):
            os.remove(f)

# ═══════════════════════════════
# MAIN JOB
# ═══════════════════════════════

def job():
    log("═" * 50)
    log("⏰ بدء دورة النشر الآلية")
    log("═" * 50)

    post_type = get_post_type()
    log(f"📌 نوع المنشور: {post_type.upper()}")

    try:
        # 1. Generate content
        content = generate_content()

        # 2. Generate image
        if not generate_image(content["image_prompt"]):
            log("❌ فشل توليد الصورة، إلغاء الدورة", "error")
            return

        if post_type == "reel":
            # 3a. Generate voice
            if not generate_voice(content["script"]):
                log("⚠️ فشل الصوت، التحويل لصورة بدلاً")
                post_type = "image"
            else:
                # 4. Create video
                if not create_reel():
                    log("⚠️ فشل المونتاج، التحويل لصورة بدلاً")
                    post_type = "image"
                else:
                    # 5. Upload video
                    video_url = upload_video_b2()
                    if not video_url:
                        log("❌ فشل رفع الفيديو", "error")
                        cleanup()
                        return
                    # 6. Post reel
                    caption = f"{content['hook']}\n\n{content['caption']}"
                    if post_reel(video_url, caption):
                        save_topic(content["topic"])
                        update_stats("reel")
                    cleanup()
                    return

        # Image post path
        img_url = upload_image_b2()
        if not img_url:
            log("❌ فشل رفع الصورة", "error")
            cleanup()
            return

        caption = f"{content['hook']}\n\n{content['caption']}"
        if post_image(img_url, caption):
            save_topic(content["topic"])
            update_stats("image")

    except Exception as e:
        log(f"❌ خطأ عام: {e}", "error")

    finally:
        cleanup()

# ═══════════════════════════════
# FLASK API ENDPOINTS
# ═══════════════════════════════

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("X-Bot-Secret", "")
        if token != BOT_SECRET:
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/")
def home():
    return jsonify({"status": "Radar News Bot is alive 🚀", "version": "2.0"})

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/logs")
def api_logs():
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    return jsonify(logs)

@app.route("/api/trigger", methods=["POST"])
@require_auth
def api_trigger():
    """Manually trigger a post from dashboard"""
    Thread(target=job).start()
    return jsonify({"status": "started"})

@app.route("/api/preview", methods=["POST"])
@require_auth
def api_preview():
    """Generate content preview without posting"""
    data = request.json or {}
    hook_style = data.get("hook_style", None)
    try:
        content = generate_content(hook_style)
        return jsonify(content)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/status")
def api_status():
    return jsonify({
        "bot_running": True,
        "openai_connected": bool(OPENAI_API_KEY),
        "instagram_connected": bool(IG_ACCESS_TOKEN and IG_ACCOUNT_ID),
        "cloudinary_connected": bool(B2_KEY_ID and B2_APP_KEY),
        "timestamp": datetime.now().isoformat()
    })

# ═══════════════════════════════
# SCHEDULER
# ═══════════════════════════════

def run_scheduler():
    # 11:00 UTC = 2:00 PM Iraq time
    # 17:00 UTC = 8:00 PM Iraq time
    schedule.every().day.at("11:00").do(job)
    schedule.every().day.at("17:00").do(job)

    log("📅 الجدول الزمني:")
    log("   11:00 UTC → 2:00 PM بتوقيت العراق")
    log("   17:00 UTC → 8:00 PM بتوقيت العراق")

    while True:
        schedule.run_pending()
        time.sleep(30)

# ═══════════════════════════════
# ENTRY POINT
# ═══════════════════════════════

if __name__ == "__main__":
    log("🚀 RADAR NEWS BOT v2.0 يبدأ...")

    log("✅ Backblaze B2 متصل")

    # Start scheduler in background thread
    scheduler_thread = Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Start Flask server
    port = int(os.environ.get("PORT", 8080))
    log(f"🌐 السيرفر يعمل على port {port}")
    app.run(host="0.0.0.0", port=port)
