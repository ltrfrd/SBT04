from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_driver_pin(pin: str) -> str:
    return pwd_context.hash(pin)

