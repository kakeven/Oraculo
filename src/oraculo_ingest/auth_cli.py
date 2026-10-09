"""Comandos de autenticação da conta ChatGPT usada pelo Oráculo."""

from __future__ import annotations

import argparse
import json

from . import chatgpt_auth


def main() -> None:
    parser = argparse.ArgumentParser(prog="oraculo-auth")
    parser.add_argument("command", choices=["login", "status", "models", "logout"])
    parser.add_argument("--new-account", action="store_true", help="Registrar outra conta no Oráculo")
    args = parser.parse_args()
    if args.new_account and args.command != "login":
        parser.error("--new-account só pode ser usado com login.")
    try:
        if args.command == "login":
            print("Abrindo o navegador para autorizar o Oráculo com sua conta ChatGPT...", flush=True)
            result = chatgpt_auth.login(new_account=args.new_account)
        elif args.command == "status":
            result = chatgpt_auth.status()
        elif args.command == "models":
            result = chatgpt_auth.list_models()
        else:
            result = chatgpt_auth.logout()
    except (OSError, RuntimeError, TimeoutError, ValueError, KeyError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
