"""OAuth próprio do Oráculo para uso elegível do plano ChatGPT."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .windows_secrets import protect, unprotect


AUTH_BASE = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
SERVICE = "oraculo-chatgpt-plan"
VAULT_PART_SIZE = 900  # Windows Credential Manager limits each credential blob.
SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
APP_NAME = "Oráculo RPG"
CALLBACK_PATH = "/auth/callback"


def default_auth_dir() -> Path:
    configured = os.environ.get("ORACULO_AUTH_DIR")
    return Path(configured) if configured else Path.cwd() / "data" / "auth"


def _metadata_path(directory: Path) -> Path:
    return directory / "chatgpt-auth.json"


def _load_metadata(directory: Path) -> dict[str, Any]:
    path = _metadata_path(directory)
    if not path.exists():
        return {"host_id": f"urn:uuid:{uuid.uuid4()}", "active_client_id": None, "profiles": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("profiles"), dict):
        raise RuntimeError("Metadados de autenticação inválidos.")
    return value


def _save_metadata(directory: Path, value: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = _metadata_path(directory)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _vault():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("Instale as dependências com pip install -e '.[auth]'.") from exc
    return keyring


def _read_legacy_tokens(client_id: str) -> dict[str, Any] | None:
    raw = _vault().get_password(SERVICE, client_id)
    if not raw:
        return None
    index = json.loads(raw)
    if index.get("format") != "chunks-v1":
        return index  # Credentials saved before chunking.
    parts = []
    for position in range(index["parts"]):
        part = _vault().get_password(SERVICE, _part_key(client_id, index["id"], position))
        if part is None:
            raise RuntimeError("Credenciais incompletas. Execute 'oraculo-auth login' novamente.")
        parts.append(part)
    return json.loads("".join(parts))


def _save_legacy_tokens(client_id: str, tokens: dict[str, Any]) -> None:
    vault = _vault()
    previous = vault.get_password(SERVICE, client_id)
    serialized = json.dumps(tokens, ensure_ascii=True)
    chunks = [serialized[i:i + VAULT_PART_SIZE] for i in range(0, len(serialized), VAULT_PART_SIZE)]
    record_id = secrets.token_hex(8)
    written = []
    try:
        for position, chunk in enumerate(chunks):
            key = _part_key(client_id, record_id, position)
            vault.set_password(SERVICE, key, chunk)
            written.append(key)
        vault.set_password(SERVICE, client_id, json.dumps({
            "format": "chunks-v1", "id": record_id, "parts": len(chunks),
        }))
    except Exception as exc:
        for key in written:
            try:
                vault.delete_password(SERVICE, key)
            except Exception:
                pass
        raise RuntimeError("Não foi possível guardar as credenciais no Windows.") from exc
    if previous:
        _delete_parts(vault, client_id, previous)


def _part_key(client_id: str, record_id: str, position: int) -> str:
    return f"{client_id}:part:{record_id}:{position}"


def _delete_parts(vault: Any, client_id: str, raw_index: str) -> None:
    index = json.loads(raw_index)
    if index.get("format") == "chunks-v1":
        for position in range(index["parts"]):
            try:
                vault.delete_password(SERVICE, _part_key(client_id, index["id"], position))
            except Exception:
                pass


def _delete_legacy_tokens(client_id: str) -> None:
    vault = _vault()
    index = vault.get_password(SERVICE, client_id)
    if index:
        _delete_parts(vault, client_id, index)
        vault.delete_password(SERVICE, client_id)


def _token_path(directory: Path, client_id: str) -> Path:
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()
    return directory / f"tokens-{digest}.bin"


def _read_tokens(client_id: str, directory: Path | None = None) -> dict[str, Any] | None:
    path = _token_path(directory or default_auth_dir(), client_id)
    if not path.exists():
        return None
    try:
        return json.loads(unprotect(path.read_bytes()))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError("Não foi possível ler as credenciais protegidas. Faça login novamente.") from exc


def _save_tokens(client_id: str, tokens: dict[str, Any], directory: Path | None = None) -> None:
    directory = directory or default_auth_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _token_path(directory, client_id)
    temporary = path.with_suffix(".tmp")
    protected = protect(json.dumps(tokens, ensure_ascii=True).encode("utf-8"))
    temporary.write_bytes(protected)
    os.replace(temporary, path)


def _delete_tokens(client_id: str, directory: Path | None = None) -> None:
    _token_path(directory or default_auth_dir(), client_id).unlink(missing_ok=True)


def _form_post(url: str, values: dict[str, str], *, expect_json: bool = True) -> dict[str, Any]:
    payload = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response) if expect_json else {}
    except urllib.error.HTTPError as exc:
        # OAuth errors can contain private details; surface only the status.
        raise RuntimeError(f"Serviço de autenticação retornou HTTP {exc.code}.") from exc


def _get_json(url: str, access_token: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Serviço OpenAI retornou HTTP {exc.code}.") from exc


def _verify_id_token(token: str, client_id: str, nonce: str) -> dict[str, Any]:
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("Instale as dependências com pip install -e '.[auth]'.") from exc
    configuration = _get_json(f"{AUTH_BASE}/.well-known/openid-configuration")
    if configuration.get("issuer") != AUTH_BASE:
        raise RuntimeError("Emissor OAuth inesperado.")
    key = jwt.PyJWKClient(configuration["jwks_uri"]).get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                        issuer=AUTH_BASE, options={"require": ["exp", "iss", "aud", "sub"]})
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise RuntimeError("Nonce OAuth inválido.")
    return claims


def _callback_handler():
    class Handler(BaseHTTPRequestHandler):
        params: dict[str, str] | None = None

        def do_GET(self) -> None:
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403)
                return
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)
                return
            type(self).params = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query).items()}
            body = b"Autorizacao recebida. Pode voltar ao terminal do Oraculo."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            # Never log callback URLs: they contain the authorization code.
            pass

    return Handler


def login(directory: Path | None = None, *, new_account: bool = False,
          open_browser: bool = True, timeout_seconds: int = 600) -> dict[str, str]:
    directory = directory or default_auth_dir()
    metadata = _load_metadata(directory)
    active_id = None if new_account else metadata.get("active_client_id")
    active = metadata["profiles"].get(active_id, {}) if active_id else {}
    old_tokens = _read_tokens(active_id, directory) if active_id else None
    client_id = active_id or "dynamic_agent_client"
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    handler = _callback_handler()
    server = HTTPServer(("127.0.0.1", 0), handler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}{CALLBACK_PATH}"
    query = {
        "client_id": client_id,
        "ext_agent_host_id": metadata["host_id"],
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    if active_id:
        if old_tokens and old_tokens.get("id_token"):
            query["id_token_hint"] = old_tokens["id_token"]
        if active.get("email"):
            query["login_hint"] = active["email"]
    else:
        query["agent_name_hint"] = APP_NAME
    url = f"{AUTH_BASE}/api/accounts/authorize?{urllib.parse.urlencode(query)}"
    # Persist the host ID before first authorization so retries use the same host.
    _save_metadata(directory, metadata)
    try:
        if open_browser:
            if not webbrowser.open(url):
                raise RuntimeError("Não foi possível abrir o navegador para o login.")
        else:
            raise RuntimeError("O navegador precisa ser aberto para concluir o login.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and handler.params is None:
            server.handle_request()
        if handler.params is None:
            raise TimeoutError("O login não foi concluído no navegador a tempo.")
        params = handler.params
    finally:
        server.server_close()
    if not secrets.compare_digest(params.get("state", ""), state):
        raise RuntimeError("Estado OAuth inválido.")
    if "error" in params:
        raise RuntimeError("Autorização não concedida no navegador.")
    code = params.get("code")
    issued_id = params.get("client_id", active_id)
    if not code or not issued_id or issued_id == "dynamic_agent_client":
        raise RuntimeError("O retorno OAuth não trouxe o código ou o client ID emitido.")
    if active_id and issued_id != active_id:
        raise RuntimeError("O retorno OAuth pertence a outro registro de aplicativo.")
    tokens = _form_post(f"{AUTH_BASE}/api/accounts/oauth/token", {
        "grant_type": "authorization_code", "client_id": issued_id, "code": code,
        "code_verifier": verifier, "redirect_uri": redirect_uri, "resource": RESOURCE,
    })
    scopes = set(tokens.get("scope", "").split())
    if not {"resource.invoke", "chatgpt.tokens.use.direct"} <= scopes:
        raise RuntimeError("O plano ChatGPT não foi autorizado para o Oráculo.")
    claims = _verify_id_token(tokens["id_token"], issued_id, nonce)
    if active_id and claims["sub"] != active.get("subject"):
        raise RuntimeError("A conta retornada difere da conta selecionada.")
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("O serviço não forneceu credenciais renováveis.")
    record = {
        "access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
        "id_token": tokens["id_token"], "scopes": sorted(scopes),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
    }
    _save_tokens(issued_id, record, directory)
    metadata["profiles"][issued_id] = {
        "email": claims.get("email", ""), "subject": claims["sub"],
        "issuer": claims["iss"],
    }
    metadata["active_client_id"] = issued_id
    _save_metadata(directory, metadata)
    return {"email": claims.get("email", ""), "client_id": issued_id, "status": "connected"}


def status(directory: Path | None = None) -> dict[str, str]:
    directory = directory or default_auth_dir()
    metadata = _load_metadata(directory)
    active_id = metadata.get("active_client_id")
    if not active_id:
        return {"status": "disconnected"}
    profile = metadata["profiles"].get(active_id, {})
    return {"status": "connected" if _read_tokens(active_id, directory) else "disconnected",
            "email": profile.get("email", ""), "client_id": active_id}


def access_token(directory: Path | None = None) -> str:
    directory = directory or default_auth_dir()
    metadata = _load_metadata(directory)
    client_id = metadata.get("active_client_id")
    tokens = _read_tokens(client_id, directory) if client_id else None
    if not tokens:
        raise RuntimeError("Faça login próprio do Oráculo com 'oraculo-auth login'.")
    if tokens["expires_at"] > time.time() + 90:
        return tokens["access_token"]
    refreshed = _form_post(f"{AUTH_BASE}/api/accounts/oauth/token", {
        "grant_type": "refresh_token", "client_id": client_id,
        "refresh_token": tokens["refresh_token"], "resource": RESOURCE,
    })
    if not refreshed.get("access_token") or not refreshed.get("refresh_token"):
        raise RuntimeError("Não foi possível renovar o login. Execute 'oraculo-auth login'.")
    scopes = set(refreshed.get("scope", " ".join(tokens["scopes"])).split())
    if "chatgpt.tokens.use.direct" not in scopes:
        raise RuntimeError("A permissão de usar o plano ChatGPT foi removida.")
    replacement = {
        **tokens, "access_token": refreshed["access_token"],
        "refresh_token": refreshed["refresh_token"], "scopes": sorted(scopes),
        "expires_at": time.time() + int(refreshed.get("expires_in", 3600)),
    }
    if refreshed.get("id_token"):
        replacement["id_token"] = refreshed["id_token"]
    _save_tokens(client_id, replacement, directory)
    return replacement["access_token"]


def list_models(directory: Path | None = None) -> list[dict[str, str]]:
    catalog = _get_json(f"{RESOURCE}/models", access_token(directory))
    return [{"slug": row["slug"], "display_name": row.get("display_name", row["slug"])}
            for row in catalog.get("models", []) if row.get("visibility") == "list" and row.get("slug")]


def answer(prompt: str, model: str | None = None, directory: Path | None = None) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Instale as dependências com pip install -e '.[auth]'.") from exc
    models = list_models(directory)
    available = {entry["slug"] for entry in models}
    chosen = model or ("gpt-6.1-sol" if "gpt-6.1-sol" in available else (models[0]["slug"] if models else None))
    if not chosen or chosen not in available:
        raise ValueError("Modelo indisponível para esta conta. Consulte 'oraculo-auth models'.")
    client = OpenAI(api_key=access_token(directory), base_url=RESOURCE, max_retries=0, timeout=120)
    parts: list[str] = []
    completed = False
    with client.responses.create(model=chosen, input=[{"role": "user", "content": prompt}],
                                 store=False, stream=True) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                parts.append(event.delta)
            elif event.type == "response.failed":
                code = getattr(getattr(event.response, "error", None), "code", "unknown_error")
                raise RuntimeError(f"A resposta falhou: {code}")
            elif event.type == "response.completed":
                completed = True
    if not completed:
        raise RuntimeError("A conexão terminou antes da resposta completa.")
    return "".join(parts).strip()


def logout(directory: Path | None = None) -> dict[str, str]:
    directory = directory or default_auth_dir()
    metadata = _load_metadata(directory)
    client_id = metadata.get("active_client_id")
    if not client_id:
        return {"status": "disconnected"}
    tokens = _read_tokens(client_id, directory)
    remote_revoked = False
    if tokens and tokens.get("refresh_token"):
        try:
            config = _get_json(f"{AUTH_BASE}/.well-known/openid-configuration")
            _form_post(config["revocation_endpoint"], {
                "token": tokens["refresh_token"], "token_type_hint": "refresh_token",
                "client_id": client_id,
            }, expect_json=False)
            remote_revoked = True
        except (OSError, RuntimeError):
            pass
    try:
        _delete_tokens(client_id, directory)
    except Exception:
        pass
    metadata["active_client_id"] = None
    _save_metadata(directory, metadata)
    return {"status": "disconnected", "remote_revoked": str(remote_revoked).lower()}
