"""T-01 get_db lifecycle and T-02 CORS hardening.

The coder's ``TestDependencyOverride::test_get_db_is_overridable`` proves the
override is *installed*. It does not prove the real ``get_db`` closes its
session, and closes it even when the handler raises — which is the whole reason
the manual ``try/finally`` blocks were removed. Nor is CORS tested at all.
"""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.deps import get_db
from app.main import app as main_app


# --------------------------------------------------------------------------
# get_db
# --------------------------------------------------------------------------


class _TrackingSession:
    """Stand-in for a SQLAlchemy Session that records its own closure."""

    def __init__(self, log):
        self._log = log
        self.closed = False

    def close(self):
        self.closed = True
        self._log.append(self)


class TestGetDbLifecycle:
    @pytest.fixture()
    def tracked(self, monkeypatch):
        """Point the real get_db at a tracking session factory."""
        created = []

        def _factory():
            session = _TrackingSession(created)
            return session

        monkeypatch.setattr("app.deps.SessionLocal", _factory)
        return created

    def test_session_is_closed_on_success(self, tracked):
        generator = get_db()
        session = next(generator)
        assert session.closed is False
        with pytest.raises(StopIteration):
            next(generator)
        assert session.closed is True

    def test_session_is_closed_when_the_consumer_raises(self, tracked):
        """The finally block must run even on an exception path."""
        generator = get_db()
        session = next(generator)
        with pytest.raises(RuntimeError):
            generator.throw(RuntimeError("handler exploded"))
        assert session.closed is True, "session leaked on the exception path"

    def test_session_is_closed_when_the_consumer_abandons_the_generator(self, tracked):
        generator = get_db()
        session = next(generator)
        generator.close()
        assert session.closed is True

    def test_each_call_yields_a_distinct_session(self, tracked):
        first_gen, second_gen = get_db(), get_db()
        first, second = next(first_gen), next(second_gen)
        assert first is not second
        first_gen.close()
        second_gen.close()


class TestGetDbInsideFastAPI:
    """Exercise get_db through a real request lifecycle on a throwaway app."""

    @pytest.fixture()
    def probe_app(self, monkeypatch):
        closed = []

        class _Session:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True
                closed.append(self)

        monkeypatch.setattr("app.deps.SessionLocal", _Session)

        app = FastAPI()

        @app.get("/ok")
        def ok(db: Session = Depends(get_db)):
            return {"closed_so_far": len(closed)}

        @app.get("/boom")
        def boom(db: Session = Depends(get_db)):
            raise RuntimeError("handler exploded")

        @app.get("/http-error")
        def http_error(db: Session = Depends(get_db)):
            raise HTTPException(status_code=418, detail="teapot")

        return app, closed

    def test_session_closed_after_successful_request(self, probe_app):
        app, closed = probe_app
        with TestClient(app) as client:
            assert client.get("/ok").status_code == 200
        assert len(closed) == 1
        assert closed[0].closed is True

    def test_session_closed_after_unhandled_exception(self, probe_app):
        """A failing request must still close its session (no pool leak)."""
        app, closed = probe_app
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/boom").status_code == 500
        assert len(closed) == 1, "session was not closed on the 500 path"
        assert closed[0].closed is True

    def test_session_closed_after_http_exception(self, probe_app):
        app, closed = probe_app
        with TestClient(app) as client:
            assert client.get("/http-error").status_code == 418
        assert len(closed) == 1
        assert closed[0].closed is True

    def test_sessions_are_not_shared_across_requests(self, probe_app):
        app, closed = probe_app
        with TestClient(app) as client:
            client.get("/ok")
            client.get("/ok")
        assert len(closed) == 2
        assert closed[0] is not closed[1]


class TestDependencyOverrideIsolation:
    def test_override_is_removed_after_the_fixture_tears_down(self, client):
        """The client fixture must not leak its override into other tests."""
        assert get_db in main_app.dependency_overrides

    def test_real_get_db_is_restored_between_tests(self):
        """Runs without the client fixture — the override must be gone."""
        assert get_db not in main_app.dependency_overrides

    def test_failing_request_does_not_poison_the_overridden_session(
        self, client, db_session
    ):
        """A 400 must leave the session usable for the next request."""
        assert client.post("/api/settings", json={"secret.x": "bad"}).status_code == 400
        assert client.post("/api/settings", json={"good": "value"}).status_code == 200
        assert client.get("/api/settings").json()["good"] == "value"


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------


def _cors_middleware_kwargs():
    for middleware in main_app.user_middleware:
        if middleware.cls.__name__ == "CORSMiddleware":
            return dict(middleware.kwargs)
    raise AssertionError("CORSMiddleware is not installed on the app")


class TestCorsConfiguration:
    def test_cors_middleware_is_installed(self):
        assert _cors_middleware_kwargs()

    def test_wildcard_is_never_paired_with_credentials(self):
        """The exact invalid combination T-02 was raised to remove."""
        kwargs = _cors_middleware_kwargs()
        if kwargs.get("allow_credentials") is True:
            assert "*" not in kwargs.get("allow_origins", []), (
                "allow_credentials=True paired with a wildcard origin"
            )

    def test_default_origin_is_localhost_3000_only(self):
        assert _cors_middleware_kwargs()["allow_origins"] == ["http://localhost:3000"]

    def test_credentials_are_still_enabled(self):
        """Hardening must not silently disable credentialed requests."""
        assert _cors_middleware_kwargs()["allow_credentials"] is True

    def test_disallowed_origin_gets_no_allow_origin_header(self, client):
        res = client.get("/", headers={"Origin": "http://evil.example"})
        assert res.status_code == 200
        assert "access-control-allow-origin" not in {
            key.lower() for key in res.headers
        }, "a non-allowlisted origin was granted CORS access"

    def test_allowed_origin_is_echoed_exactly_not_as_wildcard(self, client):
        res = client.get("/", headers={"Origin": "http://localhost:3000"})
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert res.headers["access-control-allow-origin"] != "*"

    def test_preflight_from_disallowed_origin_is_not_approved(self, client):
        res = client.options(
            "/api/settings",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert res.headers.get("access-control-allow-origin") != "http://evil.example"

    def test_preflight_from_allowed_origin_is_approved(self, client):
        res = client.options(
            "/api/settings",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert res.status_code == 200
        assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


class TestCorsOriginsParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("http://localhost:3000", ["http://localhost:3000"]),
            ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
            ("http://a.test, http://b.test ", ["http://a.test", "http://b.test"]),
            ("http://a.test,,http://b.test", ["http://a.test", "http://b.test"]),
            ("http://a.test,", ["http://a.test"]),
            ("  ", []),
            ("", []),
        ],
    )
    def test_comma_separated_parsing(self, monkeypatch, raw, expected):
        monkeypatch.setenv("CORS_ORIGINS", raw)
        assert Settings().CORS_ORIGINS_LIST == expected

    def test_env_var_overrides_the_default(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
        assert Settings().CORS_ORIGINS_LIST == ["https://app.example.com"]

    def test_wildcard_in_env_is_still_parsed_through(self, monkeypatch):
        """Documents a real gap: nothing rejects CORS_ORIGINS='*'.

        The hardcoded wildcard is gone, but an operator can reintroduce the
        insecure combination purely through configuration. See the tester
        summary — this is a finding, not an endorsement.
        """
        monkeypatch.setenv("CORS_ORIGINS", "*")
        assert Settings().CORS_ORIGINS_LIST == ["*"]
