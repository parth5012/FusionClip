"""Unit tests for the encrypted secret store and its HTTP surface."""

import pytest

from app.config import DEV_DEFAULT_SECRET_KEY, settings
from app.models import Configuration
from app.services import secrets as secret_store


class TestEncryption:
    def test_round_trip(self):
        token = secret_store.encrypt_value("super-secret-value")
        assert token != "super-secret-value"
        assert secret_store.decrypt_value(token) == "super-secret-value"

    def test_ciphertext_is_not_readable(self):
        token = secret_store.encrypt_value("AIzaTOTALLYFAKEKEY1234")
        assert "AIzaTOTALLYFAKEKEY1234" not in token

    def test_encryption_is_randomised(self):
        assert secret_store.encrypt_value("same") != secret_store.encrypt_value("same")

    def test_decrypt_rejects_garbage(self):
        with pytest.raises(secret_store.SecretStoreError):
            secret_store.decrypt_value("not-a-fernet-token")

    def test_decrypt_fails_under_a_different_master_key(self, monkeypatch):
        token = secret_store.encrypt_value("rotate-me")
        monkeypatch.setattr(settings, "FUSIONCLIP_SECRET_KEY", "a-completely-different-key")
        with pytest.raises(secret_store.SecretStoreError):
            secret_store.decrypt_value(token)


class TestKeyNaming:
    def test_provider_aliases_resolve(self):
        assert secret_store.resolve_key("gemini") == "secret.gemini_api_key"
        assert secret_store.resolve_key("elevenlabs") == "secret.elevenlabs_api_key"

    def test_full_key_passes_through(self):
        assert secret_store.resolve_key("secret.custom") == "secret.custom"

    def test_is_secret_key(self):
        assert secret_store.is_secret_key("secret.gemini_api_key")
        assert not secret_store.is_secret_key("colab_tunnel_url")


class TestStore:
    def test_set_get_has_delete(self, db_session):
        assert secret_store.get_secret("gemini", db=db_session) is None
        assert secret_store.has_secret("gemini", db=db_session) is False

        secret_store.set_secret("gemini", "AIza-test-key-9876", db=db_session)

        assert secret_store.has_secret("gemini", db=db_session) is True
        assert secret_store.get_secret("gemini", db=db_session) == "AIza-test-key-9876"

        assert secret_store.delete_secret("gemini", db=db_session) is True
        assert secret_store.get_secret("gemini", db=db_session) is None
        assert secret_store.delete_secret("gemini", db=db_session) is False

    def test_raw_db_value_is_ciphertext(self, db_session):
        secret_store.set_secret("elevenlabs", "el-plaintext-key-4321", db=db_session)
        row = (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.elevenlabs_api_key")
            .one()
        )
        assert row.value != "el-plaintext-key-4321"
        assert "el-plaintext-key-4321" not in row.value
        assert secret_store.decrypt_value(row.value) == "el-plaintext-key-4321"

    def test_set_overwrites_existing(self, db_session):
        secret_store.set_secret("gemini", "first", db=db_session)
        secret_store.set_secret("gemini", "second", db=db_session)
        assert secret_store.get_secret("gemini", db=db_session) == "second"
        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .count()
            == 1
        )

    def test_empty_secret_rejected(self, db_session):
        with pytest.raises(ValueError):
            secret_store.set_secret("gemini", "", db=db_session)

    def test_status_is_redacted(self, db_session):
        assert secret_store.secret_status("gemini", db=db_session) == {
            "configured": False,
            "last4": None,
        }
        secret_store.set_secret("gemini", "abcdefgh1234", db=db_session)
        assert secret_store.secret_status("gemini", db=db_session) == {
            "configured": True,
            "last4": "1234",
        }

    def test_undecryptable_secret_reports_unconfigured(self, db_session):
        db_session.add(Configuration(key="secret.gemini_api_key", value="corrupt"))
        db_session.commit()
        assert secret_store.has_secret("gemini", db=db_session) is False
        assert secret_store.secret_status("gemini", db=db_session)["configured"] is False


class TestDevKeyWarning:
    def test_warns_on_dev_default(self, monkeypatch):
        monkeypatch.setattr(settings, "FUSIONCLIP_SECRET_KEY", DEV_DEFAULT_SECRET_KEY)
        assert secret_store.warn_if_dev_secret_key() is True

    def test_silent_on_custom_key(self, monkeypatch):
        monkeypatch.setattr(settings, "FUSIONCLIP_SECRET_KEY", "a-real-production-key")
        assert secret_store.warn_if_dev_secret_key() is False


class TestSecretsEndpoints:
    def test_post_then_get_returns_only_status(self, client):
        res = client.post(
            "/api/settings/secrets",
            json={"gemini_api_key": "AIza-endpoint-key-5555"},
        )
        assert res.status_code == 200
        assert res.json() == {"status": "SUCCESS", "updated": ["gemini"]}

        status = client.get("/api/settings/secrets")
        assert status.status_code == 200
        body = status.json()
        assert body == {
            "gemini": {"configured": True, "last4": "5555"},
            "elevenlabs": {"configured": False, "last4": None},
        }
        assert "AIza-endpoint-key-5555" not in status.text

    def test_post_both_providers(self, client):
        res = client.post(
            "/api/settings/secrets",
            json={"gemini_api_key": "gem-1111", "elevenlabs_api_key": "el-2222"},
        )
        assert res.status_code == 200
        assert sorted(res.json()["updated"]) == ["elevenlabs", "gemini"]

    def test_post_with_no_values_is_rejected(self, client):
        assert client.post("/api/settings/secrets", json={}).status_code == 400
        assert (
            client.post("/api/settings/secrets", json={"gemini_api_key": "   "}).status_code
            == 400
        )

    def test_omitted_field_leaves_existing_value(self, client, db_session):
        client.post("/api/settings/secrets", json={"gemini_api_key": "keep-me-1234"})
        client.post("/api/settings/secrets", json={"elevenlabs_api_key": "other-5678"})
        assert secret_store.get_secret("gemini", db=db_session) == "keep-me-1234"

    def test_delete_secret(self, client):
        client.post("/api/settings/secrets", json={"gemini_api_key": "delete-me-0001"})
        res = client.delete("/api/settings/secrets/gemini")
        assert res.status_code == 200
        assert res.json() == {"status": "SUCCESS", "provider": "gemini", "deleted": True}
        assert client.get("/api/settings/secrets").json()["gemini"]["configured"] is False

    def test_delete_unknown_provider_is_404(self, client):
        assert client.delete("/api/settings/secrets/openai").status_code == 404


class TestSettingsRedaction:
    def test_get_settings_never_leaks_secret_rows(self, client, db_session):
        client.post("/api/settings", json={"colab_tunnel_url": "https://example.test"})
        client.post("/api/settings/secrets", json={"gemini_api_key": "leak-check-7777"})

        res = client.get("/api/settings")
        assert res.status_code == 200
        body = res.json()
        assert body["colab_tunnel_url"] == "https://example.test"
        assert not any(key.startswith("secret.") for key in body)
        assert "leak-check-7777" not in res.text

        # The encrypted row really is in the table — it is filtered, not absent.
        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "secret.gemini_api_key")
            .count()
            == 1
        )

    def test_post_settings_refuses_secret_prefixed_keys(self, client):
        res = client.post("/api/settings", json={"secret.gemini_api_key": "sneaky"})
        assert res.status_code == 400
