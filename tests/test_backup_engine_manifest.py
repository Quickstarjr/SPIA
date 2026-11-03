import json
import tempfile
import unittest
from pathlib import Path

from backup_engine import BackupEngine, BackupError


class BackupManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.root.mkdir()

        self.project = self.root / "alpha"
        self.project.mkdir()

        self.target = self.project / "docs" / "test.txt"
        self.target.parent.mkdir()
        self.target.write_bytes(b"conteudo inicial")

        self.engine = BackupEngine(self.root)
        self.relative = "alpha/docs/test.txt"

        self.engine.create_version(
            self.relative,
            origin="initial",
            trigger="open",
        )

        self.manifest = (
            self.project / "backups" / "manifest.jsonl"
        )

    def tearDown(self):
        self.temp.cleanup()

    def load_events(self):
        return [
            json.loads(line)
            for line in self.manifest.read_text(
                encoding="utf-8"
            ).splitlines()
        ]

    def write_events(self, events):
        data = "".join(
            json.dumps(event, ensure_ascii=False) + "\n"
            for event in events
        )
        self.manifest.write_text(data, encoding="utf-8")

    def assert_manifest_rejected(self):
        before = self.manifest.read_bytes()

        self.target.write_bytes(b"novo conteudo")

        with self.assertRaises(BackupError):
            self.engine.create_version(
                self.relative,
                origin="spia",
                trigger="save",
            )

        self.assertEqual(self.manifest.read_bytes(), before)

        version_dir = (
            self.project / "backups" / "docs" / "test.txt"
        )
        self.assertEqual(
            sorted(p.name for p in version_dir.iterdir()
                   if p.name.startswith("versao_")),
            ["versao_000001"],
        )

    def test_uuid_invalido(self):
        events = self.load_events()
        events[0]["event_id"] = "nao-e-uuid"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_event_id_duplicado(self):
        events = self.load_events()
        duplicate = dict(events[0])
        duplicate["event_type"] = "version_created"
        events.append(duplicate)
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_schema_desconhecido(self):
        events = self.load_events()
        events[0]["schema_version"] = 999
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_evento_desconhecido(self):
        events = self.load_events()
        events[0]["event_type"] = "evento_nao_suportado"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_campo_obrigatorio_ausente(self):
        events = self.load_events()
        del events[0]["sha256"]
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_sha256_malformado(self):
        events = self.load_events()
        events[0]["sha256"] = "123abc"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_size_bytes_negativo(self):
        events = self.load_events()
        events[0]["size_bytes"] = -1
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_size_bytes_booleano(self):
        events = self.load_events()
        events[0]["size_bytes"] = True
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_version_id_invalido(self):
        events = self.load_events()
        events[0]["version_id"] = "../versao_000001"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_caminho_incompativel_com_versao(self):
        events = self.load_events()
        events[0]["backup_path"] = "outro/versao_000001"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_related_versions_com_tipo_incorreto(self):
        events = self.load_events()
        events[0]["related_versions"] = "versao_000001"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_timestamp_sem_fuso(self):
        events = self.load_events()
        events[0]["timestamp"] = "2026-11-01T12:00:00"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_registro_invalido_no_meio_do_historico(self):
        original = self.manifest.read_bytes()
        lines = original.splitlines(keepends=True)

        self.manifest.write_bytes(
            lines[0] + b'{"registro": invalid}\n'
        )

        self.assert_manifest_rejected()


    def test_rejeita_campo_extra(self):
        events = self.load_events()
        events[0]["campo_surpresa"] = "nao previsto"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_rejeita_projeto_incompativel(self):
        events = self.load_events()
        events[0]["project"] = "outro_projeto"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_rejeita_caminho_original_com_traversal(self):
        events = self.load_events()
        events[0]["original_path"] = "../fora/test.txt"
        events[0]["backup_path"] = "../fora/test.txt/versao_000001"
        self.write_events(events)
        self.assert_manifest_rejected()

    def test_rejeita_origin_com_tipo_incorreto(self):
        events = self.load_events()
        events[0]["origin"] = ["initial"]
        self.write_events(events)
        self.assert_manifest_rejected()


if __name__ == "__main__":
    unittest.main(verbosity=2)
