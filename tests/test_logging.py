import logging

from rawkuma_bot.utils.logging_setup import RedactSecrets


def test_redacts_sensitive_values() -> None:
    record = logging.LogRecord("test", logging.ERROR, __file__, 1, "DISCORD_TOKEN=%s Bearer %s cookie=%s", (), None)
    record.args = ("secret-token", "secret-bearer", "secret-cookie")
    RedactSecrets().filter(record)
    message = record.getMessage()
    assert "secret-token" not in message
    assert "secret-bearer" not in message
    assert "secret-cookie" not in message
    assert "[REDACTED]" in message
