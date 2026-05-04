from __future__ import annotations

import hmac
import os
import tempfile
import unittest
from pathlib import Path

from backend.core import encryption


class EncryptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_key_path = os.environ.get("LOCAL_ENCRYPTION_KEY_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["LOCAL_ENCRYPTION_KEY_PATH"] = str(Path(self._tmpdir.name) / "model_config.key")

    def tearDown(self) -> None:
        if self._old_key_path is None:
            os.environ.pop("LOCAL_ENCRYPTION_KEY_PATH", None)
        else:
            os.environ["LOCAL_ENCRYPTION_KEY_PATH"] = self._old_key_path
        self._tmpdir.cleanup()

    def test_encrypt_string_writes_v2_and_round_trips(self) -> None:
        token = encryption.encrypt_string("secret-value")

        self.assertTrue(token.startswith("enc:v2:"))
        self.assertTrue(encryption.is_encrypted_string(token))
        self.assertEqual(encryption.decrypt_string(token), "secret-value")

    def test_decrypt_string_rejects_tampered_v2_payload(self) -> None:
        token = encryption.encrypt_string("secret-value")
        replacement = "A" if token[-1] != "A" else "B"

        self.assertEqual(encryption.decrypt_string(token[:-1] + replacement), "")

    def test_decrypt_string_keeps_v1_compatibility(self) -> None:
        plaintext = "legacy-secret"
        salt = b"\x01" * encryption._SALT_BYTES
        nonce = b"\x02" * encryption._V1_NONCE_BYTES
        key = encryption._derive_v1_key(salt)
        stream = encryption._legacy_keystream(key, nonce, len(plaintext.encode("utf-8")))
        ciphertext = bytes(a ^ b for a, b in zip(plaintext.encode("utf-8"), stream))
        tag = hmac.new(key, b"v1" + salt + nonce + ciphertext, encryption.hashlib.sha256).digest()
        token = encryption._ENC_V1_PREFIX + encryption._b64_encode(salt + nonce + ciphertext + tag)

        self.assertTrue(encryption.is_encrypted_string(token))
        self.assertEqual(encryption.decrypt_string(token), plaintext)


if __name__ == "__main__":
    unittest.main()
