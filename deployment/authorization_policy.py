"""Política central de responsabilidades para el ciclo de vida de Rifas.

No concede privilegios del sistema operativo. La firma SSHSIG y las
restricciones de cuenta siguen siendo obligatorias y se verifican aparte.
"""
from dataclasses import dataclass

ROLES = frozenset({"server_admin", "domain_owner", "platform_admin", "entity_admin", "participant", "service"})
ACTIONS = frozenset({
    "provision_host", "change_host_service", "change_proxy", "delegate_service_control",
    "configure_domain", "manage_platform", "manage_entity", "participate",
    "deployment_plan", "deployment_apply", "deployment_recover",
    "deployment_intervene", "deployment_recover_intervention",
    "backup_application", "restore_application", "serve_http",
})
PERMISSIONS = {
    "server_admin": frozenset({"provision_host", "change_host_service", "change_proxy",
                               "delegate_service_control"}),
    "domain_owner": frozenset({"configure_domain", "manage_platform", "manage_entity",
                               "deployment_plan", "deployment_apply", "deployment_recover",
                               "deployment_intervene", "deployment_recover_intervention",
                               "backup_application", "restore_application"}),
    "platform_admin": frozenset({"manage_platform", "manage_entity"}),
    "entity_admin": frozenset({"manage_entity"}),
    "participant": frozenset({"participate"}),
    "service": frozenset({"serve_http"}),
}
DEPLOYMENT_OPERATIONS = {
    "apply": "deployment_apply",
    "recover": "deployment_recover",
    "intervene": "deployment_intervene",
    "recover-intervention": "deployment_recover_intervention",
}
SIGNATURE_REQUIRED = frozenset(DEPLOYMENT_OPERATIONS)


@dataclass(frozen=True)
class Principal:
    role: str
    domain: str
    entity: str | None = None

    def __post_init__(self):
        if self.role not in ROLES or not self.domain or "/" in self.domain or "\\x00" in self.domain:
            raise ValueError("Identidad o dominio inválido")
        if self.role == "entity_admin" and not self.entity:
            raise ValueError("El administrador de entidad requiere una entidad")
        if self.role != "entity_admin" and self.entity is not None:
            raise ValueError("La entidad solo se admite para su administrador")


def authorize(principal, action, *, domain, entity=None):
    """Deniega por defecto; no interpreta esta decisión como firma de despliegue."""
    if action not in ACTIONS or not domain or principal.domain != domain:
        return False
    if action not in PERMISSIONS[principal.role]:
        return False
    if principal.role == "entity_admin":
        return entity is not None and entity == principal.entity
    return True


def authorize_deployment(principal, operation, *, domain, signature_verified=False):
    """Operaciones mutables requieren propietario del dominio y firma ya verificada.

    signature_verified solo debe provenir de deployment.approval.verified(),
    nunca de un parámetro recibido por HTTP.
    """
    action = DEPLOYMENT_OPERATIONS.get(operation)
    return (action is not None and principal.role == "domain_owner"
            and authorize(principal, action, domain=domain)
            and signature_verified is True)
