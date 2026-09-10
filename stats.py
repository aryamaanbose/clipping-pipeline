"""Pull YouTube stats into state.db, dump dashboard.json + dashboard.html.

Run manually (python stats.py) or bot.py calls refresh() hourly.
"""
import datetime
import json
import sqlite3
from pathlib import Path

import uploader

ROOT = Path(__file__).resolve().parent
RPM = 0.15  # ponytail: $/1000 Shorts views estimate; swap for real estimatedRevenue once in YPP


def refresh(db):
    ids = [r[0] for r in db.execute("SELECT video_id FROM uploads")]
    now = datetime.datetime.now().isoformat(timespec="seconds")
    today = datetime.date.today().isoformat()

    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        resp = uploader.service().videos().list(
            part="statistics", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            s = item["statistics"]
            db.execute(
                "UPDATE uploads SET views=?, likes=?, est_revenue=?, fetched_at=? WHERE video_id=?",
                (int(s.get("viewCount", 0)), int(s.get("likeCount", 0)),
                 int(s.get("viewCount", 0)) * RPM / 1000, now, item["id"]))

    analytics = uploader.service("youtubeAnalytics", "v2")
    if ids:
        resp = analytics.reports().query(
            ids="channel==MINE", startDate="2020-01-01", endDate=today,
            metrics="subscribersGained", dimensions="video",
            filters="video==" + ",".join(ids[:200])).execute()
        for vid, subs in resp.get("rows", []):
            db.execute("UPDATE uploads SET subs_gained=? WHERE video_id=?", (subs, vid))

    ch = analytics.reports().query(
        ids="channel==MINE", startDate="2020-01-01", endDate=today,
        metrics="views,estimatedMinutesWatched,subscribersGained").execute()
    row = (ch.get("rows") or [[0, 0, 0]])[0]
    db.commit()

    clips = [dict(zip(("video_id", "title", "source_url", "published_at", "views",
                       "likes", "subs_gained", "est_revenue"), r))
             for r in db.execute(
                 "SELECT video_id,title,source_url,published_at,views,likes,subs_gained,"
                 "est_revenue FROM uploads ORDER BY published_at DESC")]
    data = {
        "generated": now,
        "channel": {"views": row[0], "watch_minutes": row[1], "subs_gained": row[2],
                    "est_revenue": round(row[0] * RPM / 1000, 2), "clips_posted": len(clips)},
        "clips": clips,
    }
    (ROOT / "dashboard.json").write_text(json.dumps(data, indent=1))
    (ROOT / "dashboard.html").write_text(render_html(data))
    return data


def render_html(d):
    tiles = "".join(
        '<div class="tile"><div class="num">%s</div><div class="lbl">%s</div></div>' % (v, k)
        for k, v in [("total views", "{:,}".format(d["channel"]["views"])),
                     ("subs gained", "{:,}".format(d["channel"]["subs_gained"])),
                     ("est. revenue*", "$%.2f" % d["channel"]["est_revenue"]),
                     ("watch minutes", "{:,}".format(d["channel"]["watch_minutes"])),
                     ("clips posted", d["channel"]["clips_posted"])])
    rows = "".join(
        '<tr><td><a href="https://youtube.com/shorts/%s">%s</a></td>'
        '<td>%s</td><td>%s</td><td>%s</td><td>$%.2f</td><td>%s</td></tr>'
        % (c["video_id"], c["title"], "{:,}".format(c["views"]), c["likes"],
           c["subs_gained"], c["est_revenue"], (c["published_at"] or "")[:10])
        for c in d["clips"])
    return """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Clips Dashboard</title>
<style>
body{font-family:system-ui;margin:0;padding:24px 16px;background:#111;color:#eee}
h1{font-size:20px} .sub{color:#888;font-size:12px}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}
.tile{background:#1c1c1e;border-radius:10px;padding:14px 20px;min-width:120px}
.num{font-size:26px;font-weight:700}.lbl{color:#999;font-size:12px;margin-top:4px}
table{border-collapse:collapse;width:100%%;font-size:14px}
td,th{padding:8px 10px;border-bottom:1px solid #2a2a2c;text-align:left}
a{color:#6cf;text-decoration:none}
</style>
<h1>Clips Dashboard</h1><div class="sub">updated %s &middot; *revenue estimated at $%.2f RPM until channel is monetized</div>
<div class="tiles">%s</div>
<table><tr><th>clip</th><th>views</th><th>likes</th><th>subs</th><th>est. $</th><th>posted</th></tr>%s</table>
""" % (d["generated"], RPM, tiles, rows)


if __name__ == "__main__":
    db = sqlite3.connect(ROOT / "state.db")
    d = refresh(db)
    print("dashboard.html written -", d["channel"])
