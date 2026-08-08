"""Adversarial tests for the T-03 secret store — the plan's CRITICAL risk.

``test_secrets.py`` proves the happy path: store a key, ``GET /api/settings``
filters it. These tests attack the filter instead, and cover the failure modes
the coder's suite does not reach:

* ``secret.``-prefixed keys injected by every writable route, not just the one
  the filter was written for.
* Case, whitespace and unicode variants of the prefix.
* Master-key rotation and corrupted ciphertext.
* ``last4`` boundary behaviour on short secrets.
* Whether an undecryptable secret can still be *deleted* (otherwise a rotated
  key strands a row that ``configured:false`` claims does not exist).
"""

import pytest

from app.models import Configuration
from app.services import secrets as secret_store

PLAINTEXT_CANARY = "CANARY-PLAINTEXT-3f9a2b-DO-NOT-LEAK"


class TestSettingsCannotLeakSecretsUnderAnyInput:
    """GET /api/settings must never emit a `secret.`-prefixed key."""

    def test_secret_rows_written_directly_to_the_db_are_filtered(self, client, db_session):
        """Bypass the API entirely — a row planted by a worker or migration."""
        db_session.add(
            Configuration(
                key="secret.gemini_api_key",
                value=secret_store.encrypt_value(PLAINTEXT_CANARY),
            )
        )
        db_session.add(Configuration(key="secret.some_future_provider", value="ciphertext"))
        db_session.add(Configuration(key="normal_key", value="visible"))
        db_session.commit()

        res = client.get("/api/settings")
        body = res.json()

        assert body["normal_key"] == "visible"
        assert not any(key.startswith("secret.") for key in body)
        assert PLAINTEXT_CANARY not in res.text
        assert "ciphertext" not in res.text

    def test_many_secret_rows_are_all_filtered(self, client, db_session):
        """The filter must be per-row, not a special case for two known keys."""
        for index in range(25):
            db_session.add(
                Configuration(key=f"secret.provider_{index}", value=f"cipher-{index}")
            )
        db_session.add(Configuration(key="visible_key", value="ok"))
        db_session.commit()

        body = client.get("/api/settings").json()
        assert body == {"visible_key": "ok"}

    def test_settings_is_empty_when_only_secrets_exist(self, client, db_session):
        db_session.add(Configuration(key="secret.gemini_api_key", value="cipher"))
        db_session.commit()
        assert client.get("/api/settings").json() == {}

    def test_secret_written_via_the_secrets_endpoint_is_filtered(self, client):
        client.post("/api/settings/secrets", json={"gemini_api_key": PLAINTEXT_CANARY})
        res = client.get("/api/settings")
        assert PLAINTEXT_CANARY not in res.text
        assert not any(key.startswith("secret.") for key in res.json())

    @pytest.mark.parametrize(
        "key",
        [
            "secret.gemini_api_key",
            "secret.",
            "secret.a",
            "secret.nested.key",
            "secret.UPPER",
        ],
    )
    def test_post_settings_rejects_every_secret_prefixed_key(self, client, key):
        """The generic writer must not create plaintext rows under `secret.`."""
        res = client.post("/api/settings", json={key: "plaintext-should-not-persist"})
        assert res.status_code == 400
        assert "plaintext-should-not-persist" not in client.get("/api/settings").text

    def test_rejected_batch_does_not_partially_persist_the_safe_keys(
        self, client, db_session
    ):
        """A mixed payload is rejected wholesale, leaving no half-written state."""
        res = client.post(
            "/api/settings",
            json={"safe_key": "value", "secret.gemini_api_key": "bad"},
        )
        assert res.status_code == 400
        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .count()
            == 0
        )

    def test_secrets_status_endpoint_never_returns_plaintext(self, client):
        client.post("/api/settings/secrets", json={"gemini_api_key": PLAINTEXT_CANARY})
        res = client.get("/api/settings/secrets")
        assert PLAINTEXT_CANARY not in res.text
        body = res.json()
        assert set(body) == {"gemini", "elevenlabs"}
        assert set(body["gemini"]) == {"configured", "last4"}
        assert body["gemini"]["last4"] == PLAINTEXT_CANARY[-4:]

    def test_no_route_in_the_whole_app_echoes_a_stored_secret(self, client):
        """Sweep every registered GET route for the canary."""
        from fastapi.routing import APIRoute

        from tests.test_routers_smoke import _walk_routes

        client.post("/api/settings/secrets", json={"gemini_api_key": PLAINTEXT_CANARY})

        checked = 0
        for route in _walk_routes(client.app.routes):
            if not isinstance(route, APIRoute) or "GET" not in route.methods:
                continue
            if "{" in route.path:  # skip parameterised routes
                continue
            response = client.get(route.path)
            checked += 1
            assert PLAINTEXT_CANARY not in response.text, (
                f"{route.path} leaked the stored secret"
            )
        assert checked >= 4, "route sweep did not exercise enough endpoints"


