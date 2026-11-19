"""End-to-end tests against disposable Git, SSH and SQLite fixtures."""

from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import Mock
import unittest

from deployment import approval, backup_integral, schema
from deployment.artifact import build
from deployment.deploy import Deployment
from deployment.intervention import Intervention, STEPS
from deployment.backup_sqlite import sha256
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
        with (cls.repository / "wsgi.py").open("a") as wsgi:
            wsgi.write("""
import os
import sqlite3
from pathlib import Path
old_wsgi = app.wsgi_app
def synthetic_write(environ, start_response):
    if environ['PATH_INFO'] == '/fixture-write' and environ['REQUEST_METHOD'] == 'POST':
        with sqlite3.connect(Path(os.environ['RIFAS_DATA_ROOT']) / 'central/plataforma.sqlite') as db:
            db.execute("INSERT INTO audit (actor, action) VALUES ('fixture', 'confirmed')")
        start_response('201 Created', [('Content-Type', 'text/plain')])
        return [b'confirmed']
    return old_wsgi(environ, start_response)
app.wsgi_app = synthetic_write
""")

        recipe = cls.repository / RECIPE
        recipe.parent.mkdir(parents=True)
        shutil.copy2(PROJECT / RECIPE, recipe)
        cls.bootstrap_recipe = str(Path(RECIPE).with_name("bootstrap.json"))
        (cls.repository / cls.bootstrap_recipe).write_text(json.dumps({
            "package": "bootstrap", "version": "1.0.0", "platform_from": [None],
            "platform_to": "2.3.1", "schema": json.loads(recipe.read_text())["schema"],
            "migration": None, "checks": ["sorteos"],
        }))
        cls.git("init", "-q")
        cls.git("add", ".")
        cls.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Fixture")
        cls.commit = cls.git("rev-parse", "HEAD").strip()
        cls.key = parent / "fixture-key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(cls.key)], check=True)
        cls.signers = parent / "allowed_signers"
        cls.signers.write_text("rifas-release " + cls.key.with_suffix(".pub").read_text())
        cls.operator_keys = {}
        cls.operator_signers = {}
        for environment in ("synthetic", "staging", "production"):
            key = parent / f"operator-{environment}"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            cls.operator_keys[environment] = key
            signers = parent / f"allowed-{environment}"
            signers.write_text("rifas-operator " + key.with_suffix(".pub").read_text())
            cls.operator_signers[environment] = signers


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
        self.assets = self.root / "entidades/demo/uploads"
        self.assets.mkdir()
        (self.assets / "photo.jpg").write_bytes(b"synthetic media")
        self.ops = self.root / "ops"
        self.ops.mkdir()
        (self.ops / "nginx.conf").write_text("proxy synthetic")
        (self.ops / "supervisor.ini").write_text("supervisor synthetic")
        (self.ops / "runtime.lock").write_text("runtime synthetic")
        noop = [sys.executable, "-B", "-c", "pass"]
        self.config = {
            "environment": "synthetic", "data_root": str(self.root), "baseline": str(self.baseline),
            "allowed_signers": str(self.signers), "approval_signers": str(self.operator_signers["synthetic"]),
            "runtime_python": sys.executable, "backup_components": ["ops"],
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

    def make_bundle(self, recipe, name, *, repository=None, commit=None):
        path = self.folder / name
        fingerprint = build(repository or self.repository, commit or self.commit, recipe, path)
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(self.key),
                        "-n", "rifas-deploy-v1", str(path / "manifest.json")],
                       check=True, capture_output=True)
        return path, fingerprint

    def command(self, source):
        return [sys.executable, "-B", "-c", source]

    def approval(self, action, *, environment="synthetic", fingerprint=None, run=None, signer=None):
        if action == "recover" and run is None:
            run = json.loads(self.deployment.pending.read_text())["run"]
        data = approval.request(action, environment, self.root, fingerprint or self.fingerprint, run)
        document = self.folder / f"approval-{data['nonce']}.json"
        document.write_text(json.dumps(data))
        subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(self.operator_keys[signer or environment]),
                        "-n", approval.namespace(environment), str(document)],
                       check=True, capture_output=True)
        return document

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
        with self.assertRaisesRegex(ValueError, "Aprobación"):
            self.deployment.apply(self.bundle, self.approval("apply", environment="production"))
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
        self.assertEqual(fresh.apply(bundle, self.approval("apply", fingerprint=fingerprint)), fingerprint)
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

    def interrupt(self, phase):
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
    if phase == sys.argv[4]:
        os.kill(os.getpid(), signal.SIGKILL)
