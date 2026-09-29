import ast

import pytest
from mcp import Client

import main
from config import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
async def mcp_client(opcua_server, monkeypatch):
    url, _ = opcua_server
    monkeypatch.setattr(main, "settings", Settings(opcua_server_url=url))
    async with Client(main.mcp) as client:
        yield client


async def call(client: Client, tool: str, **arguments) -> tuple[bool, str]:
    result = await client.call_tool(tool, arguments)
    return result.is_error, result.content[0].text


async def test_lists_all_tools(mcp_client):
    tools = {t.name for t in (await mcp_client.list_tools()).tools}
    assert tools == {
        "get_opcua_connection_info",
        "read_opcua_node",
        "write_opcua_node",
        "browse_opcua_node_children",
        "read_multiple_opcua_nodes",
        "write_multiple_opcua_nodes",
    }


async def test_read_node(mcp_client, opcua_server):
    _, ids = opcua_server
    is_error, text = await call(mcp_client, "read_opcua_node", node_id=ids["float"])
    assert not is_error
    assert text == f"Node {ids['float']} value: 21.5"


async def test_read_unknown_node_reports_status(mcp_client):
    is_error, text = await call(mcp_client, "read_opcua_node", node_id="ns=2;i=9999")
    assert is_error
    assert "BadNodeIdUnknown" in text


@pytest.mark.parametrize(
    "key, value, expected",
    [("float", "42.25", 42.25), ("int", "13", 13), ("bool", "true", True), ("string", "running", "running")],
)
async def test_write_node_converts_to_node_type(mcp_client, opcua_server, key, value, expected):
    _, ids = opcua_server
    is_error, text = await call(mcp_client, "write_opcua_node", node_id=ids[key], value=value)
    assert not is_error, text
    _, text = await call(mcp_client, "read_opcua_node", node_id=ids[key])
    assert text == f"Node {ids[key]} value: {expected}"


async def test_browse_children(mcp_client, opcua_server):
    _, ids = opcua_server
    is_error, text = await call(mcp_client, "browse_opcua_node_children", node_id=ids["machine"])
    assert not is_error
    children = ast.literal_eval(text.split(": ", 1)[1])
    names = {c["browse_name"].split(":", 1)[1] for c in children}
    assert names == {"Temperature", "Counter", "Running", "Mode"}


async def test_read_multiple_reports_per_node_errors(mcp_client, opcua_server):
    _, ids = opcua_server
    is_error, text = await call(
        mcp_client, "read_multiple_opcua_nodes", node_ids=[ids["float"], ids["string"], "ns=2;i=9999"]
    )
    assert not is_error
    results = text.split(": ", 1)[1]
    assert "21.5" in results and "'idle'" in results
    assert "Error reading node ns=2;i=9999: BadNodeIdUnknown" in results


async def test_write_multiple(mcp_client, opcua_server):
    _, ids = opcua_server
    is_error, text = await call(
        mcp_client,
        "write_multiple_opcua_nodes",
        nodes_to_write=[
            {"node_id": ids["float"], "value": 1.5},
            {"node_id": ids["int"], "value": 99},
            {"node_id": "ns=2;i=9999", "value": 1},
        ],
    )
    assert not is_error
    assert text.count("'Success'") == 2
    assert "BadNodeIdUnknown" in text
    _, text = await call(mcp_client, "read_multiple_opcua_nodes", node_ids=[ids["float"], ids["int"]])
    assert "1.5" in text and "99" in text


async def test_write_sends_no_timestamps(mcp_client, opcua_server):
    # Like B&R, the test server rejects writes with a SourceTimestamp (reject_timestamped_writes)
    _, ids = opcua_server
    is_error, text = await call(mcp_client, "write_opcua_node", node_id=ids["int"], value="2")
    assert not is_error, text
    assert text == f"Successfully wrote 2 to node {ids['int']}"


@pytest.mark.parametrize("value, expected", [("TRUE", True), (" false ", False), ("1", True), ("0", False)])
async def test_write_bool_accepts_documented_forms(mcp_client, opcua_server, value, expected):
    _, ids = opcua_server
    is_error, text = await call(mcp_client, "write_opcua_node", node_id=ids["bool"], value=value)
    assert not is_error, text
    _, text = await call(mcp_client, "read_opcua_node", node_id=ids["bool"])
    assert text.endswith(f"value: {expected}")


@pytest.mark.parametrize("value", ["yes", "2", "ture", ""])
async def test_write_bool_rejects_other_values(mcp_client, opcua_server, value):
    _, ids = opcua_server
    # Start from True so that a silent conversion to False would show
    await call(mcp_client, "write_opcua_node", node_id=ids["bool"], value="true")
    is_error, text = await call(mcp_client, "write_opcua_node", node_id=ids["bool"], value=value)
    assert is_error
    assert "Invalid boolean value" in text
    _, text = await call(mcp_client, "read_opcua_node", node_id=ids["bool"])
    assert text.endswith("value: True")


async def test_write_multiple_rejects_invalid_bool(mcp_client, opcua_server):
    _, ids = opcua_server
    is_error, text = await call(
        mcp_client,
        "write_multiple_opcua_nodes",
        nodes_to_write=[{"node_id": ids["bool"], "value": 2}, {"node_id": ids["int"], "value": 5}],
    )
    assert not is_error
    assert "Invalid boolean value 2" in text
    assert text.count("'Success'") == 1
