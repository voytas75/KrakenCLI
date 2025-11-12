"""
Logging configuration for Kraken CLI.

Updates: v0.9.2 - 2025-11-12 - Harden console logging for limited encodings.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


class EncodingSafeStreamHandler(logging.StreamHandler):
    """Stream handler that tolerates consoles without full Unicode support."""

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        stream = self.stream
        if stream is None:
            return

        msg = self.format(record)

        try:
            stream.write(msg + self.terminator)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "utf-8"
            safe_message = msg.encode(encoding, errors="replace").decode(encoding, errors="replace")
            try:
                stream.write(safe_message + self.terminator)
            except Exception:
                self.handleError(record)
                return
        except Exception:
            self.handleError(record)
            return

        self.flush()


def setup_logging(log_level: str = "INFO",
                  log_file: str = "kraken_cli.log",
                  max_bytes: int = 10 * 1024 * 1024,  # 10MB
                  backup_count: int = 5) -> None:
    """Setup logging configuration and ensure safe Unicode output."""

    normalized_level = log_level.upper() if isinstance(log_level, str) else "INFO"
    if normalized_level not in logging._nameToLevel:
        normalized_level = "INFO"
    
    # Create logs directory if it doesn't exist
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(logging._nameToLevel[normalized_level])
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_dir / log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Console handler
    console_handler: logging.Handler = EncodingSafeStreamHandler(sys.stdout)
    console_handler.setLevel(logging._nameToLevel[normalized_level])
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Set third-party loggers to WARNING to reduce noise
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
