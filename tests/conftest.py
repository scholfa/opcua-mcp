import os
import socket
from contextlib import asynccontextmanager

# Keep a developer's local .env out of the tests; must happen before config is imported
os.environ["OPCUA_MCP_ENV_FILE"] = os.devnull

import pytest
from asyncua import Server, ua


@pytest.fixture
def anyio_backend():
    # asyncua is built on asyncio
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def run_opcua_server(user_manager=None):
    """Start an in-process OPC UA test server with a small address space.

    Yields the endpoint URL and a dict of the test variables' node IDs.
    """
    server = Server(user_manager=user_manager)
    await server.init()
    url = f"opc.tcp://127.0.0.1:{_free_port()}/test/"
    server.set_endpoint(url)
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    if user_manager is not None:
        server.set_identity_tokens([ua.UserNameIdentityToken])

    idx = await server.register_namespace("urn:opcua-mcp:test")
    machine = await server.nodes.objects.add_object(idx, "Machine")
    nodes = {
        "machine": machine,
        "float": await machine.add_variable(idx, "Temperature", 21.5),
        "int": await machine.add_variable(idx, "Counter", 7, ua.VariantType.Int32),
        "bool": await machine.add_variable(idx, "Running", False),
        "string": await machine.add_variable(idx, "Mode", "idle"),
    }
    for name, node in nodes.items():
        if name != "machine":
            await node.set_writable()

    async with server:
        yield url, {name: node.nodeid.to_string() for name, node in nodes.items()}


@pytest.fixture
async def opcua_server():
    async with run_opcua_server() as server:
        yield server
