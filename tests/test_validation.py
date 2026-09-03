from src.utils.validation import is_safe_camera_name, snapshot_filename, is_valid_email, password_is_strong_enough


def test_snapshot_filename_strips_path_traversal():
    name = snapshot_filename("../../etc/passwd")
    assert ".." not in name
    assert "/" not in name
    assert name.endswith(".png")


def test_unsafe_camera_names_rejected():
    assert not is_safe_camera_name("../etc/passwd")
    assert not is_safe_camera_name("cam/../../x")
    assert is_safe_camera_name("Lobby Cam 1")


def test_email_and_password_rules():
    assert is_valid_email("user@example.com")
    assert not is_valid_email("not-an-email")
    assert password_is_strong_enough("password1")
    assert not password_is_strong_enough("short")
