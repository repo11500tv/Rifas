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

    def test_targeted_route_reads_anchor_and_enclosing_rules_without_values(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-route-acl-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            profile = Path(temp)
            (profile / "vhost_nginx.conf").write_text(
                "\n" * 37 + "server {\n  deny 192.0.2.68;\n"
                "  location /sensitive-alias {\n    if (-f /sensitive-gate) { return 503; }\n"
                "    proxy_pass http://127.0.0.1:8768;\n"
                "  }\n}\n"
            )
            namespace["BASE"] = profile
            namespace["route"]()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["state"], "anchor_parsed")
        self.assertFalse(rows[0]["effective_verified"])
        self.assertTrue(any(row.get("directive") == "deny" and row.get("scope") == "server" for row in rows))
        self.assertTrue(any(row.get("returns_503") and row.get("scope") == "conditional" for row in rows))
        self.assertNotIn("sensitive-", output.getvalue())
        self.assertNotIn("192.0.2.68", output.getvalue())

    def test_acl_fallback_reports_effective_write_counts_or_specific_error(self):
        import errno
        import struct
        from unittest.mock import patch

        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-route-acl-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        entries = struct.pack("<IHHIHHI", 2, 2, 7, 23456, 16, 5, 0xffffffff)
        with patch("os.getxattr", return_value=entries):
            self.assertEqual(namespace["acl_xattr"](Path("/fixture"), "access"),
                             {"state": "read", "named": 1, "named_effective_write": 0})
        with patch("os.getxattr", side_effect=OSError(errno.EACCES, "raw diagnostic")):
            self.assertEqual(namespace["acl_xattr"](Path("/fixture"), "access"), {"state": "path_denied"})
        with patch("subprocess.run", side_effect=FileNotFoundError):
            self.assertEqual(namespace["acl_tool"](Path("/fixture")), "executable_missing")

    def test_final_inspector_expands_includes_in_order_and_hides_vhost_values(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-route-acl-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            root = Path(temp)
            nginx = root / "nginx"
            vhost = root / "vhost"
            nginx.mkdir()
            vhost.mkdir()
            (nginx / "nginx.conf").write_text(
                f"http {{ include {nginx}/upstream.conf; include {vhost}/vhost_nginx.conf; }}"
            )
            (nginx / "upstream.conf").write_text("upstream private_target { server 127.0.0.1:8768; }")
            (vhost / "vhost_nginx.conf").write_text(
                "server { server_name private.example.invalid; "
                "location /privatealias { auth_basic hidden; proxy_pass http://private_target; } }"
            )
            namespace["NGINX"], namespace["BASE"] = nginx, vhost
            namespace["proxy_final"]()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        includes = [row for row in rows if row["section"] == "include_order"]
        self.assertEqual([row["order"] for row in includes], [1, 2])
        self.assertTrue(any(row.get("via_named_upstream") for row in rows))
        self.assertTrue(any(row.get("directive") == "auth_basic" for row in rows))
        self.assertTrue(any(row.get("effective_verified") is False for row in rows))
        for value in ("hidden", "private.example.invalid", "privatealias", "private_target"):
            self.assertNotIn(value, output.getvalue())

    def test_final_inspector_does_not_expand_globs_outside_configuration_roots(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-route-acl-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output):
            root = Path(temp)
            nginx, outside = root / "nginx", root / "outside"
            nginx.mkdir()
            outside.mkdir()
            (outside / "protected.conf").write_text("location /fixture { proxy_pass http://localhost:8768; }")
            (nginx / "nginx.conf").write_text(f"http {{ include {nginx}/../outside/*.conf; }}")
            namespace["NGINX"], namespace["BASE"] = nginx, root / "vhost"
            from unittest.mock import patch
            with (patch("glob.glob", side_effect=AssertionError("unsafe glob expanded")),
                  patch("glob.iglob", side_effect=AssertionError("unsafe glob expanded"))):
                namespace["proxy_final"]()
        self.assertIn("external_include", namespace["PENDING"])
        self.assertNotIn("protected.conf", output.getvalue())

    def test_final_inspector_reports_stop_propagation_even_if_unit_was_seen_earlier(self):
        script = Path(__file__).resolve().parents[1] / "deployment/arsys/inspect-route-acl-readonly.sh"
        namespace = {"__name__": "fixture"}
        exec(compile(shlex.split(script.read_text())[-1], str(script), "exec"), namespace)
        units = {
            "rifas-pruebas.service": {
                "Id": "rifas-pruebas.service", "LoadState": "loaded", "Requires": "rifas-platform.service",
                "Wants": "auxiliary.service",
            },
            "rifas-platform.service": {"Id": "rifas-platform.service", "LoadState": "loaded"},
            "auxiliary.service": {
                "Id": "auxiliary.service", "LoadState": "loaded", "PropagatesStopTo": "rifas-platform.service",
            },
        }
        namespace["show_unit"] = lambda name, fields: units[name]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            namespace["dependencies_final"]()
        hits = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(any(row.get("edge") == "PropagatesStopTo" and row.get("depth") == 2
                            and row.get("scopes") == ["production"] for row in hits))
