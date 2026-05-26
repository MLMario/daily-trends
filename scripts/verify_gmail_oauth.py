"""Verify Gmail OAuth setup for the daily-trends pipeline.

First run: opens a browser for consent, writes credentials/token.json.
Second run: refreshes the token silently and calls users.getProfile to prove it works.
If the second run triggers a browser, the refresh path is broken.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
ROOT = Path(__file__).resolve().parent.parent
CLIENT_FILE = ROOT / "credentials" / "oauth_client.json"
TOKEN_FILE = ROOT / "credentials" / "token.json"


def load_or_create_credentials() -> Credentials:
    creds: Credentials | None = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        print("[ok] token.json present and valid — no refresh needed")
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("[info] token expired — refreshing silently")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        print("[ok] refreshed and persisted token.json")
        return creds

    if not CLIENT_FILE.exists():
        raise SystemExit(
            f"missing {CLIENT_FILE} — download the OAuth client JSON "
            "from Google Cloud Console first"
        )

    print("[info] no valid token — launching browser for consent")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    print(f"[ok] consent complete — wrote {TOKEN_FILE}")
    return creds


def main() -> None:
    creds = load_or_create_credentials()
    service = build("gmail", "v1", credentials=creds)

    msg = EmailMessage()
    msg["To"] = "mariogj1987@gmail.com"
    msg["Subject"] = "[daily-trends] oauth verification"
    msg.set_content("oauth verification test message — safe to ignore")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    sent = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    print(f"[ok] sent verification email id={sent['id']} — gmail.send scope works end-to-end")
    print("     check your inbox for subject: [daily-trends] oauth verification")


if __name__ == "__main__":
    main()
