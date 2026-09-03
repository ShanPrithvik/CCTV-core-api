from src.config.redis_config import get_redis_url


def test_injects_password_when_url_has_none(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("REDIS_PASSWORD", "s3cret/value")
    url = get_redis_url()
    assert "s3cret%2Fvalue" in url
    assert url.startswith("redis://:")
    assert url.endswith("localhost:6379/0")


def test_leaves_existing_url_password_alone(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:already@redis:6379/1")
    monkeypatch.setenv("REDIS_PASSWORD", "ignored")
    assert get_redis_url() == "redis://:already@redis:6379/1"


def test_url_without_password_env(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    assert get_redis_url() == "redis://localhost:6379/0"
