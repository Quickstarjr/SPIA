import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backup_engine import BackupEngine, BackupError


class ServerFileSaveBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.target = self.project / "docs" / "test.txt"

        self.target.parent.mkdir(parents=True)
        self.original = b"conteudo original A"
        self.target.write_bytes(self.original)

        self.engine = BackupEngine(self.root)
        self.relative = "alpha/docs/test.txt"

        self.project_patch = patch.object(server, "PROJECT", self.root)
        self.engine_patch = patch.object(server, "BACKUP_ENGINE", self.engine)

        self.project_patch.start()
        self.engine_patch.start()

        self.addCleanup(self.project_patch.stop)
        self.addCleanup(self.engine_patch.stop)
        self.addCleanup(self.temp.cleanup)

        self.client = TestClient(server.app)

        # Simula a abertura inicial pelo editor.
        self.engine.create_version(
            self.relative,
            origin="initial",
            trigger="open",
        )

    def hash(self, data):
        return hashlib.sha256(data).hexdigest()

    def salvar(self, content, expected=None):
        if expected is None:
            expected = self.hash(self.original)

        return self.client.post(
            "/api/file",
            json={
                "path": self.relative,
                "content": content.decode("utf-8"),
                "expected_sha256": expected,
            },
        )

    def assert_save_error_contract(
        self, response, status, code,
        preservation_complete, source_replaced
    ):
        self.assertEqual(response.status_code, status)
        detail = response.json().get("detail")

        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("code"), code)
        self.assertIsInstance(detail.get("message"), str)
        self.assertTrue(detail["message"].strip())
        self.assertIs(
            detail.get("preservation_complete"),
            preservation_complete,
        )
        self.assertIs(
            detail.get("source_replaced"),
            source_replaced,
        )

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
        return sorted(
            p.name for p in folder.iterdir()
            if p.is_file() and p.name.startswith("versao_")
        )

    def backup_bytes(self, version):
        path = (
            self.project / "backups" / "docs" / "test.txt" / version
        )
        return path.read_bytes()

    def test_salvamento_normal_preserva_B_antes_de_gravar(self):
        content_b = b"conteudo novo B"

        response = self.salvar(content_b)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "SAVE_COMPLETED")
        self.assertIsInstance(data["message"], str)
        self.assertTrue(data["message"].strip())
        self.assertTrue(data["saved"])
        self.assertTrue(data["source_replaced"])
        self.assertTrue(data["preservation_complete"])
        self.assertTrue(data["durability_confirmed"])
        self.assertIsNone(data["warning"])
        self.assertEqual(data["sha256"], self.hash(content_b))
        self.assertEqual(self.target.read_bytes(), content_b)

        self.assertEqual(
            self.versoes(),
            ["versao_000001", "versao_000002"],
        )
        self.assertEqual(self.backup_bytes("versao_000002"), content_b)

        events = self.eventos()
        self.assertEqual(
            [event["origin"] for event in events],
            ["initial", "spia"],
        )
        self.assertEqual(events[1]["trigger"], "save")

    def test_conflito_preserva_B_e_C_sem_alterar_disco(self):
        content_b = b"conteudo do editor B"
        content_c = b"conteudo externo C"
        self.target.write_bytes(content_c)

        response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 409, "SAVE_CONFLICT", True, False
        )
        self.assertEqual(self.target.read_bytes(), content_c)

        self.assertEqual(
            self.versoes(),
            ["versao_000001", "versao_000002", "versao_000003"],
        )
        self.assertEqual(self.backup_bytes("versao_000002"), content_c)
        self.assertEqual(self.backup_bytes("versao_000003"), content_b)

        events = self.eventos()
        self.assertEqual(
            [event["origin"] for event in events],
            ["initial", "external", "spia"],
        )
        self.assertEqual(events[1]["trigger"], "conflict")
        self.assertEqual(events[2]["trigger"], "conflict")

    def test_conflito_com_B_igual_a_C_nao_duplica(self):
        same_content = b"mesmo conteudo B e C"
        self.target.write_bytes(same_content)

        response = self.salvar(same_content)

        self.assert_save_error_contract(
            response, 409, "SAVE_CONFLICT", True, False
        )
        self.assertEqual(self.target.read_bytes(), same_content)

        self.assertEqual(
            self.versoes(),
            ["versao_000001", "versao_000002"],
        )

        events = self.eventos()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["origin"], "external")
        self.assertEqual(events[1]["trigger"], "conflict")
        self.assertEqual(self.backup_bytes("versao_000002"), same_content)

    def test_falha_no_backup_B_impede_salvamento(self):
        content_b = b"conteudo B"

        with patch.object(
            self.engine,
            "create_version_from_bytes",
            side_effect=BackupError("falha simulada"),
        ):
            response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 503, "BACKUP_PRESERVATION_FAILED", False, False
        )
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.versoes(), ["versao_000001"])

    def test_falha_no_backup_C_bloqueia_salvamento_mas_preserva_B(self):
        content_b = b"conteudo B"
        content_c = b"conteudo externo C"
        self.target.write_bytes(content_c)

        real_preserve = self.engine.create_version_from_bytes
        calls = 0

        def fail_first(data, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise BackupError("falha simulada ao preservar C")
            return real_preserve(data, *args, **kwargs)

        with patch.object(
            self.engine,
            "create_version_from_bytes",
            side_effect=fail_first,
        ):
            response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 503, "BACKUP_PRESERVATION_FAILED", False, False
        )
        self.assertEqual(self.target.read_bytes(), content_c)
        self.assertEqual(calls, 2)

        events = self.eventos()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["origin"], "spia")
        self.assertEqual(self.backup_bytes("versao_000002"), content_b)

    def test_falha_no_backup_B_apos_preservar_C_bloqueia_salvamento(self):
        content_b = b"conteudo B"
        content_c = b"conteudo externo C"
        self.target.write_bytes(content_c)

        real_preserve = self.engine.create_version_from_bytes
        calls = 0

        def fail_second(data, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BackupError("falha simulada ao preservar B")
            return real_preserve(data, *args, **kwargs)

        with patch.object(
            self.engine,
            "create_version_from_bytes",
            side_effect=fail_second,
        ):
            response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 503, "BACKUP_PRESERVATION_FAILED", False, False
        )
        self.assertEqual(self.target.read_bytes(), content_c)
        self.assertEqual(calls, 2)

        events = self.eventos()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]["origin"], "external")
        self.assertEqual(self.backup_bytes("versao_000002"), content_c)

    def test_mudanca_durante_salvamento_preserva_versao_externa(self):
        content_b = b"conteudo B"
        content_c = b"mudanca externa durante salvamento"

        real_read = self.engine.read_source
        calls = 0

        def read_then_change(path):
            nonlocal calls
            calls += 1

            if calls == 1:
                return real_read(path)

            if calls == 2:
                self.target.write_bytes(content_c)

            return real_read(path)

        with patch.object(
            self.engine,
            "read_source",
            side_effect=read_then_change,
        ):
            response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 409, "SAVE_CONFLICT", True, False
        )
        self.assertEqual(self.target.read_bytes(), content_c)

        events = self.eventos()
        self.assertEqual(
            [event["origin"] for event in events],
            ["initial", "spia", "external"],
        )
        self.assertEqual(self.backup_bytes("versao_000002"), content_b)
        self.assertEqual(self.backup_bytes("versao_000003"), content_c)


    def test_substituicao_realizada_com_durabilidade_nao_confirmada(self):
        content_b = b"conteudo novo B"
        real_replace = self.engine.replace_source

        def replace_without_durability(*args, **kwargs):
            result = real_replace(*args, **kwargs)
            result["durability_confirmed"] = False
            return result

        with patch.object(
            self.engine,
            "replace_source",
            side_effect=replace_without_durability,
        ):
            response = self.salvar(content_b)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["code"], "SAVE_DURABILITY_UNCONFIRMED")
        self.assertIsInstance(data["message"], str)
        self.assertTrue(data["message"].strip())
        self.assertTrue(data["saved"])
        self.assertTrue(data["source_replaced"])
        self.assertTrue(data["preservation_complete"])
        self.assertFalse(data["durability_confirmed"])
        self.assertIsNotNone(data["warning"])
        self.assertEqual(self.target.read_bytes(), content_b)
        self.assertEqual(self.backup_bytes("versao_000002"), content_b)

    def test_conflito_detectado_pelo_motor_preserva_versao_externa(self):
        content_b = b"conteudo do editor B"
        content_c = b"mudanca externa dentro da substituicao"
        real_replace = self.engine.replace_source

        def replace_after_external_change(*args, **kwargs):
            self.target.write_bytes(content_c)
            return real_replace(*args, **kwargs)

        with patch.object(
            self.engine,
            "replace_source",
            side_effect=replace_after_external_change,
        ):
            response = self.salvar(content_b)

        self.assert_save_error_contract(
            response, 409, "SAVE_CONFLICT", True, False
        )
        self.assertEqual(self.target.read_bytes(), content_c)

        self.assertEqual(
            self.versoes(),
            ["versao_000001", "versao_000002", "versao_000003"],
        )
        self.assertEqual(self.backup_bytes("versao_000002"), content_b)
        self.assertEqual(self.backup_bytes("versao_000003"), content_c)

        events = self.eventos()
        self.assertEqual(
            [event["origin"] for event in events],
            ["initial", "spia", "external"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
