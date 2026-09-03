from io import BytesIO


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def register_user(client, email, password="password1", org="Org One", name="User"):
    return client.post("/api/auth/register", json={
        "email": email,
        "name": name,
        "password": password,
        "organization_name": org,
    })


def test_register_and_login(client):
    res = register_user(client, "owner@example.com")
    assert res.status_code == 201
    body = res.get_json()
    assert body["token"]
    assert body["user"]["email"] == "owner@example.com"

    login = client.post("/api/auth/login", json={
        "email": "owner@example.com",
        "password": "password1",
    })
    assert login.status_code == 200
    assert login.get_json()["token"]


def test_weak_password_rejected(client):
    res = register_user(client, "weak@example.com", password="123")
    assert res.status_code == 400


def test_pending_email_cannot_register_new_org_without_invite(client, app):
    owner = register_user(client, "owner2@example.com", org="Secure Org")
    token = owner.get_json()["token"]
    org_id = owner.get_json()["user"]["active_organization_id"]

    invite = client.post(
        "/api/org/members",
        headers=auth_header(token),
        json={"email": "invited@example.com", "organization_id": org_id, "role": "Member"},
    )
    assert invite.status_code == 201

    takeover = client.post("/api/auth/register", json={
        "email": "invited@example.com",
        "name": "Attacker",
        "password": "password1",
        "organization_name": "Stolen Org",
    })
    assert takeover.status_code == 409


def test_tenant_isolation_for_cameras(client, monkeypatch):
    monkeypatch.setattr(
        "src.services.camera_service.capture_rtsp_screenshot",
        lambda url: BytesIO(b"fake-png"),
    )
    monkeypatch.setattr("src.services.camera_service.save_to_local_storage", lambda *a, **k: None)
    monkeypatch.setattr("src.services.camera_service.validate_stream_url", lambda url: url)

    a = register_user(client, "a@example.com", org="Org A", name="A")
    b = register_user(client, "b@example.com", org="Org B", name="B")
    token_a = a.get_json()["token"]
    token_b = b.get_json()["token"]

    created = client.post(
        "/api/camera",
        headers=auth_header(token_a),
        json={"cameraName": "Lobby", "rtsp": "rtsp://cam.example/stream"},
    )
    assert created.status_code == 201
    camera_id = created.get_json()["camera"]["id"]

    other = client.get(f"/api/camera/{camera_id}", headers=auth_header(token_b))
    assert other.status_code in (403, 404)

    listed = client.get("/api/camera", headers=auth_header(token_b))
    assert listed.status_code == 200
    assert listed.get_json() == []


def test_admin_cannot_invite_owner(client):
    owner = register_user(client, "boss@example.com", org="Role Org")
    token = owner.get_json()["token"]
    org_id = owner.get_json()["user"]["active_organization_id"]

    invite = client.post(
        "/api/org/members",
        headers=auth_header(token),
        json={"email": "admin@example.com", "organization_id": org_id, "role": "Admin"},
    )
    assert invite.status_code == 201
    invite_token = invite.get_json()["invite_token"]

    accepted = client.post("/api/auth/register", json={
        "email": "admin@example.com",
        "name": "Admin",
        "password": "password1",
        "invite_token": invite_token,
    })
    assert accepted.status_code == 201
    admin_token = accepted.get_json()["token"]

    escalate = client.post(
        "/api/org/members",
        headers=auth_header(admin_token),
        json={"email": "newowner@example.com", "organization_id": org_id, "role": "Owner"},
    )
    assert escalate.status_code == 403


def test_health_endpoints(client):
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert "error" not in (ready.get_json() or {})


def test_invite_list_does_not_return_tokens(client):
    owner = register_user(client, "lister@example.com", org="Invite Org")
    token = owner.get_json()["token"]
    org_id = owner.get_json()["user"]["active_organization_id"]
    client.post(
        "/api/org/members",
        headers=auth_header(token),
        json={"email": "pending@example.com", "organization_id": org_id, "role": "Member"},
    )
    listed = client.get(f"/api/org/invites?organization_id={org_id}", headers=auth_header(token))
    assert listed.status_code == 200
    for row in listed.get_json():
        assert "invite_token" not in row
