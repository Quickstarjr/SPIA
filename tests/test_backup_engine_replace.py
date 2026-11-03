import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup_engine
from backup_engine import BackupEngine, BackupError


class TestReplaceSource(unittest.TestCase):
    def test_bloqueia_substituicao_se_pasta_destino_for_trocada(self):
        with tempfile.TemporaryDirectory() as tmp:
            admin = Path(tmp)
            project = admin / "projeto"
            destination = project / "sub"
            destination.mkdir(parents=True)

            original = b"conteudo original"
            external = b"arquivo da nova pasta"
            replacement = b"conteudo novo"

            (destination / "arquivo.txt").write_bytes(original)

            engine = BackupEngine(admin)
            expected = hashlib.sha256(original).hexdigest()

            real_fsync = backup_engine.os.fsync
            swapped = False

            def fsync_with_directory_swap(fd):
                nonlocal swapped
                real_fsync(fd)

                if not swapped:
                    swapped = True

                    destination.rename(project / "sub_movida")
                    destination.mkdir()
                    (destination / "arquivo.txt").write_bytes(external)

            with patch.object(
                backup_engine.os,
                "fsync",
                side_effect=fsync_with_directory_swap,
            ):
                with self.assertRaises(BackupError):
                    engine.replace_source(
                        "projeto/sub/arquivo.txt",
                        replacement,
                        expected_sha256=expected,
                    )

            moved_file = project / "sub_movida" / "arquivo.txt"
            current_file = destination / "arquivo.txt"

            self.assertEqual(moved_file.read_bytes(), original)
            self.assertEqual(current_file.read_bytes(), external)

            self.assertFalse(
                any(project.rglob(".spia-save-*")),
                "Um arquivo temporário ficou abandonado.",
            )


    def test_substituicao_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            admin = Path(tmp)
            target = admin / "projeto" / "arquivo.txt"
            target.parent.mkdir()
            original = b"original"
            replacement = b"novo"
            target.write_bytes(original)

            engine = BackupEngine(admin)
            result = engine.replace_source(
                "projeto/arquivo.txt",
                replacement,
                expected_sha256=hashlib.sha256(original).hexdigest(),
            )

            self.assertTrue(result["replaced"])
            self.assertTrue(result["durability_confirmed"])
            self.assertEqual(target.read_bytes(), replacement)
            self.assertFalse(list(target.parent.glob(".spia-save-*")))

    def test_conflito_nao_substitui_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            admin = Path(tmp)
            target = admin / "projeto" / "arquivo.txt"
            target.parent.mkdir()
            current = b"alterado externamente"
            target.write_bytes(current)

            engine = BackupEngine(admin)
            result = engine.replace_source(
                "projeto/arquivo.txt",
                b"novo",
                expected_sha256=hashlib.sha256(b"original").hexdigest(),
            )

            self.assertFalse(result["replaced"])
            self.assertTrue(result["conflict"])
            self.assertEqual(target.read_bytes(), current)
            self.assertFalse(list(target.parent.glob(".spia-save-*")))

    def test_falha_no_replace_preserva_original_e_remove_temporario(self):
        with tempfile.TemporaryDirectory() as tmp:
            admin = Path(tmp)
            target = admin / "projeto" / "arquivo.txt"
            target.parent.mkdir()
            original = b"original"
            target.write_bytes(original)

            engine = BackupEngine(admin)
            with patch.object(
                backup_engine.os,
                "replace",
                side_effect=OSError("falha simulada"),
            ):
                with self.assertRaises(BackupError):
                    engine.replace_source(
                        "projeto/arquivo.txt",
                        b"novo",
                        expected_sha256=hashlib.sha256(original).hexdigest(),
                    )

            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(list(target.parent.glob(".spia-save-*")))

    def test_fsync_da_pasta_falha_apos_substituicao(self):
        with tempfile.TemporaryDirectory() as tmp:
            admin = Path(tmp)
            target = admin / "projeto" / "arquivo.txt"
            target.parent.mkdir()
            original = b"original"
            replacement = b"novo"
            target.write_bytes(original)

            engine = BackupEngine(admin)
            real_fsync = backup_engine.os.fsync
            calls = 0

            def fail_directory_fsync(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("falha simulada no fsync do diretório")
                return real_fsync(fd)

            with patch.object(
                backup_engine.os,
                "fsync",
                side_effect=fail_directory_fsync,
            ):
                result = engine.replace_source(
                    "projeto/arquivo.txt",
                    replacement,
                    expected_sha256=hashlib.sha256(original).hexdigest(),
                )

            self.assertTrue(result["replaced"])
            self.assertFalse(result["durability_confirmed"])
            self.assertEqual(target.read_bytes(), replacement)
            self.assertFalse(list(target.parent.glob(".spia-save-*")))


if __name__ == "__main__":
    unittest.main()
