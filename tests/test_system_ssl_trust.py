"""Inspect a real native-trust context without a network or provider double."""
import ssl
from app.config import system_ssl_context


def test_system_context_requires_certificates_and_hostname_verification():
    context = system_ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
