"""Release cloud database sockets while waiting on external services."""
from django.db import connections, OperationalError, InterfaceError


def release_connections():
    # TestCase and explicit transactions must retain their transaction connection.
    for connection in connections.all():
        if not connection.in_atomic_block:
            connection.close()


def database_retry(operation):
    """Retry SQL only; callers must never place provider calls in this closure."""
    for attempt in range(2):
        try:
            return operation()
        except (OperationalError, InterfaceError):
            if attempt or any(connection.in_atomic_block for connection in connections.all()):
                raise
            release_connections()
