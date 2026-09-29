import pytest
from asyncua.crypto.permission_rules import User, UserRole
from mcp import Client

import main
from config import Settings
from conftest import run_opcua_server

pytestmark = pytest.mark.anyio

USERNAME = "operator"
PASSWORD = "s3cret!"


class PasswordUserManager:
    """Accept only USERNAME/PASSWORD; anonymous logins are rejected."""

    def get_user(self, iserver, username=None, password=None, certificate=None):
        if username == USERNAME and password == PASSWORD:
            return User(role=UserRole.User)
        return None


@pytest.fixture
async def auth_server():
    async with run_opcua_server(user_manager=PasswordUserManager()) as server:
        yield server


async def test_connects_with_credentials(auth_server, monkeypatch):
    url, ids = auth_server
    settings = Settings(opcua_server_url=url, opcua_username=USERNAME, opcua_password=PASSWORD)
    monkeypatch.setattr(main, "settings", settings)
    async with Client(main.mcp) as client:
        result = await client.call_tool("read_opcua_node", {"node_id": ids["float"]})
    assert not result.is_error
    assert result.content[0].text.endswith("21.5")


@pytest.mark.parametrize(
    "credentials",
    [{"opcua_username": USERNAME, "opcua_password": "wrong"}, {}],
    ids=["wrong-password", "anonymous"],
)
async def test_rejected_login_fails_startup(auth_server, monkeypatch, caplog, credentials):
    url, _ = auth_server
    monkeypatch.setattr(main, "settings", Settings(opcua_server_url=url, **credentials))
    with pytest.raises(Exception):
        async with Client(main.mcp):
            pass
    assert "Could not connect to OPC UA server" in caplog.text
    assert "wrong" not in caplog.text


async def test_create_client_sets_credentials():
    client = await main.create_client(
        Settings(opcua_server_url="opc.tcp://plc:4840", opcua_username=USERNAME, opcua_password=PASSWORD),
        "opc.tcp://plc:4840",
    )
    assert client._username == USERNAME
    assert client._password == PASSWORD


async def test_create_client_anonymous():
    client = await main.create_client(Settings(opcua_server_url="opc.tcp://plc:4840"), "opc.tcp://plc:4840")
    assert client._username is None
    assert client._password is None


@pytest.mark.parametrize(
    "url, expected",
    [
        ("opc.tcp://plc:4840", "opc.tcp://plc:4840"),
        ("opc.tcp://user:pw@plc:4840/path", "opc.tcp://user:***@plc:4840/path"),
        ("opc.tcp://user:pw@plc", "opc.tcp://user:***@plc"),
    ],
)
def test_redact_url(url, expected):
    assert main._redact_url(url) == expected


def test_invalid_config_does_not_print_password(monkeypatch):
    monkeypatch.setenv("OPCUA_PASSWORD", PASSWORD)
    monkeypatch.delenv("OPCUA_USERNAME", raising=False)
    with pytest.raises(SystemExit) as exc:
        main.load_settings()
    assert "OPCUA_PASSWORD is set but OPCUA_USERNAME is not" in str(exc.value.code)
    assert PASSWORD not in str(exc.value.code)


async def test_username_without_password_sends_empty_password():
    client = await main.create_client(
        Settings(opcua_server_url="opc.tcp://plc:4840", opcua_username="Anonymous"), "opc.tcp://plc:4840"
    )
    assert client._username == "Anonymous"
    assert client._password == ""
