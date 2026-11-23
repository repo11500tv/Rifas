"""Use only production's delegated systemd commands from the coordinator."""

import sys

from deployment.arsys.staging_service_bridge import request, run


LAUNCHER = "/usr/local/sbin/rifas-produccion-deploy"
SERVICE = "/usr/local/sbin/rifas-production-service"
WRITERS = "/usr/local/sbin/rifas-produccion-observe-writers"
REPORTS = {
    name: [sys.executable, "-B", "-m", "deployment.arsys.inspect_production_isolation", action]
    for name, action in ((b"isolation-report", "active"), (b"stopped-report", "stopped"), (b"policy-report", "policy"))
}
REPORTS[b"writer-report"] = ["/usr/bin/sudo", "-n", WRITERS]


def main(args):
    try:
        if len(args) == 2 and args[0] == "request":
            return request(args[1].encode("ascii"))
        if len(args) >= 2 and args[0] == "run":
            return run(args[1:], launcher=LAUNCHER, service=SERVICE, reports=REPORTS)
        raise ValueError("Uso: production_service_bridge run OPERACIÓN | request ACCIÓN")
    except (KeyError, OSError, ValueError) as error:
        print(f"PRODUCCIÓN: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
