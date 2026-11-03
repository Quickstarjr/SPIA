import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backup_engine import BackupEngine, BackupError


class BackupEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()
        self.engine = BackupEngine(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def make_file(self, project="alpha", relative="docs/test.txt", content=b"original"):
        project_root = self.root / project
        target = project_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target, f"{project}/{relative}"

    def events(self, project="alpha"):
        manifest = self.root / project / "backups" / "manifest.jsonl"
        if not manifest.exists():
            return []
        return [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
        ]

    def test_primeira_versao_e_deduplicacao(self):
        target, relative = self.make_file()

        first = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )
        second = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        self.assertTrue(first["created"])
        self.assertEqual(first["version_id"], "versao_000001")
        self.assertFalse(second["created"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(len(self.events()), 1)

        backup = self.root / "alpha" / "backups" / first["backup_path"]
        self.assertEqual(backup.read_bytes(), target.read_bytes())

    def test_alteracao_cria_nova_versao(self):
        target, relative = self.make_file()

        first = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        target.write_bytes(b"conteudo alterado")

        second = self.engine.create_version(
            relative, origin="spia", trigger="save"
        )

        self.assertTrue(second["created"])
        self.assertEqual(second["version_id"], "versao_000002")
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(len(self.events()), 2)

    def test_isolamento_entre_projetos(self):
        _, path_a = self.make_file("alpha", content=b"projeto A")
        _, path_b = self.make_file("beta", content=b"projeto B")

        a = self.engine.create_version(
            path_a, origin="initial", trigger="open"
        )
        b = self.engine.create_version(
            path_b, origin="initial", trigger="open"
        )

        self.assertEqual(a["version_id"], "versao_000001")
        self.assertEqual(b["version_id"], "versao_000001")
        self.assertEqual(len(self.events("alpha")), 1)
        self.assertEqual(len(self.events("beta")), 1)

    def test_rejeita_link_simbolico_na_origem(self):
        outside = Path(self.temp.name) / "fora.txt"
        outside.write_text("segredo", encoding="utf-8")

        project = self.root / "alpha"
        project.mkdir()
        link = project / "atalho.txt"
        link.symlink_to(outside)

        with self.assertRaises(BackupError):
            self.engine.create_version(
                "alpha/atalho.txt", origin="initial", trigger="open"
            )

    def test_detecta_e_registra_arquivo_orfao(self):
        target, relative = self.make_file()

        orphan_dir = (
            self.root / "alpha" / "backups" / "docs" / "test.txt"
        )
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "versao_000007"
        orphan.write_bytes(b"versao sem registro")

        result = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        self.assertEqual(result["version_id"], "versao_000008")
        event_types = [event["event_type"] for event in self.events()]
        self.assertIn("backup_orphan_detected", event_types)
        self.assertIn("version_created", event_types)

        # Uma nova versão força outra varredura da pasta de versões.
        target.write_bytes(b"conteudo alterado")

        next_result = self.engine.create_version(
            relative, origin="spia", trigger="save"
        )
        self.assertEqual(next_result["version_id"], "versao_000009")

        orphan_events = [
            event for event in self.events()
            if event["event_type"] == "backup_orphan_detected"
            and event["version_id"] == "versao_000007"
        ]
        self.assertEqual(len(orphan_events), 1)

    def test_falha_no_fsync_do_manifesto_preserva_versao(self):
        _, relative = self.make_file(content=b"original")

        real_fsync = os.fsync
        calls = 0

        def fail_manifest_fsync(fd):
            nonlocal calls
            calls += 1

            # 1: arquivo temporário
            # 2: diretório da versão publicada
            # 3: arquivo do manifesto
            if calls == 3:
                raise OSError("falha simulada no fsync do manifesto")

            return real_fsync(fd)

        with patch(
            "backup_engine.os.fsync",
            side_effect=fail_manifest_fsync,
        ):
            with self.assertRaises(BackupError):
                self.engine.create_version(
                    relative, origin="initial", trigger="open"
                )

        self.assertEqual(calls, 3)

        backup = (
            self.root / "alpha" / "backups"
            / "docs" / "test.txt" / "versao_000001"
        )
        self.assertEqual(backup.read_bytes(), b"original")

        # Os bytes do evento foram escritos antes da falha no fsync.
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "version_created")

        # A nova tentativa reconhece a versão e não cria outra.
        retry = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )
        self.assertFalse(retry["created"])
        self.assertEqual(retry["version_id"], "versao_000001")
        self.assertEqual(len(self.events()), 1)

    def test_rejeita_deduplicacao_se_backup_mais_recente_foi_corrompido(self):
        _, relative = self.make_file()

        result = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        backup = self.root / "alpha" / "backups" / result["backup_path"]
        backup.write_bytes(b"conteudo corrompido")

        with self.assertRaises(BackupError):
            self.engine.create_version(
                relative, origin="initial", trigger="open"
            )

    def test_concorrencia_nao_duplica_mesmo_conteudo(self):
        _, relative = self.make_file(content=b"mesmo conteudo")

        def create():
            return self.engine.create_version(
                relative, origin="initial", trigger="open"
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: create(), range(8)))

        created = [result for result in results if result["created"]]
        self.assertEqual(len(created), 1)
        self.assertEqual(len(self.events()), 1)

    def test_falha_no_manifesto_deixa_orfao_detectavel(self):
        _, relative = self.make_file()

        with patch(
            "backup_engine._append_event",
            side_effect=BackupError("falha simulada no manifesto"),
        ):
            with self.assertRaises(BackupError):
                self.engine.create_version(
                    relative, origin="initial", trigger="open"
                )

        version_dir = (
            self.root / "alpha" / "backups" / "docs" / "test.txt"
        )
        self.assertTrue((version_dir / "versao_000001").exists())
        self.assertEqual(self.events(), [])

        # A próxima tentativa deve detectar o arquivo sem registro.
        result = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )
        self.assertEqual(result["version_id"], "versao_000002")

        event_types = [event["event_type"] for event in self.events()]
        self.assertIn("backup_orphan_detected", event_types)

    def test_manifesto_com_cauda_incompleta_nao_deve_ser_alterado(self):
        _, relative = self.make_file()

        self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        manifest = self.root / "alpha" / "backups" / "manifest.jsonl"
        with manifest.open("ab") as file:
            file.write(b'{"registro":"incompleto"')

        before = manifest.read_bytes()

        # O manifesto é append-only: não deve ser truncado silenciosamente.
        with self.assertRaises(BackupError):
            self.engine.create_version(
                relative, origin="initial", trigger="open"
            )

        self.assertEqual(manifest.read_bytes(), before)

    def test_nao_reutiliza_id_de_versao_ja_registrado(self):
        target, relative = self.make_file()

        first = self.engine.create_version(
            relative, origin="initial", trigger="open"
        )

        backup = self.root / "alpha" / "backups" / first["backup_path"]
        backup.unlink()

        target.write_bytes(b"segunda versao")

        second = self.engine.create_version(
            relative, origin="spia", trigger="save"
        )

        # O identificador anterior continua registrado no histórico.
        self.assertEqual(second["version_id"], "versao_000002")


if __name__ == "__main__":
    unittest.main(verbosity=2)
