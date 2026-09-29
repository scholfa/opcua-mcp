"""Server configuration, read from environment variables and an optional .env file.

Real environment variables take precedence over values in the .env file, so a
container or MCP client config can override single settings.
"""

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_DIR = Path(__file__).parent

# The .env next to this file, not in the working directory: MCP clients often
# start the server from an unrelated directory. OPCUA_MCP_ENV_FILE overrides it.
ENV_FILE = Path(os.getenv("OPCUA_MCP_ENV_FILE", PROJECT_DIR / ".env"))

# Accepted spellings: the OPC UA names as servers list them (e.g. "Aes128_Sha256_RsaOaep"),
# with or without underscores, in any case
SECURITY_POLICIES = {
    name.replace("_", "").lower(): name
    for name in ("None", "Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss")
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # OPC UA connection
    # Comma-separated endpoint URLs, tried in order at startup; the first reachable one is used,
    # e.g. "opc.tcp://localhost:4840,opc.tcp://192.168.0.10:4840" (simulation first, then hardware)
    opcua_server_url: Annotated[list[str], NoDecode] = ["opc.tcp://localhost:4840"]
    # A username without a password logs in with an empty password
    opcua_username: str | None = None
    opcua_password: SecretStr | None = None
    opcua_timeout: float = 4.0
    opcua_auto_reconnect: bool = True

    # Certificate-based security. With a policy other than None, the client certificate and key
    # are generated on first start if neither file exists. Relative paths are resolved against
    # the directory of this file.
    opcua_security_policy: Literal["None", "Basic256Sha256", "Aes128_Sha256_RsaOaep", "Aes256_Sha256_RsaPss"] = "None"
    opcua_security_mode: Literal["Sign", "SignAndEncrypt"] = "SignAndEncrypt"
    opcua_client_cert: Path = Path("certs/client_cert.der")
    opcua_client_key: Path = Path("certs/client_key.pem")
    opcua_client_key_password: SecretStr | None = None
    # Pin the server certificate; without it the server's certificate is accepted as presented
    opcua_server_cert: Path | None = None
    # Default: the URI in the client certificate, or urn:opcua-mcp:client for a generated one
    opcua_application_uri: str | None = None
    # DNS name written into a generated certificate; fixed so that a container's changing
    # hostname never invalidates the certificate the server was told to trust
    opcua_client_hostname: str = "opcua-mcp"

    # MCP transport
    mcp_transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    # Comma-separated Host header values accepted over HTTP, e.g. "localhost:*,127.0.0.1:*".
    # Empty keeps the SDK default: protection on for a loopback host, off otherwise.
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = []

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator(
        "opcua_username",
        "opcua_password",
        "opcua_client_key_password",
        "opcua_server_cert",
        "opcua_application_uri",
        mode="before",
    )
    @classmethod
    def _empty_as_unset(cls, value):
        # An empty "OPCUA_USERNAME=" line in .env means "not set"
        return None if value == "" else value

    @field_validator("opcua_security_policy", mode="before")
    @classmethod
    def _normalize_policy(cls, value):
        if isinstance(value, str):
            return SECURITY_POLICIES.get(value.replace("_", "").replace("-", "").lower(), value)
        return value

    @field_validator("opcua_client_cert", "opcua_client_key", "opcua_server_cert")
    @classmethod
    def _resolve_path(cls, value):
        return value if value is None or value.is_absolute() else PROJECT_DIR / value

    @field_validator("opcua_server_url", "mcp_allowed_hosts", mode="before")
    @classmethod
    def _split_list(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("opcua_server_url")
    @classmethod
    def _at_least_one_url(cls, value):
        if not value:
            raise ValueError("OPCUA_SERVER_URL must contain at least one endpoint URL")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value):
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _password_needs_username(self):
        if self.opcua_password is not None and self.opcua_username is None:
            raise ValueError("OPCUA_PASSWORD is set but OPCUA_USERNAME is not")
        return self
