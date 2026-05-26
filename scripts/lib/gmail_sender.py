"""Gmail dispatcher: load OAuth, assemble multipart/mixed MIME, drafts.create or messages.send."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable, Literal

EmailMode = Literal["draft", "send"]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes


@dataclass(frozen=True)
class SendResult:
    mode: EmailMode
    id: str
    ok: bool


class GmailSender:
    def __init__(self, *, client_file: Path, token_file: Path) -> None:
        self._client_file = Path(client_file)
        self._token_file = Path(token_file)
        self.__service = None  # lazy

    @staticmethod
    def build_mime(
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: Iterable[Attachment],
    ) -> bytes:
        msg = MIMEMultipart("mixed")
        msg["To"] = to
        msg["Subject"] = subject

        msg.attach(MIMEText(html_body, "html", _charset="utf-8"))

        for att in attachments:
            part = MIMEApplication(att.content, _subtype="json")
            part.add_header("Content-Disposition", "attachment", filename=att.filename)
            msg.attach(part)

        return msg.as_bytes()

    # ---- live Gmail API path ----

    def _service(self):
        if self.__service is None:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            creds = None
            if self._token_file.exists():
                creds = Credentials.from_authorized_user_file(str(self._token_file), GMAIL_SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self._client_file), GMAIL_SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                self._token_file.write_text(creds.to_json(), encoding="utf-8")
            self.__service = build("gmail", "v1", credentials=creds)
        return self.__service

    def dispatch(
        self,
        *,
        mode: EmailMode,
        to: str,
        subject: str,
        html_body: str,
        attachments: Iterable[Attachment],
    ) -> SendResult:
        raw = self.build_mime(
            to=to, subject=subject, html_body=html_body, attachments=list(attachments)
        )
        encoded = base64.urlsafe_b64encode(raw).decode("ascii")
        service = self._service()

        if mode == "draft":
            response = (
                service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": encoded}})
                .execute()
            )
            return SendResult(mode="draft", id=response["id"], ok=True)

        response = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": encoded})
            .execute()
        )
        return SendResult(mode="send", id=response["id"], ok=True)

    def list_drafts(self) -> list[dict]:
        service = self._service()
        response = service.users().drafts().list(userId="me").execute()
        return response.get("drafts", [])

    def delete_draft(self, draft_id: str) -> None:
        service = self._service()
        service.users().drafts().delete(userId="me", id=draft_id).execute()
