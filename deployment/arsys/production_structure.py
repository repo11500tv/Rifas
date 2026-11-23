"""Isolated coordinator policy for the Arsys production installation."""

from pathlib import Path

from deployment.arsys.production_serve import CONTROL, COORDINATOR, ROOT
from deployment.arsys.staging_structure import ArsysStagingStructure


UNIT = "rifas-platform.service"
PEER = "rifas-pruebas.service"
MODE = "arsys-isolated-production"
FOREIGN = (
    ROOT / "staging",
    ROOT.parent / "rifas-deployment/staging",
    Path("/var/lib/rifas-pruebas-control"),
)


class ArsysProductionStructure(ArsysStagingStructure):
    environment = "production"
    application = ROOT
    control = CONTROL
    coordinator = COORDINATOR
    unit_name = UNIT
    peer_name = PEER
    service_port = 8767
    service_read_only = (
        ROOT, ROOT / ".rifas-deploy", COORDINATOR / "checkout", CONTROL,
        *FOREIGN,
    )
    service_writable = (ROOT / "central", ROOT / "entidades")
    foreign_root = ROOT / "staging"
