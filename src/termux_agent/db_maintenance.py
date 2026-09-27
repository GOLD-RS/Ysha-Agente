"""Private, verified SQLite backup and guarded restore operations."""

from contextlib import closing
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile


class DatabaseMaintenanceError(RuntimeError):
    """Safe error for database maintenance commands."""


class DatabaseLock:
    """Advisory process lock shared by the agent and maintenance commands."""

    def __init__(self, database_path: str | Path, *, exclusive: bool = False, nonblocking: bool = False):
        database = Path(database_path).expanduser()
        if not database.is_absolute():
            database = Path.cwd() / database
        self.path = Path(str(database.absolute()) + ".lock")
        self.exclusive = exclusive
        self.nonblocking = nonblocking
        self._fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise DatabaseMaintenanceError("Arquivo de bloqueio do banco inválido.")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        try:
            self._fd = os.open(self.path, flags, 0o600)
            os.fchmod(self._fd, 0o600)
            operation = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
            if self.nonblocking:
                operation |= fcntl.LOCK_NB
            fcntl.flock(self._fd, operation)
        except BlockingIOError:
            self.close()
            raise DatabaseMaintenanceError("Pare o agente antes de restaurar o banco.") from None
        except OSError:
            self.close()
            raise DatabaseMaintenanceError("Não foi possível obter o bloqueio privado do banco.") from None
        return self

    def close(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _database_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.absolute()
    if path.is_symlink():
        raise DatabaseMaintenanceError("O arquivo do banco não pode ser um link simbólico.")
    return path


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise DatabaseMaintenanceError("O arquivo SQLite não foi encontrado ou não é regular.")
    uri = path.resolve(strict=True).as_uri() + "?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True, timeout=15)
    except sqlite3.DatabaseError:
        raise DatabaseMaintenanceError("Não foi possível abrir o arquivo SQLite.") from None


def _verify_database(path: Path) -> None:
    try:
        with closing(_readonly_connection(path)) as db:
            result = db.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise DatabaseMaintenanceError("A verificação de integridade do SQLite falhou.")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "messages" not in tables:
                raise DatabaseMaintenanceError("O arquivo não contém o histórico esperado do Ysha.")
            columns = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
            if not {"id", "session_id", "role", "content", "created_at"}.issubset(columns):
                raise DatabaseMaintenanceError("O esquema do histórico SQLite não é compatível.")
    except DatabaseMaintenanceError:
        raise
    except (sqlite3.DatabaseError, OSError):
        raise DatabaseMaintenanceError("O arquivo SQLite está inválido ou não pôde ser verificado.") from None


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _create_verified_snapshot(source_path: Path, destination_path: Path) -> Path:
    destination_path = destination_path.absolute()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path == source_path or destination_path.exists() or destination_path.is_symlink():
        raise DatabaseMaintenanceError("O destino já existe ou coincide com o banco; nada foi sobrescrito.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.", suffix=".tmp", dir=destination_path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        with closing(_readonly_connection(source_path)) as source:
            with closing(sqlite3.connect(str(temporary), timeout=15)) as target:
                source.backup(target)
                target.commit()
        os.chmod(temporary, 0o600)
        _fsync_file(temporary)
        _verify_database(temporary)
        try:
            os.link(temporary, destination_path)
        except FileExistsError:
            raise DatabaseMaintenanceError("O destino já existe; nada foi sobrescrito.") from None
        os.chmod(destination_path, 0o600)
        _fsync_directory(destination_path.parent)
        return destination_path
    except DatabaseMaintenanceError:
        raise
    except (OSError, sqlite3.DatabaseError, ValueError):
        raise DatabaseMaintenanceError("O backup SQLite não pôde ser criado e verificado.") from None
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _default_backup_path(database_path: Path, suffix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return database_path.with_name(f"{database_path.name}.{suffix}-{stamp}-{secrets.token_hex(3)}.sqlite3")


def verify_database(database_path: str | Path) -> bool:
    _verify_database(_database_path(database_path))
    return True


def backup_database(database_path: str | Path, destination_path: str | Path | None = None) -> Path:
    database = _database_path(database_path)
    if not database.is_file():
        raise DatabaseMaintenanceError("O banco de dados ainda não existe.")
    destination = _database_path(destination_path) if destination_path is not None else _default_backup_path(database, "backup")
    with DatabaseLock(database, exclusive=False):
        return _create_verified_snapshot(database, destination)


def _copy_snapshot(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.is_symlink():
        raise DatabaseMaintenanceError("O banco de destino não pode ser um link simbólico.")
    if not destination_path.exists():
        fd = os.open(destination_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
    try:
        os.chmod(destination_path, 0o600)
        with closing(_readonly_connection(source_path)) as source:
            with closing(sqlite3.connect(str(destination_path), timeout=15)) as target:
                source.backup(target)
                target.commit()
                try:
                    target.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
                except sqlite3.DatabaseError:
                    pass
        os.chmod(destination_path, 0o600)
        _fsync_file(destination_path)
    except (OSError, sqlite3.DatabaseError, DatabaseMaintenanceError):
        raise DatabaseMaintenanceError("A restauração SQLite não foi concluída.") from None


def restore_database(
    backup_path: str | Path,
    database_path: str | Path,
    *,
    confirmed: bool = False,
) -> Path | None:
    if not confirmed:
        raise DatabaseMaintenanceError("Confirme explicitamente a restauração antes de substituir o histórico.")
    source = _database_path(backup_path)
    database = _database_path(database_path)
    if source == database:
        raise DatabaseMaintenanceError("O backup e o banco ativo precisam ser arquivos diferentes.")
    _verify_database(source)

    with DatabaseLock(database, exclusive=True, nonblocking=True):
        # Stage and verify the requested backup before touching the live database.
        staged = database.with_name(f".{database.name}.restore-{secrets.token_hex(6)}.sqlite3")
        _create_verified_snapshot(source, staged)
        safeguard: Path | None = None
        try:
            if database.exists():
                safeguard = _create_verified_snapshot(database, _default_backup_path(database, "before-restore"))
            try:
                _copy_snapshot(staged, database)
                _verify_database(database)
            except DatabaseMaintenanceError:
                if safeguard is not None:
                    try:
                        _copy_snapshot(safeguard, database)
                        _verify_database(database)
                    except DatabaseMaintenanceError:
                        raise DatabaseMaintenanceError(
                            f"A restauração falhou; a cópia anterior está preservada em {safeguard}."
                        ) from None
                else:
                    for suffix in ("-wal", "-shm"):
                        try:
                            Path(str(database) + suffix).unlink()
                        except FileNotFoundError:
                            pass
                    try:
                        database.unlink()
                    except FileNotFoundError:
                        pass
                raise DatabaseMaintenanceError(
                    "A restauração não passou na verificação; o histórico anterior foi mantido."
                ) from None
            return safeguard
        finally:
            try:
                staged.unlink()
            except FileNotFoundError:
                pass
            _fsync_directory(database.parent)
