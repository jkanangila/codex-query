from cryptography.fernet import Fernet, InvalidToken


class SecretDecryptionError(Exception):
    """Ciphertext is corrupt or was produced with a different master key."""


class SecretCipher:
    """Thin Fernet wrapper that works on `str` and raises a typed error."""

    def __init__(self, key: str | bytes) -> None:
        self._fernet = Fernet(key)  # ValueError if not a valid Fernet key

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            msg = "Could not decrypt secret with the current master key"
            raise SecretDecryptionError(msg) from exc
