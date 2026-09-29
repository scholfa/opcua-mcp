import os
import socket
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

# Keep a developer's local .env out of the tests; must happen before config is imported
os.environ["OPCUA_MCP_ENV_FILE"] = os.devnull

import pytest
from asyncua import Server, ua
from asyncua.crypto import cert_gen
from asyncua.crypto.permission_rules import UserRole
from cryptography.x509.oid import ExtendedKeyUsageOID

# Policies an encrypted test server offers, like a B&R PLC with security policy None disabled
SECURE_POLICIES = [
    ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
    ua.SecurityPolicyType.Aes128Sha256RsaOaep_SignAndEncrypt,
]


@pytest.fixture
def anyio_backend():
    # asyncua is built on asyncio
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def reject_timestamped_writes(server: Server):
    """Answer a Value write that carries a SourceTimestamp with BadWriteNotSupported.

    B&R and S7-1500 servers behave like this; the asyncua server would accept the write.
    Only client writes are checked: the server's own writes (startup, the CurrentTime clock,
    shutdown) run as the admin user and carry timestamps.
    """
    service = server.iserver.attribute_service
    original = service.write

    async def write(params, **kwargs):
        user = kwargs.get("user")
        if user is None or user.role == UserRole.Admin:
            return await original(params, **kwargs)
        results = []
        for write_value in params.NodesToWrite:
            if write_value.AttributeId == ua.AttributeIds.Value and write_value.Value.SourceTimestamp is not None:
                results.append(ua.StatusCode(ua.StatusCodes.BadWriteNotSupported))
            else:
                results.extend(await original(ua.WriteParameters(NodesToWrite=[write_value]), **kwargs))
        return results

    service.write = write
    try:
        yield
    finally:
        service.write = original


async def make_certificate(directory: Path, name: str, app_uri: str, use=ExtendedKeyUsageOID.SERVER_AUTH):
    """Create a self-signed certificate/key pair; returns (cert_path, key_path)."""
    cert, key = directory / f"{name}_cert.der", directory / f"{name}_key.pem"
    await cert_gen.setup_self_signed_certificate(key, cert, app_uri, "localhost", [use], {})
    return cert, key


@asynccontextmanager
async def run_opcua_server(
    user_manager=None, secure_dir: Path | None = None, certificate_validator=None, policies=SECURE_POLICIES
):
    """Start an in-process OPC UA test server with a small address space.

    With secure_dir, the server only offers the given secure policies, using a
    certificate created in that directory. Yields the endpoint URL and a dict of the test
    variables' node IDs.
    """
    server = Server(user_manager=user_manager)
    await server.init()
    url = f"opc.tcp://127.0.0.1:{_free_port()}/test/"
    server.set_endpoint(url)
    if secure_dir is None:
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    else:
        server.set_server_name("opcua-mcp test server")
        cert, key = await make_certificate(secure_dir, "server", "urn:opcua-mcp:test-server")
        await server.set_application_uri("urn:opcua-mcp:test-server")
        await server.load_certificate(cert)
        await server.load_private_key(key)
        server.set_security_policy(policies)
    if certificate_validator is not None:
        server.set_certificate_validator(certificate_validator)
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
        with reject_timestamped_writes(server):
            yield url, {name: node.nodeid.to_string() for name, node in nodes.items()}


@pytest.fixture
async def opcua_server():
    async with run_opcua_server() as server:
        yield server