class TestPrefixMatchingIsCaseSensitiveByDesign:
    """Document the exact matching rule so a future change is a conscious one.

    ``is_secret_key`` is a plain ``startswith('secret.')``. Uppercase variants
    are NOT treated as secrets. That is safe only because ``set_secret`` always
    writes the lowercase prefix; these tests pin both halves of that invariant.
    """

    def test_store_always_writes_the_lowercase_prefix(self, db_session):
        secret_store.set_secret("gemini", "value-1234", db=db_session)
        keys = [
            row.key
            for row in db_session.query(Configuration).all()
            if "gemini" in row.key
        ]
        assert keys == ["secret.gemini_api_key"]
        assert all(secret_store.is_secret_key(key) for key in keys)

    @pytest.mark.parametrize("variant", ["SECRET.x", "Secret.x"])
    def test_case_variants_are_classified_as_secret(self, variant):
        """L-1 fix: is_secret_key is now casefolded, so variant-cased
        prefixes are still recognised as secret keys — removing a footgun
        before five branches add config keys."""
        assert secret_store.is_secret_key(variant) is True

    @pytest.mark.parametrize("variant", [" secret.x"])
    def test_leading_whitespace_variant_is_not_classified_as_secret(self, variant):
        """Casefolding does not strip whitespace; a leading space means the
        key does not start with 'secret.' and is not a secret key."""
        assert secret_store.is_secret_key(variant) is False

    def test_non_canonical_variant_is_rejected_by_settings_endpoint(
        self, client
    ):
        """Consequence of L-1: 'SECRET.demo' is now classified as a secret
        key (casefolded), so the plain settings endpoint rejects it with
        400 — it must be written via POST /api/settings/secrets."""
        res = client.post("/api/settings", json={"SECRET.demo": "ordinary-value"})
        assert res.status_code == 400
        assert "secret" in res.json()["detail"].lower()


class TestEncryptionRoundTripAndKeyRotation:
    def test_round_trip_preserves_exotic_values(self, db_session):
        for value in [
            "sk-simple",
            "with spaces and  tabs\t",
            "unicode-\u00e9\u00e8-\u4e2d\u6587-\U0001f511",
            "x" * 4096,
            "newline\nembedded",
        ]:
            secret_store.set_secret("gemini", value, db=db_session)
            assert secret_store.get_secret("gemini", db=db_session) == value

    def test_stored_ciphertext_is_ascii_and_survives_a_text_column(self, db_session):
        secret_store.set_secret("gemini", "unicode-\u4e2d\u6587-key", db=db_session)
        row = (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .one()
        )
        row.value.encode("ascii")  # raises if the no-migration claim is wrong
        assert row.value.startswith("gAAAAA")

    def test_get_secret_raises_after_master_key_rotation(self, db_session, monkeypatch):
        from app.config import settings as app_settings

        secret_store.set_secret("gemini", "pre-rotation-value", db=db_session)
        monkeypatch.setattr(app_settings, "FUSIONCLIP_SECRET_KEY", "rotated-master-key")

        with pytest.raises(secret_store.SecretStoreError):
            secret_store.get_secret("gemini", db=db_session)

    def test_status_and_has_secret_degrade_safely_after_rotation(
        self, db_session, monkeypatch
    ):
        """A rotated key must report 'not configured' rather than crashing."""
        from app.config import settings as app_settings

        secret_store.set_secret("gemini", "pre-rotation-value", db=db_session)
        monkeypatch.setattr(app_settings, "FUSIONCLIP_SECRET_KEY", "rotated-master-key")

        assert secret_store.has_secret("gemini", db=db_session) is False
        assert secret_store.secret_status("gemini", db=db_session) == {
            "configured": False,
            "last4": None,
        }

    def test_status_endpoint_survives_a_rotated_master_key(self, client, monkeypatch):
        from app.config import settings as app_settings

        client.post("/api/settings/secrets", json={"gemini_api_key": "pre-rotation"})
        monkeypatch.setattr(app_settings, "FUSIONCLIP_SECRET_KEY", "rotated-master-key")

        res = client.get("/api/settings/secrets")
        assert res.status_code == 200, "rotation must not produce a 500"
        assert res.json()["gemini"]["configured"] is False

    def test_undecryptable_secret_can_still_be_deleted(self, client, db_session):
        """Otherwise a rotated key strands an invisible, unremovable row."""
        db_session.add(Configuration(key="secret.gemini_api_key", value="corrupt"))
        db_session.commit()

        assert client.get("/api/settings/secrets").json()["gemini"]["configured"] is False

        res = client.delete("/api/settings/secrets/gemini")
        assert res.status_code == 200
        assert res.json()["deleted"] is True
        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .count()
            == 0
        )

    def test_overwrite_after_corruption_recovers(self, client, db_session):
        db_session.add(Configuration(key="secret.gemini_api_key", value="corrupt"))
        db_session.commit()

        client.post("/api/settings/secrets", json={"gemini_api_key": "fresh-key-8888"})
        assert secret_store.get_secret("gemini", db=db_session) == "fresh-key-8888"
        assert client.get("/api/settings/secrets").json()["gemini"] == {
            "configured": True,
            "last4": "8888",
        }


