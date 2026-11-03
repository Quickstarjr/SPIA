import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backup_engine import BackupEngine


class ServerBackupPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "projects"
        self.project = self.root / "alpha"
        self.docs = self.project / "docs"
        self.docs.mkdir(parents=True)

        self.project_patch = patch.object(server, "PROJECT", self.root)
        self.engine = BackupEngine(self.root)
        self.engine_patch = patch.object(server, "BACKUP_ENGINE", self.engine)

        self.project_patch.start()
        self.engine_patch.start()

        self.addCleanup(self.project_patch.stop)
        self.addCleanup(self.engine_patch.stop)
        self.addCleanup(self.temp.cleanup)

        self.client = TestClient(server.app)

    def criar_arquivo(self, relative, content=b"conteudo"):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def eventos(self):
        manifest = self.project / "backups" / "manifest.jsonl"
        if not manifest.exists():
            return []
        return [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
        ]

    def test_le_backup_sem_criar_nova_versao(self):
        content = b"conteudo historico"
        self.criar_arquivo("alpha/backups/docs/test.txt", content)

        response = self.client.get(
            "/api/file",
            params={"path": "alpha/backups/docs/test.txt"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], content.decode("utf-8"))
        self.assertIs(response.json().get("read_only"), True)
        self.assertEqual(self.eventos(), [])

    def test_salvamento_em_backup_e_bloqueado(self):
        target = self.criar_arquivo(
            "alpha/backups/docs/test.txt",
            b"original",
        )

        response = self.client.post(
            "/api/file",
            json={
                "path": "alpha/backups/docs/test.txt",
                "content": "alterado",
                "expected_sha256": hashlib.sha256(b"original").hexdigest(),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(target.read_bytes(), b"original")

    def test_criacao_de_arquivo_dentro_de_backup_e_bloqueada(self):
        (self.project / "backups").mkdir()

        response = self.client.post(
            "/api/files/create",
            json={
                "directory": "alpha/backups",
                "name": "novo",
                "extension": ".txt",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.project / "backups" / "novo.txt").exists())

    def test_criacao_da_pasta_backups_e_bloqueada(self):
        response = self.client.post(
            "/api/files/create-directory",
            json={
                "directory": "alpha",
                "name": "backups",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.project / "backups").exists())

    def test_criacao_de_subpasta_dentro_de_backup_e_bloqueada(self):
        (self.project / "backups").mkdir()

        response = self.client.post(
            "/api/files/create-directory",
            json={
                "directory": "alpha/backups",
                "name": "nova_pasta",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            (self.project / "backups" / "nova_pasta").exists()
        )

    def test_preview_de_backup_e_bloqueada(self):
        self.criar_arquivo(
            "alpha/backups/site.html",
            b"<h1>historico</h1>",
        )

        response = self.client.get("/preview/alpha/backups/site.html")

        self.assertEqual(response.status_code, 403)

    def test_imagem_de_backup_e_bloqueada(self):
        self.criar_arquivo(
            "alpha/backups/image.png",
            b"\x89PNG\r\n\x1a\n",
        )

        response = self.client.get(
            "/api/image",
            params={"path": "alpha/backups/image.png"},
        )

        self.assertEqual(response.status_code, 403)

    def test_listagem_mantem_backups_visivel(self):
        self.criar_arquivo(
            "alpha/backups/docs/test.txt",
            b"historico",
        )

        project_response = self.client.get(
            "/api/files",
            params={"path": "alpha"},
        )
        backup_response = self.client.get(
            "/api/files",
            params={"path": "alpha/backups"},
        )

        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(backup_response.status_code, 200)

        project_items = {
            item["name"]: item["type"]
            for item in project_response.json()["items"]
        }
        backup_items = {
            item["name"]: item["type"]
            for item in backup_response.json()["items"]
        }

        self.assertEqual(project_items.get("backups"), "directory")
        self.assertEqual(backup_items.get("docs"), "directory")

    def test_subpasta_backups_comum_continua_utilizavel(self):
        ordinary = self.docs / "backups"
        ordinary.mkdir()

        create_response = self.client.post(
            "/api/files/create",
            json={
                "directory": "alpha/docs/backups",
                "name": "ordinary",
                "extension": ".txt",
            },
        )

        self.assertEqual(create_response.status_code, 200)

        target = ordinary / "ordinary.txt"
        target.write_text("conteudo original", encoding="utf-8")

        open_response = self.client.get(
            "/api/file",
            params={"path": "alpha/docs/backups/ordinary.txt"},
        )

        self.assertEqual(open_response.status_code, 200)
        self.assertNotIn("read_only", open_response.json())

        original = b"conteudo original"
        updated = "conteudo atualizado"

        save_response = self.client.post(
            "/api/file",
            json={
                "path": "alpha/docs/backups/ordinary.txt",
                "content": updated,
                "expected_sha256": hashlib.sha256(original).hexdigest(),
            },
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(target.read_text(encoding="utf-8"), updated)

        mkdir_response = self.client.post(
            "/api/files/create-directory",
            json={
                "directory": "alpha/docs/backups",
                "name": "subpasta",
            },
        )

        self.assertEqual(mkdir_response.status_code, 200)
        self.assertTrue((ordinary / "subpasta").is_dir())

    def test_backups_administrativo_na_raiz_continua_bloqueado(self):
        self.criar_arquivo("backups/admin.txt", b"administrativo")

        response = self.client.get(
            "/api/file",
            params={"path": "backups/admin.txt"},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
