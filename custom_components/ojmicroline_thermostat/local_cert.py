"""Self-signed certificate for the local device gateway.

The thermostat connects to the gateway over TLS but does not validate the
certificate, so a self-signed one generated on this host is enough. It is
created once under the Home Assistant config directory and reused after that.
Nothing here touches the device firmware.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .local_const import DOMAIN, GATEWAY_HOST

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

CERT_NAME = "gateway.crt"
KEY_NAME = "gateway.key"


def _generate(cert_path: Path, key_path: Path) -> None:
    """Create a self-signed cert/key pair (blocking; run in an executor)."""
    # pylint: disable=import-outside-toplevel
    # Imported lazily: cryptography ships with Home Assistant but is heavy.
    from cryptography import x509  # noqa: PLC0415 - imported in executor
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, GATEWAY_HOST)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(GATEWAY_HOST)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.chmod(0o600)


async def async_ensure_cert(hass: HomeAssistant) -> tuple[str, str]:
    """Return (certfile, keyfile), generating them on first use."""

    def _ensure() -> tuple[str, str]:
        base = Path(hass.config.path(DOMAIN))
        base.mkdir(parents=True, exist_ok=True)
        cert_path = base / CERT_NAME
        key_path = base / KEY_NAME
        if not cert_path.exists() or not key_path.exists():
            _generate(cert_path, key_path)
        return str(cert_path), str(key_path)

    return await hass.async_add_executor_job(_ensure)
