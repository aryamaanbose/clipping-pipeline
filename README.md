# Clipping Pipeline

Personal-use tool, operated solely by its owner, for repurposing podcast/stream content into
short-form video. Send a video link to your Telegram bot from your phone; your laptop downloads
it, transcribes it (Whisper, local), has Claude pick the 3–5 most engaging moments, cuts them
into 9:16 captioned Shorts, uploads them to your own YouTube channel, and replies with the
links. `dashboard.html` shows views / subs / estimated revenue.

**This application uses YouTube API Services.** By using this application, the owner agrees to
be bound by the [YouTube Terms of Service](https://www.youtube.com/t/terms). See the
[Privacy Policy](PRIVACY_POLICY_URL_HERE) and [Terms of Service](TOS_URL_HERE) for how data is
handled.

## One-time setup

1. **Python env** (needs python3.12; already at `/opt/homebrew/bin/python3.12`). Everything —
   including yt-dlp and a static ffmpeg — installs via pip (brew no longer supports macOS 13):
   ```
   python3.12 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```
3. **Telegram**: message @BotFather → `/newbot` → copy the token. Send your new bot any
   message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy
   your `chat.id`. Put both in `.env` (copy `.env.example`).
4. **Anthropic**: console.anthropic.com → API key → `.env`. (~$0.02–0.05 per video on Haiku.)
5. **Google Cloud** (for YouTube upload + stats):
   - console.cloud.google.com → new project
   - Enable **YouTube Data API v3** and **YouTube Analytics API**
   - OAuth consent screen: External, publishing status **"In production"** (Testing mode
     expires tokens every 7 days and silently breaks the bot)
   - Credentials → OAuth client → **Desktop app** → download as `client_secret.json` here
   - `.venv/bin/python uploader.py auth` (browser opens; click through the "unverified app"
     warning once)
   - **Submit the [YouTube API compliance audit form](https://support.google.com/youtube/contact/yt_api_form)
     now.** Until it's approved, all API uploads are locked private (that's why
     `uploader.PRIVACY = "private"`). When approved, flip it to `"public"`.

## Run

```
caffeinate -i .venv/bin/python bot.py
```

Laptop must be **plugged in with the lid open** — `caffeinate` does not prevent lid-close
sleep. Links sent while the laptop sleeps aren't lost (Telegram holds them 24h), just late.

- Test the pipeline alone: `.venv/bin/python pipeline.py <url>` (prints picks, writes clips to `work/`)
- Test one upload: `.venv/bin/python uploader.py upload work/.../clip1.mp4 "Test"`
- Refresh dashboard now: `.venv/bin/python stats.py` then open `dashboard.html`
- Logic self-check (no deps): `python3 test_pipeline.py`

## Limits & knobs

- **6 uploads/day max** (YouTube quota: 10k units/day, 1600/upload). Extra clips are held and
  noted in the Telegram reply.
- Revenue is estimated at `views × $0.15/1000` (`stats.RPM`) until the channel is in the
  Partner Program.
- Clip picker model: `pipeline.CLAUDE_MODEL` (`claude-haiku-4-5`; try `claude-sonnet-5` if
  picks feel weak). Whisper model: `pipeline.WHISPER_MODEL` (`small`; use `base` if too slow).
- Clip only creators who welcome clipping — podcast clips commonly draw Content ID claims
  (survivable revenue-share); takedown strikes are the real risk. Burned captions + title card
  help against a "reused content" monetization denial but aren't a guarantee.
