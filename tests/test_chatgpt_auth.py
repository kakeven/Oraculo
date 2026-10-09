import threading
import urllib.error
import urllib.request

from oraculo_ingest import chatgpt_auth


class MemoryVault:
    def __init__(self):
        self.items = {}

    def get_password(self, service, key):
        return self.items.get((service, key))

    def set_password(self, service, key, value):
        assert len(value) <= chatgpt_auth.VAULT_PART_SIZE
        self.items[(service, key)] = value

    def delete_password(self, service, key):
        self.items.pop((service, key), None)


def test_callback_captures_parameters_without_logging_code():
    handler = chatgpt_auth._callback_handler()
    server = chatgpt_auth.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_port}/auth/callback?code=private&state=check",
            timeout=3,
        ) as response:
            assert response.status == 200
        thread.join(timeout=3)
        assert handler.params == {"code": "private", "state": "check"}
    finally:
        server.server_close()


def test_callback_rejects_unexpected_host():
    handler = chatgpt_auth._callback_handler()
    server = chatgpt_auth.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/auth/callback?code=private&state=check",
            headers={"Host": "unexpected.example"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3):
                assert False, "callback aceitou Host externo"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        thread.join(timeout=3)
        assert handler.params is None
    finally:
        server.server_close()


def test_refresh_replaces_rotating_token(tmp_path, monkeypatch):
    metadata = {"host_id": "urn:uuid:test", "active_client_id": "oaiapp_test",
                "profiles": {"oaiapp_test": {"email": "user@example.test", "subject": "subject"}}}
    chatgpt_auth._save_metadata(tmp_path, metadata)
    chatgpt_auth._save_tokens("oaiapp_test", {
        "access_token": "old", "refresh_token": "refresh_old", "id_token": "id",
        "scopes": ["resource.invoke", "chatgpt.tokens.use.direct"], "expires_at": 0,
    }, tmp_path)
    calls = []

    def fake_post(url, values, **kwargs):
        calls.append(values)
        return {"access_token": "new", "refresh_token": "refresh_new", "expires_in": 3600}

    monkeypatch.setattr(chatgpt_auth, "_form_post", fake_post)
    assert chatgpt_auth.access_token(tmp_path) == "new"
    assert calls[0]["refresh_token"] == "refresh_old"
    assert chatgpt_auth._read_tokens("oaiapp_test", tmp_path)["refresh_token"] == "refresh_new"


def test_large_credential_is_encrypted_and_replaced(tmp_path):
    first = {"access_token": "a" * 3500, "refresh_token": "b" * 3500}
    chatgpt_auth._save_tokens("client", first, tmp_path)
    assert chatgpt_auth._read_tokens("client", tmp_path) == first
    path = chatgpt_auth._token_path(tmp_path, "client")
    assert b"a" * 100 not in path.read_bytes()
    second = {"access_token": "new", "refresh_token": "new"}
    chatgpt_auth._save_tokens("client", second, tmp_path)
    assert chatgpt_auth._read_tokens("client", tmp_path) == second
    chatgpt_auth._delete_tokens("client", tmp_path)
    assert not path.exists()


def test_legacy_chunked_credential_can_be_migrated(monkeypatch):
    vault = MemoryVault()
    monkeypatch.setattr(chatgpt_auth, "_vault", lambda: vault)
    original = {"access_token": "a" * 3500, "refresh_token": "b" * 3500}
    chatgpt_auth._save_legacy_tokens("client", original)
    assert chatgpt_auth._read_legacy_tokens("client") == original
    chatgpt_auth._delete_legacy_tokens("client")
    assert vault.items == {}


def test_logout_accepts_empty_revocation_response(tmp_path, monkeypatch):
    chatgpt_auth._save_metadata(tmp_path, {
        "host_id": "urn:uuid:test", "active_client_id": "oaiapp_test", "profiles": {},
    })
    chatgpt_auth._save_tokens("oaiapp_test", {"refresh_token": "secret"}, tmp_path)
    monkeypatch.setattr(chatgpt_auth, "_get_json", lambda url: {"revocation_endpoint": "https://example.test/revoke"})
    seen = []
    monkeypatch.setattr(chatgpt_auth, "_form_post", lambda url, values, **kw: seen.append(kw) or {})
    assert chatgpt_auth.logout(tmp_path)["remote_revoked"] == "true"
    assert seen == [{"expect_json": False}]
    assert chatgpt_auth._read_tokens("oaiapp_test", tmp_path) is None


def test_model_catalog_preserves_server_order(monkeypatch):
    monkeypatch.setattr(chatgpt_auth, "access_token", lambda directory=None: "token")
    monkeypatch.setattr(chatgpt_auth, "_get_json", lambda *args, **kwargs: {"models": [
        {"slug": "first", "display_name": "First", "visibility": "list"},
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
        {"slug": "second", "display_name": "Second", "visibility": "list"},
    ]})
    assert [m["slug"] for m in chatgpt_auth.list_models()] == ["first", "second"]
