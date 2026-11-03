#!/usr/bin/env python3
"""Motor isolado de versionamento e integridade de backups do SPIA."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid

from datetime import datetime, timezone
from pathlib import Path


class BackupError(Exception):
    """Erro controlado durante a preservação de uma versão."""


VALID_ORIGINS = {"initial", "spia", "external", "recovery"}
VALID_TRIGGERS = {"open", "save", "conflict", "recovery"}
VERSION_PATTERN = re.compile(r"^versao_(\d{6})$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_manifest_events(
    events: list[dict],
    expected_project: str,
) -> None:
    """Valida integralmente os eventos antes de usá-los como histórico."""

    common_fields = {
        "schema_version", "event_id", "event_type", "timestamp",
        "project", "original_path", "version_id", "backup_path",
        "sha256", "size_bytes",
    }
    event_fields = {
        "version_created": common_fields | {
            "origin", "trigger", "related_versions",
        },
        "backup_orphan_detected": common_fields,
    }

    seen_ids = set()

    for index, event in enumerate(events, start=1):
        def invalid(reason: str) -> None:
            raise BackupError(
                f"Manifesto inválido na linha {index}: {reason}"
            )

        event_type = event.get("event_type")
        if not isinstance(event_type, str) or event_type not in event_fields:
            invalid("tipo de evento desconhecido.")

        if set(event) != event_fields[event_type]:
            invalid("campos obrigatórios ausentes ou campos inesperados.")

        if (
            type(event["schema_version"]) is not int
            or event["schema_version"] != 1
        ):
            invalid("versão de esquema incompatível.")

        event_id = event["event_id"]
        if not isinstance(event_id, str):
            invalid("identificador de evento inválido.")
        try:
            parsed_id = uuid.UUID(event_id)
        except (ValueError, AttributeError):
            invalid("identificador de evento não é UUID.")
        if str(parsed_id) != event_id:
            invalid("UUID não está no formato canônico.")
        if event_id in seen_ids:
            invalid("identificador de evento duplicado.")
        seen_ids.add(event_id)

        timestamp = event["timestamp"]
        if not isinstance(timestamp, str):
            invalid("timestamp inválido.")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            invalid("timestamp não é ISO-8601 válido.")
        if (
            parsed_timestamp.tzinfo is None
            or parsed_timestamp.utcoffset() is None
        ):
            invalid("timestamp sem informação de fuso horário.")

        if event["project"] != expected_project:
            invalid("nome do projeto incompatível com o manifesto.")

        original_path = event["original_path"]
        if (
            not isinstance(original_path, str)
            or not original_path
            or "\\" in original_path
            or "\x00" in original_path
            or original_path.startswith("/")
        ):
            invalid("caminho original inválido.")

        path_parts = original_path.split("/")
        if (
            any(part in {"", ".", ".."} for part in path_parts)
            or path_parts[0] == "backups"
        ):
            invalid("caminho original inseguro ou reservado.")

        version_id = event["version_id"]
        if (
            not isinstance(version_id, str)
            or VERSION_PATTERN.fullmatch(version_id) is None
        ):
            invalid("identificador de versão inválido.")

        backup_path = event["backup_path"]
        if (
            not isinstance(backup_path, str)
            or backup_path != f"{original_path}/{version_id}"
        ):
            invalid("caminho de backup incompatível com a versão.")

        digest = event["sha256"]
        if (
            not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
        ):
            invalid("hash SHA-256 inválido.")

        size_bytes = event["size_bytes"]
        if type(size_bytes) is not int or size_bytes < 0:
            invalid("tamanho em bytes inválido.")

        if event_type == "version_created":
            origin = event["origin"]
            if not isinstance(origin, str) or origin not in VALID_ORIGINS:
                invalid("origem da versão inválida.")

            trigger = event["trigger"]
            if not isinstance(trigger, str) or trigger not in VALID_TRIGGERS:
                invalid("gatilho da versão inválido.")

            related = event["related_versions"]
            if not isinstance(related, list):
                invalid("related_versions precisa ser uma lista.")
            for related_id in related:
                if (
                    not isinstance(related_id, str)
                    or VERSION_PATTERN.fullmatch(related_id) is None
                ):
                    invalid("related_versions contém versão inválida.")




def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()



def _open_directory_at(
    parent_fd: int,
    name: str,
    *,
    create: bool = False,
    mode: int = 0o700,
) -> int:
    """Abre um diretório relativo a um descritor, sem seguir symlinks."""

    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise BackupError("Nome de diretório inválido.")

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")

    if any(not hasattr(os, flag) for flag in required_flags):
        raise BackupError(
            "A plataforma não oferece proteção segura para diretórios."
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    try:
        if create:
            try:
                os.mkdir(name, mode=mode, dir_fd=parent_fd)
            except FileExistsError:
                pass

        directory_fd = os.open(
            name,
            flags,
            dir_fd=parent_fd,
        )

        try:
            info = os.fstat(directory_fd)

            if not stat.S_ISDIR(info.st_mode):
                raise BackupError(
                    "O objeto aberto não é um diretório seguro."
                )

            return directory_fd

        except BaseException:
            os.close(directory_fd)
            raise

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            f"Não foi possível abrir o diretório com segurança: {name}."
        ) from exc


def _open_absolute_directory(path: Path) -> int:
    """Abre um caminho absoluto componente por componente, sem symlinks."""

    target = Path(path)

    if not target.is_absolute():
        raise BackupError("O caminho da raiz precisa ser absoluto.")

    parts = target.parts

    if not parts or parts[0] != "/":
        raise BackupError("Caminho absoluto inválido.")

    required_flags = ("O_DIRECTORY", "O_NOFOLLOW")

    if any(not hasattr(os, flag) for flag in required_flags):
        raise BackupError(
            "A plataforma não oferece proteção segura para diretórios."
        )

    current_fd = None

    try:
        current_fd = os.open(
            "/",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )

        for part in parts[1:]:
            next_fd = _open_directory_at(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd

        result_fd = current_fd
        current_fd = None
        return result_fd

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível abrir a raiz administrativa com segurança."
        ) from exc
    finally:
        if current_fd is not None:
            os.close(current_fd)

def _check_regular_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BackupError(f"Arquivo inacessível: {path.name}") from exc

    if not stat.S_ISREG(info.st_mode):
        raise BackupError(f"Não é um arquivo regular: {path.name}")


def _assert_project_entry_identity(
    root_fd: int,
    project_name: str,
    project_fd: int,
) -> None:
    """Confirma que o nome do projeto ainda aponta para o diretório aberto."""

    try:
        named = os.stat(
            project_name,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        opened = os.fstat(project_fd)

        if (
            not stat.S_ISDIR(named.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or (named.st_dev, named.st_ino)
            != (opened.st_dev, opened.st_ino)
        ):
            raise BackupError(
                "O projeto foi movido ou substituído durante a operação."
            )

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível confirmar a identidade do projeto."
        ) from exc


def _read_source_at(admin_root: Path | int, relative_path: str) -> bytes:
    """Lê a origem usando descritores ancorados e sem seguir symlinks."""

    if not isinstance(relative_path, str) or not relative_path:
        raise BackupError("Caminho do arquivo obrigatório.")

    parts = relative_path.split("/")
    if (
        len(parts) < 2
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in relative_path
        or "\x00" in relative_path
        or parts[0] == "backups"
    ):
        raise BackupError("Caminho de origem inválido.")

    current_fd = None
    file_fd = None

    try:
        if isinstance(admin_root, int) and not isinstance(admin_root, bool):
            current_fd = os.dup(admin_root)
        elif isinstance(admin_root, Path):
            current_fd = _open_absolute_directory(admin_root)
        else:
            raise BackupError("Referência à raiz administrativa inválida.")

        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise BackupError("Raiz administrativa inválida.")

        next_fd = _open_directory_at(current_fd, parts[0])
        os.close(current_fd)
        current_fd = next_fd

        for part in parts[1:-1]:
            next_fd = _open_directory_at(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd

        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)

        before = os.fstat(file_fd)

        if not stat.S_ISREG(before.st_mode):
            raise BackupError("A origem não é um arquivo regular.")

        chunks = []

        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(file_fd)

        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )

        if identity_before != identity_after:
            raise BackupError("O arquivo mudou durante a leitura.")

        return b"".join(chunks)

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível ler a origem por um caminho seguro."
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd is not None:
            os.close(current_fd)


def _read_source_in_project_at(project_fd: int, relative_path: str) -> bytes:
    """Lê um arquivo ancorado no descritor já aberto da raiz do projeto."""

    if (
        not isinstance(project_fd, int)
        or isinstance(project_fd, bool)
        or not isinstance(relative_path, str)
        or not relative_path
    ):
        raise BackupError("Referência à origem do projeto inválida.")

    parts = relative_path.split("/")
    if (
        relative_path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in relative_path
        or "\x00" in relative_path
        or parts[0] == "backups"
    ):
        raise BackupError("Caminho de origem inválido.")

    current_fd = None
    file_fd = None

    try:
        current_fd = os.dup(project_fd)

        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise BackupError("Raiz do projeto inválida.")

        for part in parts[:-1]:
            next_fd = _open_directory_at(current_fd, part)
            os.close(current_fd)
            current_fd = next_fd

        file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)

        before = os.fstat(file_fd)

        if not stat.S_ISREG(before.st_mode):
            raise BackupError("A origem não é um arquivo regular.")

        chunks = []

        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(file_fd)

        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )

        if identity_before != identity_after:
            raise BackupError("O arquivo mudou durante a leitura.")

        return b"".join(chunks)

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível ler a origem por um caminho seguro."
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd is not None:
            os.close(current_fd)



def resolve_project(admin_root: Path, relative_path: str) -> tuple[Path, Path]:
    """Retorna (raiz do projeto, arquivo), validando o caminho informado."""

    if not isinstance(relative_path, str) or not relative_path:
        raise BackupError("Caminho do arquivo obrigatório.")

    if "\x00" in relative_path or "\\" in relative_path:
        raise BackupError("Caminho inválido.")

    if relative_path.startswith("/"):
        raise BackupError("Caminho absoluto não permitido.")

    raw_parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise BackupError("Componentes inválidos no caminho.")

    relative = Path(relative_path)

    try:
        admin_root = Path(admin_root).resolve(strict=True)
    except OSError as exc:
        raise BackupError("Raiz administrativa inacessível.") from exc

    if len(relative.parts) < 2:
        raise BackupError("O caminho precisa identificar um projeto e um arquivo.")

    project_name = relative.parts[0]

    if project_name == "backups":
        raise BackupError("Caminho administrativo não é um projeto.")

    project_root = admin_root / project_name

    try:
        project_info = project_root.lstat()
    except OSError as exc:
        raise BackupError("Raiz do projeto inexistente.") from exc

    if not stat.S_ISDIR(project_info.st_mode):
        raise BackupError("Raiz do projeto inválida.")

    project_root = project_root.resolve(strict=True)

    try:
        project_root.relative_to(admin_root)
    except ValueError as exc:
        raise BackupError("Projeto fora da raiz administrativa.") from exc

    internal_parts = relative.parts[1:]

    # Somente backups diretamente na raiz do projeto é reservado.
    if internal_parts[0] == "backups":
        raise BackupError("A pasta backups é reservada.")

    target = project_root

    for part in internal_parts:
        target = target / part
        try:
            info = target.lstat()
        except OSError as exc:
            raise BackupError("Arquivo ou diretório inexistente.") from exc

        if stat.S_ISLNK(info.st_mode):
            raise BackupError("Links simbólicos não são permitidos.")

    if not stat.S_ISREG(target.lstat().st_mode):
        raise BackupError("O caminho não é um arquivo regular.")

    return project_root, target


def _ensure_directory(parent: Path, name: str) -> Path:
    """Cria um diretório e rejeita links simbólicos e outros tipos de objeto."""

    target = parent / name

    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise BackupError(f"Não foi possível criar o diretório {name}.") from exc

    try:
        info = target.lstat()
    except OSError as exc:
        raise BackupError(f"Diretório inacessível: {name}.") from exc

    if not stat.S_ISDIR(info.st_mode):
        raise BackupError(f"Destino não é um diretório seguro: {name}.")

    return target


def _ensure_backup_tree(project_root: Path, original_path: str) -> tuple[Path, Path]:
    backup_root = _ensure_directory(project_root, "backups")
    current = backup_root

    parts = Path(original_path).parts

    for part in parts:
        current = _ensure_directory(current, part)

    return backup_root, current



def _ensure_backup_tree_at(
    project_fd: int,
    original_path: str,
) -> tuple[int, int]:
    """Cria e abre a árvore de backups usando apenas descritores seguros."""

    if not isinstance(original_path, str) or not original_path:
        raise BackupError("Caminho original inválido.")

    parts = original_path.split("/")

    if (
        original_path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in original_path
        or "\x00" in original_path
        or parts[0] == "backups"
    ):
        raise BackupError("Caminho original inválido.")

    backup_fd = None
    current_fd = None
    success = False

    try:
        backup_fd = _open_directory_at(
            project_fd,
            "backups",
            create=True,
        )

        current_fd = os.dup(backup_fd)

        for part in parts:
            next_fd = _open_directory_at(
                current_fd,
                part,
                create=True,
            )
            os.close(current_fd)
            current_fd = next_fd

        version_fd = current_fd
        current_fd = None
        success = True

        return backup_fd, version_fd

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível criar a árvore de backups com segurança."
        ) from exc
    finally:
        if current_fd is not None:
            os.close(current_fd)

        if backup_fd is not None and not success:
            os.close(backup_fd)


def _safe_backup_file(backup_root: Path, relative_path: str) -> Path:
    """Resolve um backup registrado sem aceitar caminhos externos ou symlinks."""

    if not isinstance(relative_path, str) or not relative_path:
        raise BackupError("Caminho de backup inválido.")

    if relative_path.startswith("/") or "\\" in relative_path:
        raise BackupError("Caminho de backup inválido.")

    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BackupError("Caminho de backup inválido.")

    current = backup_root

    for part in parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise BackupError("Versão registrada não encontrada.") from exc

        if stat.S_ISLNK(info.st_mode):
            raise BackupError("Link simbólico encontrado na árvore de backups.")

    if not stat.S_ISREG(current.lstat().st_mode):
        raise BackupError("A versão registrada não é um arquivo regular.")

    return current



def _load_manifest(
    manifest: Path | int,
    expected_project: str,
) -> list[dict]:
    """Lê e valida o manifesto por descritor de diretório."""

    directory_fd = None
    file_fd = None

    try:
        if isinstance(manifest, int) and not isinstance(manifest, bool):
            directory_fd = os.dup(manifest)
            manifest_name = "manifest.jsonl"
        elif isinstance(manifest, Path):
            directory_fd = _open_absolute_directory(manifest.parent)
            manifest_name = manifest.name
        else:
            raise BackupError("Referência ao manifesto inválida.")

        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise BackupError("Diretório do manifesto inválido.")

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

        try:
            file_fd = os.open(
                manifest_name,
                flags,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return []

        before = os.fstat(file_fd)

        if not stat.S_ISREG(before.st_mode):
            raise BackupError("O manifesto não é um arquivo regular.")

        chunks = []

        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(file_fd)

        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )

        if identity_before != identity_after:
            raise BackupError("O manifesto mudou durante a leitura.")

        data = b"".join(chunks)

        if len(data) != after.st_size:
            raise BackupError("Leitura incompleta do manifesto.")

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Não foi possível abrir ou ler o manifesto com segurança."
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)

    if data and not data.endswith(b"\n"):
        raise BackupError(
            "Manifesto termina com registro incompleto; "
            "conteúdo preservado para investigação."
        )

    events = []

    for line_number, line in enumerate(data.splitlines(), start=1):
        if not line:
            raise BackupError(
                f"Linha vazia inesperada no manifesto: {line_number}."
            )

        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BackupError(
                f"Registro inválido no manifesto, linha {line_number}."
            ) from exc

        if not isinstance(event, dict):
            raise BackupError("Registro do manifesto não é um objeto JSON.")

        events.append(event)

    _validate_manifest_events(events, expected_project)
    return events



def _append_event(backup_root: Path | int, event: dict) -> None:
    """Acrescenta um evento e sincroniza manifesto e diretório."""

    directory_fd = None
    file_fd = None

    encoded = (
        json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        if isinstance(backup_root, int) and not isinstance(backup_root, bool):
            directory_fd = os.dup(backup_root)
        elif isinstance(backup_root, Path):
            directory_fd = _open_absolute_directory(backup_root)
        else:
            raise BackupError("Referência à pasta de backups inválida.")

        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise BackupError("Diretório de backups inválido.")

        file_fd = os.open(
            "manifest.jsonl",
            flags,
            0o600,
            dir_fd=directory_fd,
        )

        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise BackupError("O manifesto não é um arquivo regular.")

        remaining = memoryview(encoded)

        while remaining:
            written = os.write(file_fd, remaining)
            if written <= 0:
                raise OSError("Falha ao escrever o manifesto.")
            remaining = remaining[written:]

        os.fsync(file_fd)
        os.fsync(directory_fd)

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError(
            "Falha ao registrar evento no manifesto."
        ) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)





def _read_backup_at(backup_fd: int, relative_path: str) -> bytes:
    """Lê um backup relativo ao descritor da raiz, sem seguir symlinks."""

    if not isinstance(relative_path, str) or not relative_path:
        raise BackupError("Caminho de backup inválido.")

    parts = relative_path.split("/")
    if (
        relative_path.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in relative_path
        or "\x00" in relative_path
    ):
        raise BackupError("Caminho de backup inválido.")

    directory_fd = os.dup(backup_fd)
    file_fd = None

    try:
        for part in parts[:-1]:
            next_fd = _open_directory_at(directory_fd, part)
            os.close(directory_fd)
            directory_fd = next_fd

        file_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )

        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise BackupError("O backup não é um arquivo regular.")

        chunks = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)

        after = os.fstat(file_fd)

        identity_before = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )

        if identity_before != identity_after:
            raise BackupError("O backup mudou durante a leitura.")

        return b"".join(chunks)

    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("Não foi possível ler o backup com segurança.") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(directory_fd)


class BackupEngine:
    """Cria versões imutáveis e registra eventos em manifesto JSONL."""

    def __init__(self, admin_root: Path):
        try:
            lexical_root = Path(os.path.abspath(os.fspath(admin_root)))
        except (TypeError, ValueError, OSError) as exc:
            raise BackupError("Raiz administrativa inválida.") from exc

        root_fd = _open_absolute_directory(lexical_root)
        try:
            root_info = os.fstat(root_fd)
            self.admin_root = lexical_root
            self._admin_root_identity = (
                root_info.st_dev,
                root_info.st_ino,
            )
        finally:
            os.close(root_fd)

    def create_version(
        self,
        relative_path: str,
        *,
        origin: str,
        trigger: str,
        related_versions: list[str] | None = None,
    ) -> dict:
        if not isinstance(trigger, str) or trigger not in VALID_TRIGGERS:
            raise BackupError("Gatilho de versão inválido.")

        if origin == "auto":
            if trigger != "open":
                raise BackupError(
                    "Origem automática permitida somente na abertura."
                )
        elif not isinstance(origin, str) or origin not in VALID_ORIGINS:
            raise BackupError("Origem de versão inválida.")

        if related_versions is not None:
            if not isinstance(related_versions, list):
                raise BackupError("related_versions precisa ser uma lista.")
            if any(
                not isinstance(item, str)
                or VERSION_PATTERN.fullmatch(item) is None
                for item in related_versions
            ):
                raise BackupError("related_versions contém versão inválida.")

        if not isinstance(relative_path, str) or not relative_path:
            raise BackupError("Caminho do arquivo obrigatório.")

        parts = relative_path.split("/")
        if (
            len(parts) < 2
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative_path
            or "\x00" in relative_path
            or parts[0] == "backups"
            or parts[1] == "backups"
        ):
            raise BackupError("Caminho de origem inválido.")

        project_name = parts[0]
        original_path = "/".join(parts[1:])

        root_fd = None
        project_fd = None
        backup_fd = None
        version_fd = None
        lock_fd = None

        try:
            root_fd = _open_absolute_directory(self.admin_root)
            root_info = os.fstat(root_fd)

            if (
                root_info.st_dev,
                root_info.st_ino,
            ) != self._admin_root_identity:
                raise BackupError("A raiz administrativa foi substituída.")

            project_fd = _open_directory_at(root_fd, project_name)
            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )

            content = _read_source_in_project_at(project_fd, original_path)
            digest = sha256_bytes(content)
            size_bytes = len(content)

            backup_fd, version_fd = _ensure_backup_tree_at(
                project_fd,
                original_path,
            )

            lock_flags = (
                os.O_CREAT
                | os.O_RDWR
                | os.O_NOFOLLOW
            )
            lock_fd = os.open(
                ".manifest.lock",
                lock_flags,
                0o600,
                dir_fd=backup_fd,
            )

            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise BackupError("Arquivo de bloqueio inválido.")

            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            return self._create_locked(
                project_name=project_name,
                root_fd=root_fd,
                project_fd=project_fd,
                backup_root=backup_fd,
                version_dir=version_fd,
                original_path=original_path,
                content=content,
                digest=digest,
                size_bytes=size_bytes,
                origin=origin,
                trigger=trigger,
                related_versions=(
                    related_versions if related_versions is not None else []
                ),
            )

        except BackupError:
            raise
        except OSError as exc:
            raise BackupError("Falha na operação de backup.") from exc
        finally:
            for fd in (lock_fd, version_fd, backup_fd, project_fd, root_fd):
                if fd is not None:
                    os.close(fd)

    def create_version_from_bytes(
        self,
        relative_path: str,
        content: bytes,
        *,
        origin: str,
        trigger: str,
        related_versions: list[str] | None = None,
    ) -> dict:
        """Preserva bytes fornecidos em memória no histórico do projeto."""

        if not isinstance(content, bytes):
            raise BackupError("O conteúdo da versão precisa ser bytes.")

        if not isinstance(trigger, str) or trigger not in VALID_TRIGGERS:
            raise BackupError("Gatilho de versão inválido.")

        if not isinstance(origin, str) or origin not in VALID_ORIGINS:
            raise BackupError("Origem de versão inválida.")

        if related_versions is not None:
            if not isinstance(related_versions, list):
                raise BackupError("related_versions precisa ser uma lista.")
            if any(
                not isinstance(item, str)
                or VERSION_PATTERN.fullmatch(item) is None
                for item in related_versions
            ):
                raise BackupError("related_versions contém versão inválida.")

        if not isinstance(relative_path, str) or not relative_path:
            raise BackupError("Caminho do arquivo obrigatório.")

        parts = relative_path.split("/")
        if (
            len(parts) < 2
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative_path
            or "\x00" in relative_path
            or parts[0] == "backups"
            or parts[1] == "backups"
        ):
            raise BackupError("Caminho de origem inválido.")

        project_name = parts[0]
        original_path = "/".join(parts[1:])
        digest = sha256_bytes(content)
        size_bytes = len(content)

        root_fd = None
        project_fd = None
        backup_fd = None
        version_fd = None
        lock_fd = None

        try:
            root_fd = _open_absolute_directory(self.admin_root)
            root_info = os.fstat(root_fd)

            if (
                root_info.st_dev,
                root_info.st_ino,
            ) != self._admin_root_identity:
                raise BackupError("A raiz administrativa foi substituída.")

            project_fd = _open_directory_at(root_fd, project_name)
            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )

            # Confirma que o caminho de origem ainda aponta para um arquivo
            # regular acessível. O conteúdo preservado vem do argumento.
            _read_source_in_project_at(project_fd, original_path)

            backup_fd, version_fd = _ensure_backup_tree_at(
                project_fd,
                original_path,
            )

            lock_fd = os.open(
                ".manifest.lock",
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
                dir_fd=backup_fd,
            )

            if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                raise BackupError("Arquivo de bloqueio inválido.")

            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            return self._create_locked(
                project_name=project_name,
                root_fd=root_fd,
                project_fd=project_fd,
                backup_root=backup_fd,
                version_dir=version_fd,
                original_path=original_path,
                content=content,
                digest=digest,
                size_bytes=size_bytes,
                origin=origin,
                trigger=trigger,
                related_versions=(
                    related_versions if related_versions is not None else []
                ),
            )

        except BackupError:
            raise
        except OSError as exc:
            raise BackupError(
                "Falha ao preservar conteúdo fornecido em memória."
            ) from exc
        finally:
            for fd in (lock_fd, version_fd, backup_fd, project_fd, root_fd):
                if fd is not None:
                    os.close(fd)

    def read_source(self, relative_path: str) -> bytes:
        """Lê um arquivo do projeto com as mesmas proteções do motor."""

        if not isinstance(relative_path, str) or not relative_path:
            raise BackupError("Caminho do arquivo obrigatório.")

        parts = relative_path.split("/")
        if (
            len(parts) < 2
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative_path
            or "\x00" in relative_path
            or parts[0] == "backups"
            or parts[1] == "backups"
        ):
            raise BackupError("Caminho de origem inválido.")

        project_name = parts[0]
        original_path = "/".join(parts[1:])

        root_fd = None
        project_fd = None

        try:
            root_fd = _open_absolute_directory(self.admin_root)
            root_info = os.fstat(root_fd)

            if (root_info.st_dev, root_info.st_ino) != self._admin_root_identity:
                raise BackupError("A raiz administrativa foi substituída.")

            project_fd = _open_directory_at(root_fd, project_name)
            _assert_project_entry_identity(root_fd, project_name, project_fd)

            content = _read_source_in_project_at(project_fd, original_path)

            _assert_project_entry_identity(root_fd, project_name, project_fd)
            return content

        except BackupError:
            raise
        except OSError as exc:
            raise BackupError("Falha na leitura segura do arquivo.") from exc
        finally:
            for fd in (project_fd, root_fd):
                if fd is not None:
                    os.close(fd)

    def replace_source(
        self,
        relative_path: str,
        content: bytes,
        *,
        expected_sha256: str,
    ) -> dict:
        """Substitui um arquivo somente se o hash original ainda corresponder."""

        if not isinstance(content, bytes):
            raise BackupError("O conteúdo novo precisa ser bytes.")

        if (
            not isinstance(expected_sha256, str)
            or SHA256_PATTERN.fullmatch(expected_sha256) is None
        ):
            raise BackupError("SHA-256 esperado inválido.")

        if not isinstance(relative_path, str) or not relative_path:
            raise BackupError("Caminho do arquivo obrigatório.")

        parts = relative_path.split("/")
        if (
            len(parts) < 2
            or relative_path.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative_path
            or "\x00" in relative_path
            or parts[0] == "backups"
            or parts[1] == "backups"
        ):
            raise BackupError("Caminho de origem inválido.")

        project_name = parts[0]
        original_parts = parts[1:]
        leaf_name = original_parts[-1]
        parent_parts = original_parts[:-1]

        root_fd = None
        project_fd = None
        parent_fd = None
        temp_fd = None
        temp_name = None
        replaced = False

        def assert_parent_identity() -> None:
            """Confirma que o caminho ainda aponta para o diretório aberto."""

            check_fd = os.dup(project_fd)
            try:
                for component in parent_parts:
                    next_fd = _open_directory_at(check_fd, component)
                    os.close(check_fd)
                    check_fd = next_fd

                opened = os.fstat(parent_fd)
                named = os.fstat(check_fd)

                if (
                    not stat.S_ISDIR(named.st_mode)
                    or (opened.st_dev, opened.st_ino)
                    != (named.st_dev, named.st_ino)
                ):
                    raise BackupError(
                        "O diretório de destino foi movido ou substituído."
                    )
            finally:
                os.close(check_fd)

        def read_current(directory_fd: int) -> tuple[bytes, os.stat_result]:
            fd = None
            try:
                fd = os.open(
                    leaf_name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                before = os.fstat(fd)

                if not stat.S_ISREG(before.st_mode):
                    raise BackupError("A origem não é um arquivo regular.")

                chunks = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)

                after = os.fstat(fd)
                identity_before = (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                identity_after = (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                )

                if identity_before != identity_after:
                    raise BackupError(
                        "A origem mudou durante a leitura de validação."
                    )

                return b"".join(chunks), before

            except BackupError:
                raise
            except OSError as exc:
                raise BackupError(
                    "Não foi possível validar a origem com segurança."
                ) from exc
            finally:
                if fd is not None:
                    os.close(fd)

        try:
            root_fd = _open_absolute_directory(self.admin_root)
            root_info = os.fstat(root_fd)

            if (root_info.st_dev, root_info.st_ino) != self._admin_root_identity:
                raise BackupError("A raiz administrativa foi substituída.")

            project_fd = _open_directory_at(root_fd, project_name)
            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )

            parent_fd = os.dup(project_fd)
            for component in parent_parts:
                next_fd = _open_directory_at(parent_fd, component)
                os.close(parent_fd)
                parent_fd = next_fd

            # Primeira validação: não sobrescrever conteúdo já alterado.
            current, source_info = read_current(parent_fd)
            if sha256_bytes(current) != expected_sha256:
                return {
                    "replaced": False,
                    "conflict": True,
                    "durability_confirmed": False,
                }

            original_mode = stat.S_IMODE(source_info.st_mode)

            # Temporário exclusivo dentro do diretório já ancorado.
            temp_name = f".spia-save-{uuid.uuid4().hex}"
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )

            view = memoryview(content)
            written = 0
            while written < len(view):
                count = os.write(temp_fd, view[written:])
                if count <= 0:
                    raise BackupError("Falha ao gravar o arquivo temporário.")
                written += count

            os.fchmod(temp_fd, original_mode)
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None

            # Segunda validação imediatamente antes da substituição.
            latest, _ = read_current(parent_fd)
            if sha256_bytes(latest) != expected_sha256:
                return {
                    "replaced": False,
                    "conflict": True,
                    "durability_confirmed": False,
                }

            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )
            assert_parent_identity()

            os.replace(
                temp_name,
                leaf_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temp_name = None
            replaced = True

            try:
                os.fsync(parent_fd)
            except OSError:
                return {
                    "replaced": True,
                    "conflict": False,
                    "durability_confirmed": False,
                    "sha256": sha256_bytes(content),
                }

            return {
                "replaced": True,
                "conflict": False,
                "durability_confirmed": True,
                "sha256": sha256_bytes(content),
            }

        except BackupError:
            raise
        except OSError as exc:
            if replaced:
                return {
                    "replaced": True,
                    "conflict": False,
                    "durability_confirmed": False,
                    "sha256": sha256_bytes(content),
                }
            raise BackupError("Falha na substituição segura do arquivo.") from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)

            if temp_name is not None and parent_fd is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass

            for fd in (parent_fd, project_fd, root_fd):
                if fd is not None:
                    os.close(fd)

    def _create_locked(
        self,
        *,
        project_name: str,
        root_fd: int,
        project_fd: int,
        backup_root: int,
        version_dir: int,
        original_path: str,
        content: bytes,
        digest: str,
        size_bytes: int,
        origin: str,
        trigger: str,
        related_versions: list[str],
    ) -> dict:
        _assert_project_entry_identity(
            root_fd,
            project_name,
            project_fd,
        )

        events = _load_manifest(backup_root, project_name)

        referenced = {
            event.get("backup_path")
            for event in events
            if isinstance(event.get("backup_path"), str)
        }

        known_orphans = {
            event.get("backup_path")
            for event in events
            if event.get("event_type") == "backup_orphan_detected"
        }

        latest = None
        for event in events:
            if (
                event.get("event_type") == "version_created"
                and event.get("original_path") == original_path
            ):
                latest = event

        # "auto" é uma instrução interna da abertura, nunca uma origem
        # gravada no manifesto.
        # Se o conteúdo já foi preservado para este caminho, recupera a
        # origem da ocorrência correspondente mais recente.
        effective_origin = origin
        if origin == "auto":
            matching_content = [
                event
                for event in events
                if (
                    event.get("event_type") == "version_created"
                    and event.get("original_path") == original_path
                    and event.get("sha256") == digest
                )
            ]

            if matching_content:
                effective_origin = matching_content[-1]["origin"]
            else:
                effective_origin = "initial" if latest is None else "external"

        # Deduplica somente quando caminho, hash e origem correspondem.
        # Todas as candidatas correspondentes precisam continuar íntegras.
        matching_versions = [
            event
            for event in events
            if (
                event.get("event_type") == "version_created"
                and event.get("original_path") == original_path
                and event.get("sha256") == digest
                and event.get("origin") == effective_origin
            )
        ]

        for candidate in matching_versions:
            registered_data = _read_backup_at(
                backup_root,
                candidate.get("backup_path"),
            )

            if (
                len(registered_data) != candidate.get("size_bytes")
                or sha256_bytes(registered_data) != candidate.get("sha256")
            ):
                raise BackupError(
                    "Uma versão histórica correspondente está corrompida; "
                    "deduplicação bloqueada."
                )

        if matching_versions:
            existing = matching_versions[-1]

            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )

            return {
                "created": False,
                "version_id": existing.get("version_id"),
                "sha256": digest,
                "backup_path": existing.get("backup_path"),
            }

        highest = 0

        # IDs registrados nunca são reutilizados.
        for event in events:
            if (
                event.get("event_type") in {
                    "version_created",
                    "backup_orphan_detected",
                }
                and event.get("original_path") == original_path
            ):
                registered_id = event.get("version_id")
                if isinstance(registered_id, str):
                    match = VERSION_PATTERN.fullmatch(registered_id)
                    if match:
                        highest = max(highest, int(match.group(1)))

        # Detecta versões publicadas cujo evento não chegou ao manifesto.
        for name in os.listdir(version_dir):
            info = os.stat(
                name,
                dir_fd=version_dir,
                follow_symlinks=False,
            )

            if stat.S_ISLNK(info.st_mode):
                raise BackupError(
                    "Link simbólico encontrado na pasta de versões."
                )

            match = VERSION_PATTERN.fullmatch(name)
            if not match:
                continue

            if not stat.S_ISREG(info.st_mode):
                raise BackupError("Objeto inesperado na pasta de versões.")

            highest = max(highest, int(match.group(1)))
            relative_backup = f"{original_path}/{name}"

            if (
                relative_backup not in referenced
                and relative_backup not in known_orphans
            ):
                orphan_data = _read_backup_at(
                    backup_root,
                    relative_backup,
                )

                _assert_project_entry_identity(
                    root_fd,
                    project_name,
                    project_fd,
                )

                _append_event(
                    backup_root,
                    {
                        "schema_version": 1,
                        "event_id": str(uuid.uuid4()),
                        "event_type": "backup_orphan_detected",
                        "timestamp": _timestamp(),
                        "project": project_name,
                        "original_path": original_path,
                        "version_id": name,
                        "backup_path": relative_backup,
                        "sha256": sha256_bytes(orphan_data),
                        "size_bytes": len(orphan_data),
                    },
                )

        if highest >= 999999:
            raise BackupError("Limite de numeração de versões atingido.")

        sequence = highest + 1
        version_id = f"versao_{sequence:06d}"
        temp_name = f".spia-pending-{uuid.uuid4().hex}"
        temp_fd = None
        published = False

        try:
            temp_fd = os.open(
                temp_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=version_dir,
            )

            view = memoryview(content)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise BackupError("Falha ao gravar o backup temporário.")
                view = view[written:]

            os.fsync(temp_fd)

            info = os.fstat(temp_fd)
            if not stat.S_ISREG(info.st_mode):
                raise BackupError("Backup temporário inválido.")

            os.lseek(temp_fd, 0, os.SEEK_SET)
            chunks = []
            while True:
                chunk = os.read(temp_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)

            if sha256_bytes(b"".join(chunks)) != digest:
                raise BackupError("Falha na verificação de integridade.")

            _assert_project_entry_identity(
                root_fd,
                project_name,
                project_fd,
            )

            # Publica sem substituir um nome que já exista.
            os.link(
                temp_name,
                version_id,
                src_dir_fd=version_dir,
                dst_dir_fd=version_dir,
                follow_symlinks=False,
            )
            published = True

            os.unlink(temp_name, dir_fd=version_dir)
            temp_name = None

            os.fsync(version_dir)

        except BackupError:
            raise
        except OSError as exc:
            raise BackupError("Não foi possível preservar a versão.") from exc
        finally:
            if temp_fd is not None:
                os.close(temp_fd)

            if temp_name is not None:
                try:
                    os.unlink(temp_name, dir_fd=version_dir)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

        backup_relative = f"{original_path}/{version_id}"

        event = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "event_type": "version_created",
            "timestamp": _timestamp(),
            "project": project_name,
            "original_path": original_path,
            "version_id": version_id,
            "backup_path": backup_relative,
            "sha256": digest,
            "size_bytes": size_bytes,
            "origin": effective_origin,
            "trigger": trigger,
            "related_versions": related_versions,
        }

        # Uma troca após a publicação deixa a versão como órfã detectável.
        _assert_project_entry_identity(
            root_fd,
            project_name,
            project_fd,
        )

        # Se o manifesto falhar, o arquivo publicado permanece órfão detectável.
        _append_event(backup_root, event)

        return {
            "created": True,
            "version_id": version_id,
            "sha256": digest,
            "size_bytes": size_bytes,
            "backup_path": backup_relative,
        }
