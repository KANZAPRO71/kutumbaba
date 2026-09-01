"""Generate self-signed dev TLS cert for Persona AI (LAN + localhost)."""

from __future__ import annotations

import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cert_dir = root / ".persona_ai" / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)

    lan_ip = sys.argv[1] if len(sys.argv) > 1 else _lan_ip()
    cert_path = cert_dir / "dev-cert.pem"
    key_path = cert_dir / "dev-key.pem"
    android_raw = root / "android" / "app" / "src" / "main" / "res" / "raw"
    android_raw.mkdir(parents=True, exist_ok=True)
    android_cert = android_raw / "persona_ai_cert"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Persona AI"),
            x509.NameAttribute(NameOID.COMMON_NAME, lan_ip),
        ]
    )
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address(lan_ip)),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=825))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    android_cert.write_bytes(cert_pem)
    print(f"LAN IP: {lan_ip}")
    print(f"Wrote {cert_path}")
    print(f"Wrote {key_path}")
    print(f"Wrote {android_cert}")


if __name__ == "__main__":
    main()
