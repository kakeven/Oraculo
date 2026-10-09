"""Falha antes do commit se arquivos privados entrarem no conjunto público do Git."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SUFFIXES = {".pdf", ".epub", ".mobi", ".cbz", ".cbr", ".pem", ".key",
                    ".p12", ".pfx", ".jks", ".sqlite3", ".db"}
PRIVATE_NAMES = {".env", "credentials.json", "secrets.json", "chatgpt-auth.json"}
SECRET_PATTERNS = {
    "chave privada": re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "token de API": re.compile(rb"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "chave AWS": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "credencial em configuração": re.compile(
        rb"(?im)^\s*(?:OPENAI_API_KEY|CLIENT_SECRET|REFRESH_TOKEN|ACCESS_TOKEN)\s*=\s*['\"]?[A-Za-z0-9_-]{16,}"
    ),
}


def candidates() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    )
    return [ROOT / name.decode("utf-8", errors="surrogateescape")
            for name in result.stdout.split(b"\0") if name]


def check(path: Path) -> list[str]:
    relative = path.relative_to(ROOT).as_posix()
    name = path.name.lower()
    issues = []
    if relative.startswith("data/"):
        issues.append("arquivo de dados locais")
    if path.suffix.lower() in PRIVATE_SUFFIXES or name in PRIVATE_NAMES or name.startswith(".env."):
        issues.append("formato ou nome privado")
    if not path.is_file():
        return issues
    if path.stat().st_size > 5 * 1024 * 1024:
        issues.append("arquivo acima de 5 MiB; revise antes de publicar")
        return issues
    content = path.read_bytes()
    if content.startswith(b"%PDF-") or content.startswith(b"SQLite format 3\0"):
        issues.append("assinatura de PDF ou banco SQLite")
    if b"\0" in content:
        issues.append("arquivo binário")
        return issues
    for label, pattern in SECRET_PATTERNS.items():
        if pattern.search(content):
            issues.append(label)
    return issues


def main() -> int:
    try:
        files = candidates()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Não foi possível listar arquivos públicos do Git: {type(exc).__name__}.", file=sys.stderr)
        return 2
    failures = [(path.relative_to(ROOT).as_posix(), issue)
                for path in files for issue in check(path)]
    for path, issue in failures:
        print(f"BLOQUEADO: {path} — {issue}")
    if failures:
        print(f"Publicação bloqueada: {len(failures)} problema(s) em {len(files)} arquivo(s) candidatos.")
        return 1
    print(f"Pré-publicação: {len(files)} arquivos candidatos, nenhum PDF, dado local ou segredo conhecido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