deployment.event = interrupt
deployment.apply(Path(sys.argv[2]), Path(sys.argv[3]))
"""
        result = subprocess.run([*self.command(code), str(settings), str(self.bundle), str(self.approval("apply")), phase],
                                cwd=PROJECT)
        self.assertEqual(result.returncode, -9)

    def test_hard_interrupt_recovery_after_first_database(self):
        self.interrupt("migrated")
        self.assertEqual(self.version(), "2.4.0")
        self.assertEqual(self.version("entidades/other/data/rifas.sqlite3"), "2.2.0")
        self.deployment.recover(self.approval("recover"))
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual(self.deployment.active(), self.baseline)
        self.assertFalse(self.deployment.pending.exists())

    def live_service(self):
        controls = self.folder / "supervisor"
        controls.mkdir()
        gate = controls / "maintenance"
        script = PROJECT / "tests/synthetic_supervisor.py"
        stop = [sys.executable, "-B", str(script), str(controls), "stop"]
        self.addCleanup(subprocess.run, stop, check=True)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            backend = f"127.0.0.1:{listener.getsockname()[1]}"
        opener = build_opener(ProxyHandler({}))

        class Proxy(BaseHTTPRequestHandler):
            def forward(self):
                if gate.is_file():
                    self.send_error(503)
                    return
                request = Request(f"http://{backend}{self.path}", method=self.command)
                try:
                    with opener.open(request, timeout=3) as response:
                        body = response.read()
                        self.send_response(response.status)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                except HTTPError as error:
                    self.send_error(error.code)
                except URLError:
                    self.send_error(502)

            do_GET = do_POST = forward

            def log_message(self, *_):
                pass

        proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        worker = Thread(target=proxy.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(proxy.server_close)
        self.addCleanup(worker.join, 5)
        self.addCleanup(proxy.shutdown)
        public = f"http://127.0.0.1:{proxy.server_port}"
        private = f"http://{backend}"
        hook_config = self.ops / "hooks.json"
        hook = [*self.command(f"import sys; sys.path.insert(0, {str(PROJECT)!r}); "
                              "from deployment.hooks import main; main()"),
                "--config", str(hook_config)]
        hook_config.write_text(json.dumps({
            "gate": str(gate), "target": str(controls / "target.json"),
            "scope": {"environment": "synthetic", "data_root": str(self.root),
                      "baseline": str(self.baseline)},
            "closed_url": public + "/health", "private_url": private + "/health",
            "gunicorn": {"python": sys.executable,
                         "arguments": ["--bind", backend, "--graceful-timeout", "2"],
                         "environment": {"RIFAS_SESSION_COOKIE_NAME": "synthetic_session",
                                         "RIFAS_SESSION_COOKIE_PATH": "/synthetic",
                                         "RIFAS_PROXY_X_FOR": "0"}},
            "start": [sys.executable, "-B", str(script), str(controls), "start", *hook, "serve"],
            "stop": stop,
        }))
        check = [sys.executable, "-B", str(PROJECT / "deployment/smoke.py"),
                 "--base", private, "--version", "2.3.1", "--slug", "demo"]
        self.deployment.hooks.update({name: [*hook, name] for name in ("drain", "activate", "resume")})
        self.deployment.hooks["ready"] = check
        self.deployment.checks["sorteos"] = [*check, "--raffle-id", "1", "--marker", "Texto sintetico"]
        process_env = {**os.environ, "RIFAS_RELEASE_ROOT": str(self.baseline), "RIFAS_DATA_ROOT": str(self.root),
                       "RIFAS_DEPLOY_ENVIRONMENT": "synthetic",
                       "PYTHONDONTWRITEBYTECODE": "1"}
        gate.touch()
        subprocess.run(self.deployment.hooks["activate"], env=process_env, check=True)
        subprocess.run(self.deployment.hooks["resume"], env=process_env, check=True)
        return controls, gate, public

    def test_reactivate_after_drain_or_backup_failure(self):
        controls, gate, public = self.live_service()
        event = self.deployment.event

        def inject(phase, **details):
            event(phase, **details)
            hit = (fail_phase == "backed_up" and phase == "backed_up" and "component" in details
                   or fail_phase == "snapshot_complete" and phase == "backed_up" and "component" not in details)
            if hit:
                self.assertFalse((controls / "pid").exists(), "Gunicorn debía estar detenido")
                self.assertTrue(gate.exists())
                with self.assertRaises(HTTPError) as closed:
                    build_opener(ProxyHandler({})).open(public + "/health", timeout=3)
                self.assertEqual(closed.exception.code, 503)
                closed.exception.close()
                raise RuntimeError("fallo durante respaldo")

        for fail_phase in ("drain", "backed_up", "snapshot_complete"):
            with self.subTest(fail_phase=fail_phase):
                pid = (controls / "pid").read_text()
                if fail_phase == "drain":
                    (controls / "fail-stop").touch()
                    expected = subprocess.CalledProcessError
                else:
                    self.deployment.event = inject
                    expected = RuntimeError
                with self.assertRaises(expected):
                    self.apply()
                self.assertNotEqual((controls / "pid").read_text(), pid)
                self.assertFalse(gate.exists())
                self.assertFalse(self.deployment.pending.exists())
                self.assertEqual(self.version(), "2.2.0")
                with build_opener(ProxyHandler({})).open(public + "/health", timeout=3) as response:
                    self.assertEqual(response.status, 200)
        self.deployment.event = event

    def test_hard_interrupt_while_service_stopped(self):
        controls, gate, public = self.live_service()
        for phase in ("hook_passed", "backed_up"):
            with self.subTest(phase=phase):
                self.interrupt(phase)
                self.assertFalse((controls / "pid").exists())
                self.assertTrue(gate.exists())
                status = self.deployment.status()["pending"]
                self.assertEqual(status["phase"], "draining")
                self.deployment.recover(self.approval("recover", run=status["run"]))
                self.assertEqual(self.version(), "2.2.0")
                self.assertFalse(gate.exists())
                with build_opener(ProxyHandler({})).open(public + "/health", timeout=3) as response:
                    self.assertEqual(response.status, 200)

    def test_resume_failure_does_not_restore_committed_data(self):
        _, gate, public = self.live_service()
        resume = self.deployment.hooks["resume"]
        self.deployment.hooks["resume"] = self.command(f"""
