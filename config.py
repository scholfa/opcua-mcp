"""Server configuration, read from environment variables and an optional .env file.

Real environment variables take precedence over values in the .env file, so a
container or MCP client config can override single settings.
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The .env next to this file, not in the working directory: MCP clients often
# start the server from an unrelated directory. OPCUA_MCP_ENV_FILE overrides it.
ENV_FILE = Path(os.getenv("OPCUA_MCP_ENV_FILE", Path(__file__).parent / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # OPC UA connection
    opcua_server_url: str = "opc.tcp://localhost:4840"
    opcua_username: str | None = None
    opcua_password: SecretStr | None = None
    opcua_timeout: float = 4.0
    opcua_auto_reconnect: bool = True

    # Reserved for certificate-based security, not implemented yet:
    # OPCUA_SECURITY_POLICY, OPCUA_SECURITY_MODE, OPCUA_CLIENT_CERT,
    # OPCUA_CLIENT_KEY, OPCUA_SERVER_CERT

    # MCP transport
    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    # Comma-separated Host header values accepted over HTTP, e.g. "localhost:*,127.0.0.1:*".
    # Empty keeps the SDK default: protection on for a loopback host, off otherwise.
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = []

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("opcua_username", "opcua_password", mode="before")
    @classmethod
    def _empty_as_unset(cls, value):
        # An empty "OPCUA_USERNAME=" line in .env means "not set"
        return None if value == "" else value

    @field_validator("mcp_allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value):
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value):
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _username_and_password_together(self):
        if (self.opcua_username is None) != (self.opcua_password is None):
            raise ValueError("OPCUA_USERNAME and OPCUA_PASSWORD must be set together")
        return self
