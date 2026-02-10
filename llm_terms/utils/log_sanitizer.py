"""
Secure Logging Utilities
========================
Sanitizes sensitive information before logging to prevent PII/secrets exposure.
"""

import re
from typing import Any, Dict, List

# PII Patterns
PII_PATTERNS = {
    'email': (r'\b[\w.-]+@[\w.-]+\.\w+\b', '[EMAIL]'),
    'ssn': (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    'credit_card': (r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b', '[CREDIT_CARD]'),
    'phone': (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),
    'ip_address': (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]'),
    'api_key': (r'\b[A-Za-z0-9]{32,}\b', '[API_KEY]'),  # Long alphanumeric strings
}

# Sensitive keywords that indicate nearby PII
SENSITIVE_KEYWORDS = [
    'password', 'passwd', 'pwd', 'secret', 'token', 'api_key',
    'credit_card', 'ssn', 'social_security', 'phone', 'email',
    'address', 'private_key', 'access_token', 'auth'
]

class LogSanitizer:
    """Sanitizes log entries to remove sensitive information."""

    def __init__(self, max_length: int = 200, enable_pii_detection: bool = True):
        """
        Initialize the log sanitizer.

        Args:
            max_length: Maximum length of log messages (truncated after this)
            enable_pii_detection: Whether to detect and redact PII patterns
        """
        self.max_length = max_length
        self.enable_pii_detection = enable_pii_detection

    def sanitize(self, data: Any, context: str = "") -> str:
        """
        Sanitize data for safe logging.

        Args:
            data: The data to sanitize (string, dict, list, etc.)
            context: Optional context for better sanitization decisions

        Returns:
            Sanitized string safe for logging
        """
        # Convert to string if not already
        if not isinstance(data, str):
            try:
                sanitized = str(data)
            except Exception:
                sanitized = "<unrepresentable object>"
        else:
            sanitized = data

        # Apply sanitization
        if self.enable_pii_detection:
            sanitized = self._redact_pii(sanitized)

        # Truncate if too long
        if len(sanitized) > self.max_length:
            sanitized = sanitized[:self.max_length] + "..."

        return sanitized

    def _redact_pii(self, text: str) -> str:
        """Redact PII patterns from text."""
        redacted = text

        for pattern_name, (pattern, replacement) in PII_PATTERNS.items():
            redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)

        return redacted

    def sanitize_dict(self, data: Dict, sensitive_keys: List[str] = None) -> Dict:
        """
        Sanitize a dictionary by redacting sensitive values.

        Args:
            data: Dictionary to sanitize
            sensitive_keys: List of keys to always redact (defaults to common sensitive keys)

        Returns:
            New dictionary with sensitive values redacted
        """
        if sensitive_keys is None:
            sensitive_keys = [
                'password', 'passwd', 'pwd', 'secret', 'token', 'api_key',
                'api_key', 'access_token', 'auth_token', 'private_key',
                'credit_card', 'ssn', 'social_security', 'password_hash'
            ]

        sanitized = {}
        for key, value in data.items():
            # Check if key is sensitive
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_dict(value, sensitive_keys)
            elif isinstance(value, (list, tuple)):
                sanitized[key] = [
                    self.sanitize_dict(item, sensitive_keys) if isinstance(item, dict)
                    else self.sanitize(item)
                    for item in value
                ]
            elif isinstance(value, str):
                sanitized[key] = self.sanitize(value)
            else:
                sanitized[key] = value

        return sanitized

    def sanitize_log_message(self, message: str, **kwargs) -> str:
        """
        Sanitize a log message with named parameters.

        Args:
            message: Log message format string
            **kwargs: Parameters to format into the message

        Returns:
            Sanitized log message
        """
        # Sanitize all kwargs
        sanitized_kwargs = {
            k: self.sanitize(v) if not isinstance(v, (int, float, bool)) else v
            for k, v in kwargs.items()
        }

        # Format message
        try:
            formatted = message.format(**sanitized_kwargs)
        except (KeyError, ValueError):
            # Fallback if formatting fails
            formatted = message + " " + str(sanitized_kwargs)

        return self.sanitize(formatted)


# Global instance for easy import
default_sanitizer = LogSanitizer()


def sanitize_log(data: Any, max_length: int = 200) -> str:
    """
    Quick helper to sanitize data for logging.

    Args:
        data: Data to sanitize
        max_length: Maximum length (default 200)

    Returns:
        Sanitized string
    """
    return default_sanitizer.sanitize(data, max_length=max_length)


def sanitize_for_debug(data: Any) -> str:
    """
    Sanitize data for debug logging (more verbose).

    Args:
        data: Data to sanitize

    Returns:
        Sanitized string with longer max length
    """
    return default_sanitizer.sanitize(data, max_length=500)


# Example usage and testing
if __name__ == "__main__":
    sanitizer = LogSanitizer()

    # Test PII redaction
    test_data = {
        'user_email': 'test@example.com',
        'password': 'secret123',
        'api_key': 'REDACTED_API_KEY',
        'message': 'User test@example.com called from 555-123-4567',
        'normal_data': 'This is fine to log'
    }

    print("Original:")
    print(test_data)
    print("\nSanitized:")
    print(sanitizer.sanitize_dict(test_data))