import subprocess
from urllib.request import Request, urlopen
subprocess.run({resume!r}, check=True)
with urlopen(Request({public + '/fixture-write'!r}, method='POST'), timeout=3) as response:
    assert response.status == 201 and response.read() == b'confirmed'
raise SystemExit(7)
""")
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            self.apply()
        self.assertEqual(failure.exception.returncode, 7)
        self.assertFalse(gate.exists())
        self.assertEqual(json.loads(self.deployment.pending.read_text())["phase"], "committed")
        self.deployment.hooks["resume"] = resume
        self.deployment.recover(self.approval("recover"))
        self.assertEqual(self.version(), "2.4.0")
        self.assertTrue(self.deployment.current.is_symlink())
        with closing(sqlite3.connect(self.root / schema.CENTRAL)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM audit WHERE action='confirmed'"
            ).fetchone()[0], 1)

    def test_approvals_are_single_use_scoped_and_signed(self):
        self.deployment.checks["sorteos"] = self.command("raise SystemExit(3)")
        grant = self.approval("apply")
        with self.assertRaises(subprocess.CalledProcessError):
            self.deployment.apply(self.bundle, grant)
        with self.assertRaisesRegex(ValueError, "ya utilizada"):
            self.deployment.apply(self.bundle, grant)
        manipulated = self.approval("apply")
        manipulated.write_bytes(manipulated.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "fuera de alcance"):
            self.deployment.apply(self.bundle, manipulated)
        with self.assertRaisesRegex(ValueError, "fuera de alcance"):
            self.deployment.apply(self.bundle, self.approval("apply", fingerprint="a" * 64))

        for environment in ("staging", "production"):
            (self.deployment.state / "environment").write_text(environment)
            other = Deployment({**self.config, "environment": environment,
                                "approval_signers": str(self.operator_signers[environment])})
            wrong = "staging" if environment == "production" else "production"
            for grant in (self.approval("apply", environment=wrong),
                          self.approval("apply", environment=environment, signer=wrong)):
                with self.assertRaisesRegex(ValueError, "fuera de alcance"):
                    other.approve("apply", self.fingerprint, grant)
            other.approve("apply", self.fingerprint, self.approval("apply", environment=environment))
        overlap = self.folder / "overlap"
        overlap.write_text("rifas-operator " + self.key.with_suffix(".pub").read_text())
        (self.deployment.state / "environment").write_text("synthetic")
        with self.assertRaisesRegex(ValueError, "independiente"):
            Deployment({**self.config, "approval_signers": str(overlap)})
        first_run = "a" * 32
        scoped = self.approval("recover", run=first_run)
        with self.assertRaisesRegex(ValueError, "fuera de alcance"):
            self.deployment.approve("recover", self.fingerprint, scoped, "b" * 32)
        with self.assertRaisesRegex(ValueError, "fuera de alcance"):
            self.deployment.approve("apply", self.fingerprint, scoped)

    def test_integral_restore_resumes_after_second_failure(self):
        applied_event = self.deployment.event
        original_code = (self.baseline / "wsgi.py").read_bytes()
        self.ops.chmod(0o750)
        (self.ops / "nginx.conf").chmod(0o640)
        (self.assets / "photo.jpg").chmod(0o600)
        failed_restores = []

        def fail_midway(phase, **details):
            applied_event(phase, **details)
            if phase == "migrated":
                (self.ops / "nginx.conf").unlink()
                (self.ops / "supervisor.ini").write_text("changed")
                (self.ops / "runtime.lock").write_text("changed")
                (self.ops / "untracked").write_text("new")
                (self.assets / "photo.jpg").write_bytes(b"changed")
                (self.assets / "photo.jpg").chmod(0o644)
                self.ops.chmod(0o755)
                (self.baseline / "wsgi.py").write_bytes(b"changed")
                (self.root / schema.TEMPLATE).unlink()
                raise RuntimeError("migración interrumpida")
            if phase == "restored" and not failed_restores:
                failed_restores.append(details["component"])
                raise RuntimeError("restauración interrumpida")

        self.deployment.event = fail_midway
        with self.assertRaisesRegex(RuntimeError, "restauración interrumpida"):
            self.apply()
        journal = json.loads(self.deployment.pending.read_text())
        folder = self.deployment.state / "runs" / journal["run"] / "backup"
        backup_file = folder / "data/ops/runtime.lock"
        original = backup_file.read_bytes()
        backup_file.write_text("corrupted")
        attempted = self.approval("recover")
        with self.assertRaisesRegex(ValueError, "alterado"):
            self.deployment.recover(attempted)
        with self.assertRaisesRegex(ValueError, "ya utilizada"):
            self.deployment.recover(attempted)
        backup_file.write_bytes(original)
        self.deployment.event = applied_event
        self.deployment.recover(self.approval("recover"))
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual((self.assets / "photo.jpg").read_bytes(), b"synthetic media")
        self.assertEqual((self.assets / "photo.jpg").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.ops.stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.ops / "nginx.conf").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.ops / "supervisor.ini").read_text(), "supervisor synthetic")
        self.assertEqual((self.ops / "runtime.lock").read_text(), "runtime synthetic")
        self.assertEqual((self.baseline / "wsgi.py").read_bytes(), original_code)
        self.assertFalse((self.ops / "untracked").exists())

    def intervention(self):
        source = self.folder / "steps.py"
        source.write_text("""