class TestLast4Correctness:
    @pytest.mark.parametrize(
        "plaintext,expected",
        [
            ("abcdefgh", "efgh"),
            ("1234", "1234"),
            ("123", None),
            ("12", None),
            ("a", None),
            ("key-with-\u4e2d\u6587", "h-\u4e2d\u6587"),
        ],
    )
    def test_last4_boundaries(self, db_session, plaintext, expected):
        secret_store.set_secret("gemini", plaintext, db=db_session)
        assert secret_store.secret_status("gemini", db=db_session)["last4"] == expected

    def test_last4_never_exposes_more_than_four_characters(self, db_session):
        secret_store.set_secret("gemini", "A" * 64 + "TAIL", db=db_session)
        status = secret_store.secret_status("gemini", db=db_session)
        assert status["last4"] == "TAIL"
        assert len(status["last4"]) == 4

    def test_short_secret_reports_configured_without_a_hint(self, db_session):
        """A 3-char secret is still configured; last4 is suppressed, not faked."""
        secret_store.set_secret("gemini", "abc", db=db_session)
        assert secret_store.secret_status("gemini", db=db_session) == {
            "configured": True,
            "last4": None,
        }


class TestDeleteAndOverwrite:
    def test_delete_is_idempotent_over_http(self, client):
        client.post("/api/settings/secrets", json={"gemini_api_key": "to-delete-1111"})
        first = client.delete("/api/settings/secrets/gemini")
        second = client.delete("/api/settings/secrets/gemini")

        assert first.json()["deleted"] is True
        assert second.status_code == 200
        assert second.json()["deleted"] is False

    def test_delete_one_provider_leaves_the_other_intact(self, client, db_session):
        client.post(
            "/api/settings/secrets",
            json={"gemini_api_key": "gem-1111", "elevenlabs_api_key": "el-2222"},
        )
        client.delete("/api/settings/secrets/gemini")

        status = client.get("/api/settings/secrets").json()
        assert status["gemini"]["configured"] is False
        assert status["elevenlabs"] == {"configured": True, "last4": "2222"}
        assert secret_store.get_secret("elevenlabs", db=db_session) == "el-2222"

    def test_repeated_overwrite_keeps_exactly_one_row(self, client, db_session):
        for index in range(5):
            client.post(
                "/api/settings/secrets", json={"gemini_api_key": f"rotation-{index}"}
            )
        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .count()
            == 1
        )
        assert secret_store.get_secret("gemini", db=db_session) == "rotation-4"

    def test_overwrite_leaves_no_trace_of_the_previous_value(self, client, db_session):
        client.post("/api/settings/secrets", json={"gemini_api_key": "OLD-VALUE-0000"})
        client.post("/api/settings/secrets", json={"gemini_api_key": "NEW-VALUE-1111"})

        rows = db_session.query(Configuration).all()
        dump = "|".join(row.value for row in rows)
        assert "OLD-VALUE-0000" not in dump
        assert "NEW-VALUE-1111" not in dump  # both are ciphertext

    @pytest.mark.parametrize(
        "provider", ["openai", "anthropic", "GEMINI", "Gemini", "gemini "]
    )
    def test_delete_rejects_unknown_providers_with_404(self, client, provider):
        """Provider matching is an exact allowlist lookup — verified as 404."""
        res = client.delete(f"/api/settings/secrets/{provider}")
        assert res.status_code == 404, (
            f"unknown provider '{provider}' returned {res.status_code}, expected 404"
        )

    def test_delete_with_no_provider_is_not_a_wildcard_delete(self, client):
        """An empty provider must not fall through to deleting everything."""
        client.post("/api/settings/secrets", json={"gemini_api_key": "keep-me-1234"})
        res = client.delete("/api/settings/secrets/")
        assert res.status_code == 405
        assert client.get("/api/settings/secrets").json()["gemini"]["configured"] is True

    def test_worker_path_resolves_keys_without_http_context(self, db_session):
        """Celery workers call get_secret() directly against the DB."""
        secret_store.set_secret("gemini", "worker-visible-key", db=db_session)
        secret_store.set_secret("elevenlabs", "worker-el-key", db=db_session)

        assert secret_store.get_secret("gemini", db=db_session) == "worker-visible-key"
        assert secret_store.get_secret("elevenlabs", db=db_session) == "worker-el-key"
