"""Phase 3 — JWT Auth integration tests.

Tests register, login, me, duplicate email, and wrong password.
Uses the test database via conftest.py's db_session fixture,
overriding the FastAPI dependency for get_db.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from tests.app_for_test import app
from src.database import get_db


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Override the get_db dependency with the test db_session."""

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_register(client):
    resp = await client.post(
        "/api/auth/register",
        json={
            "company_name": "TestCo",
            "username": "admin",
            "email": "admin@testco.com",
            "password": "securepass123",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "admin@testco.com"
    assert "id" in data["user"]
    assert "tenant_id" in data["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    # First registration
    resp = await client.post(
        "/api/auth/register",
        json={
            "company_name": "DupeCo",
            "username": "user1",
            "email": "dupe@test.com",
            "password": "secret123",
        },
    )
    assert resp.status_code == 201

    # Second with same email
    resp = await client.post(
        "/api/auth/register",
        json={
            "company_name": "DupeCo2",
            "username": "user2",
            "email": "dupe@test.com",
            "password": "secret456",
        },
    )
    assert resp.status_code == 409
    assert "Email already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login(client):
    # Register first
    await client.post(
        "/api/auth/register",
        json={
            "company_name": "LoginCo",
            "username": "loginuser",
            "email": "login@test.com",
            "password": "mypassword",
        },
    )

    # Login
    resp = await client.post(
        "/api/auth/login",
        json={"email": "login@test.com", "password": "mypassword"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "login@test.com"
    assert data["user"]["role"] == "admin"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    # Register first
    await client.post(
        "/api/auth/register",
        json={
            "company_name": "WrongPwCo",
            "username": "wrongpwuser",
            "email": "wrongpw@test.com",
            "password": "correctpass",
        },
    )

    # Wrong password
    resp = await client.post(
        "/api/auth/login",
        json={"email": "wrongpw@test.com", "password": "wrongpass"},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_me(client):
    # Register
    resp = await client.post(
        "/api/auth/register",
        json={
            "company_name": "MeCo",
            "username": "meuser",
            "email": "me@test.com",
            "password": "mypassword",
        },
    )
    token = resp.json()["token"]

    # Get /me
    resp = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "meuser"
    assert data["role"] == "admin"
    assert "id" in data
    assert "tenant_id" in data


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    """/me without token should return 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
