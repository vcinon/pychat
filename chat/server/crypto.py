"""Server crypto boundary.

The server intentionally treats message bodies as opaque ciphertext and does not
own decryption keys.
"""

def is_ciphertext(value: str) -> bool:
    return bool(value and isinstance(value, str))
