"""TLS supplemental-issuer behavior using generated local certificates."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import ssl as _ssl
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.services.runtime_errors import SourceReadError
from app.services.source_tls import (
    _add_supplemental_issuer_certificates,
    _load_issuer_certificates,
    source_ssl_context,
)


def _load_standard_ssl_module():
    """Load the stdlib OpenSSL adapter without the host truststore patch."""
    spec = importlib.util.spec_from_file_location(
        "vietlex_test_stdlib_ssl",
        Path(_ssl.__file__),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


stdlib_ssl = _load_standard_ssl_module()


@dataclass(frozen=True)
class LocalCertificateChain:
    root_pem: str
    issuer_pem: str
    leaf_pem: str
    leaf_key_pem: bytes


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _issue(subject, subject_key, issuer, issuer_key, *, ca: bool, path_length=None, dns_name=None, expired=False):
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=3) if expired else now - timedelta(minutes=1))
        .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=path_length), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=not ca,
                content_commitment=False,
                key_encipherment=not ca,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=ca,
                crl_sign=ca,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(subject_key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()),
            critical=False,
        )
    )
    if dns_name:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(dns_name)]),
            critical=False,
        )
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def _certificate_pem(certificate: x509.Certificate) -> str:
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


@pytest.fixture
def local_certificate_chain(tmp_path, request) -> LocalCertificateChain:
    root_key = _new_key()
    root_name = _name("generated local TLS root")
    root = _issue(root_name, root_key, type("Issuer", (), {"subject": root_name})(), root_key, ca=True, path_length=1)

    issuer_key = _new_key()
    issuer = _issue(_name("generated local TLS intermediate"), issuer_key, root, root_key, ca=True, path_length=0)

    leaf_key = _new_key()
    leaf = _issue(_name("localhost"), leaf_key, issuer, issuer_key, ca=False, dns_name="localhost", expired=getattr(request, 'param', False))
    private_key = leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    chain = LocalCertificateChain(
        root_pem=_certificate_pem(root),
        issuer_pem=_certificate_pem(issuer),
        leaf_pem=_certificate_pem(leaf),
        leaf_key_pem=private_key,
    )
    (tmp_path / "leaf.pem").write_text(chain.leaf_pem, encoding="ascii")
    (tmp_path / "leaf-key.pem").write_bytes(chain.leaf_key_pem)
    return chain


def _client_context(*trusted_pems: str):
    context = stdlib_ssl.SSLContext(stdlib_ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = stdlib_ssl.CERT_REQUIRED
    context.check_hostname = True
    context.load_verify_locations(cadata="\n".join(trusted_pems))
    partial_chain = getattr(stdlib_ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    if partial_chain:
        context.verify_flags &= ~partial_chain
    return context


def _local_https_request(local_certificate_chain, tmp_path, client_context, hostname="localhost"):
    server_context = stdlib_ssl.SSLContext(stdlib_ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(
        str(tmp_path / "leaf.pem"),
        str(tmp_path / "leaf-key.pem"),
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(4)
    port = listener.getsockname()[1]

    def serve_one_request():
        try:
            raw, _ = listener.accept()
            with raw, server_context.wrap_socket(raw, server_side=True) as server:
                server.settimeout(4)
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(1024)
                    if not chunk:
                        break
                    request.extend(chunk)
                server.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
        except (OSError, stdlib_ssl.SSLError):
            # A rejected client handshake is the expected server-side outcome
            # for negative cases; the client assertion below is authoritative.
            pass
        finally:
            listener.close()

    worker = threading.Thread(target=serve_one_request, daemon=True)
    worker.start()
    try:
        raw = socket.create_connection(("127.0.0.1", port), timeout=3)
        with client_context.wrap_socket(raw, server_hostname=hostname) as client:
            client.sendall(
                f"GET / HTTP/1.1\r\nHost: {hostname}\r\nConnection: close\r\n\r\n".encode("ascii"),
            )
            response = client.makefile("rb")
            status_line = response.readline(256).decode("ascii", errors="replace").strip()
            while True:
                line = response.readline(4096)
                if not line or line in (b"\r\n", b"\n"):
                    break
            return status_line
    finally:
        worker.join(timeout=5)
        if worker.is_alive():
            listener.close()
            raise TimeoutError("local HTTPS test server did not stop")


def test_supplemental_intermediate_verifies_local_leaf_only_http_without_partial_chain(
    local_certificate_chain,
    tmp_path,
):
    context = _client_context(local_certificate_chain.root_pem)
    _add_supplemental_issuer_certificates(context, [local_certificate_chain.issuer_pem])

    partial_chain = getattr(stdlib_ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    if partial_chain:
        assert context.verify_flags & partial_chain == 0
    assert context.verify_mode == stdlib_ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert _local_https_request(local_certificate_chain, tmp_path, context) == "HTTP/1.1 200 OK"


def test_root_only_and_intermediate_only_contexts_reject_leaf_only_server(
    local_certificate_chain,
    tmp_path,
):
    root_only = _client_context(local_certificate_chain.root_pem)
    with pytest.raises(stdlib_ssl.SSLCertVerificationError):
        _local_https_request(local_certificate_chain, tmp_path, root_only)

    intermediate_only = _client_context(local_certificate_chain.issuer_pem)
    intermediate_only.verify_flags |= stdlib_ssl.VERIFY_X509_PARTIAL_CHAIN
    _add_supplemental_issuer_certificates(intermediate_only, [local_certificate_chain.issuer_pem])
    assert not intermediate_only.verify_flags & stdlib_ssl.VERIFY_X509_PARTIAL_CHAIN
    with pytest.raises(stdlib_ssl.SSLCertVerificationError):
        _local_https_request(local_certificate_chain, tmp_path, intermediate_only)


def test_supplemental_intermediate_does_not_bypass_hostname_verification(
    local_certificate_chain,
    tmp_path,
):
    context = _client_context(local_certificate_chain.root_pem)
    _add_supplemental_issuer_certificates(context, [local_certificate_chain.issuer_pem])

    with pytest.raises(stdlib_ssl.SSLCertVerificationError, match="(?i)hostname"):
        _local_https_request(
            local_certificate_chain,
            tmp_path,
            context,
            hostname="wrong.example",
        )


def test_source_ssl_context_preserves_required_verification():
    context = source_ssl_context()

    assert context.verify_mode == _ssl.CERT_REQUIRED
    assert context.check_hostname is True
    partial_chain = getattr(_ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    if partial_chain and __import__("sys").platform.startswith("linux"):
        assert context.verify_flags & partial_chain == 0


@pytest.mark.parametrize('local_certificate_chain', [True], indirect=True)
def test_expired_leaf_rejected_with_complete_chain(local_certificate_chain, tmp_path):
    context = _client_context(local_certificate_chain.root_pem)
    _add_supplemental_issuer_certificates(context, [local_certificate_chain.issuer_pem])
    with pytest.raises(stdlib_ssl.SSLCertVerificationError, match='(?i)expired'):
        _local_https_request(local_certificate_chain, tmp_path, context)


def test_bundled_certificates_are_public_nonselfsigned_issuer_cas():
    bundle_path = Path(__file__).resolve().parents[2] / "app" / "data" / "tls" / "issuer-certificates.json"
    document = json.loads(bundle_path.read_text(encoding="utf-8"))
    certificates = document["certificates"]
    assert certificates

    for entry in certificates:
        pem = entry["pem"]
        assert "-----BEGIN CERTIFICATE-----" in pem
        assert "-----BEGIN TRUSTED CERTIFICATE-----" not in pem
        assert "PRIVATE KEY" not in pem
        certificate = x509.load_pem_x509_certificate(pem.encode("ascii"))
        assert certificate.subject != certificate.issuer
        assert certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True
        assert certificate.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign is True
        assert hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest() == entry[
            "sha256"
        ]
        assert entry["source_url"].startswith("https://")


@pytest.mark.parametrize("payload", ["not json", '{"certificates": []}', '{"certificates": [{"pem": "bad"}]}'])
def test_malformed_or_empty_issuer_bundle_fails_with_typed_source_error(tmp_path, payload):
    bundle_path = tmp_path / "issuer-certificates.json"
    bundle_path.write_text(payload, encoding="utf-8")

    with pytest.raises(SourceReadError) as error:
        _load_issuer_certificates(bundle_path)

    assert error.value.kind == "source_tls_configuration_error"


def test_missing_issuer_bundle_fails_with_typed_source_error(tmp_path):
    with pytest.raises(SourceReadError) as error:
        _load_issuer_certificates(tmp_path / "missing.json")

    assert error.value.kind == "source_tls_configuration_error"


@pytest.mark.parametrize('kind', ['root', 'leaf', 'multiple', 'hash'])
def test_issuer_bundle_rejects_anchor_leaf_multiple_and_bad_hash(tmp_path, local_certificate_chain, kind):
    chain = local_certificate_chain
    pem = {'root': chain.root_pem, 'leaf': chain.leaf_pem,
           'multiple': chain.issuer_pem + chain.root_pem, 'hash': chain.issuer_pem}[kind]
    path = tmp_path / 'issuers.json'
    digest = hashlib.sha256(x509.load_pem_x509_certificate(pem.encode()).public_bytes(serialization.Encoding.DER)).hexdigest()
    path.write_text(json.dumps({'certificates': [{'pem': pem, 'sha256': '0' * 64 if kind == 'hash' else digest}]}))
    with pytest.raises(SourceReadError):
        _load_issuer_certificates(path)
