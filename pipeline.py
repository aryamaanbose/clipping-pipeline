"""Download -> transcribe -> Claude picks moments -> cut captioned 9:16 clips.

Standalone test: python pipeline.py <video url>
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def find_ffmpeg():
    # ponytail: brew dropped macOS 13, so ffmpeg comes from the static-ffmpeg pip package
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    from static_ffmpeg import run
    return run.get_or_fetch_platform_executables_else_raise()[0]


FFMPEG = find_ffmpeg()
YTDLP = [sys.executable, "-m", "yt_dlp"]
WORK = ROOT / "work"
CLAUDE_MODEL = "claude-haiku-4-5"  # ponytail: swap to claude-sonnet-5 if picks are weak
WHISPER_MODEL = "small"            # ponytail: drop to "base" if transcription is too slow
MIN_LEN, MAX_LEN = 25, 65
MAX_CLIPS = 5


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()


def download(url, workdir):
    """Fetch video as workdir/source.mp4, return its title."""
    workdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        YTDLP + ["--no-playlist", "--ffmpeg-location", str(Path(FFMPEG).parent),
         "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
         "--remux-video", "mp4", "-o", "source.%(ext)s",
         "--no-simulate", "--print-to-file", "title", "title.txt",
         url],
        cwd=workdir, check=True)
    return (workdir / "title.txt").read_text().strip()


def transcribe(workdir):
    """Return (timestamped transcript text, [(start, end, word), ...])."""
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_MODEL, compute_type="int8")
    segments, _ = model.transcribe(str(workdir / "source.mp4"), word_timestamps=True)
    lines, words = [], []
    for seg in segments:
        lines.append("[%s-%s] %s" % (mmss(seg.start), mmss(seg.end), seg.text.strip()))
        words.extend((w.start, w.end, w.word.strip()) for w in (seg.words or []))
    return "\n".join(lines), words


def mmss(t):
    return "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)


PROMPT = """Below is a timestamped transcript of "{title}". Pick the 3-5 most engaging, \
self-contained moments for viral vertical short clips. Each must be 30-60 seconds, work with \
zero context, have a strong hook in its first 3 seconds and a payoff, and start/end on \
sentence boundaries (never mid-sentence).

Return ONLY this JSON, nothing else:
{{"clips": [{{"start_sec": <number>, "end_sec": <number>, \
"title": "<=80 char curiosity hook, no lies", \
"description": "1-2 sentences, end with: Clip from {title}", \
"hashtags": ["#shorts", ... 5-8 total, relevant + trending-style]}}]}}

TRANSCRIPT:
{transcript}"""


def pick_clips(transcript, source_title):
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model=CLAUDE_MODEL, max_tokens=2000,
        messages=[{"role": "user",
                   "content": PROMPT.format(title=source_title, transcript=transcript)}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    data = json.loads(text[text.index("{"):text.rindex("}") + 1])
    return validate_clips(data["clips"])


def validate_clips(clips):
    """Never trust LLM arithmetic: clamp lengths, drop overlaps/junk."""
    good, parsed = [], []
    for c in clips:
        try:
            parsed.append((float(c["start_sec"]), float(c["end_sec"]), c))
        except (KeyError, TypeError, ValueError):
            continue
    for start, end, c in sorted(parsed, key=lambda x: x[0]):
        end = min(end, start + MAX_LEN)
        if end - start < MIN_LEN or not str(c.get("title", "")).strip():
            continue
        if good and start < good[-1]["end_sec"]:
            continue
        c["start_sec"], c["end_sec"] = start, end
        c["hashtags"] = [h for h in c.get("hashtags", []) if h.startswith("#")] or ["#shorts"]
        good.append(c)
    return good[:MAX_CLIPS]


ASS_HEADER = """[Script Info]
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial Black,88,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,340,1
Style: Title,Arial Black,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,6,0,8,60,60,140,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(t):
    t = max(t, 0)
    return "%d:%02d:%02d.%02d" % (t // 3600, t % 3600 // 60, t % 60, round(t * 100) % 100)


def ass_escape(text):
    return str(text).replace("{", "(").replace("}", ")").replace("\n", " ")


def make_ass(words, start, end, title, path):
    """Word-group pop-in captions + 2s title card, times shifted to clip-relative."""
    clip_words = [(ws - start, we - start, w) for ws, we, w in words
                  if w and w.strip(".,!?-") and ws >= start and we <= end]
    lines = ["Dialogue: 0,%s,%s,Title,,0,0,0,,%s"
             % (ass_time(0), ass_time(2), ass_escape(title).upper())]
    for i in range(0, len(clip_words), 3):
        group = clip_words[i:i + 3]
        text = ass_escape(" ".join(w for _, _, w in group)).upper()
        lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,{\\fad(50,50)}%s"
                     % (ass_time(group[0][0]), ass_time(group[-1][1]), text))
    path.write_text(ASS_HEADER + "\n".join(lines) + "\n")


def cut(workdir, idx, clip, words):
    """Cut one 9:16 captioned clip, return its path."""
    ass = workdir / ("clip%d.ass" % idx)
    make_ass(words, clip["start_sec"], clip["end_sec"], clip["title"], ass)
    out = workdir / ("clip%d.mp4" % idx)
    # ponytail: center-crop; switch to blur-pad if multi-person frames crop badly
    subprocess.run(
        [FFMPEG, "-y", "-ss", str(clip["start_sec"]), "-to", str(clip["end_sec"]),
         "-i", "source.mp4",
         "-vf", "crop=ih*9/16:ih,scale=1080:1920,ass=%s" % ass.name,
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", out.name],
        cwd=workdir, check=True, capture_output=True)
    return out


def run(url, workdir):
    """Full pipeline for one source video. Returns list of ready-to-upload clip dicts."""
    print("downloading", url, flush=True)
    title = download(url, workdir)
    print("transcribing", flush=True)
    transcript, words = transcribe(workdir)
    print("picking moments", flush=True)
    clips = pick_clips(transcript, title)
    results = []
    for i, c in enumerate(clips, 1):
        print("cutting clip %d/%d" % (i, len(clips)), flush=True)
        c["file"] = cut(workdir, i, c, words)
        c["source_title"] = title
        results.append(c)
    return results


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python pipeline.py <video url>")
    import time
    out = run(sys.argv[1], WORK / ("manual-%d" % time.time()))
    for c in out:
        print("\n%s\n  %s | %.0fs-%.0fs\n  %s\n  %s"
              % (c["file"], c["title"], c["start_sec"], c["end_sec"],
                 c["description"], " ".join(c["hashtags"])))
