"""Tests for DELETE /ingest/jobs/{job_id} endpoint."""
import pytest
from starlette.testclient import TestClient

from app.core.security import create_jwt
import app.main
import app.queue.status as status


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    jobs_db = tmp_path / "ingest_jobs.sqlite"
    users_db = tmp_path / "users.sqlite"
    monkeypatch.setattr("app.config.settings.INGEST_STATUS_DB_PATH", str(jobs_db))
    monkeypatch.setattr("app.config.settings.AUTH_DB_PATH", str(users_db))
    monkeypatch.setattr("app.config.settings.JWT_SECRET", "test-secret-key")

    status._conn = None
    status._initialized = False

    import app.db.users as users
    users._conn = None
    users._initialized = False
    users.create_user("User One", "u1@example.com", "hash1")
    users.create_user("User Two", "u2@example.com", "hash2")
    user1 = users.get_user_by_email("u1@example.com")
    user2 = users.get_user_by_email("u2@example.com")

    client = TestClient(app.main.app)
    return client, status, user1["id"], user2["id"]


def test_delete_job_unauthenticated(test_setup):
    client, _, _, _ = test_setup
    r = client.delete("/ingest/jobs/some-job")
    assert r.status_code == 401


def test_delete_job_not_found(test_setup):
    client, _, u1_id, _ = test_setup
    token = create_jwt(u1_id)
    r = client.delete(
        "/ingest/jobs/non-existent-job",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_delete_job_success(test_setup):
    client, status_mod, u1_id, _ = test_setup
    token = create_jwt(u1_id)
    status_mod.create_job("j100", u1_id, "/tmp/fake.pdf", "sha123")
    status_mod.set_state("j100", "COMPLETED", num_chunks=2)

    r = client.delete(
        "/ingest/jobs/j100",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204
    assert status_mod.get_job("j100") is None


def test_delete_job_wrong_user_cannot_delete(test_setup):
    client, status_mod, u1_id, u2_id = test_setup
    token = create_jwt(u2_id)
    status_mod.create_job("j200", u1_id, "/tmp/fake.pdf", "sha123")

    r = client.delete(
        "/ingest/jobs/j200",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    assert status_mod.get_job("j200") is not None
