"""End-to-end auth flow tests via TestClient (lifespan NOT started — no
Qdrant/Fireworks needed). Exercises register/login/me + 401 on protected
endpoints."""
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.AUTH_DB_PATH", str(tmp_path / "users.sqlite"))
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")
    # Reset the users-store singleton so it opens at the per-test tmp path.
    import app.db.users as users
    users._conn = None
    users._initialized = False
    from starlette.testclient import TestClient

    import app.main

    return TestClient(app.main.app)


def test_register_returns_token_and_user(client):
    r = client.post(
        "/auth/register",
        json={"name": "Alice", "email": "alice@example.com", "password": "password123"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert "token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["name"] == "Alice"


def test_register_duplicate_email_409(client):
    payload = {"name": "Alice", "email": "alice@example.com", "password": "password123"}
    client.post("/auth/register", json=payload)
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 409


def test_login_success(client):
    client.post(
        "/auth/register",
        json={"name": "Bob", "email": "bob@example.com", "password": "password123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "bob@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert "token" in r.json()


def test_login_wrong_password_401(client):
    client.post(
        "/auth/register",
        json={"name": "Bob", "email": "bob@example.com", "password": "password123"},
    )
    r = client.post(
        "/auth/login",
        json={"email": "bob@example.com", "password": "wrong-password"},
    )
    assert r.status_code == 401


def test_me_with_token(client):
    r = client.post(
        "/auth/register",
        json={"name": "Cy", "email": "cy@example.com", "password": "password123"},
    )
    token = r.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "cy@example.com"


def test_me_without_token_401(client):
    assert client.get("/auth/me").status_code == 401


def test_ask_without_token_401(client):
    assert client.post("/ask", json={"query": "hello"}).status_code == 401


def test_ingest_jobs_without_token_401(client):
    assert client.get("/ingest/jobs").status_code == 401
