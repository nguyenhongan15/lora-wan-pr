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

import smtplib
from datetime import datetime
from email.message import EmailMessage

import structlog

from ..application.identity import Mailer, MailerError

logger = structlog.get_logger("lora_coverage_api.mailer")


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
        msg.add_alternative(
            _HTML_BODY.format(url=reset_url, minutes=expires_in_minutes),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email reset password")

    def send_email_verification(
        self,
        to_email: str,
        *,
        verify_url: str,
        expires_in_minutes: int,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Xác thực email LoRa Coverage"
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        msg.set_content(_VERIFY_PLAIN_BODY.format(url=verify_url, minutes=expires_in_minutes))
        msg.add_alternative(
            _VERIFY_HTML_BODY.format(url=verify_url, minutes=expires_in_minutes),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email xác thực")

    def send_contribution_approved(
        self,
        to_email: str,
        *,
        point_timestamp: datetime,
        latitude: float,
        longitude: float,
        gateway_code: str | None,
        rssi_dbm: float,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Cảm ơn bạn đã đóng góp dữ liệu phủ sóng"
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        ts_local = point_timestamp.strftime("%Y-%m-%d %H:%M UTC")
        gw_label = gateway_code or "(không xác định)"
        msg.set_content(
            _THANKS_PLAIN_BODY.format(
                ts=ts_local,
                lat=latitude,
                lon=longitude,
                gw=gw_label,
                rssi=rssi_dbm,
            )
        )
        msg.add_alternative(
            _THANKS_HTML_BODY.format(
                ts=ts_local,
                lat=latitude,
                lon=longitude,
                gw=gw_label,
                rssi=rssi_dbm,
            ),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email cảm ơn")

    def send_contribution_batch_approved(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Cảm ơn bạn đã đóng góp dữ liệu phủ sóng"
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        upload_ts = uploaded_at.strftime("%Y-%m-%d %H:%M UTC")
        range_label = _format_time_range(earliest_timestamp, latest_timestamp)
        msg.set_content(
            _THANKS_BATCH_PLAIN_BODY.format(
                upload_ts=upload_ts,
                count=approved_count,
                range=range_label,
            )
        )
        msg.add_alternative(
            _THANKS_BATCH_HTML_BODY.format(
                upload_ts=upload_ts,
                count=approved_count,
                range=range_label,
            ),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email cảm ơn")

    def send_contribution_batch_rejected(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        rejected_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
        note: str | None,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Đóng góp dữ liệu phủ sóng không được duyệt"
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        upload_ts = uploaded_at.strftime("%Y-%m-%d %H:%M UTC")
        range_label = _format_time_range(earliest_timestamp, latest_timestamp)
        note_clean = (note or "").strip()
        note_plain = f"\n  - Lý do: {note_clean}\n" if note_clean else ""
        note_html = (
            f'<tr><td style="padding: 4px 12px 4px 0; color: #666;">Lý do:</td>'
            f'<td style="padding: 4px 0;"><strong>{note_clean}</strong></td></tr>'
            if note_clean
            else ""
        )
        msg.set_content(
            _REJECT_BATCH_PLAIN_BODY.format(
                upload_ts=upload_ts,
                count=rejected_count,
                range=range_label,
                note_block=note_plain,
            )
        )
        msg.add_alternative(
            _REJECT_BATCH_HTML_BODY.format(
                upload_ts=upload_ts,
                count=rejected_count,
                range=range_label,
                note_row=note_html,
            ),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email thông báo từ chối")

    def send_admin_self_contribution_published(
        self,
        to_email: str,
        *,
        contributor_email: str,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = (
            f"[LoRa Coverage] Admin {contributor_email} vừa đóng góp "
            f"{approved_count} điểm — đã tự động duyệt"
        )
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        upload_ts = uploaded_at.strftime("%Y-%m-%d %H:%M UTC")
        range_label = _format_time_range(earliest_timestamp, latest_timestamp)
        msg.set_content(
            _ADMIN_SELF_PUBLISH_PLAIN_BODY.format(
                contributor=contributor_email,
                upload_ts=upload_ts,
                count=approved_count,
                range=range_label,
            )
        )
        msg.add_alternative(
            _ADMIN_SELF_PUBLISH_HTML_BODY.format(
                contributor=contributor_email,
                upload_ts=upload_ts,
                count=approved_count,
                range=range_label,
            ),
            subtype="html",
        )
        self._send(msg, error_message="Không gửi được email thông báo auto-publish")

    def _send(self, msg: EmailMessage, *, error_message: str) -> None:
        try:
            with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as server:
                if self._use_starttls:
                    server.starttls()
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error(
                "smtp_send_failed",
                host=self._host,
                port=self._port,
                error=str(exc),
            )
            raise MailerError(error_message) from exc


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
            "noop_mailer_password_reset",
            to_email=to_email,
            ttl_minutes=expires_in_minutes,
            reset_url=reset_url,
        )

    def send_email_verification(
        self,
        to_email: str,
        *,
        verify_url: str,
        expires_in_minutes: int,
    ) -> None:
        logger.warning(
            "noop_mailer_email_verification",
            to_email=to_email,
            ttl_minutes=expires_in_minutes,
            verify_url=verify_url,
        )

    def send_contribution_approved(
        self,
        to_email: str,
        *,
        point_timestamp: datetime,
        latitude: float,
        longitude: float,
        gateway_code: str | None,
        rssi_dbm: float,
    ) -> None:
        logger.warning(
            "noop_mailer_contribution_approved",
            to_email=to_email,
            point_timestamp=point_timestamp.isoformat(),
            latitude=latitude,
            longitude=longitude,
            gateway_code=gateway_code,
            rssi_dbm=rssi_dbm,
        )

    def send_contribution_batch_approved(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None:
        logger.warning(
            "noop_mailer_contribution_batch_approved",
            to_email=to_email,
            uploaded_at=uploaded_at.isoformat(),
            approved_count=approved_count,
            earliest=earliest_timestamp.isoformat(),
            latest=latest_timestamp.isoformat(),
        )

    def send_contribution_batch_rejected(
        self,
        to_email: str,
        *,
        uploaded_at: datetime,
        rejected_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
        note: str | None,
    ) -> None:
        logger.warning(
            "noop_mailer_contribution_batch_rejected",
            to_email=to_email,
            uploaded_at=uploaded_at.isoformat(),
            rejected_count=rejected_count,
            earliest=earliest_timestamp.isoformat(),
            latest=latest_timestamp.isoformat(),
            note=note,
        )

    def send_admin_self_contribution_published(
        self,
        to_email: str,
        *,
        contributor_email: str,
        uploaded_at: datetime,
        approved_count: int,
        earliest_timestamp: datetime,
        latest_timestamp: datetime,
    ) -> None:
        logger.warning(
            "noop_mailer_admin_self_contribution_published",
            to_email=to_email,
            contributor_email=contributor_email,
            uploaded_at=uploaded_at.isoformat(),
            approved_count=approved_count,
            earliest=earliest_timestamp.isoformat(),
            latest=latest_timestamp.isoformat(),
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


_VERIFY_PLAIN_BODY = """Xác thực email LoRa Coverage.

Bạn cần xác thực email để có thể đóng góp dữ liệu đo cho dataset cộng đồng.

Mở liên kết dưới đây để hoàn tất xác thực (hết hạn sau {minutes} phút):

{url}

Nếu bạn không yêu cầu, có thể bỏ qua email này.
"""


_VERIFY_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #1a73e8;">Xác thực email LoRa Coverage</h2>
  <p>Bạn cần xác thực email để có thể đóng góp dữ liệu đo cho dataset cộng đồng.</p>
  <p>Nhấn nút dưới đây để hoàn tất (link hết hạn sau {minutes} phút):</p>
  <p style="margin: 24px 0;">
    <a href="{url}" style="background: #1a73e8; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block;">Xác thực email</a>
  </p>
  <p style="color: #666; font-size: 14px;">Hoặc copy URL: <br><code style="word-break: break-all;">{url}</code></p>
  <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 24px 0;">
  <p style="color: #666; font-size: 13px;">Nếu bạn không yêu cầu, có thể bỏ qua email này.</p>
</body>
</html>
"""


_THANKS_PLAIN_BODY = """Xin cảm ơn bạn đã đóng góp dữ liệu đo cho LoRa Coverage Đà Nẵng!

Điểm đóng góp của bạn vừa được admin xét duyệt và đưa vào dataset cộng đồng:

  - Thời điểm đo:    {ts}
  - Vị trí:          ({lat:.4f}, {lon:.4f})
  - Gateway phục vụ: {gw}
  - RSSI:            {rssi} dBm

Dữ liệu này sẽ được dùng để huấn luyện mô hình phủ sóng cộng đồng,
giúp các user khác tra cứu chính xác hơn. Cảm ơn bạn rất nhiều!
"""


_THANKS_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #1a73e8;">Cảm ơn bạn đã đóng góp!</h2>
  <p>Điểm đóng góp của bạn vừa được admin xét duyệt và đưa vào dataset cộng đồng LoRa Coverage Đà Nẵng:</p>
  <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Thời điểm đo:</td><td style="padding: 4px 0;"><strong>{ts}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Vị trí:</td><td style="padding: 4px 0;"><strong>({lat:.4f}, {lon:.4f})</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Gateway phục vụ:</td><td style="padding: 4px 0;"><strong>{gw}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">RSSI:</td><td style="padding: 4px 0;"><strong>{rssi} dBm</strong></td></tr>
  </table>
  <p style="color: #666; font-size: 14px;">Dữ liệu này sẽ được dùng để huấn luyện mô hình phủ sóng cộng đồng, giúp các user khác tra cứu chính xác hơn. Cảm ơn bạn rất nhiều!</p>
</body>
</html>
"""


_THANKS_BATCH_PLAIN_BODY = """Xin cảm ơn bạn đã đóng góp dữ liệu đo cho LoRa Coverage Đà Nẵng!

Admin vừa xét duyệt file CSV bạn upload và đưa {count} điểm đo vào dataset
cộng đồng:

  - Upload lúc:   {upload_ts}
  - Số điểm duyệt: {count}
  - Khoảng đo:    {range}

Dữ liệu này sẽ được dùng để huấn luyện mô hình phủ sóng cộng đồng,
giúp các user khác tra cứu chính xác hơn. Cảm ơn bạn rất nhiều!
"""


_THANKS_BATCH_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #1a73e8;">Cảm ơn bạn đã đóng góp!</h2>
  <p>Admin vừa xét duyệt file CSV bạn upload và đưa <strong>{count}</strong> điểm đo vào dataset cộng đồng LoRa Coverage Đà Nẵng:</p>
  <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Upload lúc:</td><td style="padding: 4px 0;"><strong>{upload_ts}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Số điểm duyệt:</td><td style="padding: 4px 0;"><strong>{count}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Khoảng đo:</td><td style="padding: 4px 0;"><strong>{range}</strong></td></tr>
  </table>
  <p style="color: #666; font-size: 14px;">Dữ liệu này sẽ được dùng để huấn luyện mô hình phủ sóng cộng đồng, giúp các user khác tra cứu chính xác hơn. Cảm ơn bạn rất nhiều!</p>
</body>
</html>
"""


_REJECT_BATCH_PLAIN_BODY = """Cảm ơn bạn đã đóng góp dữ liệu đo cho LoRa Coverage Đà Nẵng.

Rất tiếc, chúng tôi vừa xét duyệt file CSV bạn upload và quyết định KHÔNG đưa
{count} điểm đo vào dataset cộng đồng:

  - Upload lúc:    {upload_ts}
  - Số điểm bị từ chối: {count}
  - Khoảng đo:     {range}{note_block}
Các điểm đo bị từ chối sẽ không được dùng để huấn luyện mô hình phủ sóng.
Bạn có thể upload lại với dữ liệu mới — chúng tôi luôn hoan nghênh đóng góp.
"""


_REJECT_BATCH_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #b91c1c;">Đóng góp không được duyệt</h2>
  <p>Cảm ơn bạn đã đóng góp dữ liệu đo cho LoRa Coverage Đà Nẵng.</p>
  <p>Rất tiếc, admin vừa xét duyệt file CSV bạn upload và quyết định <strong>không đưa {count} điểm đo</strong> vào dataset cộng đồng:</p>
  <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Upload lúc:</td><td style="padding: 4px 0;"><strong>{upload_ts}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Số điểm bị từ chối:</td><td style="padding: 4px 0;"><strong>{count}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Khoảng đo:</td><td style="padding: 4px 0;"><strong>{range}</strong></td></tr>
    {note_row}
  </table>
  <p style="color: #666; font-size: 14px;">Các điểm đo bị từ chối sẽ không được dùng để huấn luyện mô hình phủ sóng. Bạn có thể upload lại với dữ liệu mới — chúng tôi luôn hoan nghênh đóng góp.</p>
</body>
</html>
"""


_ADMIN_SELF_PUBLISH_PLAIN_BODY = """Thông báo từ LoRa Coverage Đà Nẵng.

Tài khoản admin {contributor} vừa đóng góp dữ liệu đo cho dataset cộng đồng.
Vì là tài khoản admin (mặc định tin cậy), {count} điểm đã được TỰ ĐỘNG DUYỆT
và đưa thẳng vào bản đồ chung — KHÔNG đi qua hàng đợi review.

  - Người đóng góp: {contributor}
  - Upload lúc:      {upload_ts}
  - Số điểm:         {count}
  - Khoảng đo:       {range}

Email này được gửi tới (1) admin đóng góp và (2) super admin để lưu vết.
Nếu phát hiện dữ liệu sai, có thể xoá thủ công ở mục "Dữ liệu đã duyệt"
trong trang Admin.
"""


_ADMIN_SELF_PUBLISH_HTML_BODY = """\
<!DOCTYPE html>
<html lang="vi">
<body style="font-family: -apple-system, system-ui, sans-serif; max-width: 560px; margin: 0 auto; padding: 24px; color: #1a1a1a;">
  <h2 style="color: #1a73e8;">Đóng góp dữ liệu — đã tự động duyệt</h2>
  <p>Tài khoản admin <strong>{contributor}</strong> vừa đóng góp dữ liệu đo cho dataset cộng đồng LoRa Coverage Đà Nẵng.</p>
  <p>Vì là tài khoản admin (mặc định tin cậy), <strong>{count}</strong> điểm đã được <strong>tự động duyệt</strong> và đưa thẳng vào bản đồ chung — không đi qua hàng đợi review.</p>
  <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Người đóng góp:</td><td style="padding: 4px 0;"><strong>{contributor}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Upload lúc:</td><td style="padding: 4px 0;"><strong>{upload_ts}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Số điểm:</td><td style="padding: 4px 0;"><strong>{count}</strong></td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Khoảng đo:</td><td style="padding: 4px 0;"><strong>{range}</strong></td></tr>
  </table>
  <p style="color: #666; font-size: 13px;">Email này được gửi tới (1) admin đóng góp và (2) super admin để lưu vết. Nếu phát hiện dữ liệu sai, có thể xoá thủ công ở mục "Dữ liệu đã duyệt" trong trang Admin.</p>
</body>
</html>
"""


def _format_time_range(earliest: datetime, latest: datetime) -> str:
    """Format khoảng thời gian đo: nếu cùng ngày chỉ show ngày, khác ngày show range."""
    e_fmt = earliest.strftime("%Y-%m-%d %H:%M")
    if earliest.date() == latest.date():
        l_fmt = latest.strftime("%H:%M UTC")
        return f"{e_fmt} → {l_fmt}"
    l_fmt = latest.strftime("%Y-%m-%d %H:%M UTC")
    return f"{e_fmt} → {l_fmt}"
