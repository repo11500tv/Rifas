"""Transporte SMTP con destino IP validado y TLS obligatorio."""

import smtplib
import socket
import ssl

from platform_app.smtp_network import resolve_smtp_host


class SecureSMTPMixin:
    def _get_socket(self, host, port, timeout):
        if self.debuglevel > 0:
            self._print_debug('connect:', (host, port))

        return socket.create_connection(
            (self._validated_ip, port),
            timeout,
            self.source_address,
        )


class SecureSMTPSSL(SecureSMTPMixin, smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        raw_socket = super()._get_socket(host, port, timeout)

        try:
            return self.context.wrap_socket(
                raw_socket,
                server_hostname=host,
            )
        except Exception:
            raw_socket.close()
            raise

    def __init__(self, host, port=465, timeout=15):
        addresses = resolve_smtp_host(host)
        self._validated_ip = addresses[0]

        context = ssl.create_default_context()

        super().__init__(
            host=host,
            port=port,
            timeout=timeout,
            context=context,
        )


class SecureSMTPSTARTTLS(SecureSMTPMixin, smtplib.SMTP):
    def __init__(self, host, port=587, timeout=15):
        addresses = resolve_smtp_host(host)
        self._validated_ip = addresses[0]

        super().__init__(
            host=host,
            port=port,
            timeout=timeout,
        )

    def starttls_required(self):
        context = ssl.create_default_context()

        self.ehlo()

        if not self.has_extn("starttls"):
            raise smtplib.SMTPNotSupportedError(
                "El servidor no admite STARTTLS"
            )

        self.starttls(context=context)
        self.ehlo()

        return self


def open_secure_smtp(host, port, security):
    if security == "ssl" and port == 465:
        return SecureSMTPSSL(host, port)

    if security == "starttls" and port == 587:
        smtp = SecureSMTPSTARTTLS(host, port)

        try:
            smtp.starttls_required()
            return smtp
        except Exception:
            smtp.close()
            raise

    raise ValueError(
        "Configuración SMTP de seguridad no permitida"
    )
