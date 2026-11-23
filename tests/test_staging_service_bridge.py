import io
import subprocess
import sys
import unittest
from unittest.mock import patch

from deployment.arsys import staging_service_bridge as bridge


class StagingServiceBridgeTests(unittest.TestCase):
    def test_request_crosses_pipes_and_uses_fixed_staging_executable(self):
        with subprocess.Popen(
            [sys.executable, "-B", "-m", "deployment.arsys.staging_service_bridge", "request", "stop"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        ) as child:
            with patch.object(
                bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"")
            ) as control:
                bridge.relay(child.stdout, child.stdin, io.BytesIO())
            self.assertEqual(child.wait(timeout=3), 0)
        self.assertEqual(control.call_args.args[0], ["/usr/bin/sudo", "-n", bridge.SERVICE, "stop"])

    def test_request_for_another_service_is_rejected_without_running_sudo(self):
        request = bridge.PREFIX + b"stop rifas-platform.service\n"
        reply = io.BytesIO()
        output = io.BytesIO()
        with patch.object(bridge.subprocess, "run") as control:
            bridge.relay(io.BytesIO(b"normal output\n" + request), reply, output)
        control.assert_not_called()
        self.assertEqual(reply.getvalue(), b"ERROR\n")
        self.assertEqual(output.getvalue(), b"normal output\n")

    def test_status_distinguishes_inactive_from_unknown(self):
        for stdout, expected in ((b"inactive\n", b"INACTIVE\n"), (b"unknown\n", b"ERROR\n")):
            with self.subTest(stdout=stdout):
                reply = io.BytesIO()
                with patch.object(
                    bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 3, stdout)
                ):
                    bridge.relay(io.BytesIO(bridge.PREFIX + b"status\n"), reply, io.BytesIO())
                self.assertEqual(reply.getvalue(), expected)

    def test_timeout_returns_failure_to_the_hook(self):
        reply = io.BytesIO()
        with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("sudo", 35)):
            bridge.relay(io.BytesIO(bridge.PREFIX + b"start\n"), reply, io.BytesIO())
        self.assertEqual(reply.getvalue(), b"ERROR\n")

    def test_writer_report_uses_the_fixed_read_only_helper(self):
        report = b'{"complete": true, "paths": [], "writers": []}'
        reply = io.BytesIO()
        with patch.object(
            bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, report)
        ) as control:
            bridge.relay(io.BytesIO(bridge.PREFIX + b"writer-report\n"), reply, io.BytesIO())
        self.assertEqual(control.call_args.args[0], ["/usr/bin/sudo", "-n", bridge.WRITERS])
        self.assertEqual(reply.getvalue(), bridge.REPORT_PREFIX + report + b"\n")

    def test_structural_lookup_keeps_the_coordinator_output_pipe(self):
        query = (
            "import json; from deployment.arsys.staging_structure import ArsysStagingStructure; "
            "print(json.dumps(ArsysStagingStructure.report('policy-report')))"
        )
        report = b'{"environment": "staging", "unit": "rifas-pruebas.service", "policy": "digest"}'
        with subprocess.Popen(
            [sys.executable, "-B", "-c", query], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        ) as child:
            output = io.BytesIO()
            with patch.object(
                bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, report)
            ) as host:
                bridge.relay(child.stdout, child.stdin, output)
            self.assertEqual(child.wait(timeout=3), 0)
        self.assertEqual(host.call_args.args[0], bridge.REPORTS[b"policy-report"])
        self.assertEqual(output.getvalue(), report + b"\n")

    def test_invalid_writer_report_is_not_passed_to_the_coordinator(self):
        for report in (b"not json", b"[]", b'{"too_large":"' + b"x" * bridge.MAX_REPLY + b'"}'):
            with self.subTest(length=len(report)):
                reply = io.BytesIO()
                with patch.object(
                    bridge.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, report)
                ):
                    bridge.relay(io.BytesIO(bridge.PREFIX + b"writer-report\n"), reply, io.BytesIO())
                self.assertEqual(reply.getvalue(), b"ERROR\n")
