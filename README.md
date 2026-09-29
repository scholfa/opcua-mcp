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
- **Encrypted connections**: Sign / SignAndEncrypt with an automatically generated or supplied client certificate.
- **Runs in Docker**: Over stdio (started by the MCP client) or as a long-running Streamable HTTP service.
- **Seamless Integration**: Works with MCP clients like Claude Desktop for natural language interaction.


### Tools
The server exposes six tools:
- **`get_opcua_connection_info`**:
  - **Description**: Show which OPC UA server the MCP server is connected to, checked live: the endpoint, the server's application URI and state, and the configured endpoints. Fails if the server is not answering (e.g. during a restart).
  - **Returns**: e.g. "Connected to opc.tcp://host.docker.internal:4840 (server application URI urn:127.0.0.1/BR/UA/EmbeddedServer, state Running) as user 'Anonymous' with security Basic256Sha256 SignAndEncrypt. ..." — on B&R, `urn:127.0.0.1/...` identifies ARsim.

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
| `OPCUA_USERNAME` / `OPCUA_PASSWORD` | *(empty)* | Username/password login. Leave both empty for anonymous. A username without a password logs in with an empty password (B&R: user `Anonymous`); a password without a username is an error. |
| `OPCUA_TIMEOUT` | `4` | Request timeout in seconds |
| `OPCUA_AUTO_RECONNECT` | `true` | Reconnect automatically when the connection drops |
| `OPCUA_SECURITY_POLICY` | `None` | `None`, `Basic256Sha256`, `Aes128_Sha256_RsaOaep` or `Aes256_Sha256_RsaPss` — see [Certificate-based security](#certificate-based-security) |
| `OPCUA_SECURITY_MODE` | `SignAndEncrypt` | `Sign` or `SignAndEncrypt` |
| `OPCUA_CLIENT_CERT` / `OPCUA_CLIENT_KEY` | `certs/client_cert.der` / `certs/client_key.pem` | Client certificate (DER or PEM) and private key; generated if neither exists |
| `OPCUA_CLIENT_KEY_PASSWORD` | *(empty)* | Password of an encrypted private key |
| `OPCUA_SERVER_CERT` | *(empty)* | Pin the server certificate |
| `OPCUA_APPLICATION_URI` | from the client certificate | Application URI the client presents |
| `OPCUA_CLIENT_HOSTNAME` | `opcua-mcp` | DNS name written into a generated certificate |
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
- The same credentials and security settings are used for every endpoint.
- The `get_opcua_connection_info` tool asks the server live which one it is (its application URI),
  so you (or the model) can check whether it is the simulation or the hardware before writing values.
- Use `127.0.0.1` rather than `localhost`: on Windows a stopped `localhost` endpoint takes about
  4 s to skip instead of 2 s. In Docker, `localhost` is the container itself; use
  `opc.tcp://host.docker.internal:4840` to reach a simulation on the host (the server logs a warning
  at startup for a loopback entry when it runs in a container).

### Certificate-based security

Set a security policy to sign and encrypt the connection. B&R PLCs disable policy `None` by
default and only accept encrypted connections:

```bash
OPCUA_SECURITY_POLICY=Basic256Sha256
OPCUA_SECURITY_MODE=SignAndEncrypt
```

- **Client certificate:** if neither `OPCUA_CLIENT_CERT` nor `OPCUA_CLIENT_KEY` exists, a
  self-signed certificate (valid for 5 years) and key are generated in `certs/` on first start and
  the log shows the certificate's SHA-256 fingerprint. Existing files are never replaced, so you can
  also supply your own (e.g. CA-issued) certificate; the application URI is then taken from it.
  To renew a generated certificate, delete both files and restart. `certs/` is ignored by git and
  by the Docker build.
- **Trust on the server:** the OPC UA server must trust the client certificate, unless it is
  configured not to validate clients. When it rejects the certificate, the log names the file to
  add to the server's trusted certificates. For a B&R PLC in Automation Studio:
  1. Add `certs/client_cert.der` to the Configuration View under
     *AccessAndSecurity > CertificateStore > ThirdPartyCertificates* (Object Catalog → existing file).
  2. Under *AccessAndSecurity > TransportLayerSecurity*, open the SSL configuration of type
     *OPC UA SSL configuration* that the OPC UA server uses (or add one), enable
     *Validate SSL communication partner* and select the certificate under *Trusted certificates*.
  3. In the OPC UA server's security settings, select that SSL configuration as
     *CertificateStore configuration*, then transfer the project.
- **Server certificate:** by default the certificate the server presents is accepted and its
  SHA-256 fingerprint is logged, which encrypts the connection but does not prove the server's
  identity. Set `OPCUA_SERVER_CERT` to the server's certificate file to accept only that server.
- **Passwords** in the username token are encrypted with the server certificate, including an
  empty password (B&R rejects an unencrypted empty password with `BadIdentityTokenInvalid`).

With policy `None` there is no encryption; depending on the server the password may then be sent in
plain text (asyncua logs `Sending plain-text password`). Only use that on trusted networks.

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

The compose file mounts `./certs` into the container, so it uses the same client certificate as
a local run, and the OPC UA server only has to trust it once. On Linux, make sure `certs/` is
writable for the container user (uid 10001) if the certificate is to be generated there.

### Reaching the OPC UA server from the container

- OPC UA server on the Docker host: `OPCUA_SERVER_URL=opc.tcp://host.docker.internal:4840`
  (works on Docker Desktop; the compose file also maps it on Linux).
- PLC or server on the LAN: use its IP address or DNS name as usual.

## Development

```bash
uv run pytest
```

The tests start in-process asyncua servers: plain, requiring a username and password, and
encrypted-only (like a B&R PLC).

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
