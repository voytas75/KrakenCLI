"""Tests for the logging helpers."""

from __future__ import annotations

import io
import logging

from utils.logger import EncodingSafeStreamHandler, setup_logging


def test_setup_logging_attaches_handlers(tmp_path) -> None:
    log_file = "test_logging.log"
    setup_logging(log_level="debug", log_file=log_file, max_bytes=1024, backup_count=1)

    root = logging.getLogger()
    handler_types = {type(handler) for handler in root.handlers}
    assert any("RotatingFileHandler" in repr(handler) for handler in root.handlers)
    assert any(isinstance(handler, EncodingSafeStreamHandler) for handler in root.handlers)

    # Invalid log level should fall back to INFO without raising.
    setup_logging(log_level="invalid", log_file=log_file, max_bytes=1024, backup_count=1)


def test_encoding_safe_stream_handler_handles_unicode_errors() -> None:
    class _MockStream(io.StringIO):
        def write(self, __s: str) -> int:  # type: ignore[override]
            raise UnicodeEncodeError("ascii", "é", 0, 1, "invalid")

    handler = EncodingSafeStreamHandler(_MockStream())
    record = logging.LogRecord("test", logging.INFO, __file__, 0, "message", args=None, exc_info=None)

    # Should swallow error without raising.
    handler.emit(record)
