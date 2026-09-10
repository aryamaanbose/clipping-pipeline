"""Telegram bot loop: receive links -> run pipeline -> upload -> reply.

Run: caffeinate -i .venv/bin/python bot.py   (laptop plugged in, lid open)
"""
import json
import os
import re
import shutil
import sqlite3
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

import pipeline  # also loads .env
import stats
import uploader

ROOT = Path(__file__).resolve().parent
TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
API = "https://api.telegram.org/bot" + TOKEN
MAX_UPLOADS_PER_DAY = 6  # ponytail: YouTube quota = 10k units/day, 1600/upload


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + "/" + method, data, timeout=70) as r:
        return json.load(r)["result"]


def send_video(path, caption):
    """Deliver the clip file itself to Telegram, so it can be published by hand
    (YouTube app upload) without going through the API's audit-gated private lock."""
    boundary = "----clip" + os.urandom(8).hex()
    b = boundary.encode()

    def field(name, value):
        return (b"--" + b + b"\r\n"
                b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n' +
                value + b"\r\n")

    body = (
        field("chat_id", CHAT_ID.encode()) +
        field("caption", caption[:1024].encode()) +
        b"--" + b + b"\r\n"
        b'Content-Disposition: form-data; name="video"; filename="' +
        Path(path).name.encode() + b'"\r\n'
        b"Content-Type: video/mp4\r\n\r\n" +
        Path(path).read_bytes() + b"\r\n"
        b"--" + b + b"--\r\n"
    )
    req = urllib.request.Request(
        API + "/sendVideo", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["result"]


def say(text):
    try:
        tg("sendMessage", chat_id=CHAT_ID, text=text[:4000])
    except Exception:
        pass  # never let a notify failure kill the loop


def init_db():
    db = sqlite3.connect(ROOT / "state.db")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id INTEGER PRIMARY KEY, url TEXT, status TEXT DEFAULT 'pending',
        error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("""CREATE TABLE IF NOT EXISTS uploads(
        video_id TEXT PRIMARY KEY, job_id INTEGER, title TEXT, source_url TEXT,
        published_at TEXT DEFAULT CURRENT_TIMESTAMP, views INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0, subs_gained INTEGER DEFAULT 0,
        est_revenue REAL DEFAULT 0, fetched_at TEXT)""")
    db.commit()
    return db


def uploads_today(db):
    # ponytail: UTC day, close enough to YouTube's midnight-Pacific quota reset
    return db.execute(
        "SELECT COUNT(*) FROM uploads WHERE date(published_at)=date('now')").fetchone()[0]


def process_job(db, job_id, url):
    workdir = pipeline.WORK / ("job%d" % job_id)
    clips = pipeline.run(url, workdir)
    links, held = [], 0
    for c in clips:
        # deliver the file itself regardless of quota, so it can be published by
        # hand (YouTube app) - not gated by the API's audit-locked private uploads
        caption = "%s\n\n%s\n\n%s" % (c["title"], c["description"], " ".join(c["hashtags"]))
        send_video(c["file"], caption)
        if uploads_today(db) >= MAX_UPLOADS_PER_DAY:
            held += 1
            continue
        vid = uploader.upload(c["file"], c["title"], c["description"], c["hashtags"])
        db.execute("INSERT INTO uploads(video_id, job_id, title, source_url) VALUES(?,?,?,?)",
                   (vid, job_id, c["title"], url))
        db.commit()
        links.append("https://youtube.com/shorts/" + vid)
    db.execute("UPDATE jobs SET status='done' WHERE id=?", (job_id,))
    db.commit()
    msg = "sent %d clip file(s) above for manual posting; %d also auto-uploaded (private) from %s:\n%s" % (
        len(clips), len(links), clips[0]["source_title"] if clips else url, "\n".join(links))
    if held:
        msg += "\n%d clip(s) skipped auto-upload - daily quota hit (still sent as files above)" % held
    if not held:
        shutil.rmtree(workdir, ignore_errors=True)
    say(msg)


def main():
    db = init_db()
    last_stats = 0.0
    offset = 0
    print("bot running - send a video link to your Telegram bot")
    while True:
        pending = db.execute(
            "SELECT id, url FROM jobs WHERE status='pending' ORDER BY id").fetchall()
        can_work = pending and uploads_today(db) < MAX_UPLOADS_PER_DAY

        try:
            updates = tg("getUpdates", offset=offset, timeout=0 if can_work else 50)
        except Exception:
            time.sleep(5)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != CHAT_ID:
                continue  # trust boundary: only the owner's chat
            urls = re.findall(r"https?://\S+", msg.get("text") or "")
            for url in urls:
                db.execute("INSERT INTO jobs(url) VALUES(?)", (url,))
            db.commit()
            if urls:
                say("queued %d video(s)" % len(urls))
            elif msg.get("text"):
                say("send me a video link")

        if can_work:
            job_id, url = pending[0]
            try:
                process_job(db, job_id, url)
            except Exception:
                db.execute("UPDATE jobs SET status='failed', error=? WHERE id=?",
                           (traceback.format_exc()[-1500:], job_id))
                db.commit()
                say("job %d failed (%s):\n%s" % (job_id, url, traceback.format_exc()[-500:]))

        if time.time() - last_stats > 3600:
            last_stats = time.time()
            try:
                stats.refresh(db)
            except Exception as e:
                print("stats refresh failed:", e)


if __name__ == "__main__":
    main()
