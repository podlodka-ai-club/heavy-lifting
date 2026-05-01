from __future__ import annotations

import secrets

from flask import Flask, Response, request

from backend.settings import Settings

AUTH_REALM = "heavy-lifting"
LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1"})


def register_basic_auth_guard(app: Flask, settings: Settings) -> None:
    @app.before_request
    def require_basic_auth() -> Response | None:
        username = settings.api_basic_auth_username
        password = settings.api_basic_auth_password
        if not username or not password:
            return None

        if request.remote_addr in LOCALHOST_ADDRESSES:
            return None

        auth = request.authorization
        if auth is not None and _credentials_match(
            actual_username=auth.username or "",
            actual_password=auth.password or "",
            expected_username=username,
            expected_password=password,
        ):
            return None

        return _unauthorized_response()


def _credentials_match(
    *,
    actual_username: str,
    actual_password: str,
    expected_username: str,
    expected_password: str,
) -> bool:
    username_matches = secrets.compare_digest(
        actual_username,
        expected_username,
    )
    password_matches = secrets.compare_digest(
        actual_password,
        expected_password,
    )
    return username_matches and password_matches


def _unauthorized_response() -> Response:
    response = Response(status=401)
    response.headers["WWW-Authenticate"] = f'Basic realm="{AUTH_REALM}"'
    return response


__all__ = ["register_basic_auth_guard"]
