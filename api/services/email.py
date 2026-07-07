import smtplib
from email.message import EmailMessage

try:
    import api.config as config_module
except ImportError:  # pragma: no cover
    import config as config_module


class EmailService:
    def __init__(self) -> None:
        self.host = getattr(config_module, "EMAIL_HOST", None)
        self.port = int(getattr(config_module, "EMAIL_PORT", 587) or 587)
        self.username = getattr(config_module, "EMAIL_USERNAME", None)
        self.password = getattr(config_module, "EMAIL_PASSWORD", None)
        self.from_address = getattr(config_module, "EMAIL_FROM", None) or self.username
        self.use_tls = str(getattr(config_module, "EMAIL_USE_TLS", "true")).lower() == "true"

    def send(self, to_address: str, subject: str, body: str) -> bool:
        if not self.host:
            print(f"[email] to={to_address} subject={subject} body={body}")
            return True
        try:
            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = self.from_address
            message["To"] = to_address
            message.set_content(body)
            with smtplib.SMTP(self.host, self.port) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(message)
            return True
        except Exception as exc:  # pragma: no cover
            print(f"[email] failed: {exc}")
            return False


email_service = EmailService()
