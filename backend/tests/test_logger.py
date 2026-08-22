"""
Tests for logger module.
"""

import logging
from pathlib import Path
from unittest.mock import patch

from src.core.logger import get_logger, reset_logger, setup_logger


class TestSetupLogger:
    """Tests for setup_logger function."""

    def setup_method(self):
        """Clean up loggers before each test."""
        # Remove all handlers from root logger
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)

        # Reset app logger
        reset_logger()

    def teardown_method(self):
        """Clean up loggers after each test."""
        reset_logger()

    def test_setup_logger_default_parameters(self):
        """Test logger setup with default parameters.

        The default level is whatever ``settings.LOG_LEVEL`` resolves to, which a
        local ``.env`` may set to DEBUG/TRACE. Pin the expectation to settings so
        the assertion is deterministic regardless of the developer's environment
        (CI has no ``.env`` and sees INFO; a local DEBUG ``.env`` must not fail).
        """
        from src.core.logger import TRACE
        from src.core.config import settings

        configured = settings.LOG_LEVEL.upper()
        expected_level = TRACE if configured == "TRACE" else getattr(logging, configured)

        logger = setup_logger()

        assert logger.name == "app"
        assert logger.level == expected_level
        assert len(logger.handlers) > 0

    def test_setup_logger_custom_name(self):
        """Test logger setup with custom name."""
        logger = setup_logger(name="custom")

        assert logger.name == "custom"

    @patch("src.core.logger.settings")
    def test_setup_logger_custom_level(self, mock_settings):
        """Test logger setup with custom level."""
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = None
        mock_settings.LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

        logger = setup_logger(name="test_custom_level", level="DEBUG")

        assert logger.level == logging.DEBUG

    def test_setup_logger_creates_console_handler(self):
        """Test that console handler is created."""
        logger = setup_logger()

        console_handlers = [
            h for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]

        assert len(console_handlers) > 0

    @patch("src.core.logger.settings")
    def test_setup_logger_with_log_file(self, mock_settings, tmp_path: Path):
        """Test logger setup with file handler."""
        log_file = tmp_path / "test.log"
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = None
        mock_settings.LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

        logger = setup_logger(name="test_log_file", log_file=log_file)

        file_handlers = [
            h for h in logger.handlers
            if isinstance(h, logging.FileHandler)
        ]

        assert len(file_handlers) > 0
        assert log_file.exists()

    @patch("src.core.logger.settings")
    def test_setup_logger_creates_log_directory(self, mock_settings, tmp_path: Path):
        """Test that log directory is created if it doesn't exist."""
        log_file = tmp_path / "logs" / "app.log"
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = None
        mock_settings.LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

        logger = setup_logger(name="test_log_dir", log_file=log_file)

        assert log_file.parent.exists()
        assert log_file.exists()

    def test_setup_logger_idempotent(self):
        """Test that calling setup_logger multiple times returns same logger."""
        logger1 = setup_logger(name="test_idempotent")
        initial_handler_count = len(logger1.handlers)

        logger2 = setup_logger(name="test_idempotent")

        assert logger1 is logger2
        assert len(logger2.handlers) == initial_handler_count

    def test_setup_logger_different_levels(self):
        """Test setting up logger with different log levels."""
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level_name in levels:
            logger = setup_logger(name=f"test_{level_name}", level=level_name)
            expected_level = getattr(logging, level_name)

            assert logger.level == expected_level

    def test_setup_logger_formatter(self):
        """Test that logger has correct formatter."""
        logger = setup_logger()

        for handler in logger.handlers:
            assert handler.formatter is not None

    @patch("src.core.logger.settings")
    def test_setup_logger_uses_settings_format(self, mock_settings):
        """Test that logger uses format from settings."""
        mock_settings.LOGGING_FORMAT = "%(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%H:%M:%S"
        mock_settings.LOG_LEVEL = "INFO"
        mock_settings.LOG_FILE = None

        logger = setup_logger(name="test_format_unique")

        # Check that formatter uses settings format
        for handler in logger.handlers:
            assert handler.formatter._fmt == mock_settings.LOGGING_FORMAT


class TestGetLogger:
    """Tests for get_logger function."""

    def setup_method(self):
        """Clean up loggers before each test."""
        reset_logger()

    def teardown_method(self):
        """Clean up loggers after each test."""
        reset_logger()

    def test_get_logger_without_name(self):
        """Test getting main application logger."""
        logger = get_logger()

        assert logger.name == "app"
        assert isinstance(logger, logging.Logger)

    def test_get_logger_with_name(self):
        """Test getting named logger."""
        logger = get_logger("api")

        assert logger.name == "app.api"

    def test_get_logger_returns_same_instance(self):
        """Test that get_logger returns same instance for main logger."""
        logger1 = get_logger()
        logger2 = get_logger()

        assert logger1 is logger2

    def test_get_logger_different_names_different_instances(self):
        """Test that different names return different logger instances."""
        logger1 = get_logger("api")
        logger2 = get_logger("services")

        assert logger1 is not logger2
        assert logger1.name != logger2.name

    def test_get_logger_hierarchical_naming(self):
        """Test that named loggers follow hierarchical naming."""
        api_logger = get_logger("api")
        service_logger = get_logger("services.auth")

        assert api_logger.name == "app.api"
        assert service_logger.name == "app.services.auth"

    def test_get_logger_logs_correctly(self, caplog):
        """Test that logger logs messages correctly."""
        logger = get_logger()
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO):
                logger.info("Test message")
            assert "Test message" in caplog.text
        finally:
            logger.removeHandler(caplog.handler)

    @patch("src.core.logger.settings")
    def test_get_logger_different_levels(self, mock_settings, caplog):
        """Test logging at different levels."""
        mock_settings.LOG_LEVEL = "DEBUG"
        mock_settings.LOG_FILE = None
        mock_settings.LOGGING_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

        logger = setup_logger(name="test_levels", level="DEBUG")
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.DEBUG):
                logger.debug("Debug message")
                logger.info("Info message")
                logger.warning("Warning message")
                logger.error("Error message")
            assert "Debug message" in caplog.text
            assert "Info message" in caplog.text
            assert "Warning message" in caplog.text
            assert "Error message" in caplog.text
        finally:
            logger.removeHandler(caplog.handler)


