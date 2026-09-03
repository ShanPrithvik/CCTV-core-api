from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_env_example_defines_redis_password():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "REDIS_PASSWORD=" in text


def test_compose_env_file_is_optional():
    """CI has no committed .env; Compose must not require one to parse."""
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "path: .env" in text
    assert "required: false" in text
    assert text.count("required: false") >= 2
