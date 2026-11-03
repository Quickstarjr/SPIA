import json
import tempfile
import unittest
from pathlib import Path

from backup_engine import BackupEngine, BackupError


class BackupEngineAutoOriginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.target = self.project / "docs" / "test.txt"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"conteudo inicial")
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

    def test_primeira_abertura_usa_initial(self):
        result = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )

        self.assertTrue(result["created"])
        self.assertEqual(result["version_id"], "versao_000001")
        self.assertEqual(self.events()[0]["origin"], "initial")

    def test_reabertura_sem_mudanca_deduplica(self):
        first = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )
        second = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.events()[0]["origin"], "initial")

    def test_abertura_apos_alteracao_externa_usa_external(self):
        first = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )
        self.target.write_bytes(b"alteracao externa")

        second = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )

        self.assertTrue(second["created"])
        self.assertEqual(first["version_id"], "versao_000001")
        self.assertEqual(second["version_id"], "versao_000002")

        events = self.events()
        self.assertEqual([event["origin"] for event in events],
                         ["initial", "external"])

    def test_reaparecimento_de_versao_antiga_nao_cria_duplicata(self):
        conteudo_c = b"versao externa C"
        conteudo_b = b"versao do editor B"

        self.target.write_bytes(conteudo_c)
        primeira_c = self.engine.create_version(
            self.relative, origin="external", trigger="conflict"
        )

        self.target.write_bytes(conteudo_b)
        versao_b = self.engine.create_version(
            self.relative, origin="spia", trigger="conflict"
        )

        self.target.write_bytes(conteudo_c)
        c_reaparecida = self.engine.create_version(
            self.relative, origin="auto", trigger="open"
        )

        self.assertTrue(primeira_c["created"])
        self.assertTrue(versao_b["created"])
        self.assertFalse(c_reaparecida["created"])
        self.assertEqual(
            c_reaparecida["version_id"],
            primeira_c["version_id"],
        )
        self.assertEqual(c_reaparecida["sha256"], primeira_c["sha256"])
        self.assertEqual(len(self.events()), 2)

    def test_mesmo_hash_com_origem_diferente_nao_deduplica(self):
        self.target.write_bytes(b"mesmo conteudo")
        versao_spia = self.engine.create_version(
            self.relative, origin="spia", trigger="conflict"
        )
        versao_external = self.engine.create_version(
            self.relative, origin="external", trigger="conflict"
        )

        self.assertTrue(versao_spia["created"])
        self.assertTrue(versao_external["created"])
        self.assertNotEqual(
            versao_spia["version_id"], versao_external["version_id"]
        )
        self.assertEqual(
            [event["origin"] for event in self.events()],
            ["spia", "external"],
        )

    def test_backup_historico_corrompido_bloqueia_deduplicacao(self):
        conteudo_c = b"versao externa C"
        conteudo_b = b"versao do editor B"

        self.target.write_bytes(conteudo_c)
        primeira_c = self.engine.create_version(
            self.relative, origin="external", trigger="conflict"
        )

        self.target.write_bytes(conteudo_b)
        self.engine.create_version(
            self.relative, origin="spia", trigger="conflict"
        )

        backup_c = self.project / "backups" / primeira_c["backup_path"]
        backup_c.write_bytes(b"conteudo corrompido")

        self.target.write_bytes(conteudo_c)
        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative, origin="auto", trigger="open"
            )

    def test_auto_nao_e_permitido_em_salvamento(self):
        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative, origin="auto", trigger="save"
            )

        self.assertEqual(self.events(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