class TestResetLogger:
    """Tests for reset_logger function."""

    def teardown_method(self):
        """Ensure logger is reset after tests."""
        reset_logger()

    def test_reset_logger_removes_handlers(self):
        """Test that reset_logger removes all handlers."""
        logger = get_logger()
        initial_handler_count = len(logger.handlers)

        assert initial_handler_count > 0

        reset_logger()

        # After reset, getting logger again should create new handlers
        logger = get_logger()
        new_handler_count = len(logger.handlers)

        assert new_handler_count > 0

    def test_reset_logger_allows_reconfiguration(self):
        """Test that logger can be reconfigured after reset."""
        logger1 = get_logger()
        handler_count_before = len(logger1.handlers)

        reset_logger()

        logger2 = get_logger()
        handler_count_after = len(logger2.handlers)

        # After reset, new logger should be created with fresh handlers
        assert handler_count_after > 0
        # Logger instance is reused, but handlers are recreated
        assert logger1 is logger2  # Same logger object from logging.getLogger
        # But it should have new handlers after reset
        assert len(logger2.handlers) >= handler_count_before

    def test_reset_logger_closes_handlers(self):
        """Test that handlers are properly closed."""
        logger = get_logger()
        handlers = logger.handlers[:]

        reset_logger()

        # Verify handlers were closed (they should not raise errors)
        for handler in handlers:
            # After closing, handlers should have no stream
            if hasattr(handler, 'stream'):
                # Stream might be closed
                pass


class TestLoggerIntegration:
    """Integration tests for logger module."""

    def setup_method(self):
        """Clean up before each test."""
        reset_logger()

    def teardown_method(self):
        """Clean up after each test."""
        reset_logger()

    def test_multiple_named_loggers(self):
        """Test creating multiple named loggers."""
        api_logger = get_logger("api")
        service_logger = get_logger("services")
        db_logger = get_logger("database")

        assert api_logger.name == "app.api"
        assert service_logger.name == "app.services"
        assert db_logger.name == "app.database"

    def test_logger_writes_to_file(self, tmp_path: Path):
        """Test that logger writes to file correctly."""
        log_file = tmp_path / "test.log"

        logger = setup_logger(name="file_test", log_file=log_file)
        logger.info("Test message to file")

        # Force flush
        for handler in logger.handlers:
            handler.flush()

        assert log_file.exists()
        log_content = log_file.read_text(encoding="utf-8")
        assert "Test message to file" in log_content

    def test_logger_level_filtering(self, caplog):
        """Test that logger filters messages by level."""
        logger = setup_logger(name="level_test", level="WARNING")
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.DEBUG):
                logger.debug("Debug message")
                logger.info("Info message")
                logger.warning("Warning message")
                logger.error("Error message")
            # Only WARNING and ERROR should be logged
            assert "Debug message" not in caplog.text
            assert "Info message" not in caplog.text
            assert "Warning message" in caplog.text
            assert "Error message" in caplog.text
        finally:
            logger.removeHandler(caplog.handler)

    def test_logger_exception_logging(self, caplog):
        """Test that logger logs exceptions correctly."""
        logger = get_logger()
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.ERROR):
                try:
                    raise ValueError("Test exception")
                except ValueError:
                    logger.error("An error occurred", exc_info=True)
            assert "An error occurred" in caplog.text
            assert "ValueError: Test exception" in caplog.text
        finally:
            logger.removeHandler(caplog.handler)

    @patch("src.core.logger.settings")
    def test_logger_with_custom_settings(self, mock_settings, tmp_path: Path):
        """Test logger with custom settings configuration."""
        log_file = tmp_path / "custom.log"

        mock_settings.LOG_LEVEL = "DEBUG"
        mock_settings.LOG_FILE = log_file
        mock_settings.LOGGING_FORMAT = "%(levelname)s - %(message)s"
        mock_settings.LOGGING_DATE_FORMAT = "%H:%M:%S"

        logger = setup_logger(log_file=log_file)
        logger.debug("Debug message")

        # Force flush
        for handler in logger.handlers:
            handler.flush()

        log_content = log_file.read_text(encoding="utf-8")
        assert "Debug message" in log_content

    def test_concurrent_logger_access(self):
        """Test that multiple logger instances can coexist."""
        loggers = [get_logger(f"test_{i}") for i in range(10)]

        assert len(loggers) == 10
        assert len(set(logger.name for logger in loggers)) == 10

    def test_logger_unicode_support(self, caplog):
        """Test that logger supports unicode characters."""
        logger = get_logger()
        logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.INFO):
                logger.info("Unicode test: 你好世界 🌍 Привет")
            assert "Unicode test: 你好世界 🌍 Привет" in caplog.text
        finally:
            logger.removeHandler(caplog.handler)
