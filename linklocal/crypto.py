import base64
import hashlib
import hmac
from typing import Dict, Tuple

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .config import get_keys_dir
from .utils import safety_number


def _private_key_path():
    return get_keys_dir() / "private_key.pem"


def _public_key_path():
    return get_keys_dir() / "public_key.pem"


def generate_keypair() -> Tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    keys_dir = get_keys_dir()
    private_key_path = _private_key_path()
    public_key_path = _public_key_path()
    keys_dir.mkdir(parents=True, exist_ok=True)
    if private_key_path.exists() and public_key_path.exists():
        return load_keypair()

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_key_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key, public_key


def load_keypair() -> Tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    private_key_path = _private_key_path()
    public_key_path = _public_key_path()
    if not private_key_path.exists() or not public_key_path.exists():
        return generate_keypair()

    private_key = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=None,
    )
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    return private_key, public_key


def encrypt_message(plaintext: str, recipient_public_key) -> Dict[str, str]:
    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)
    encrypted_body = fernet.encrypt(plaintext.encode("utf-8"))
    encrypted_key = recipient_public_key.encrypt(
        fernet_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    signature = hmac.new(fernet_key, plaintext.encode("utf-8"), hashlib.sha256).digest()
    return {
        "encrypted_key": base64.b64encode(encrypted_key).decode("ascii"),
        "encrypted_body": base64.b64encode(encrypted_body).decode("ascii"),
        "body_hmac": base64.b64encode(signature).decode("ascii"),
    }


def decrypt_message(encrypted_key: str, encrypted_body: str, private_key, body_hmac: str = "") -> str:
    fernet_key = private_key.decrypt(
        base64.b64decode(encrypted_key.encode("ascii")),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    fernet = Fernet(fernet_key)
    try:
        plaintext = fernet.decrypt(base64.b64decode(encrypted_body.encode("ascii")))
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt message body") from exc
    if body_hmac:
        expected = hmac.new(fernet_key, plaintext, hashlib.sha256).digest()
        provided = base64.b64decode(body_hmac.encode("ascii"))
        if not hmac.compare_digest(expected, provided):
            raise ValueError("Message integrity verification failed")
    return plaintext.decode("utf-8")


def export_public_key_pem(public_key) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def load_public_key_from_pem(pem: str):
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def public_key_fingerprint(public_key) -> str:
    pem = export_public_key_pem(public_key)
    digest = hashlib.sha256(pem.encode("utf-8")).hexdigest()
    return digest


def peer_verification_code(our_public_key, their_public_key) -> str:
    return safety_number([public_key_fingerprint(our_public_key), public_key_fingerprint(their_public_key)])
