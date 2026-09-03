from src.init import db
from src.models.camera import Camera
from src.models.event import Alert, Event


def _register(client, email, org):
    response = client.post("/api/auth/register", json={
        "email": email,
        "name": email.split("@")[0],
        "password": "password1",
        "organization_name": org,
    })
    assert response.status_code == 201
    body = response.get_json()
    return body["token"], body["user"]["active_organization_id"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_alert(app, org_id, camera_name="Loading dock"):
    with app.app_context():
        camera = Camera(
            camera_name=camera_name,
            rtsp_url="rtsp://camera.example/stream",
            view="/camera-view/loading-dock.png",
            organization_id=org_id,
        )
        db.session.add(camera)
        db.session.flush()
        event = Event(
            organization_id=org_id,
            camera_id=camera.id,
            event_type="person_entered_restricted_zone",
            severity="HIGH",
            confidence=0.91,
            event_metadata={"zone": "Stockroom"},
        )
        db.session.add(event)
        db.session.flush()
        alert = Alert(organization_id=org_id, event_id=event.id)
        db.session.add(alert)
        db.session.commit()
        return camera.id, alert.id


def test_overview_returns_alerts_and_health(client, app, monkeypatch):
    token, org_id = _register(client, "operator@example.com", "Retail One")
    camera_id, alert_id = _seed_alert(app, org_id)
    monkeypatch.setattr(
        "src.controllers.operations_controller.get_latest_frame",
        lambda requested_id: b"jpeg" if requested_id == camera_id else None,
    )

    response = client.get("/api/operations/overview", headers=_headers(token))
    assert response.status_code == 200
    body = response.get_json()
    assert body["summary"] == {
        "new_alerts": 1,
        "active_cameras": 1,
        "online_cameras": 1,
        "attention_cameras": 0,
    }
    assert body["alerts"][0]["id"] == alert_id
    assert body["alerts"][0]["event"]["camera_name"] == "Loading dock"
    assert body["camera_health"][0]["status"] == "ONLINE"


def test_alert_can_be_acknowledged(client, app):
    token, org_id = _register(client, "ack@example.com", "Ack Org")
    _, alert_id = _seed_alert(app, org_id)

    response = client.patch(
        f"/api/alerts/{alert_id}",
        headers=_headers(token),
        json={"status": "ACKNOWLEDGED"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ACKNOWLEDGED"
    assert body["acknowledged_by"] is not None
    assert body["acknowledged_at"] is not None


def test_operations_are_tenant_scoped(client, app, monkeypatch):
    token_a, org_a = _register(client, "tenant-a@example.com", "Tenant A")
    token_b, _ = _register(client, "tenant-b@example.com", "Tenant B")
    _, alert_id = _seed_alert(app, org_a)
    monkeypatch.setattr(
        "src.controllers.operations_controller.get_latest_frame", lambda _camera_id: None
    )

    alerts = client.get("/api/alerts", headers=_headers(token_b))
    assert alerts.status_code == 200
    assert alerts.get_json() == []

    update = client.patch(
        f"/api/alerts/{alert_id}",
        headers=_headers(token_b),
        json={"status": "ACKNOWLEDGED"},
    )
    assert update.status_code == 404

    own = client.get("/api/alerts", headers=_headers(token_a))
    assert len(own.get_json()) == 1
