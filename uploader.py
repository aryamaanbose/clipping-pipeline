"""YouTube OAuth + upload.

One-time login:  python uploader.py auth
Manual test:     python uploader.py upload clip.mp4 "Some title"
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
# ponytail: locked to private until the YouTube API compliance audit passes, then flip to "public"
PRIVACY = "private"


def auth():
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(ROOT / "client_secret.json", SCOPES)
    creds = flow.run_local_server(port=0)
    (ROOT / "token.json").write_text(creds.to_json())
    print("token.json written")


def _creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    tok = ROOT / "token.json"
    if not tok.exists():
        raise SystemExit("no token.json - run: python uploader.py auth")
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tok.write_text(creds.to_json())
    return creds


def service(name="youtube", version="v3"):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds())


def upload(path, title, description, hashtags):
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {
            "title": title[:100],
            "description": "%s\n\n%s" % (description, " ".join(hashtags)),
            "tags": [h.lstrip("#") for h in hashtags],
            "categoryId": "24",  # Entertainment
        },
        "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False},
    }
    req = service().videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), resumable=True))
    return req.execute()["id"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["auth"]:
        auth()
    elif sys.argv[1:2] == ["upload"] and len(sys.argv) >= 3:
        title = sys.argv[3] if len(sys.argv) > 3 else Path(sys.argv[2]).stem
        print("https://youtube.com/shorts/" + upload(sys.argv[2], title, "test upload", ["#shorts"]))
    else:
        sys.exit("usage: python uploader.py auth | upload <file> [title]")
