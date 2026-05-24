from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from easy_social import create_app
from easy_social.auth import _CAPTCHA_CHARS, _CAPTCHA_LENGTH, _generate_captcha_text, _validate_captcha
from easy_social.extensions import db


# ---------------------------------------------------------------------------
# Fixtures: non-TESTING app so CAPTCHA validation is never bypassed
# ---------------------------------------------------------------------------

@pytest.fixture()
def captcha_app():
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(
            {
                "SECRET_KEY": "test",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "UPLOAD_FOLDER": str(Path(temp_dir) / "uploads"),
                "MEDIA_STORAGE_BACKEND": "local",
            }
        )
        with app.app_context():
            db.create_all()
        yield app


@pytest.fixture()
def captcha_client(captcha_app):
    return captcha_app.test_client()


# ===========================================================================
# Unit Tests
# ===========================================================================

pytestmark_unit = pytest.mark.unit


@pytest.mark.unit
def test_generate_captcha_text_has_correct_length():
    text = _generate_captcha_text()
    assert len(text) == _CAPTCHA_LENGTH


@pytest.mark.unit
def test_generate_captcha_text_uses_allowed_chars():
    for _ in range(20):
        text = _generate_captcha_text()
        assert all(c in _CAPTCHA_CHARS for c in text)


@pytest.mark.unit
def test_generate_captcha_text_is_random():
    results = {_generate_captcha_text() for _ in range(10)}
    # With 36^5 = 60 million possibilities, 10 calls producing all identical
    # values is astronomically unlikely.
    assert len(results) > 1


@pytest.mark.unit
def test_validate_captcha_correct_input(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        assert _validate_captcha("ABCDE") is True


@pytest.mark.unit
def test_validate_captcha_wrong_input(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        assert _validate_captcha("ZZZZZ") is False


@pytest.mark.unit
def test_validate_captcha_case_insensitive(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        assert _validate_captcha("abcde") is True


@pytest.mark.unit
def test_validate_captcha_strips_whitespace(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        assert _validate_captcha("  ABCDE  ") is True


@pytest.mark.unit
def test_validate_captcha_no_session_returns_false(captcha_app):
    with captcha_app.test_request_context("/"):
        assert _validate_captcha("ABCDE") is False


@pytest.mark.unit
def test_validate_captcha_clears_session_after_use(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        _validate_captcha("ABCDE")
        assert "captcha_text" not in session


@pytest.mark.unit
def test_validate_captcha_clears_session_even_on_failure(captcha_app):
    with captcha_app.test_request_context("/"):
        from flask import session
        session["captcha_text"] = "ABCDE"
        _validate_captcha("WRONG")
        assert "captcha_text" not in session


# ===========================================================================
# Integration Tests
# ===========================================================================


@pytest.mark.integration
def test_captcha_image_returns_png(captcha_client):
    response = captcha_client.get("/auth/captcha")
    assert response.status_code == 200
    assert response.content_type == "image/png"


@pytest.mark.integration
def test_captcha_image_is_non_empty(captcha_client):
    response = captcha_client.get("/auth/captcha")
    assert len(response.data) > 0


@pytest.mark.integration
def test_captcha_image_sets_session(captcha_client):
    captcha_client.get("/auth/captcha")
    with captcha_client.session_transaction() as sess:
        assert "captcha_text" in sess
        assert len(sess["captcha_text"]) == _CAPTCHA_LENGTH


@pytest.mark.integration
def test_register_page_contains_captcha_image(captcha_client):
    response = captcha_client.get("/auth/register")
    assert response.status_code == 200
    assert b"captcha-img" in response.data
    assert b"/auth/captcha" in response.data


@pytest.mark.integration
def test_register_with_valid_captcha_succeeds(captcha_client):
    with captcha_client.session_transaction() as sess:
        sess["captcha_text"] = "ABCDE"
    response = captcha_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "ABCDE",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Feed" in response.data


@pytest.mark.integration
def test_register_with_invalid_captcha_fails(captcha_client):
    with captcha_client.session_transaction() as sess:
        sess["captcha_text"] = "ABCDE"
    response = captcha_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "WRONG",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Incorrect CAPTCHA" in response.data


@pytest.mark.integration
def test_register_with_missing_captcha_fails(captcha_client):
    response = captcha_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Please enter the CAPTCHA" in response.data


@pytest.mark.integration
def test_captcha_is_single_use(captcha_client):
    """The same captcha answer cannot be reused for a second registration."""
    with captcha_client.session_transaction() as sess:
        sess["captcha_text"] = "ABCDE"

    # First registration consumes the captcha
    first_response = captcha_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "ABCDE",
        },
        follow_redirects=True,
    )
    assert b"Feed" in first_response.data

    # Log out alice so the register route is accessible again
    captcha_client.post("/auth/logout", follow_redirects=True)

    # Second attempt: captcha_text is gone from session → should fail
    response = captcha_client.post(
        "/auth/register",
        data={
            "username": "bob",
            "email": "bob@example.com",
            "password": "password",
            "captcha": "ABCDE",
        },
        follow_redirects=True,
    )
    assert b"Incorrect CAPTCHA" in response.data


@pytest.mark.integration
def test_register_captcha_case_insensitive(captcha_client):
    with captcha_client.session_transaction() as sess:
        sess["captcha_text"] = "ABCDE"
    response = captcha_client.post(
        "/auth/register",
        data={
            "username": "alice",
            "email": "alice@example.com",
            "password": "password",
            "captcha": "abcde",
        },
        follow_redirects=True,
    )
    assert b"Feed" in response.data
