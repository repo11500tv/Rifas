"""Comprobaciones de seguridad para destinos SMTP."""

import ipaddress
import socket

from platform_app.smtp_validation import valid_hostname


class SMTPDestinationError(ValueError):
    pass


def public_ip(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
        and not ip.is_loopback
        and not ip.is_link_local
    )


def resolve_smtp_host(host):
    if not valid_hostname(host):
        raise SMTPDestinationError(
            "El nombre del servidor SMTP no es válido"
        )

    try:
        results = socket.getaddrinfo(
            host,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise SMTPDestinationError(
            "No se puede resolver el servidor SMTP"
        ) from exc

    addresses = sorted({
        result[4][0]
        for result in results
    })

    if not addresses:
        raise SMTPDestinationError(
            "El servidor SMTP no tiene direcciones IP"
        )

    if not all(public_ip(address) for address in addresses):
        raise SMTPDestinationError(
            "El servidor SMTP resuelve a una dirección no pública"
        )

    return addresses