import os
from pathlib import Path
import sys
step = sys.argv[1]
backup = Path(os.environ["RIFAS_INTERVENTION_BACKUP"])
root = Path(os.environ["RIFAS_DATA_ROOT"])
config = root / "settings.synthetic"
gate = root / "gate.synthetic"
if step == "backup":
    (backup / "config").write_bytes(config.read_bytes())
elif step == "verify_backup":
    assert (backup / "config").read_text() == "before"
elif step == "close":
    gate.touch()
elif step == "apply":
    assert gate.exists()
    config.write_text("after")
elif step == "verify":
    assert config.read_text() == "after"
elif step == "rollback":
    assert gate.exists()
    config.write_bytes((backup / "config").read_bytes())
elif step == "verify_rollback":
    assert config.read_text() == "before"
elif step == "reopen":
    gate.unlink(missing_ok=True)
if (root / f"fail-{step}").exists():
    raise SystemExit(4)
""")
        (self.root / "settings.synthetic").write_text("before")
        self.config["intervention_signers"] = str(self.operator_signers["staging"])
        recipe = self.folder / "intervention.json"
        recipe.write_text(json.dumps({
            "format": 1, "environment": self.deployment.name, "installation": str(self.root),
            "files": {str(source): sha256(source), sys.executable: sha256(Path(sys.executable))},
            "steps": {step: [sys.executable, "-I", "-B", str(source), step] for step in STEPS},
        }))
        return Intervention(self.deployment, recipe)

    def test_intervention_is_separately_approved_and_rolls_back_partial_mutation(self):
        intervention = self.intervention()
        with self.assertRaisesRegex(ValueError, "caducada o fuera de alcance"):
            intervention.execute(self.approval("intervene", fingerprint=intervention.fingerprint))
        (self.root / "fail-apply").touch()
        grant = self.approval("intervene", fingerprint=intervention.fingerprint, signer="staging")
        with self.assertRaisesRegex(RuntimeError, "apply"):
            intervention.execute(grant)
        self.assertEqual((self.root / "settings.synthetic").read_text(), "before")
        self.assertFalse((self.root / "gate.synthetic").exists())
        self.assertFalse(intervention.pending.exists())

    def test_intervention_excludes_protected_inputs_and_unreviewed_staging_batch(self):
        intervention = self.intervention()
        production = self.folder / "production"
        legacy = self.folder / "sorteos"
        production.mkdir()
        legacy.mkdir()
        self.deployment.protected = (production, legacy)
        protected = production / "config"
        historic = legacy / "config"
        for path in (protected, historic):
            path.write_text("never touched")
        alias = self.folder / "outside-input"
        for path in (protected, historic):
            alias.symlink_to(path)
            intervention.files[str(alias)] = sha256(path)
            with self.assertRaisesRegex(ValueError, "ámbito protegido"):
                intervention.verify_files()
            alias.unlink()
            del intervention.files[str(alias)]
        self.deployment.name = "staging"
        with self.assertRaisesRegex(ValueError, "lote fijado"):
            intervention.verify_review()
        self.deployment.config["intervention_reviewed_digest"] = intervention.fingerprint
        intervention.verify_review()
        self.deployment.name = "synthetic"

        grant = self.approval("intervene", fingerprint=intervention.fingerprint, signer="staging")
        (self.root / "fail-apply").touch()
        with self.assertRaisesRegex(RuntimeError, "apply"):
            intervention.execute(grant)
        for path in (protected, historic):
            self.assertEqual(path.read_text(), "never touched")

    def test_pending_intervention_blocks_deploy_and_only_reopens_after_commit(self):
        intervention = self.intervention()
        (self.root / "fail-reopen").touch()
        grant = self.approval("intervene", fingerprint=intervention.fingerprint, signer="staging")
        with self.assertRaisesRegex(RuntimeError, "reopen"):
            intervention.execute(grant)
        journal = self.deployment.status()["intervention"]
        self.assertEqual(journal["phase"], "committed")
        with self.assertRaisesRegex(ValueError, "intervención"):
            self.deployment.plan(self.bundle)
        with self.assertRaisesRegex(ValueError, "intervención"):
            self.apply()
        (self.root / "fail-reopen").unlink()
        grant = self.approval("recover-intervention", run=journal["run"],
                              fingerprint=intervention.fingerprint, signer="staging")
        intervention.execute(grant, recovering=True)
        self.assertFalse(intervention.pending.exists())
        self.assertEqual((self.root / "settings.synthetic").read_text(), "after")

    def test_intervention_double_failure_persists_unverified_publication(self):
        intervention = self.intervention()
        intervention.publication = ["https://fixture.invalid/health"]
        protected = [self.folder / name for name in ("production", "sorteos")]
        self.deployment.protected = tuple(protected)
        for directory in protected:
            directory.mkdir()
            (directory / "config").write_text("original")

        def verify(expected):
            if expected == 401 and (self.root / "settings.synthetic").read_text() == "after":
                (self.root / "fail-close").touch()
                raise ValueError("alias no longer requires Basic")

        intervention.verify_publication = verify
        grant = self.approval("intervene", fingerprint=intervention.fingerprint, signer="staging")
        with self.assertRaisesRegex(RuntimeError, "no se verificó el nuevo cierre"):
            intervention.execute(grant)
        journal = self.deployment.status()["intervention"]
        self.assertEqual(journal["phase"], "committed")
        self.assertEqual(journal["publication"], "unverified")
        self.assertEqual((self.root / "settings.synthetic").read_text(), "after")
        retry = self.approval("recover-intervention", run=journal["run"],
                              fingerprint=intervention.fingerprint, signer="staging")
        with self.assertRaisesRegex(RuntimeError, "no se verificó el nuevo cierre"):
            intervention.execute(retry, recovering=True)
        self.assertEqual(self.deployment.status()["intervention"], journal)
        for directory in protected:
            self.assertEqual((directory / "config").read_text(), "original")
        events = (self.deployment.state / "events.jsonl").read_text()
        self.assertIn('"phase": "intervention_reclose_failed"', events)
        self.assertNotIn("intervention_reclose_verified", events)
        self.assertEqual(events.count('"phase": "intervention_reclose_failed"'), 2)
        with self.assertRaisesRegex(ValueError, "intervención"):
            self.deployment.plan(self.bundle)

    def test_structural_writer_guard_blocks_before_snapshot_or_migration(self):
        structure = Mock()
        structure.settings = {"unit": "synthetic.service"}
        structure.port = 8768
        structure.evidence.return_value = {"digest": "fixture"}

        def writers(*, drained=False):
            if drained:
                raise ValueError("writer still open")
            return 1

        structure.writers.side_effect = writers
        self.deployment.structure = structure
        with self.assertRaisesRegex(ValueError, "writer still open"):
            self.apply()
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual(self.deployment.active(), self.baseline)
        self.assertFalse(self.deployment.pending.exists())
        self.assertFalse(list((self.deployment.state / "runs").glob("*/backup")))
        structure.service.assert_any_call(stopped=True)

    def test_snapshot_recovers_empty_managed_scopes(self):
        areas = ["ops"]
        databases = schema.inventory(self.root, dry=True)
        original_wsgi = (self.baseline / "wsgi.py").read_bytes()
        self.assets.chmod(0o750)
        snapshot = self.folder / "recovery-snapshot"
        noop = lambda *_args, **_kwargs: None
        fingerprint = backup_integral.capture(
            self.root, self.baseline, areas, databases, snapshot, noop
        )
        for name in ("central", "entidades", "ops"):
            shutil.rmtree(self.root / name)
        shutil.rmtree(self.baseline)
        backup_integral.restore(self.root, self.baseline, areas, databases, snapshot, fingerprint, noop)
        self.assertEqual(schema.inventory(self.root, dry=True), databases)
        self.assertEqual(self.version(), "2.2.0")
        self.assertEqual((self.baseline / "wsgi.py").read_bytes(), original_wsgi)
        self.assertEqual((self.assets / "photo.jpg").read_bytes(), b"synthetic media")
        self.assertEqual(self.assets.stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.ops / "nginx.conf").read_text(), "proxy synthetic")
        self.assertEqual((self.ops / "supervisor.ini").read_text(), "supervisor synthetic")
        self.assertEqual((self.ops / "runtime.lock").read_text(), "runtime synthetic")

    def test_second_package_uses_different_contract_and_migration_without_coordinator_changes(self):
        clone = self.folder / "second-git"
        subprocess.run(["git", "clone", "-q", str(self.repository), str(clone)], check=True)
        relative = "platform_app/fixture_migration.py"
        (clone / relative).write_text("""
