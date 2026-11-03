"""Pure exception classification, not a mocked transport/provider success."""
import socket
import ssl

import httpx
import pytest


@pytest.mark.parametrize('cause,expected', [
    (ssl.SSLCertVerificationError(1, 'private certificate detail'), 'tls_certificate_verification'),
    (ssl.SSLError(1, 'private TLS detail'), 'tls'),
    (socket.gaierror(-2, 'private hostname'), 'dns'),
    (ConnectionRefusedError('private endpoint'), 'connection_refused'),
    (ConnectionResetError('private endpoint'), 'connection_reset'),
])
def test_wrapped_real_exception_types_have_sanitized_cause(cause, expected):
    from app.services.trusted_source_reader import _transport_cause
    outer = httpx.ConnectError('private wrapper')
    outer.__cause__ = cause
    assert _transport_cause(outer) == expected


def test_unrecognized_or_cyclic_cause_stays_unknown():
    from app.services.trusted_source_reader import _transport_cause
    error = httpx.ConnectError('private unknown')
    error.__context__ = error
    assert _transport_cause(error) == 'unknown'


def test_grouped_connection_failures_only_report_an_agreed_cause():
    from app.services.trusted_source_reader import _transport_cause
    outer = httpx.ConnectError('private wrapper')
    outer.__cause__ = ExceptionGroup('connection attempts', [
        ssl.SSLCertVerificationError(1, 'private one'),
        ssl.SSLCertVerificationError(1, 'private two'),
    ])
    assert _transport_cause(outer) == 'tls_certificate_verification'
    outer.__cause__ = ExceptionGroup('different attempts', [
        socket.gaierror(-2, 'private hostname'), ConnectionRefusedError('private endpoint')])
    assert _transport_cause(outer) == 'unknown'

@pytest.mark.parametrize('code,expected', [
    (20, 'tls_certificate_untrusted_issuer'),
    (21, 'tls_certificate_untrusted_issuer'),
    (10, 'tls_certificate_expired'),
    (62, 'tls_certificate_hostname_mismatch'),
    (999, 'tls_certificate_verification'),
])
def test_certificate_verification_codes_are_controlled_categories(code, expected):
    from app.services.trusted_source_reader import _transport_cause
    error = ssl.SSLCertVerificationError(1, 'private detail')
    error.verify_code = code
    assert _transport_cause(error) == expected
