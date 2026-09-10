"""Smallest check that fails if the clip validation / caption logic breaks.
Run: python3 test_pipeline.py  (no deps needed)
"""
import pipeline as p

# validate_clips: clamps long clips, drops short/overlapping/junk, sorts
clips = p.validate_clips([
    {"start_sec": 100, "end_sec": 300, "title": "too long, gets clamped", "hashtags": ["#shorts"]},
    {"start_sec": 10, "end_sec": 20, "title": "too short, dropped"},
    {"start_sec": 120, "end_sec": 160, "title": "overlaps first, dropped"},
    {"start_sec": 400, "end_sec": 440, "title": "fine", "hashtags": ["nohash", "#ok"]},
    {"start_sec": "bad", "end_sec": 500, "title": "junk, dropped"},
    {"start_sec": 600, "end_sec": 640, "title": "   "},
])
assert [c["title"] for c in clips] == ["too long, gets clamped", "fine"], clips
assert clips[0]["end_sec"] == 100 + p.MAX_LEN
assert clips[1]["hashtags"] == ["#ok"]

# ass timing format
assert p.ass_time(0) == "0:00:00.00"
assert p.ass_time(61.5) == "0:01:01.50"
assert p.ass_time(3599.99) == "0:59:59.99"

# make_ass: title card + word groups, clip-relative times, braces escaped
out = p.ROOT / "work"
out.mkdir(exist_ok=True)
f = out / "_test.ass"
words = [(10.0, 10.4, "hello"), (10.4, 10.9, "{world}"), (11.0, 11.5, "again"),
         (11.5, 11.6, "..."), (11.6, 12.0, "bye")]  # "..." = music, must be dropped
p.make_ass(words, 10.0, 12.0, "My {Title}", f)
text = f.read_text()
assert "Title,,0,0,0,,MY (TITLE)" in text
assert "HELLO (WORLD) AGAIN" in text          # grouped by 3, uppercased, escaped
assert "0:00:00.00,0:00:01.50,Cap" in text     # shifted by -start
assert "BYE" in text and "..." not in text
f.unlink()

print("all checks passed")
