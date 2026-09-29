import pytest
from pydantic import ValidationError

from config import Settings

ENV_VARS = [
    "OPCUA_SERVER_URL",
    "OPCUA_USERNAME",
    "OPCUA_PASSWORD",
    "OPCUA_TIMEOUT",
    "MCP_TRANSPORT",
    "MCP_ALLOWED_HOSTS",
    "LOG_LEVEL",
    "OPCUA_SECURITY_POLICY",
    "OPCUA_SECURITY_MODE",
    "OPCUA_CLIENT_CERT",
    "OPCUA_CLIENT_KEY",
    "OPCUA_SERVER_CERT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"

    def write(content: str):
        path.write_text(content, encoding="utf-8")
        return path

    return write


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.opcua_server_url == ["opc.tcp://localhost:4840"]
    assert settings.opcua_username is None
    assert settings.opcua_password is None
    assert settings.mcp_transport == "stdio"
    assert settings.mcp_allowed_hosts == []


def test_reads_env_file(env_file):
    path = env_file(
        "OPCUA_SERVER_URL=opc.tcp://192.168.0.10:4840\n"
        "OPCUA_USERNAME=operator\n"
        "OPCUA_PASSWORD=s3cret!\n"
        "OPCUA_TIMEOUT=10\n"
        "MCP_TRANSPORT=streamable-http\n"
        "MCP_ALLOWED_HOSTS=localhost:*, 127.0.0.1:*\n"
        "LOG_LEVEL=debug\n"
    )
    settings = Settings(_env_file=path)
    assert settings.opcua_server_url == ["opc.tcp://192.168.0.10:4840"]
    assert settings.opcua_username == "operator"
    assert settings.opcua_password.get_secret_value() == "s3cret!"
    assert settings.opcua_timeout == 10.0
    assert settings.mcp_transport == "streamable-http"
    assert settings.mcp_allowed_hosts == ["localhost:*", "127.0.0.1:*"]
    assert settings.log_level == "DEBUG"


def test_environment_overrides_env_file(env_file, monkeypatch):
    path = env_file("OPCUA_SERVER_URL=opc.tcp://from-file:4840\n")
    monkeypatch.setenv("OPCUA_SERVER_URL", "opc.tcp://from-env:4840")
    assert Settings(_env_file=path).opcua_server_url == ["opc.tcp://from-env:4840"]


def test_empty_credentials_mean_anonymous(env_file):
    settings = Settings(_env_file=env_file("OPCUA_USERNAME=\nOPCUA_PASSWORD=\n"))
    assert settings.opcua_username is None
    assert settings.opcua_password is None


def test_username_without_password_means_empty_password(env_file):
    # B&R: the user "Anonymous" without a password
    settings = Settings(_env_file=env_file("OPCUA_USERNAME=Anonymous\nOPCUA_PASSWORD=\n"))
    assert settings.opcua_username == "Anonymous"
    assert settings.opcua_password is None


def test_password_requires_username(env_file):
    with pytest.raises(ValidationError, match="OPCUA_PASSWORD is set but OPCUA_USERNAME is not"):
        Settings(_env_file=env_file("OPCUA_PASSWORD=s3cret!\n"))


def test_password_is_not_shown(env_file):
    settings = Settings(_env_file=env_file("OPCUA_USERNAME=operator\nOPCUA_PASSWORD=s3cret!\n"))
    assert "s3cret!" not in repr(settings)
    assert "s3cret!" not in str(settings.model_dump())


def test_rejects_unknown_transport():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, mcp_transport="websocket")


def test_server_url_list_keeps_order(env_file):
    path = env_file("OPCUA_SERVER_URL=opc.tcp://localhost:4840, opc.tcp://192.168.0.10:4840\n")
    assert Settings(_env_file=path).opcua_server_url == ["opc.tcp://localhost:4840", "opc.tcp://192.168.0.10:4840"]


def test_server_url_must_not_be_empty(env_file):
    with pytest.raises(ValidationError, match="at least one endpoint URL"):
        Settings(_env_file=env_file("OPCUA_SERVER_URL=\n"))


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Aes128_Sha256_RsaOaep", "Aes128_Sha256_RsaOaep"),
        ("aes128sha256rsaoaep", "Aes128_Sha256_RsaOaep"),
        ("basic256sha256", "Basic256Sha256"),
        ("none", "None"),
    ],
)
def test_security_policy_spellings(value, expected):
    assert Settings(_env_file=None, opcua_security_policy=value).opcua_security_policy == expected


def test_rejects_unknown_security_policy():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, opcua_security_policy="Basic128Rsa15")


def test_certificate_paths_are_relative_to_project(env_file):
    from config import PROJECT_DIR

    settings = Settings(_env_file=env_file("OPCUA_CLIENT_CERT=certs/mine.der\nOPCUA_SERVER_CERT=\n"))
    assert settings.opcua_client_cert == PROJECT_DIR / "certs" / "mine.der"
    assert settings.opcua_client_key == PROJECT_DIR / "certs" / "client_key.pem"
    assert settings.opcua_server_cert is None
