"""Relay staging service operations through the isolated coordinator's pipes."""

import json
import os
import pwd
import subprocess
import sys


PREFIX = b"RIFAS-STAGING-SERVICE "
ACTIONS = {b"start", b"stop", b"status"}
LAUNCHER = "/usr/local/sbin/rifas-pruebas-deploy"
SERVICE = "/usr/local/sbin/rifas-staging-service"
WRITERS = "/usr/local/sbin/rifas-pruebas-observe-writers"
REPORTS = {
    b"isolation-report": [sys.executable, "-B", "-m", "deployment.arsys.inspect_staging_isolation"],
    b"writer-report": ["/usr/bin/sudo", "-n", WRITERS],
}
REPORT_PREFIX = b"REPORT "
MAX_REPLY = 65536


def request(action):
    if (action not in ACTIONS and action not in REPORTS) or sys.stdin.isatty() or sys.stdout.isatty():
        raise ValueError("El control de PRUEBAS requiere el puente del coordinador")
    sys.stdout.buffer.write(PREFIX + action + b"\n")
    sys.stdout.buffer.flush()
    reply = sys.stdin.buffer.readline(MAX_REPLY + 1)
    if action in REPORTS and reply.startswith(REPORT_PREFIX) and reply.endswith(b"\n") and len(reply) <= MAX_REPLY:
        report = json.loads(reply[len(REPORT_PREFIX):])
        if not isinstance(report, dict):
            raise ValueError("Informe inválido del puente de PRUEBAS")
        print(json.dumps(report))
        return 0
    if reply == b"OK\n":
        return 0
    if reply == b"INACTIVE\n" and action == b"status":
        return 3
    raise ValueError("Falló el control delegado de PRUEBAS")


def relay(source, reply, output):
    for line in iter(source.readline, b""):
        if not line.startswith(PREFIX):
            output.write(line)
            output.flush()
            continue
        action = line[len(PREFIX):].removesuffix(b"\n")
        result = b"ERROR\n"
        command = REPORTS.get(action)
        if action in ACTIONS:
            command = ["/usr/bin/sudo", "-n", SERVICE, action.decode("ascii")]
        if command is not None and line.endswith(b"\n"):
            try:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    timeout=35, check=False,
                )
                if completed.returncode == 0 and action in REPORTS:
                    report = json.loads(completed.stdout)
                    if isinstance(report, dict):
                        encoded = REPORT_PREFIX + json.dumps(report).encode("ascii") + b"\n"
                        if len(encoded) <= MAX_REPLY:
                            result = encoded
                elif completed.returncode == 0:
                    result = b"OK\n"
                elif (action == b"status" and completed.returncode == 3
                      and completed.stdout.strip() == b"inactive"):
                    result = b"INACTIVE\n"
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        reply.write(result)
        reply.flush()


def run(args):
    if os.geteuid() != pwd.getpwnam("dealfonsocom").pw_uid:
        raise ValueError("Ejecutar el puente de PRUEBAS como dealfonsocom")
    with subprocess.Popen(
        ["/usr/bin/sudo", "-n", LAUNCHER, *args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True,
    ) as process:
        try:
            relay(process.stdout, process.stdin, sys.stdout.buffer)
        finally:
            process.stdin.close()
        return process.wait()


def main(args):
    try:
        if len(args) == 2 and args[0] == "request":
            return request(args[1].encode("ascii"))
        if len(args) >= 2 and args[0] == "run":
            return run(args[1:])
        raise ValueError("Uso: staging_service_bridge run OPERACIÓN | request ACCIÓN")
    except (KeyError, OSError, ValueError) as error:
        print(f"PRUEBAS: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
