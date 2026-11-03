import tempfile
import unittest
from pathlib import Path

from backup_engine import BackupEngine, BackupError


class BackupEngineReadSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.target = self.project / "docs" / "test.txt"

        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"conteudo seguro")

        self.engine = BackupEngine(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_leitura_devolve_bytes_originais(self):
        content = self.engine.read_source("alpha/docs/test.txt")
        self.assertEqual(content, b"conteudo seguro")
        self.assertIsInstance(content, bytes)

    def test_leitura_detecta_conteudo_atualizado(self):
        self.target.write_bytes(b"conteudo atualizado")
        content = self.engine.read_source("alpha/docs/test.txt")
        self.assertEqual(content, b"conteudo atualizado")

    def test_leitura_rejeita_link_simbolico(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_bytes(b"nao ler")

        self.target.unlink()
        self.target.symlink_to(outside)

        with self.assertRaises(BackupError):
            self.engine.read_source("alpha/docs/test.txt")

    def test_leitura_rejeita_arquivo_administrativo(self):
        with self.assertRaises(BackupError):
            self.engine.read_source("arquivo.txt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
