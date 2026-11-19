"""La salida de la inspección se construye con campos permitidos."""

import contextlib
import io
import json
import shlex
from pathlib import Path
import tempfile
import unittest


class ArsysInspectionTest(unittest.TestCase):
    def test_sensitive_config_is_not_echoed(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-readonly.sh"
        source = shlex.split(script.read_text())[-1]
        namespace = {"__name__": "fixture"}
        exec(compile(source, str(script), "exec"), namespace)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            profile = Path(temp)
            (profile / "vhost_nginx.conf").write_text(
                "location /rifas/ {\n"
                "    proxy_pass http://127.0.0.1:8766;\n"
                "    proxy_set_header X-Forwarded-Host secret.example.invalid;\n"
                "    proxy_set_header Authorization example-private-token;\n"
                "}\n"
            )
            namespace["VHOST"] = profile
            namespace["command"] = lambda *_: (
                "ActiveState=active\nMainPID=42\nUser=private-account\nGroup=private-group\n"
                "ExecStart=/bin/gunicorn --bind 127.0.0.1:8766 wsgi:app --env SECRET=example-private-token\n"
            )
            namespace["systemd"]()
            namespace["proxy_config"]()
        contents = output.getvalue()
        for private in ("secret.example.invalid", "example-private-token", "private-account", "private-group"):
            self.assertNotIn(private, contents)
        rows = [json.loads(row) for row in contents.splitlines()]
        self.assertIn({"section": "proxy_route_hint", "file": "vhost_nginx.conf",
                       "route": "/rifas/", "loopback_ports": [8766]}, rows)
        self.assertEqual(rows[0]["bind_port_hints"], [8766])

    def test_pending_inspection_reports_apache_and_dependencies_without_values(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-pending-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            profile = Path(temp)
            (profile / "vhost.conf").write_text(
                "ServerAlias personal.example.invalid\n"
                "ProxyPass /rifas/staging/prueba_231 http://secret.example.invalid:8768/\n"
            )
            namespace["VHOST"] = profile
            namespace["read_command"] = lambda *_: (
                "Requires=rifas-platform.service private-aux.service\n"
                "EnvironmentFiles=/private/secret-file\n"
            )
            namespace["proxy"]()
            namespace["dependencies"]()
        contents = output.getvalue()
        for secret in ("private-aux.service", "secret-file", "personal.example.invalid", "secret.example.invalid"):
            self.assertNotIn(secret, contents)
        rows = [json.loads(line) for line in contents.splitlines()]
        self.assertTrue(any(row.get("backend_8768") and row.get("staging_literal") for row in rows))
        self.assertTrue(any(row.get("production_reference") for row in rows))
