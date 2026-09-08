"""Unit tests are hermetic with respect to the developer's ``.env``.

``Settings`` reads the repository-root ``.env`` by design, which is right for the
running application and wrong for unit tests: a developer setting
``DEV_AUTH_ENABLED=true`` locally would otherwise change what the test suite
asserts, and a production-guard test would fail on their machine and pass in CI.

So env-file loading is switched off for every unit test. Explicit environment
variables still work — ``monkeypatch.setenv`` is how a test exercises them
deliberately.

Integration tests are deliberately *not* covered by this: they need the local
``DATABASE_URL`` to find the developer's PostgreSQL.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _settings_ignore_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
