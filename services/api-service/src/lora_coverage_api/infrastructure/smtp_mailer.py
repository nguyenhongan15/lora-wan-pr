"""SMTP mailer — implementation cho `Mailer` port.

stdlib `smtplib` direct (không dùng yagmail/django.core.mail — overkill cho
1 template). Hỗ trợ STARTTLS (port 587) hoặc plain (dev SMTP server vd
mailpit/mailcatcher port 1025).

Auth: gửi LOGIN nếu cả `username` và `password` được set; không thì gửi
unauthenticated (mailpit không auth).

KHÔNG retry trong impl — nếu SMTP fail, raise MailerError ngay. User request
reset link lại nếu cần (mỗi request invalidate token cũ → safe).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..application.identity import Mailer, MailerError

logger = logging.getLogger(__name__)


class SmtpMailer(Mailer):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_email: str,
        from_name: str,
        use_starttls: bool,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._from_name = from_name
        self._use_starttls = use_starttls
        self._timeout = timeout_seconds

    def send_password_reset(
        self,
        to_email: str,
        *,
        reset_url: str,
        expires_in_minutes: int,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Đặt lại mật khẩu LoRa Coverage"
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        msg.set_content(_PLAIN_BODY.format(url=reset_url, minutes=expires_in_minutes))
        # HTML alternative — client modern hiển thị HTML, fallback plain.
        msg.add_alternative(
            _HTML_BODY.format(url=reset_url, minutes=expires_in_minutes),
            subtype="html",
        )

        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                if self._use_starttls:
                    server.starttls()
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            # OSError bắt timeout + hostname không resolve. KHÔNG log
            # `to_email` (PII) — chỉ log host:port để debug.
            logger.error("SMTP send failed: host=%s:%s err=%s", self._host, self._port, exc)
            raise MailerError("Không gửi được email reset password") from exc


class NoOpMailer(Mailer):
    """Dev mailer — log reset URL ra console, không gửi mail thật.

    Wire khi `SMTP_HOST` empty (dev environment chưa setup SMTP server).
    Log ra WARNING để dev dễ thấy trong terminal `docker compose logs`.
    """

    def send_password_reset(
        self,
        to_email: str,
        *,
        reset_url: str,
        expires_in_minutes: int,
    ) -> None:
        logger.warning(
            "[NoOpMailer] Password reset for %s (TTL %d min): %s",
            to_email,
            expires_in_minutes,
            reset_url,
        )


_PLAIN_BODY = """Bạn vừa yêu cầu đặt lại mật khẩu cho tài khoản LoRa Coverage.

Mở liên kết dưới đây (hết hạn sau {minutes} phút):

{url}

Nếu bạn không yêu cầu, có thể bỏ qua email này — mật khẩu hiện tại vẫn dùng được.
"""

_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #1a73e8;">Đặt lại mật khẩu LoRa Coverage</h2>
  <p>Bạn vừa yêu cầu đặt lại mật khẩu. Nhấn nút dưới đây để tiếp tục (link hết hạn sau {minutes} phút):</p>
  <p style="margin: 24px 0;">
    <a href="{url}" style="background: #1a73e8; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Đặt lại mật khẩu</a>
  </p>
  <p style="color: #666; font-size: 14px;">Hoặc copy URL: <br><code style="word-break: break-all;">{url}</code></p>
  <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 24px 0;">
  <p style="color: #666; font-size: 13px;">Nếu bạn không yêu cầu, có thể bỏ qua email này — mật khẩu hiện tại vẫn dùng được.</p>
</body>
</html>
"""
