import json
import os
import stat
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backup_engine import (
    BackupEngine,
    BackupError,
    _load_manifest,
    _open_directory_at,
    _ensure_backup_tree_at,
    _read_source_at,
    _read_source_in_project_at,
    _assert_project_entry_identity,
)


class BackupEngineHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "projects"
        self.root.mkdir()

        self.project = self.root / "alpha"
        self.project.mkdir()

        self.target = self.project / "docs" / "test.txt"
        self.target.parent.mkdir()
        self.target.write_bytes(b"conteudo inicial")

        self.engine = BackupEngine(self.root)
        self.relative = "alpha/docs/test.txt"

    def tearDown(self):
        self.temp.cleanup()

    def test_leitura_permanece_ancorada_apos_substituicao_do_projeto(self):
        project_fd = os.open(
            self.project,
            os.O_RDONLY | os.O_DIRECTORY,
        )

        moved_project = self.root / "alpha_original"

        try:
            # O descritor já aponta para o projeto original.
            original_identity = (
                os.fstat(project_fd).st_dev,
                os.fstat(project_fd).st_ino,
            )

            # Remove o nome original sem fechar o descritor.
            self.project.rename(moved_project)

            # Cria outro projeto com o mesmo nome e conteúdo diferente.
            self.project.mkdir()
            replacement_target = self.project / "docs" / "test.txt"
            replacement_target.parent.mkdir()
            replacement_target.write_bytes(b"conteudo substituto")

            replacement_identity = (
                self.project.stat().st_dev,
                self.project.stat().st_ino,
            )

            self.assertNotEqual(original_identity, replacement_identity)

            # A leitura deve seguir o descritor, não o nome antigo.
            content = _read_source_in_project_at(
                project_fd,
                "docs/test.txt",
            )

            self.assertEqual(content, b"conteudo inicial")
            self.assertEqual(
                replacement_target.read_bytes(),
                b"conteudo substituto",
            )

        finally:
            os.close(project_fd)

    def test_identidade_detecta_substituicao_do_projeto(self):
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        project_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)

        try:
            _assert_project_entry_identity(
                root_fd,
                "alpha",
                project_fd,
            )

            moved = self.root / "alpha_original"
            self.project.rename(moved)
            self.project.mkdir()

            with self.assertRaises(BackupError):
                _assert_project_entry_identity(
                    root_fd,
                    "alpha",
                    project_fd,
                )
        finally:
            os.close(project_fd)
            os.close(root_fd)

    def test_create_version_aborta_se_projeto_for_substituido(self):
        moved = self.root / "alpha_original"

        def replace_project_after_read(project_fd, original_path):
            content = _read_source_in_project_at(
                project_fd,
                original_path,
            )

            self.project.rename(moved)
            self.project.mkdir()

            replacement = self.project / "docs" / "test.txt"
            replacement.parent.mkdir()
            replacement.write_bytes(b"conteudo substituto")

            return content

        with patch(
            "backup_engine._read_source_in_project_at",
            side_effect=replace_project_after_read,
        ):
            with self.assertRaises(BackupError):
                self.engine.create_version(
                    self.relative,
                    origin="spia",
                    trigger="save",
                )

        self.assertEqual(
            (self.project / "docs" / "test.txt").read_bytes(),
            b"conteudo substituto",
        )

        version_dir = moved / "backups" / "docs" / "test.txt"
        if version_dir.exists():
            self.assertEqual(
                list(version_dir.glob("versao_*")),
                [],
            )

    def test_construtor_rejeita_raiz_com_link_simbolico(self):
        alias = self.base / "projects_alias"
        alias.symlink_to(self.root, target_is_directory=True)

        with self.assertRaises(BackupError):
            BackupEngine(alias)

        # A raiz verdadeira continua acessível.
        valid_engine = BackupEngine(self.root)
        self.assertEqual(valid_engine.admin_root, self.root)

    def manifest(self):
        return self.project / "backups" / "manifest.jsonl"

    def events(self):
        if not self.manifest().exists():
            return []

        return [
            json.loads(line)
            for line in self.manifest().read_text(
                encoding="utf-8"
            ).splitlines()
        ]

    def version_files(self):
        version_dir = (
            self.project / "backups" / "docs" / "test.txt"
        )
        if not version_dir.exists():
            return []

        return sorted(
            p for p in version_dir.iterdir()
            if p.name.startswith("versao_")
        )


    def test_open_directory_at_cria_e_abre_diretorio(self):
        parent_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)

        try:
            directory_fd = _open_directory_at(
                parent_fd,
                "novo_diretorio",
                create=True,
            )

            try:
                info = os.fstat(directory_fd)
                self.assertTrue(os.path.isdir(
                    self.project / "novo_diretorio"
                ))
                self.assertTrue(stat.S_ISDIR(info.st_mode))
            finally:
                os.close(directory_fd)

        finally:
            os.close(parent_fd)

    def test_open_directory_at_rejeita_symlink(self):
        outside = self.base / "fora"
        outside.mkdir()

        (self.project / "link_diretorio").symlink_to(
            outside,
            target_is_directory=True,
        )

        parent_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)

        try:
            with self.assertRaises(BackupError):
                _open_directory_at(parent_fd, "link_diretorio")
        finally:
            os.close(parent_fd)

        self.assertEqual(list(outside.iterdir()), [])

    def test_open_directory_at_rejeita_nomes_invalidos(self):
        parent_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)

        try:
            for name in ("", ".", "..", "a/b", "a\\\\b", "a\\x00b"):
                with self.subTest(name=repr(name)):
                    with self.assertRaises(BackupError):
                        _open_directory_at(
                            parent_fd,
                            name,
                            create=True,
                        )
        finally:
            os.close(parent_fd)



    def test_ensure_backup_tree_at_cria_arvore_aninhada(self):
        project_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)
        try:
            backup_fd, version_fd = _ensure_backup_tree_at(
                project_fd, "docs/sub/test.txt"
            )
            try:
                backup_path = self.project / "backups"
                version_path = backup_path / "docs" / "sub" / "test.txt"

                self.assertTrue(version_path.is_dir())
                self.assertEqual(os.fstat(backup_fd).st_ino, backup_path.stat().st_ino)
                self.assertEqual(os.fstat(version_fd).st_ino, version_path.stat().st_ino)
            finally:
                os.close(version_fd)
                os.close(backup_fd)
        finally:
            os.close(project_fd)

    def test_ensure_backup_tree_at_rejeita_symlink_interno(self):
        outside = self.base / "fora"
        outside.mkdir()

        backup_path = self.project / "backups"
        backup_path.mkdir()
        (backup_path / "docs").symlink_to(outside, target_is_directory=True)

        project_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaises(BackupError):
                _ensure_backup_tree_at(project_fd, "docs/test.txt")
        finally:
            os.close(project_fd)

        self.assertEqual(list(outside.iterdir()), [])

    def test_ensure_backup_tree_at_rejeita_caminhos_invalidos(self):
        project_fd = os.open(self.project, os.O_RDONLY | os.O_DIRECTORY)
        try:
            invalid_paths = (
                "",
                "/absoluto/arquivo.txt",
                "../fora.txt",
                "docs/../fora.txt",
                "docs//arquivo.txt",
                "backups/manifest.jsonl",
                "docs\\arquivo.txt",
                "docs\x00arquivo.txt",
            )

            for relative_path in invalid_paths:
                with self.subTest(path=repr(relative_path)):
                    with self.assertRaises(BackupError):
                        _ensure_backup_tree_at(project_fd, relative_path)
        finally:
            os.close(project_fd)

        self.assertFalse((self.project / "backups").exists())

    def test_open_absolute_directory_abre_caminho_seguro(self):
        from backup_engine import _open_absolute_directory

        directory_fd = _open_absolute_directory(self.project)

        try:
            info = os.fstat(directory_fd)
            self.assertTrue(stat.S_ISDIR(info.st_mode))
            self.assertEqual(info.st_ino, self.project.stat().st_ino)
        finally:
            os.close(directory_fd)

    def test_open_absolute_directory_rejeita_symlink(self):
        from backup_engine import _open_absolute_directory

        outside = self.base / "outside"
        outside.mkdir()

        link = self.base / "link"
        link.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(BackupError):
            _open_absolute_directory(link)

    def test_open_absolute_directory_rejeita_caminho_relativo(self):
        from backup_engine import _open_absolute_directory

        with self.assertRaises(BackupError):
            _open_absolute_directory(Path("projeto"))

    def test_concorrencia_com_conteudos_diferentes(self):
        barrier = threading.Barrier(2)
        guard = threading.Lock()
        assigned = {}

        contents = [b"conteudo A", b"conteudo B"]

        def controlled_read(_admin_root, _relative_path):
            barrier.wait(timeout=5)

            thread_id = threading.get_ident()
            with guard:
                if thread_id not in assigned:
                    assigned[thread_id] = contents[len(assigned)]
                return assigned[thread_id]

        with patch(
            "backup_engine._read_source_in_project_at",
            side_effect=controlled_read,
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self.engine.create_version,
                        self.relative,
                        origin="spia",
                        trigger="save",
                    )
                    for _ in range(2)
                ]
                results = [future.result(timeout=10) for future in futures]

        self.assertEqual(len(assigned), 2)
        self.assertEqual(
            {result["version_id"] for result in results},
            {"versao_000001", "versao_000002"},
        )

        versions = self.version_files()
        self.assertEqual(len(versions), 2)
        self.assertEqual(
            {path.read_bytes() for path in versions},
            {b"conteudo A", b"conteudo B"},
        )
        self.assertEqual(
            len([
                event for event in self.events()
                if event["event_type"] == "version_created"
            ]),
            2,
        )

    def test_rejeita_manifesto_com_json_invalido_sem_alterar_bytes(self):
        self.engine.create_version(
            self.relative,
            origin="initial",
            trigger="open",
        )

        with self.manifest().open("ab") as file:
            file.write(b'{"registro": invalid}\n')

        before = self.manifest().read_bytes()

        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative,
                origin="spia",
                trigger="save",
            )

        self.assertEqual(self.manifest().read_bytes(), before)

    def test_rejeita_manifesto_com_link_simbolico(self):
        outside = self.base / "manifesto_externo.jsonl"
        outside.write_text("", encoding="utf-8")

        backup_root = self.project / "backups"
        backup_root.mkdir()

        self.manifest().symlink_to(outside)

        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative,
                origin="initial",
                trigger="open",
            )

        self.assertEqual(outside.read_bytes(), b"")

    def test_rejeita_link_simbolico_na_arvore_de_backups(self):
        outside = self.base / "diretorio_externo"
        outside.mkdir()

        backup_root = self.project / "backups"
        backup_root.mkdir()

        (backup_root / "docs").symlink_to(
            outside,
            target_is_directory=True,
        )

        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative,
                origin="initial",
                trigger="open",
            )

        self.assertEqual(list(outside.iterdir()), [])

    def test_falha_na_publicacao_nao_deixa_temporario(self):
        with patch(
            "backup_engine.os.link",
            side_effect=OSError("falha simulada na publicação"),
        ):
            with self.assertRaises(BackupError):
                self.engine.create_version(
                    self.relative,
                    origin="initial",
                    trigger="open",
                )

        version_dir = (
            self.project / "backups" / "docs" / "test.txt"
        )

        self.assertEqual(
            list(version_dir.glob(".spia-pending-*")),
            [],
        )
        self.assertEqual(
            list(version_dir.glob("versao_*")),
            [],
        )
        self.assertEqual(self.events(), [])

    def test_versoes_antigas_permanecem_inalteradas(self):
        first_content = self.target.read_bytes()

        first = self.engine.create_version(
            self.relative,
            origin="initial",
            trigger="open",
        )

        first_backup = (
            self.project / "backups" / first["backup_path"]
        )
        first_bytes = first_backup.read_bytes()

        self.target.write_bytes(b"segunda versao")
        self.engine.create_version(
            self.relative,
            origin="spia",
            trigger="save",
        )

        self.target.write_bytes(b"terceira versao")
        self.engine.create_version(
            self.relative,
            origin="spia",
            trigger="save",
        )

        self.assertEqual(first_backup.read_bytes(), first_bytes)
        self.assertEqual(first_bytes, first_content)
        self.assertEqual(len(self.version_files()), 3)

    def test_rejeita_caminhos_maliciosos_e_pasta_reservada(self):
        invalid_paths = [
            "../alpha/docs/test.txt",
            "alpha/../alpha/docs/test.txt",
            "/alpha/docs/test.txt",
            "alpha//docs/test.txt",
            "alpha/./docs/test.txt",
            "alpha/backups/manifest.jsonl",
            "backups/manifest.jsonl",
        ]

        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaises(BackupError):
                    self.engine.create_version(
                        path,
                        origin="initial",
                        trigger="open",
                    )

        self.assertFalse((self.project / "backups").exists())


    def test_leitura_segura_rejeita_barra_invertida_e_nul(self):
        invalid_paths = [
            "alpha/docs\\test.txt",
            "alpha/docs/\x00test.txt",
        ]

        for relative_path in invalid_paths:
            with self.subTest(path=repr(relative_path)):
                with self.assertRaises(BackupError):
                    _read_source_at(self.root, relative_path)

    def test_aceita_subpasta_interna_chamada_backups(self):
        target = self.project / "docs" / "backups" / "test.txt"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"conteudo da subpasta")

        result = self.engine.create_version(
            "alpha/docs/backups/test.txt",
            origin="initial",
            trigger="open",
        )

        self.assertTrue(result["created"])
        saved = self.project / "backups" / result["backup_path"]
        self.assertEqual(saved.read_bytes(), b"conteudo da subpasta")

    def test_manifesto_aberto_nao_segue_symlink_substituto(self):
        self.engine.create_version(
            self.relative,
            origin="initial",
            trigger="open",
        )

        manifest = self.manifest()
        original_bytes = manifest.read_bytes()

        displaced = manifest.with_name("manifesto_original.jsonl")
        outside = self.base / "manifesto_externo.jsonl"
        outside.write_bytes(b"NAO ALTERAR")

        real_read = os.read
        swapped = False

        def replace_name_after_open(fd, amount):
            nonlocal swapped

            if not swapped:
                os.replace(manifest, displaced)
                manifest.symlink_to(outside)
                swapped = True

            return real_read(fd, amount)

        with patch(
            "backup_engine.os.read",
            side_effect=replace_name_after_open,
        ):
            with self.assertRaises(BackupError):
                _load_manifest(manifest, "alpha")

        self.assertTrue(swapped)
        self.assertEqual(displaced.read_bytes(), original_bytes)
        self.assertEqual(outside.read_bytes(), b"NAO ALTERAR")
        self.assertTrue(manifest.is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
