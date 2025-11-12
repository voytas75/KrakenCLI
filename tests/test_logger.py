"""Tests for the custom logging helpers."""

from __future__ import annotations

import io
import logging
import unittest

from utils.logger import EncodingSafeStreamHandler


class LossyCP1250Stream(io.StringIO):
    """String stream that mimics a cp1250 console with strict encoding."""

    encoding = "cp1250"

    def write(self, s: str) -> int:  # type: ignore[override]
        if any(ord(char) > 255 for char in s):
            raise UnicodeEncodeError("cp1250", s, 0, len(s), "character maps to <undefined>")
        return super().write(s)


class TestEncodingSafeStreamHandler(unittest.TestCase):
    """Ensure the logging handler does not crash on emoji output."""

    def test_emit_replaces_unencodable_characters(self) -> None:
        stream = LossyCP1250Stream()
        handler = EncodingSafeStreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("krakencli.tests.logger")
        original_handlers = list(logger.handlers)
        original_level = logger.level
        original_propagate = logger.propagate

        try:
            for existing in original_handlers:
                logger.removeHandler(existing)

            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False

            logger.info("✅ trade executed")

            contents = stream.getvalue()
            self.assertIn("trade executed", contents)
            self.assertIn("?", contents)
        finally:
            logger.removeHandler(handler)
            handler.close()

            for existing in original_handlers:
                logger.addHandler(existing)

            logger.setLevel(original_level)
            logger.propagate = original_propagate


if __name__ == "__main__":
    unittest.main()
