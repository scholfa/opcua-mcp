# OPC UA MCP Server

An MCP server that connects to OPC UA-enabled industrial systems, allowing AI agents to monitor, analyze, and control operational data in real time.

This project is ideal for developers and engineers looking to bridge AI-driven workflows with industrial automation systems.

![GitHub License](https://img.shields.io/github/license/kukapay/opcua-mcp)
![Python Version](https://img.shields.io/badge/python-3.13+-blue)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

## Features

- **Read OPC UA Nodes**: Retrieve real-time values from industrial devices.
- **Write to OPC UA Nodes**: Control devices by writing values to specified nodes.
- **Browse nodes**: Request to list allopcua  nodes
- **Read multiple OPC UA Nodes**: Retrieve multiple real-time values from devices.
- **Write to multiple OPC UA Nodes**: Control devices by writing values to multiple nodes.
- **Credentials from `.env`**: Username/password login configured in a `.env` file or environment variables.
- **Runs in Docker**: Over stdio (started by the MCP client) or as a long-running Streamable HTTP service.
- **Seamless Integration**: Works with MCP clients like Claude Desktop for natural language interaction.


### Tools
The server exposes six tools:
- **`get_opcua_connection_info`**:
  - **Description**: Show which OPC UA endpoint the server is connected to and the configured endpoints.
  - **Returns**: e.g. "Connected to opc.tcp://127.0.0.1:4840 as anonymous. Configured endpoints, tried in order at startup: ..."

- **`read_opcua_node`**:
  - **Description**: Read the value of a specific OPC UA node.
  - **Parameters**:
    - `node_id` (str): OPC UA node ID (e.g., `ns=2;i=2`).
  - **Returns**: A string with the node ID and its value (e.g., "Node ns=2;i=2 value: 42").

- **`write_opcua_node`**:
  - **Description**: Write a value to a specific OPC UA node.
  - **Parameters**:
    - `node_id` (str): OPC UA node ID (e.g., `ns=2;i=3`).
    - `value` (str): Value to write (converted based on node type).
  - **Returns**: A success or error message (e.g., "Successfully wrote 100 to node ns=2;i=3").

- **`browse_opcua_node_children`**:
  - **Description**: List the child nodes of a node, with their node IDs and browse names.
  - **Parameters**:
    - `node_id` (str): Node to browse (e.g., `ns=0;i=85` for the Objects folder).

- **`read_multiple_opcua_nodes`**:
  - **Description**: Read several node values in one request; unreadable nodes are reported individually.
  - **Parameters**:
    - `node_ids` (List[str]): Node IDs to read (e.g., `["ns=2;i=2", "ns=2;i=3"]`).

- **`write_multiple_opcua_nodes`**:
  - **Description**: Write several node values, converting each to the node's type, and report the result per node.
  - **Parameters**:
    - `nodes_to_write` (List[Dict]): Items with `node_id` and `value` (e.g., `[{"node_id": "ns=2;i=2", "value": 10.5}]`).

Failed calls are returned as MCP tool errors that include the OPC UA status code (e.g., `BadNodeIdUnknown`).


### Example Prompts

- "What’s the value of node ns=2;i=2?" → Returns the current value.
- "Set node ns=2;i=3 to 100." → Writes 100 to the node.

## Installation

### Prerequisites
- Python 3.13 or higher and [uv](https://docs.astral.sh/uv/) — or Docker
- An OPC UA server (e.g., a simulator or real industrial device)

### Install Dependencies
Clone the repository and install the required Python packages:

```bash
git clone https://github.com/scholfa/opcua-mcp.git
cd opcua-mcp
uv sync   # or: pip install "mcp[cli]>=2.2,<3" "asyncua>=2.0.1" "pydantic-settings>=2.8"
```

> **Upgrading from an earlier version:** the server now uses `asyncua` and `mcp` 2.x instead of
> `opcua` and `mcp` 1.x. Run `uv sync` again (or reinstall the packages above) before starting it.

## Configuration

Settings are read from environment variables and from a `.env` file next to `main.py`.
Real environment variables take precedence over the file. Start from the example:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `OPCUA_SERVER_URL` | `opc.tcp://localhost:4840` | Endpoint URL, or several separated by commas — see [Multiple OPC UA servers](#multiple-opc-ua-servers) |
| `OPCUA_USERNAME` / `OPCUA_PASSWORD` | *(empty)* | Username/password login. Leave both empty for anonymous; setting only one is an error. |
| `OPCUA_TIMEOUT` | `4` | Request timeout in seconds |
| `OPCUA_AUTO_RECONNECT` | `true` | Reconnect automatically when the connection drops |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http` or `sse` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8000` | Bind address for the HTTP transports |
| `MCP_ALLOWED_HOSTS` | *(empty)* | Comma-separated `Host` headers accepted over HTTP (DNS rebinding protection), e.g. `localhost:*,127.0.0.1:*` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (logs go to stderr) |
| `OPCUA_MCP_ENV_FILE` | `.env` next to `main.py` | Path of the `.env` file to read |

`.env` is ignored by git and by the Docker build, so credentials stay out of commits and images.

### Multiple OPC UA servers

List several endpoints to use a simulation when it is running and the real hardware otherwise:

```bash
OPCUA_SERVER_URL=opc.tcp://127.0.0.1:4840,opc.tcp://192.168.0.10:4840
```

- At startup the endpoints are tried in order and the first **reachable** one is used. Each
  unreachable endpoint costs up to `OPCUA_TIMEOUT` seconds before the next one is tried.
- An endpoint that is reachable but refuses the login (e.g. wrong credentials) stops startup with
  an error instead of moving on, so a configuration mistake never silently lands on the next server.
- The choice is made once, at startup. If the connection drops later, the server reconnects to the
  same endpoint and never switches to another one, e.g. from the simulation to the real machine.
  Restart the MCP server to pick again. With stdio, the MCP client starts a fresh server per session.
- The same credentials are used for every endpoint.
- The `get_opcua_connection_info` tool reports which endpoint is in use, so you (or the model) can
  check whether it is the simulation or the hardware before writing values.
- Use `127.0.0.1` rather than `localhost`: on Windows a stopped `localhost` endpoint takes about
  4 s to skip instead of 2 s. In Docker, `localhost` is the container itself; use
  `opc.tcp://host.docker.internal:4840` to reach a simulation on the host.

> **Security note:** certificate-based security (`Sign` / `SignAndEncrypt`) is not supported yet,
> so the connection uses security policy `None`. Depending on the server, the password may then be
> sent in plain text — asyncua logs `Sending plain-text password` when that happens. Only use
> username/password login on trusted networks until certificate support is added. The variable
> names `OPCUA_SECURITY_POLICY`, `OPCUA_SECURITY_MODE`, `OPCUA_CLIENT_CERT`, `OPCUA_CLIENT_KEY`
> and `OPCUA_SERVER_CERT` are reserved for it.

### MCP Client Configuration

With the settings in `.env`, the client config only needs to start the server:

```json
{
  "mcpServers": {
    "opcua-mcp": {
      "command": "uv",
      "args": ["run", "--project", "path/to/opcua-mcp", "python", "path/to/opcua-mcp/main.py"]
    }
  }
}
```

Values in `"env"` still work and override `.env`, e.g. `"env": {"OPCUA_SERVER_URL": "opc.tcp://192.168.0.10:4840"}`.

## Running in Docker

Build the image:

```bash
docker build -t opcua-mcp .
```

Credentials are never baked into the image; pass them at runtime with `--env-file .env`.
Docker takes everything after `=` literally, so don't put quotes around values in `.env`.

### stdio (the MCP client starts the container)

```json
{
  "mcpServers": {
    "opcua-mcp": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "--env-file", "C:/path/to/opcua-mcp/.env", "opcua-mcp"]
    }
  }
}
```

### Streamable HTTP (long-running service)

```bash
docker compose up -d --build
```

The MCP endpoint is then `http://localhost:8000/mcp` (set `MCP_PUBLISHED_PORT` in `.env` to use
another host port). The compose file publishes the port on localhost only, because the server has no MCP-level authentication. To accept other `Host` names
(for example when publishing the port on the LAN), set `MCP_ALLOWED_HOSTS` accordingly.

Without compose:

```bash
docker run -d --env-file .env -e MCP_TRANSPORT=streamable-http -p 127.0.0.1:8000:8000 opcua-mcp
```

### Reaching the OPC UA server from the container

- OPC UA server on the Docker host: `OPCUA_SERVER_URL=opc.tcp://host.docker.internal:4840`
  (works on Docker Desktop; the compose file also maps it on Linux).
- PLC or server on the LAN: use its IP address or DNS name as usual.

## Development

```bash
uv run pytest
```

The tests start an in-process asyncua server, including one that requires a username and password.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
