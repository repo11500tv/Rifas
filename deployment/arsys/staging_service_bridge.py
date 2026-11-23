"""Relay staging service operations through the isolated coordinator's pipes."""

import os
import pwd
import subprocess
import sys


PREFIX = b"RIFAS-STAGING-SERVICE "
ACTIONS = {b"start", b"stop", b"status"}
LAUNCHER = "/usr/local/sbin/rifas-pruebas-deploy"
SERVICE = "/usr/local/sbin/rifas-staging-service"


def request(action):
    if action not in ACTIONS or sys.stdin.isatty() or sys.stdout.isatty():
        raise ValueError("El control de PRUEBAS requiere el puente del coordinador")
    sys.stdout.buffer.write(PREFIX + action + b"\n")
    sys.stdout.buffer.flush()
    reply = sys.stdin.buffer.readline(32)
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
        if action in ACTIONS and line.endswith(b"\n"):
            try:
                completed = subprocess.run(
                    ["/usr/bin/sudo", "-n", SERVICE, action.decode("ascii")],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    timeout=35, check=False,
                )
                if completed.returncode == 0:
                    result = b"OK\n"
                elif (action == b"status" and completed.returncode == 3
                      and completed.stdout.strip() == b"inactive"):
                    result = b"INACTIVE\n"
            except (OSError, subprocess.TimeoutExpired):
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
        raise ValueError("Uso: staging_service_bridge run OPERACIÓN | request start|stop|status")
    except (KeyError, OSError, ValueError) as error:
        print(f"PRUEBAS: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
