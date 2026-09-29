from mcp.server.mcpserver import MCPServer, Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from asyncua import Client, Node, ua
from contextlib import asynccontextmanager
from pydantic import ValidationError
from typing import Any, AsyncIterator, Dict, List
from urllib.parse import urlsplit, urlunsplit
import logging
import sys

from config import Settings


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        # Leave out the input values: they can contain the password
        problems = "\n".join(
            f"  {'.'.join(map(str, err['loc'])) or 'settings'}: {err['msg']}"
            for err in e.errors(include_input=False, include_url=False)
        )
        sys.exit(f"Invalid opcua-mcp configuration:\n{problems}")


settings = load_settings()

# Log to stderr: with the stdio transport, stdout carries the MCP protocol
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("opcua-mcp")
logging.getLogger("asyncua").setLevel(logging.WARNING)


def create_client(settings: Settings) -> Client:
    """Create the OPC UA client from settings. Certificate-based security will be configured here."""
    client = Client(
        settings.opcua_server_url,
        timeout=settings.opcua_timeout,
        auto_reconnect=settings.opcua_auto_reconnect,
    )
    if settings.opcua_username is not None:
        client.set_user(settings.opcua_username)
        client.set_password(settings.opcua_password.get_secret_value())
    return client


def _redact_url(url: str) -> str:
    """Drop user:password@ from a URL before logging it."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host_port = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=f"{parts.username}:***@{host_port}"))


# Manage the lifecycle of the OPC UA client connection
@asynccontextmanager
async def opcua_lifespan(server: MCPServer) -> AsyncIterator[dict]:
    """Handle OPC UA client connection lifecycle."""
    client = create_client(settings)
    url = _redact_url(settings.opcua_server_url)
    auth = f"user '{settings.opcua_username}'" if settings.opcua_username else "anonymous"
    try:
        await client.connect()
    except Exception as e:
        logger.error("Could not connect to OPC UA server %s as %s: %s", url, auth, _describe_error(e))
        raise
    logger.info("Connected to OPC UA server %s as %s", url, auth)
    try:
        yield {"opcua_client": client}
    finally:
        await client.disconnect()
        logger.info("Disconnected from OPC UA server")


# Create an MCP server instance
mcp = MCPServer("OPCUA-Control", lifespan=opcua_lifespan)


def _get_client(ctx: Context) -> Client:
    return ctx.request_context.lifespan_context["opcua_client"]


def _describe_error(e: Exception) -> str:
    """Format an exception for the model, including the OPC UA status code if there is one."""
    if isinstance(e, ua.UaStatusCodeError):
        return f"OPC UA Error - Status: {ua.StatusCode(e.code).name} (0x{e.code:08X})"
    return f"{type(e).__name__} - {e}"


async def _write_value(node: Node, value: Any) -> None:
    """Convert a value to the node's current Python type and write it with the node's variant type."""
    current_value = await node.read_value()
    python_typed_value = value
    # bool is a subclass of int, so check it first
    if isinstance(current_value, bool):
        python_typed_value = value if isinstance(value, bool) else str(value).strip().lower() in ("true", "1")
    elif isinstance(current_value, float):
        python_typed_value = float(value)
    elif isinstance(current_value, int):
        python_typed_value = int(value)
    await node.write_value(python_typed_value, await node.read_data_type_as_variant_type())


# Tool: Read the value of an OPC UA node
@mcp.tool()
async def read_opcua_node(node_id: str, ctx: Context) -> str:
    """
    Read the value of a specific OPC UA node.

    Parameters:
        node_id (str): The OPC UA node ID in the format 'ns=<namespace>;i=<identifier>'.
                       Example: 'ns=2;i=2'.

    Returns:
        str: The value of the node as a string, prefixed with the node ID.
    """
    client = _get_client(ctx)
    try:
        value = await client.get_node(node_id).read_value()
    except Exception as e:
        raise ToolError(f"Error reading node {node_id}: {_describe_error(e)}") from e
    return f"Node {node_id} value: {value}"


# Tool: Write a value to an OPC UA node
@mcp.tool()
async def write_opcua_node(node_id: str, value: str, ctx: Context) -> str:
    """
    Write a value to a specific OPC UA node.

    Parameters:
        node_id (str): The OPC UA node ID in the format 'ns=<namespace>;i=<identifier>'.
                       Example: 'ns=2;i=3'.
        value (str): The value to write to the node. Will be converted based on node type.

    Returns:
        str: A message indicating success or failure of the write operation.
    """
    client = _get_client(ctx)
    try:
        await _write_value(client.get_node(node_id), value)
    except Exception as e:
        raise ToolError(f"Error writing to node {node_id}: {_describe_error(e)}") from e
    return f"Successfully wrote {value} to node {node_id}"


@mcp.tool()
async def browse_opcua_node_children(node_id: str, ctx: Context) -> str:
    """
    Browse the children of a specific OPC UA node.

    Parameters:
        node_id (str): The OPC UA node ID to browse (e.g., 'ns=0;i=85' for Objects folder).

    Returns:
        str: A string representation of a list of child nodes, including their NodeId and BrowseName.
             Returns an error message on failure.
    """
    client = _get_client(ctx)
    try:
        children = await client.get_node(node_id).get_children()
    except Exception as e:
        raise ToolError(f"Error browsing children of node {node_id}: {_describe_error(e)}") from e

    children_info = []
    for child in children:
        try:
            browse_name = await child.read_browse_name()
            children_info.append(
                {
                    "node_id": child.nodeid.to_string(),
                    "browse_name": f"{browse_name.NamespaceIndex}:{browse_name.Name}",
                }
            )
        except Exception as e:
            children_info.append(
                {
                    "node_id": child.nodeid.to_string(),
                    "browse_name": f"Error getting name: {_describe_error(e)}",
                }
            )

    return f"Children of {node_id}: {children_info!r}"


@mcp.tool()
async def read_multiple_opcua_nodes(node_ids: List[str], ctx: Context) -> str:
    """
    Read the values of multiple OPC UA nodes in a single request.

    Parameters:
        node_ids (List[str]): A list of OPC UA node IDs to read (e.g., ['ns=2;i=2', 'ns=2;i=3']).

    Returns:
        str: A string representation of a dictionary mapping node IDs to their values, or an error message.
    """
    client = _get_client(ctx)
    try:
        nodes = [client.get_node(nid) for nid in node_ids]
        # One Read service call; each result carries its own status code
        data_values = await client.read_attributes(nodes)
    except Exception as e:
        raise ToolError(f"Error reading multiple nodes {node_ids}: {_describe_error(e)}") from e

    results = {}
    for node, dv in zip(nodes, data_values):
        node_id = node.nodeid.to_string()
        if dv.StatusCode is not None and not dv.StatusCode.is_good():
            results[node_id] = f"Error reading node {node_id}: {dv.StatusCode.name}"
        else:
            results[node_id] = dv.Value.Value if dv.Value is not None else None

    return f"Read multiple nodes values: {results!r}"


@mcp.tool()
async def write_multiple_opcua_nodes(
    nodes_to_write: List[Dict[str, Any]], ctx: Context
) -> str:
    """
    Write values to multiple OPC UA nodes in a single request.

    Parameters:
        nodes_to_write (List[Dict[str, Any]]): A list of dictionaries, where each dictionary
                                               contains 'node_id' (str) and 'value' (Any).
                                               The value is converted based on the node's type.
                                               Example: [{'node_id': 'ns=2;i=2', 'value': 10.5},
                                                         {'node_id': 'ns=2;i=3', 'value': 'active'}]

    Returns:
        str: A message indicating the success or failure of the write operation.
             Returns status codes for each write attempt.
    """
    client = _get_client(ctx)

    status_report = []
    for item in nodes_to_write:
        node_id = item.get("node_id", "unknown_node")
        try:
            await _write_value(client.get_node(item["node_id"]), item["value"])
            status_report.append({"node_id": node_id, "value_written": item["value"], "status": "Success"})
        except Exception as e:
            status_report.append({"node_id": node_id, "status": f"Error: {_describe_error(e)}"})

    if status_report and all(entry["status"] != "Success" for entry in status_report):
        raise ToolError(f"Error writing multiple nodes: {status_report!r}")
    return f"Write multiple nodes results: {status_report!r}"


def run() -> None:
    """Run the MCP server with the transport chosen in the settings."""
    if settings.mcp_transport == "stdio":
        mcp.run("stdio")
        return
    transport_security = None
    if settings.mcp_allowed_hosts:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts,
            allowed_origins=[f"http://{host}" for host in settings.mcp_allowed_hosts],
        )
    logger.info("Serving MCP over %s on %s:%s", settings.mcp_transport, settings.mcp_host, settings.mcp_port)
    mcp.run(
        settings.mcp_transport,
        host=settings.mcp_host,
        port=settings.mcp_port,
        transport_security=transport_security,
    )


# Run the server
if __name__ == "__main__":
    run()
