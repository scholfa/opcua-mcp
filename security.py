"""Certificate-based OPC UA security: client certificate handling and client setup."""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from asyncua import Client, ua
from asyncua.crypto import cert_gen, security_policies, uacrypto
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import ExtendedKeyUsageOID

from config import Settings

logger = logging.getLogger("opcua-mcp")

DEFAULT_APPLICATION_URI = "urn:opcua-mcp:client"
# Long enough that the OPC UA server does not need to be told to trust a new certificate every year
GENERATED_CERT_DAYS = 5 * 365

POLICY_CLASSES = {
    "Basic256Sha256": security_policies.SecurityPolicyBasic256Sha256,
    "Aes128_Sha256_RsaOaep": security_policies.SecurityPolicyAes128Sha256RsaOaep,
    "Aes256_Sha256_RsaPss": security_policies.SecurityPolicyAes256Sha256RsaPss,
}


class CertificateError(Exception):
    """The client certificate configuration cannot be used."""


class OpcUaClient(Client):
    """asyncua Client that also encrypts an empty password.

    asyncua only encrypts non-empty passwords. A server whose username token policy requires
    encryption (e.g. B&R, whose "Anonymous" user has no password) rejects the unencrypted
    empty token with BadIdentityTokenInvalid.
    """

    def _add_user_auth(self, params: ua.ActivateSessionParameters, username: str | None, password: str | None) -> None:
        super()._add_user_auth(params, username, password)
        policy_uri = self.server_policy(ua.UserTokenType.UserName).SecurityPolicyUri
        if password == "" and policy_uri and policy_uri != security_policies.SecurityPolicyNone.URI:
            data, uri = self._encrypt_password("", policy_uri)
            params.UserIdentityToken.Password = data
            params.UserIdentityToken.EncryptionAlgorithm = uri


@dataclass(frozen=True)
class ClientCertificate:
    cert_path: Path
    key_path: Path
    application_uri: str


def fingerprint(der: bytes) -> str:
    """SHA-256 fingerprint as colon-separated hex, the form most certificate views show."""
    return ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())


def _application_uris(cert: x509.Certificate) -> list[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return []
    return san.value.get_values_for_type(x509.UniformResourceIdentifier)


async def _generate(settings: Settings, application_uri: str) -> None:
    cert_path, key_path = settings.opcua_client_cert, settings.opcua_client_key
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = cert_gen.generate_private_key()
    cert = cert_gen.generate_self_signed_app_certificate(
        key,
        "opcua-mcp",
        {"organizationName": "opcua-mcp"},
        [x509.UniformResourceIdentifier(application_uri), x509.DNSName(settings.opcua_client_hostname)],
        extended=[ExtendedKeyUsageOID.CLIENT_AUTH],
        days=GENERATED_CERT_DAYS,
    )
    key_path.write_bytes(cert_gen.dump_private_key_as_pem(key))
    der = cert.public_bytes(Encoding.DER)
    cert_path.write_bytes(der)
    logger.warning(
        "Generated OPC UA client certificate %s (SHA-256 %s). The OPC UA server must trust it before "
        "a secure connection works.",
        cert_path,
        fingerprint(der),
    )


async def prepare_client_certificate(settings: Settings) -> ClientCertificate | None:
    """Return the client certificate to use, generating one if neither file exists.

    Returns None when the security policy is None. An existing certificate is never
    replaced, so a certificate the server already trusts (or one issued by a CA) stays.
    """
    if settings.opcua_security_policy == "None":
        return None
    cert_path, key_path = settings.opcua_client_cert, settings.opcua_client_key
    if not cert_path.exists() and not key_path.exists():
        await _generate(settings, settings.opcua_application_uri or DEFAULT_APPLICATION_URI)
    elif not cert_path.exists() or not key_path.exists():
        missing = cert_path if not cert_path.exists() else key_path
        raise CertificateError(
            f"{missing} is missing. Provide both OPCUA_CLIENT_CERT and OPCUA_CLIENT_KEY, "
            "or remove both to generate a new pair."
        )

    try:
        cert = await uacrypto.load_certificate(cert_path)
    except Exception as e:
        raise CertificateError(f"Cannot read client certificate {cert_path}: {e}") from e
    uris = _application_uris(cert)
    application_uri = settings.opcua_application_uri or (uris[0] if uris else DEFAULT_APPLICATION_URI)
    if application_uri not in uris:
        logger.warning(
            "Client certificate %s does not contain the application URI %s; most servers reject it.",
            cert_path,
            application_uri,
        )
    logger.info(
        "Using OPC UA client certificate %s (application URI %s, valid until %s, SHA-256 %s)",
        cert_path,
        application_uri,
        cert.not_valid_after_utc.date(),
        fingerprint(cert.public_bytes(Encoding.DER)),
    )
    return ClientCertificate(cert_path, key_path, application_uri)


async def apply_security(client: Client, settings: Settings, certificate: ClientCertificate) -> None:
    """Configure the security policy on a client. Contacts the server to fetch its certificate
    unless OPCUA_SERVER_CERT pins it."""
    client.application_uri = certificate.application_uri
    password = settings.opcua_client_key_password
    await client.set_security(
        POLICY_CLASSES[settings.opcua_security_policy],
        certificate.cert_path,
        certificate.key_path,
        private_key_password=password.get_secret_value() if password else None,
        server_certificate=str(settings.opcua_server_cert) if settings.opcua_server_cert else None,
        mode=getattr(ua.MessageSecurityMode, settings.opcua_security_mode),
    )


def server_certificate_fingerprint(client: Client) -> str | None:
    """Fingerprint of the certificate the connected server presented, if any."""
    peer = getattr(client.security_policy, "peer_certificate", None)
    return fingerprint(peer) if peer else None
