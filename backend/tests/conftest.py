import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database
from app.database import Base
from app.llm import LLMError, configure_provider, reset_provider
from app.main import app  # importing main registers all models on Base.metadata


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_SessionLocal", testing_session)
    return TestClient(app)


class _OfflineProvider:
    def generate(self, prompt):
        raise LLMError("llm disabled in tests")


@pytest.fixture(autouse=True)
def _no_llm():
    configure_provider(_OfflineProvider())
    yield
    reset_provider()
