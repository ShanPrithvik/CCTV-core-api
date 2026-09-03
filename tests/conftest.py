import pytest


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-which-is-long-enough")
    monkeypatch.setenv("DB_ENGINE", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AUTO_CREATE_TABLES", "true")
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("HEADLESS", "true")
    monkeypatch.setenv("AUTH_RATE_LIMIT", "1000")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:9/0")
    monkeypatch.setattr("src.services.rate_limit.allow", lambda *args, **kwargs: True)

    from src.init import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
