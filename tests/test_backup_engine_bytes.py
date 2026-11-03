import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backup_engine import BackupEngine, BackupError


class BackupEngineBytesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.target = self.project / "docs" / "test.txt"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"conteudo atual no disco")

        self.engine = BackupEngine(self.root)
        self.relative = "alpha/docs/test.txt"

    def tearDown(self):
        self.temp.cleanup()

    def events(self):
        manifest = self.project / "backups" / "manifest.jsonl"
        if not manifest.exists():
            return []
        return [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
        ]

    def test_preserva_bytes_recebidos_independentemente_do_disco(self):
        content = b"conteudo B mantido pelo editor"

        result = self.engine.create_version_from_bytes(
            self.relative,
            content,
            origin="spia",
            trigger="conflict",
        )

        backup = self.project / "backups" / result["backup_path"]

        self.assertTrue(result["created"])
        self.assertEqual(result["version_id"], "versao_000001")
        self.assertEqual(backup.read_bytes(), content)
        self.assertNotEqual(backup.read_bytes(), self.target.read_bytes())
        self.assertEqual(
            result["sha256"],
            hashlib.sha256(content).hexdigest(),
        )

        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["origin"], "spia")
        self.assertEqual(events[0]["trigger"], "conflict")
        self.assertEqual(events[0]["sha256"], result["sha256"])

    def test_deduplica_bytes_iguais_a_ultima_versao(self):
        content = b"conteudo preservado"

        first = self.engine.create_version_from_bytes(
            self.relative,
            content,
            origin="spia",
            trigger="conflict",
        )
        second = self.engine.create_version_from_bytes(
            self.relative,
            content,
            origin="spia",
            trigger="conflict",
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertEqual(len(self.events()), 1)

    def test_rejeita_caminhos_inseguros(self):
        invalid_paths = [
            "../fora.txt",
            "alpha/../fora.txt",
            "alpha/backups/manifest.jsonl",
            "/tmp/fora.txt",
            "alpha//arquivo.txt",
            "alpha\\arquivo.txt",
        ]

        for path in invalid_paths:
            with self.subTest(path=path):
                with self.assertRaises(BackupError):
                    self.engine.create_version_from_bytes(
                        path,
                        b"conteudo",
                        origin="spia",
                        trigger="conflict",
                    )

        self.assertEqual(self.events(), [])

    def test_rejeita_conteudo_que_nao_seja_bytes(self):
        invalid_contents = [
            "texto",
            bytearray(b"bytes"),
            None,
        ]

        for content in invalid_contents:
            with self.subTest(content=content):
                with self.assertRaises(BackupError):
                    self.engine.create_version_from_bytes(
                        self.relative,
                        content,
                        origin="spia",
                        trigger="conflict",
                    )

        self.assertEqual(self.events(), [])

    def test_rejeita_origem_inexistente(self):
        with self.assertRaises(BackupError):
            self.engine.create_version_from_bytes(
                "alpha/docs/inexistente.txt",
                b"conteudo",
                origin="spia",
                trigger="conflict",
            )

        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
