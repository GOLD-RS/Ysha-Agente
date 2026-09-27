#!/usr/bin/env python3
"""Create and restore verified private SQLite snapshots."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from termux_agent.config import Settings, load_env_file  # noqa: E402
from termux_agent.db_maintenance import (  # noqa: E402
    DatabaseMaintenanceError,
    backup_database,
    restore_database,
)


def configured_database() -> Path:
    load_env_file(ROOT / ".env")
    configured = Path(Settings.from_env().database_path).expanduser()
    return configured if configured.is_absolute() else ROOT / configured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup/restore seguro do histórico SQLite do Ysha Agente.")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="cria snapshot íntegro sem sobrescrever arquivo existente")
    backup.add_argument("--output", type=Path, help="destino; se omitido, cria um nome novo ao lado do banco")
    restore = commands.add_parser("restore", help="restaura snapshot após verificação, salvaguarda e confirmação")
    restore.add_argument("backup_file", type=Path)
    restore.add_argument("--yes", action="store_true", help="confirma explicitamente, útil em automação")
    args = parser.parse_args(argv)

    try:
        database = configured_database()
        if args.command == "backup":
            output = args.output
            if output is not None and not output.is_absolute():
                output = ROOT / output
            created = backup_database(database, output)
            print(f"Backup SQLite verificado e privado: {created}")
            return 0

        source = args.backup_file
        if not source.is_absolute():
            source = ROOT / source
        if not args.yes:
            if not sys.stdin.isatty():
                parser.error("Restauração não interativa exige --yes.")
            print("O banco será restaurado. Se já houver memória, uma cópia automática será criada primeiro.")
            if input("Digite RESTAURAR para continuar: ").strip() != "RESTAURAR":
                print("Restauração cancelada; o banco não foi alterado.")
                return 0
        previous = restore_database(source, database, confirmed=True)
        print("Backup restaurado e verificado.")
        if previous:
            print(f"Cópia do banco anterior preservada em: {previous}")
        return 0
    except (DatabaseMaintenanceError, OSError, ValueError) as exc:
        print(f"Operação SQLite não concluída: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
