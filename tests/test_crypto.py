import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from linklocal import crypto
from linklocal.config import set_app_dir


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    set_app_dir(str(tmp_path / ".linklocal"))
    yield tmp_path
    set_app_dir(None)


def test_encrypt_then_decrypt_round_trip(isolated_home):
    private_key, public_key = crypto.generate_keypair()
    encrypted = crypto.encrypt_message("hello linklocal", public_key)
    decrypted = crypto.decrypt_message(
        encrypted["encrypted_key"],
        encrypted["encrypted_body"],
        private_key,
    )
    assert decrypted == "hello linklocal"


def test_wrong_private_key_raises(isolated_home):
    _, public_key = crypto.generate_keypair()
    encrypted = crypto.encrypt_message("secret", public_key)
    foreign_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(Exception):
        crypto.decrypt_message(
            encrypted["encrypted_key"],
            encrypted["encrypted_body"],
            foreign_private_key,
        )
