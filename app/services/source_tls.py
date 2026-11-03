"""System TLS contexts with a Linux-only public issuer supplement."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import ssl
import sys

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from app.config import system_ssl_context
from app.services.runtime_errors import SourceReadError


_ISSUER_BUNDLE = Path(__file__).resolve().parents[1] / "data" / "tls" / "issuer-certificates.json"


def source_ssl_context() -> ssl.SSLContext:
    """Return the system-trust context, supplementing Linux issuer candidates."""
    context = system_ssl_context()
    if not sys.platform.startswith("linux"):
        return context

    certificates = _load_issuer_certificates()
    _add_supplemental_issuer_certificates(context, certificates)
    return context


def _load_issuer_certificates(bundle_path: Path = _ISSUER_BUNDLE) -> list[str]:
    """Read and minimally validate the packaged public issuer certificate set."""
    try:
        document = json.loads(bundle_path.read_text(encoding="utf-8"))
        entries = document["certificates"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("issuer certificate list is empty")

        certificates: list[str] = []
        for entry in entries:
            pem = entry["pem"]
            if (
                not isinstance(pem, str)
                or "-----BEGIN CERTIFICATE-----" not in pem
                or "-----END CERTIFICATE-----" not in pem
                or "-----BEGIN TRUSTED CERTIFICATE-----" in pem
                or "PRIVATE KEY" in pem
            ):
                raise ValueError("invalid public certificate entry")
            parsed = x509.load_pem_x509_certificates(pem.encode('ascii'))
            if len(parsed) != 1:
                raise ValueError('one issuer certificate required')
            certificate = parsed[0]
            if (certificate.subject == certificate.issuer
                    or not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                    or not certificate.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign
                    or hashlib.sha256(certificate.public_bytes(Encoding.DER)).hexdigest() != entry['sha256']):
                raise ValueError('invalid issuer certificate policy')
            certificates.append(pem)
        return certificates
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, ssl.SSLError, x509.ExtensionNotFound):
        raise SourceReadError("source_tls_configuration_error") from None


def _add_supplemental_issuer_certificates(
    context: ssl.SSLContext,
    certificates: list[str],
) -> None:
    """Add issuer certificates as chain-building aids, never as partial roots."""
    try:
        if not certificates:
            raise ValueError("issuer certificate list is empty")
        context.load_verify_locations(cadata="\n".join(certificates))
        partial_chain = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
        if partial_chain:
            context.verify_flags &= ~partial_chain
    except (AttributeError, TypeError, ValueError, ssl.SSLError):
        raise SourceReadError("source_tls_configuration_error") from None
