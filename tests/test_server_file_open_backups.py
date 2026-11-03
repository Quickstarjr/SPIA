import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backup_engine import BackupEngine, BackupError


class ServerFileOpenBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.target = self.project / "docs" / "test.txt"

        self.target.parent.mkdir(parents=True)
        self.target.write_text("conteudo original", encoding="utf-8")

        self.engine = BackupEngine(self.root)

        self.project_patch = patch.object(server, "PROJECT", self.root)
        self.engine_patch = patch.object(server, "BACKUP_ENGINE", self.engine)

        self.project_patch.start()
        self.engine_patch.start()

        self.addCleanup(self.project_patch.stop)
        self.addCleanup(self.engine_patch.stop)
        self.addCleanup(self.temp.cleanup)

        self.client = TestClient(server.app)

    def abrir(self, path="alpha/docs/test.txt"):
        return self.client.get("/api/file", params={"path": path})

    def eventos(self):
        manifest = self.project / "backups" / "manifest.jsonl"
        if not manifest.exists():
            return []
        return [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
        ]

    def versoes(self):
        folder = self.project / "backups" / "docs" / "test.txt"
        if not folder.exists():
            return []
        return sorted(p.name for p in folder.iterdir() if p.is_file())

    def test_primeira_abertura_preserva_versao_initial(self):
        response = self.abrir()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "conteudo original")
        self.assertEqual(self.versoes(), ["versao_000001"])

        events = self.eventos()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["origin"], "initial")

    def test_reabertura_sem_mudanca_nao_duplica(self):
        first = self.abrir()
        second = self.abrir()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.versoes(), ["versao_000001"])
        self.assertEqual(len(self.eventos()), 1)

    def test_alteracao_externa_cria_versao_external(self):
        first = self.abrir()
        self.target.write_text("alteracao externa", encoding="utf-8")
        second = self.abrir()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["content"], "alteracao externa")
        self.assertEqual(
            self.versoes(),
            ["versao_000001", "versao_000002"],
        )

        events = self.eventos()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["origin"], "initial")
        self.assertEqual(events[1]["origin"], "external")

    def test_arquivo_administrativo_na_raiz_nao_gera_backup(self):
        admin_file = self.root / "README.txt"
        admin_file.write_text("arquivo administrativo", encoding="utf-8")

        response = self.abrir("README.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "arquivo administrativo")
        self.assertFalse((self.project / "backups").exists())

    def test_falha_no_backup_impede_abertura(self):
        with patch.object(
            self.engine,
            "create_version",
            side_effect=BackupError("falha simulada"),
        ):
            response = self.abrir()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.target.read_text(encoding="utf-8"), "conteudo original")

    def test_mudanca_apos_backup_retorna_conflito(self):
        original_create = self.engine.create_version

        def create_then_change(*args, **kwargs):
            result = original_create(*args, **kwargs)
            self.target.write_text("mudou durante abertura", encoding="utf-8")
            return result

        with patch.object(
            self.engine,
            "create_version",
            side_effect=create_then_change,
        ):
            response = self.abrir()

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.target.read_text(encoding="utf-8"),
            "mudou durante abertura",
        )
        self.assertEqual(self.versoes(), ["versao_000001"])

    def test_link_simbolico_na_origem_e_rejeitado(self):
        real_file = self.target.parent / "real.txt"
        real_file.write_text("conteudo real", encoding="utf-8")

        link = self.target.parent / "link.txt"
        link.symlink_to(real_file)

        response = self.abrir("alpha/docs/link.txt")

        self.assertEqual(response.status_code, 400)
        self.assertFalse((self.project / "backups").exists())

    def test_arquivo_maior_que_limite_nao_e_preservado(self):
        large = self.target.parent / "large.txt"
        large.write_bytes(b"x" * (server.MAX_READ_BYTES + 1))

        response = self.abrir("alpha/docs/large.txt")

        self.assertEqual(response.status_code, 413)
        self.assertFalse((self.project / "backups").exists())

    def test_arquivo_binario_nao_e_preservado(self):
        binary = self.target.parent / "binary.dat"
        binary.write_bytes(b"\xff\xfe\x00\x81")

        response = self.abrir("alpha/docs/binary.dat")

        self.assertEqual(response.status_code, 415)
        self.assertFalse((self.project / "backups").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
