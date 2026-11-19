"""End-to-end tests against disposable Git, SSH and SQLite fixtures."""

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from deployment import schema
from deployment.artifact import build
from deployment.deploy import Deployment
from platform_app.raffle_schema import SCHEMA_RAFFLES

PROJECT = Path(__file__).resolve().parents[1]
RECIPE = "deployment/packages/sorteos_2.4.0.json"
READY = """
from wsgi import app
with app.test_client() as client:
    assert client.get('/health').json['version'] == '2.3.1'
    assert client.get('/e/demo/').status_code == 200
"""
PACKAGE = """
import os
from wsgi import app
with app.test_client() as client:
    response = client.get('/e/demo/sorteos/1/informacion')
    assert response.status_code == 200 and b'Texto sintetico' in response.data
"""


class DeploymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rifas-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        parent = Path(cls.temp.name)
        cls.repository = parent / "git"
        cls.repository.mkdir()
        shutil.copytree(PROJECT / "platform_app", cls.repository / "platform_app",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(PROJECT / "wsgi.py", cls.repository / "wsgi.py")
        recipe = cls.repository / RECIPE
        recipe.parent.mkdir(parents=True)
        shutil.copy2(PROJECT / RECIPE, recipe)
        cls.bootstrap_recipe = str(Path(RECIPE).with_name("bootstrap.json"))
        (cls.repository / cls.bootstrap_recipe).write_text(json.dumps({
            "package": "bootstrap", "version": "1.0.0", "platform_from": [None],
            "platform_to": "2.3.1", "schema": "sorteos-v2", "migration": None, "checks": ["sorteos"],
        }))
        cls.git("init", "-q")
        cls.git("add", ".")
        cls.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Fixture")
        cls.commit = cls.git("rev-parse", "HEAD").strip()
        cls.key = parent / "fixture-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(cls.key)], check=True)
        cls.signers = parent / "allowed_signers"
        cls.signers.write_text("rifas-release " + cls.key.with_suffix(".pub").read_text())

    @classmethod
    def git(cls, *args):
        return subprocess.check_output(["git", "-C", str(cls.repository), *args], text=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.temp.name)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.root = self.folder / "data"
        state = self.root / ".rifas-deploy"
        state.mkdir(parents=True, mode=0o700)
        (state / "environment").write_text("synthetic\n")
        self.baseline = self.folder / "baseline"
        shutil.copytree(self.repository / "platform_app", self.baseline / "platform_app")
        shutil.copy2(self.repository / "wsgi.py", self.baseline / "wsgi.py")
        self.create_database(schema.CENTRAL, """
            CREATE TABLE entities (
                id INTEGER PRIMARY KEY, slug TEXT UNIQUE, name TEXT, admin_email TEXT,
                status TEXT DEFAULT 'active', version TEXT, public_name TEXT,
                logo_path TEXT, primary_color TEXT, secondary_color TEXT
            );
            CREATE TABLE audit (actor TEXT, action TEXT, entity_id INTEGER);
            INSERT INTO entities (slug, name) VALUES ('demo','Demostracion'), ('other','Otra');
        """)
        (self.root / "central/secret.key").write_text("local synthetic key")
        old_schema = SCHEMA_RAFFLES.replace(",\n image_filename TEXT,\n extended_info TEXT", "")
        for relative in (schema.TEMPLATE, Path("entidades/other/data/rifas.sqlite3")):
            self.create_database(relative, old_schema + """
                CREATE TABLE module_versions (module TEXT PRIMARY KEY, version TEXT, updated_at TEXT);
                INSERT INTO module_versions VALUES ('sorteos','2.2.0',NULL);
            """)
        self.create_database(Path("entidades/demo/data/rifas.sqlite3"), SCHEMA_RAFFLES + """
            CREATE TABLE module_versions (module TEXT PRIMARY KEY, version TEXT, updated_at TEXT);
            INSERT INTO module_versions VALUES ('sorteos','2.4.0',NULL);
            INSERT INTO raffles (
                title, number_start, number_end, number_width, donation_cents, status, created_by, extended_info
            ) VALUES ('Sorteo',1,9,1,100,'published','fixture','Texto sintetico');
        """)
        noop = [sys.executable, "-B", "-c", "pass"]
        self.config = {
            "environment": "synthetic", "data_root": str(self.root), "baseline": str(self.baseline),
            "allowed_signers": str(self.signers), "runtime_python": sys.executable,
            "hooks": {"drain": noop, "activate": noop, "resume": noop, "ready": self.command(READY)},
            "checks": {"sorteos": self.command(PACKAGE)},
        }
        self.bundle, self.fingerprint = self.make_bundle(RECIPE, "artifact")
        self.deployment = Deployment(self.config)

    def create_database(self, relative, sql):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript(sql)

    def make_bundle(self, recipe, name):
        path = self.folder / name
        fingerprint = build(self.repository, self.commit, recipe, path)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(self.key),
                        "-n", "rifas-deploy-v1", str(path / "manifest.json")],
                       check=True, capture_output=True)
        return path, fingerprint

    def command(self, source):
        return [sys.executable, "-B", "-c", source]

    def approval(self, action):
        return f"{action}:synthetic:{self.fingerprint}"

    def version(self, relative=schema.TEMPLATE):
        with closing(sqlite3.connect(self.root / relative)) as connection:
            return connection.execute("SELECT version FROM module_versions").fetchone()[0]

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def apply(self):
        return self.deployment.apply(self.bundle, self.approval("apply"))

    def test_read_only_plan_and_wrong_environment_approval(self):
        original = self.snapshot()
        plan = self.deployment.plan(self.bundle)
        self.assertEqual(plan["digest"], self.fingerprint)
        self.assertEqual(plan["commit"], self.commit)
        self.assertEqual(len(plan["databases"]), 4)
        with self.assertRaisesRegex(ValueError, "aprobación"):
            self.deployment.apply(self.bundle, f"apply:production:{self.fingerprint}")
        with self.assertRaisesRegex(ValueError, "raíz"):
            Deployment({**self.config, "environment": "production"})
        self.assertEqual(original, self.snapshot())

    def test_installation_and_migration_with_real_flask_and_cloned_template(self):
        self.assertEqual(self.apply(), self.fingerprint)
        self.assertEqual(self.version(), "2.4.0")
        self.assertEqual(self.version("entidades/other/data/rifas.sqlite3"), "2.4.0")
        release = self.deployment.active()
        self.assertTrue(release.is_relative_to(self.root))
        baseline_environment = {**os.environ, "RIFAS_DATA_ROOT": str(self.root)}
        subprocess.run(self.command("""
from wsgi import app
with app.test_client() as client:
    app.config["SESSION_COOKIE_PATH"] = "/"
    with client.session_transaction() as session:
        session['admin'] = 'fixture'
        session['_csrf'] = 'fixture-token'
    response = client.post('/entidades/nueva', data={
        'slug': 'new', 'name': 'Nueva', 'email': 'mail@example.invalid', '_csrf': 'fixture-token'
    })
    assert response.status_code == 302, response.status_code
"""), cwd=release, env=baseline_environment, check=True)
        self.assertEqual(self.version("entidades/new/data/rifas.sqlite3"), "2.4.0")
        self.assertFalse(self.deployment.pending.exists())

    def test_first_activation_with_preprovisioned_sqlite(self):
        self.apply()
        bundle, fingerprint = self.make_bundle(self.bootstrap_recipe, "bootstrap")
        self.deployment.current.unlink()
        fresh = Deployment({**self.config, "baseline": None})
        self.assertEqual(fresh.apply(bundle, f"apply:synthetic:{fingerprint}"), fingerprint)
        self.assertTrue(fresh.current.is_symlink())

    def test_exclusive_lock(self):
        with self.deployment.lock(), self.assertRaisesRegex(RuntimeError, "bloqueo"):
            self.apply()
        self.assertEqual(self.version(), "2.2.0")

    def test_smoke_failure_reverts_code_and_databases(self):
        self.deployment.checks["sorteos"] = self.command("raise SystemExit(3)")
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assertEqual(self.deployment.active(), self.baseline)
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual(self.version("entidades/other/data/rifas.sqlite3"), "2.2.0")
        self.assertFalse(self.deployment.pending.exists())
        self.assertIn('"phase": "rolled_back"', (self.deployment.state / "events.jsonl").read_text())

    def test_hard_interrupt_recovery_after_first_database(self):
        settings = self.folder / "config.json"
        settings.write_text(json.dumps(self.config))
        code = """
import json, os, signal, sys
from pathlib import Path
from deployment.deploy import Deployment
deployment = Deployment(json.loads(Path(sys.argv[1]).read_text()))
event = deployment.event
def interrupt(phase, **details):
    event(phase, **details)
    if phase == 'migrated':
        os.kill(os.getpid(), signal.SIGKILL)
deployment.event = interrupt
deployment.apply(Path(sys.argv[2]), sys.argv[3])
"""
        result = subprocess.run([*self.command(code), str(settings), str(self.bundle), self.approval("apply")],
                                cwd=PROJECT)
        self.assertEqual(result.returncode, -9)
        self.assertEqual(self.version(), "2.4.0")
        self.assertEqual(self.version("entidades/other/data/rifas.sqlite3"), "2.2.0")
        self.deployment.recover(self.approval("recover"))
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual(self.deployment.active(), self.baseline)
        self.assertFalse(self.deployment.pending.exists())

    def test_resume_failure_does_not_restore_committed_data(self):
        self.deployment.hooks["resume"] = self.command("raise SystemExit(7)")
        with self.assertRaises(subprocess.CalledProcessError):
            self.apply()
        self.assertEqual(json.loads(self.deployment.pending.read_text())["phase"], "committed")
        self.deployment.hooks["resume"] = self.command("pass")
        self.deployment.recover(self.approval("recover"))
        self.assertEqual(self.version(), "2.4.0")
        self.assertTrue(self.deployment.current.is_symlink())

    def test_rejects_tampered_payload_and_manifest(self):
        (self.bundle / "payload/wsgi.py").write_text("# tampered")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.deployment.plan(self.bundle)
        manifest = self.bundle / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        with self.assertRaises(subprocess.CalledProcessError):
            self.deployment.plan(self.bundle)

    def test_read_only_plan_rejects_live_wal(self):
        with closing(sqlite3.connect(self.root / schema.TEMPLATE)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("UPDATE module_versions SET updated_at='now'")
            connection.commit()
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, "archivos auxiliares"):
                self.deployment.plan(self.bundle)
            self.assertEqual(before, self.snapshot())

    def test_rejects_missing_entity_and_future_schema(self):
        entity = self.root / "entidades/other/data/rifas.sqlite3"
        saved = entity.with_suffix(".save")
        entity.rename(saved)
        with self.assertRaisesRegex(ValueError, "Catálogo y disco difieren"):
            self.deployment.plan(self.bundle)
        saved.rename(entity)
        with closing(sqlite3.connect(entity)) as connection, connection:
            connection.execute("UPDATE module_versions SET version='3.0.0'")
        with self.assertRaisesRegex(ValueError, "incompatible"):
            self.deployment.plan(self.bundle)


if __name__ == "__main__":
    unittest.main()
