from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def session_scope() -> Iterator[None]:
    yield
