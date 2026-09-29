import pytest
from mcp import Client

import main
from config import Settings
from conftest import _free_port, run_opcua_server
from test_auth import PasswordUserManager

pytestmark = pytest.mark.anyio


def unreachable_url() -> str:
    # A free port with nothing listening: the connection is refused
    return f"opc.tcp://127.0.0.1:{_free_port()}/"


async def connection_info(settings: Settings, monkeypatch) -> str:
    monkeypatch.setattr(main, "settings", settings)
    async with Client(main.mcp) as client:
        result = await client.call_tool("get_opcua_connection_info", {})
    assert not result.is_error
    return result.content[0].text


async def test_uses_first_reachable_server(opcua_server, monkeypatch):
    url, _ = opcua_server
    text = await connection_info(Settings(opcua_server_url=[unreachable_url(), url]), monkeypatch)
    assert text.startswith(f"Connected to {url} as anonymous.")


async def test_prefers_earlier_server_when_both_are_reachable(monkeypatch):
    async with run_opcua_server() as (first, _), run_opcua_server() as (second, _):
        text = await connection_info(Settings(opcua_server_url=[first, second]), monkeypatch)
    assert text.startswith(f"Connected to {first} ")
    assert f"tried in order at startup: {first}, {second}" in text


async def test_fails_when_no_server_is_reachable(monkeypatch, caplog):
    urls = [unreachable_url(), unreachable_url()]
    monkeypatch.setattr(main, "settings", Settings(opcua_server_url=urls))
    with pytest.raises(Exception):
        async with Client(main.mcp):
            pass
    assert f"No OPC UA server reachable, tried: {urls[0]}, {urls[1]}" in caplog.text


async def test_rejected_login_does_not_fall_through(monkeypatch, caplog):
    # The first server is up but refuses the (anonymous) login; the second would accept it
    async with run_opcua_server(user_manager=PasswordUserManager()) as (secured, _), run_opcua_server() as (open_, _):
        monkeypatch.setattr(main, "settings", Settings(opcua_server_url=[secured, open_]))
        with pytest.raises(Exception):
            async with Client(main.mcp):
                pass
    assert f"Could not connect to OPC UA server {secured}" in caplog.text
    assert f"Connected to OPC UA server {open_}" not in caplog.text
