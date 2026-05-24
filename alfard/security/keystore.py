"""Fernet-encrypted credential store with OS keyring / key-file fallback."""

from pathlib import Path

_SERVICE = "alfard"
_USERNAME = "env_encryption_key"


class KeystoreError(Exception):
    pass


def _fernet():
    try:
        from cryptography.fernet import Fernet, InvalidToken
        return Fernet, InvalidToken
    except ImportError:
        raise KeystoreError(
            "cryptography is not installed. Run: pip install 'cryptography>=42.0.0'"
        )


def _keyring():
    try:
        import keyring as _kr
        return _kr
    except ImportError:
        raise KeystoreError(
            "keyring is not installed. Run: pip install 'keyring>=25.0.0'"
        )


def _key_file(alfard_home: Path) -> Path:
    return alfard_home / ".key"


def _keyring_get() -> bytes | None:
    try:
        kr = _keyring()
        value = kr.get_password(_SERVICE, _USERNAME)
        return value.encode() if value else None
    except Exception:
        return None


def _keyring_set(key: bytes) -> bool:
    try:
        kr = _keyring()
        kr.set_password(_SERVICE, _USERNAME, key.decode())
        return True
    except Exception:
        return False


def _file_read(path: Path) -> bytes | None:
    if not path.exists():
        return None
    try:
        return path.read_bytes().strip()
    except OSError as exc:
        raise KeystoreError(f"Cannot read key file {path}: {exc}") from exc


def _file_write(path: Path, key: bytes) -> None:
    path.write_bytes(key)
    path.chmod(0o600)


def _secure_delete(path: Path) -> None:
    size = path.stat().st_size
    with path.open("wb") as f:
        f.write(b"\x00" * size)
    path.unlink()


def get_or_create_key(alfard_home: Path) -> bytes:
    """Return the Fernet encryption key, generating and persisting one if absent."""
    Fernet, _ = _fernet()
    key_file = _key_file(alfard_home)

    key = _keyring_get()
    if key:
        if key_file.exists():
            try:
                _secure_delete(key_file)
            except Exception:
                pass
        return key

    file_key = _file_read(key_file)
    if file_key:
        if _keyring_set(file_key):
            try:
                _secure_delete(key_file)
            except Exception:
                pass
        return file_key

    new_key = Fernet.generate_key()
    if not _keyring_set(new_key):
        alfard_home.mkdir(parents=True, exist_ok=True)
        _file_write(key_file, new_key)
    return new_key


def _to_dotenv(env_vars: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in env_vars.items()) + "\n"


def _from_dotenv(content: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def write_env_encrypted(alfard_home: Path, env_vars: dict[str, str], *, replace: bool = False) -> None:
    """Encrypt env_vars and write to ~/.alfard/.env.enc (chmod 600).

    By default merges with existing stored keys so partial updates don't
    wipe unrelated credentials. Pass replace=True to overwrite entirely.
    """
    Fernet, _ = _fernet()
    key = get_or_create_key(alfard_home)
    if not replace:
        try:
            existing = decrypt_env(alfard_home)
        except (KeystoreError, OSError):
            existing = {}
        env_vars = {**existing, **env_vars}
    ciphertext = Fernet(key).encrypt(_to_dotenv(env_vars).encode())
    enc_path = alfard_home / ".env.enc"
    enc_path.write_bytes(ciphertext)
    enc_path.chmod(0o600)


def decrypt_env(alfard_home: Path) -> dict[str, str]:
    """Decrypt ~/.alfard/.env.enc and return the key-value pairs."""
    Fernet, InvalidToken = _fernet()
    key = get_or_create_key(alfard_home)
    try:
        ciphertext = (alfard_home / ".env.enc").read_bytes()
        plaintext = Fernet(key).decrypt(ciphertext).decode()
        return _from_dotenv(plaintext)
    except InvalidToken as exc:
        raise KeystoreError(
            "Could not decrypt ~/.alfard/.env.enc — the key may have changed. "
            "Run 'alfard setup' to re-enter your API keys."
        ) from exc


def encrypt_env(alfard_home: Path) -> None:
    """Migrate plaintext ~/.alfard/.env to .env.enc, then securely delete .env."""
    plain_path = alfard_home / ".env"
    if not plain_path.exists():
        return
    env_vars = _from_dotenv(plain_path.read_text(encoding="utf-8"))
    write_env_encrypted(alfard_home, env_vars)
    _secure_delete(plain_path)


def using_keyring(alfard_home: Path) -> bool:
    """Return True if the encryption key is currently stored in the OS keyring."""
    return _keyring_get() is not None


def get_or_create_gog_password(alfard_home: Path | None = None) -> str:
    """Return a stable random password for gog's file keyring, generating one if absent."""
    import secrets
    if alfard_home is None:
        from alfard.paths import ALFARD_HOME
        alfard_home = ALFARD_HOME
    try:
        existing = decrypt_env(alfard_home)
        if "GOG_KEYRING_PASSWORD" in existing:
            return existing["GOG_KEYRING_PASSWORD"]
    except (KeystoreError, OSError):
        pass
    password = secrets.token_hex(32)
    write_env_encrypted(alfard_home, {"GOG_KEYRING_PASSWORD": password})
    return password
