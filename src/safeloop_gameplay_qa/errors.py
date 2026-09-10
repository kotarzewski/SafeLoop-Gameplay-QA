class SafeLoopError(Exception):
    """Base error for SafeLoop."""


class PolicyError(SafeLoopError):
    """Raised when an operation violates the workspace policy."""


class RuntimeBlockedError(SafeLoopError):
    """Raised when engine/runtime execution is not allowed."""


class AdapterError(SafeLoopError):
    """Raised when an engine adapter cannot perform an operation."""
