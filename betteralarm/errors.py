"""Errors that surface to the user as messages, not tracebacks."""


class UserError(Exception):
    """Bad input or state the user can fix; printed to stderr with exit code 2."""
