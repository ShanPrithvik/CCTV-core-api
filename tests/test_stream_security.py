from src.services.stream_security import mask_credentials, validate_stream_url


def test_mask_credentials_hides_password():
    masked = mask_credentials("rtsp://admin:supersecret@10.0.0.5:554/stream")
    assert "supersecret" not in masked
    assert "***:***@" in masked


def test_validate_rejects_http_scheme():
    try:
        validate_stream_url("http://evil.example/camera")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "scheme" in str(exc).lower() or "Unsupported" in str(exc)


def test_validate_accepts_rtsp(monkeypatch):
    monkeypatch.setenv("BLOCK_PRIVATE_STREAM_TARGETS", "false")
    assert validate_stream_url("rtsp://example.com:554/cam")