DDL = "CREATE TABLE second_fixture (id INTEGER PRIMARY KEY, value TEXT)"
def upgrade(connection, version):
    with connection:
        connection.execute(DDL)
        connection.execute("UPDATE module_versions SET version=? WHERE module='second'", (version,))
""")
        recipe = str(Path(RECIPE).with_name("second.json"))
        (clone / recipe).write_text(json.dumps({
            "package": "second", "version": "5.0.0", "platform_from": ["2.3.1"],
            "platform_to": "2.3.1",
            "schema": {"module": "second", "from": ["4.0.0"], "to": "5.0.0",
                       "tables": {"second_fixture": {"file": relative, "symbol": "DDL"}}},
            "migration": {"file": relative, "function": "upgrade", "arguments": {"version": "5.0.0"}},
            "checks": ["second"],
        }))
        subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
        subprocess.run(["git", "-C", str(clone), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "Second package"], check=True)
        commit = subprocess.check_output(["git", "-C", str(clone), "rev-parse", "HEAD"], text=True).strip()
        bases = schema.inventory(self.root, dry=True)[1:]
        for value in bases:
            with closing(sqlite3.connect(self.root / value)) as connection, connection:
                connection.execute("INSERT INTO module_versions VALUES ('second','4.0.0',NULL)")
        bundle, fingerprint = self.make_bundle(recipe, "second", repository=clone, commit=commit)
        self.deployment.checks["second"] = self.command(READY)
        self.deployment.apply(bundle, self.approval("apply", fingerprint=fingerprint))
        for value in bases:
            with closing(sqlite3.connect(self.root / value)) as connection:
                self.assertEqual(connection.execute(
                    "SELECT version FROM module_versions WHERE module='second'"
                ).fetchone()[0], "5.0.0")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM second_fixture").fetchone()[0], 0)

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
