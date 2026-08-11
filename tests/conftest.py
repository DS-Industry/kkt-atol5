"""
Patch libfptr10.IFptr before cashierService/main import so tests never load the native driver.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Prevent APScheduler autostart when main is imported under pytest (F-Q-07)
os.environ.setdefault("DISABLE_SCHEDULER", "1")

import libfptr10
from tests.fake_fptr import build_fake_fptr_class

FakeIFptr = build_fake_fptr_class(libfptr10.IFptr)
libfptr10.IFptr = FakeIFptr

# Ensure project root imports resolve even if pytest.ini pythonpath is ignored
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Re-import / import cashierService against FakeIFptr (fresh if previously loaded)
if "cashierService" in sys.modules:
    importlib.reload(sys.modules["cashierService"])
else:
    import cashierService  # noqa: F401


@pytest.fixture
def fake_fptr_cls():
    return FakeIFptr


@pytest.fixture
def service(fake_fptr_cls):
    """Fresh CashierService with a controllable FakeIFptr instance."""
    from cashierService import CashierService

    svc = CashierService()
    assert isinstance(svc.fptr, fake_fptr_cls)
    return svc


@pytest.fixture
def flask_logger():
    """Minimal logger stand-in accepted by print_check (uses app.logger.*)."""
    import logging

    class _App:
        logger = logging.getLogger("test-print-check")

    if not _App.logger.handlers:
        _App.logger.addHandler(logging.NullHandler())
    return _App()


@pytest.fixture
def sample_check():
    return {
        "name": "Робот 1",
        "price": 100.50,
        "sum": 100.50,
        "quiantity": 1,
        "type": "1",
    }


def _rebind_sqlite(main, db_path: Path) -> None:
    """Point Flask-SQLAlchemy at a fresh SQLite file without touching production checks.db."""
    from sqlalchemy import create_engine

    uri = f"sqlite:///{db_path}"
    main.app.config["SQLALCHEMY_DATABASE_URI"] = uri
    main.app.config["TESTING"] = True
    main.db.session.remove()

    engines = main.db._app_engines.setdefault(main.app, {})
    for engine in list(engines.values()):
        engine.dispose()
    engines.clear()
    engines[None] = create_engine(uri)


@pytest.fixture
def app_db(tmp_path):
    """
    Import main against FakeIFptr, then rebind SQLAlchemy to a temp SQLite file
    so tests never touch production checks.db.
    """
    # main.open_connection / _ensure_schema run at import — FakeIFptr already installed
    if "main" in sys.modules:
        main = sys.modules["main"]
    else:
        import main  # noqa: F401

        main = sys.modules["main"]

    db_path = tmp_path / "phase_a_test.db"
    with main.app.app_context():
        _rebind_sqlite(main, db_path)
        main.db.create_all()
        # Ensure Phase B columns exist on fresh + rebound engines
        main._ensure_schema()
        yield main
        main.db.session.remove()
