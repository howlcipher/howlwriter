import pytest

from howlwriter.linkedin.store import QueueStore
from tests.linkedin.helpers import FakeClock, make_service


@pytest.fixture
def store(tmp_path) -> QueueStore:
    queue_store = QueueStore(tmp_path / "repo")
    queue_store.initialize()
    return queue_store


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(store, clock):
    return make_service(store, clock)
