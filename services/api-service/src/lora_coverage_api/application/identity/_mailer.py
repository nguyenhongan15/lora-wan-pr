"""Mailer port — abstract email sender cho password reset.

Application layer KHÔNG biết SMTP/sendgrid/SES — chỉ thấy interface
`send_password_reset(to_email, reset_url, expires_in_minutes)`. Implementation
cụ thể (SMTP, NoOp, mock) wire ở edge/deps.

Tách port khỏi impl để:
  * Test dùng NoOpMailer (capture, không gửi thật).
  * Dev environment dùng NoOpMailer + log reset_url → console (xem được link
    không cần SMTP server).
  * Production wire SmtpMailer thật qua deps.
"""

from __future__ import annotations

from typing import Protocol


class Mailer(Protocol):
    """Port: gửi email transactional.

    Implementation phải swallow lỗi mạng thành log + raise `MailerError` —
    KHÔNG raise SMTPException raw vì application không biết SMTP. Đồng thời
    KHÔNG return success/failure — caller treat send là fire-and-forget
    (response trả luôn 204 trước khi user check inbox; failure log audit).
    """

    def send_password_reset(
        self,
        to_email: str,
        *,
        reset_url: str,
        expires_in_minutes: int,
    ) -> None: ...


class MailerError(Exception):
    """Lỗi gửi mail — SMTP timeout, auth fail, hostname không resolve.

    Service raise MailerError → edge handler trả 503 generic. KHÔNG leak
    SMTP details vào response (security: tránh probe).
    """
