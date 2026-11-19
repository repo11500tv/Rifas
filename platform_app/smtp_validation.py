"""Validación de configuración SMTP por entidad."""

import ipaddress
import re
from email.utils import parseaddr


def valid_email(value):
    if not isinstance(value, str):
        return False

    if not value or len(value) > 254:
        return False

    if value != value.strip():
        return False

    if any(ord(c) < 33 or ord(c) == 127 for c in value):
        return False

    name, address = parseaddr(value)

    if name or address != value:
        return False

    if value.count("@") != 1:
        return False

    local, domain = value.rsplit("@", 1)

    if not local or len(local) > 64:
        return False

    return valid_hostname(domain)


def valid_hostname(value):
    if not isinstance(value, str):
        return False

    if not value or len(value) > 253:
        return False

    if value != value.strip():
        return False

    if value.lower() == "localhost":
        return False

    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        pass

    labels = value.split(".")

    if len(labels) < 2:
        return False

    pattern = re.compile(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    )

    return all(pattern.fullmatch(label) for label in labels)


def validate_smtp(host, port, security, username, sender):
    errors = []

    if not valid_hostname(host):
        errors.append("Servidor SMTP no válido")

    if security not in ("ssl", "starttls"):
        errors.append("Tipo de seguridad no válido")

    try:
        port_number = int(port)
    except (ValueError, TypeError):
        port_number = 0

    if security == "ssl" and port_number != 465:
        errors.append("SSL/TLS requiere el puerto 465")

    if security == "starttls" and port_number != 587:
        errors.append("STARTTLS requiere el puerto 587")

    if not isinstance(username, str) or not username.strip():
        errors.append("El usuario SMTP es obligatorio")
    elif len(username) > 254 or any(
        ord(c) < 32 or ord(c) == 127 for c in username
    ):
        errors.append("Usuario SMTP no válido")

    if not valid_email(sender):
        errors.append("Correo remitente no válido")

    return errors
