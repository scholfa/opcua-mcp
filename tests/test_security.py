import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from asyncua import ua
from asyncua.common.utils import ServiceError
from asyncua.crypto.permission_rules import User, UserRole
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from mcp import Client

import main
from config import Settings
from conftest import make_certificate, run_opcua_server
from security import DEFAULT_APPLICATION_URI
from test_auth import PASSWORD, USERNAME, PasswordUserManager

pytestmark = pytest.mark.anyio


@pytest.fixture
async def secure_server(tmp_path):
    """Encrypted-only server that requires a username login, like the B&R PLC."""
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    async with run_opcua_server(user_manager=PasswordUserManager(), secure_dir=server_dir) as server:
        yield server


def secure_settings(url: str, certs_dir, **overrides) -> Settings:
    values = dict(
        opcua_server_url=url,
        opcua_username=USERNAME,
        opcua_password=PASSWORD,
        opcua_security_policy="Basic256Sha256",
        opcua_client_cert=certs_dir / "client_cert.der",
        opcua_client_key=certs_dir / "client_key.pem",
    )
    values.update(overrides)
    return Settings(**values)


async def connection_info(settings: Settings, monkeypatch) -> str:
    monkeypatch.setattr(main, "settings", settings)
    async with Client(main.mcp) as client:
        result = await client.call_tool("get_opcua_connection_info", {})
        assert not result.is_error
        read = await client.call_tool("read_opcua_node", {"node_id": "ns=2;i=2"})
        assert not read.is_error, read.content[0].text
    return result.content[0].text


async def start_fails(settings: Settings, monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", settings)
    with pytest.raises(Exception):
        async with Client(main.mcp):
            pass


@pytest.mark.parametrize("policy", ["Basic256Sha256", "Aes128_Sha256_RsaOaep"])
async def test_generates_certificate_and_connects_encrypted(secure_server, tmp_path, monkeypatch, policy):
    url, _ = secure_server
    certs = tmp_path / "certs"
    text = await connection_info(secure_settings(url, certs, opcua_security_policy=policy), monkeypatch)
    assert f"with security {policy} SignAndEncrypt" in text

    cert = x509.load_der_x509_certificate((certs / "client_cert.der").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.UniformResourceIdentifier) == [DEFAULT_APPLICATION_URI]
    assert san.get_values_for_type(x509.DNSName) == ["opcua-mcp"]
    assert cert.not_valid_after_utc - datetime.now(timezone.utc) > timedelta(days=4 * 365)
    assert (certs / "client_key.pem").exists()


async def test_reuses_existing_certificate(secure_server, tmp_path, monkeypatch):
    url, _ = secure_server
    certs = tmp_path / "certs"
    certs.mkdir()
    cert, key = await make_certificate(certs, "client", "urn:example:my-client", ExtendedKeyUsageOID.CLIENT_AUTH)
    before = cert.read_bytes(), key.read_bytes()
    await connection_info(
        secure_settings(url, certs, opcua_client_cert=cert, opcua_client_key=key), monkeypatch
    )
    assert (cert.read_bytes(), key.read_bytes()) == before


async def test_application_uri_comes_from_certificate(tmp_path):
    from security import prepare_client_certificate

    cert, key = await make_certificate(tmp_path, "client", "urn:example:my-client", ExtendedKeyUsageOID.CLIENT_AUTH)
    settings = secure_settings("opc.tcp://plc:4840", tmp_path, opcua_client_cert=cert, opcua_client_key=key)
    assert (await prepare_client_certificate(settings)).application_uri == "urn:example:my-client"


async def test_missing_key_fails_startup(secure_server, tmp_path, monkeypatch, caplog):
    url, _ = secure_server
    certs = tmp_path / "certs"
    certs.mkdir()
    cert, key = await make_certificate(certs, "client", DEFAULT_APPLICATION_URI, ExtendedKeyUsageOID.CLIENT_AUTH)
    key.unlink()
    await start_fails(secure_settings(url, certs, opcua_client_cert=cert, opcua_client_key=key), monkeypatch)
    assert f"{key} is missing" in caplog.text
    assert not key.exists()  # nothing was regenerated behind the user's back


async def test_policy_none_is_rejected_by_encrypted_server(secure_server, tmp_path, monkeypatch, caplog):
    url, _ = secure_server
    await start_fails(secure_settings(url, tmp_path, opcua_security_policy="None"), monkeypatch)
    assert "Could not connect to OPC UA server" in caplog.text


async def test_pinned_server_certificate(secure_server, tmp_path, monkeypatch):
    url, _ = secure_server
    certs = tmp_path / "certs"
    text = await connection_info(
        secure_settings(url, certs, opcua_server_cert=tmp_path / "server" / "server_cert.der"), monkeypatch
    )
    assert "SignAndEncrypt" in text


async def test_wrong_pinned_server_certificate_fails(secure_server, tmp_path, monkeypatch):
    url, _ = secure_server
    other, _ = await make_certificate(tmp_path, "other", "urn:example:other-server")
    await start_fails(secure_settings(url, tmp_path / "certs", opcua_server_cert=other), monkeypatch)


async def test_untrusted_client_certificate_logs_hint(tmp_path, monkeypatch, caplog):
    async def reject_all(certificate, application_description):
        raise ServiceError(ua.StatusCodes.BadCertificateUntrusted)

    server_dir = tmp_path / "server"
    server_dir.mkdir()
    async with run_opcua_server(
        user_manager=PasswordUserManager(), secure_dir=server_dir, certificate_validator=reject_all
    ) as (url, _):
        certs = tmp_path / "certs"
        await start_fails(secure_settings(url, certs), monkeypatch)
    assert "BadCertificateUntrusted" in caplog.text
    assert f"The server rejected the client certificate {certs / 'client_cert.der'}" in caplog.text


async def test_logs_certificate_fingerprints(secure_server, tmp_path, monkeypatch, caplog):
    url, _ = secure_server
    caplog.set_level("INFO", logger="opcua-mcp")
    await connection_info(secure_settings(url, tmp_path / "certs"), monkeypatch)
    assert "Generated OPC UA client certificate" in caplog.text
    assert "server certificate SHA-256" in caplog.text


class AnonymousUserManager:
    """Accept only the B&R-style user "Anonymous" without a password; record what arrived."""

    def __init__(self):
        self.received = []

    def get_user(self, iserver, username=None, password=None, certificate=None):
        self.received.append((username, password))
        return User(role=UserRole.User) if username == "Anonymous" and not password else None


async def test_empty_password_is_sent_encrypted(tmp_path, monkeypatch):
    # In Sign mode the asyncua server, like a B&R PLC in any mode, requires the password in the
    # username token to be encrypted; with SignAndEncrypt it relies on the channel instead
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    users = AnonymousUserManager()
    sign_only = [ua.SecurityPolicyType.Basic256Sha256_Sign]
    async with run_opcua_server(user_manager=users, secure_dir=server_dir, policies=sign_only) as (url, _):
        settings = secure_settings(
            url, tmp_path / "certs", opcua_username="Anonymous", opcua_password=None, opcua_security_mode="Sign"
        )
        await connection_info(settings, monkeypatch)
    # Decrypted by the server: an empty string, not a missing password
    assert ("Anonymous", "") in users.received


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
async def test_generated_private_key_is_owner_only(tmp_path):
    from security import prepare_client_certificate

    settings = secure_settings("opc.tcp://plc:4840", tmp_path / "certs")
    await prepare_client_certificate(settings)
    assert stat.S_IMODE(settings.opcua_client_key.stat().st_mode) == 0o600
