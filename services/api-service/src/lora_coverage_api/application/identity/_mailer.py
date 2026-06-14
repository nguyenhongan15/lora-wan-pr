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

from datetime import datetime
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

    def send_email_verification(
        self,
        to_email: str,
        *,
        verify_url: str,
        expires_in_minutes: int,
    ) -> None: ...

    def send_contribution_approved(
        self,
        to_email: str,
        *,
        point_timestamp: datetime,
        latitude: float,
        longitude: float,
        gateway_code: str | None,
        rssi_dbm: float,
    ) -> None: ...

    def send_contribution_batch_approved(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None: ...

    def send_contribution_batch_rejected(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        rejected_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
        note: str | None,
    ) -> None: ...

    def send_admin_self_contribution_published(
        self,
        to_email: str,
        *,
        contributor_email: str,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None: ...


class MailerError(Exception):
    """Lỗi gửi mail — SMTP timeout, auth fail, hostname không resolve.

    Service raise MailerError → edge handler trả 503 generic. KHÔNG leak
    SMTP details vào response (security: tránh probe).
    """
