"""Contrato de autorizaciones de dominio: pruebas puras sin servidor."""
import unittest
from deployment.authorization_policy import (
    ACTIONS, PERMISSIONS, Principal, authorize, authorize_deployment,
)


class AuthorizationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.owner = Principal("domain_owner", "dealfonso.com")
        self.server = Principal("server_admin", "dealfonso.com")
        self.admin = Principal("platform_admin", "dealfonso.com")
        self.entity = Principal("entity_admin", "dealfonso.com", "pruebas")
        self.service = Principal("service", "dealfonso.com")

    def test_every_action_has_single_defined_policy(self):
        self.assertEqual(set(ACTIONS), set().union(*PERMISSIONS.values()))

    def test_server_admin_cannot_deploy_or_manage_entities(self):
        self.assertTrue(authorize(self.server, "provision_host", domain="dealfonso.com"))
        self.assertFalse(authorize(self.server, "deployment_apply", domain="dealfonso.com"))
        self.assertFalse(authorize(self.server, "manage_entity", domain="dealfonso.com"))

    def test_owner_controls_domain_not_server(self):
        self.assertTrue(authorize(self.owner, "backup_application", domain="dealfonso.com"))
        self.assertFalse(authorize(self.owner, "change_proxy", domain="dealfonso.com"))
        self.assertFalse(authorize(self.owner, "deployment_plan", domain="otro.com"))

    def test_entity_admin_is_scoped(self):
        self.assertTrue(authorize(self.entity, "manage_entity", domain="dealfonso.com", entity="pruebas"))
        self.assertFalse(authorize(self.entity, "manage_entity", domain="dealfonso.com", entity="demostracion"))
        self.assertFalse(authorize(self.entity, "manage_platform", domain="dealfonso.com"))
        self.assertFalse(authorize(self.entity, "deployment_apply", domain="dealfonso.com"))

    def test_service_cannot_modify_deployment(self):
        self.assertTrue(authorize(self.service, "serve_http", domain="dealfonso.com"))
        self.assertFalse(authorize(self.service, "deployment_apply", domain="dealfonso.com"))

    def test_mutating_deploy_requires_owner_and_signature(self):
        for operation in ("apply", "recover", "intervene", "recover-intervention"):
            self.assertFalse(authorize_deployment(self.owner, operation, domain="dealfonso.com"))
            self.assertTrue(authorize_deployment(self.owner, operation, domain="dealfonso.com", signature_verified=True))
            self.assertFalse(authorize_deployment(self.server, operation, domain="dealfonso.com", signature_verified=True))
            self.assertFalse(authorize_deployment(self.owner, operation, domain="otro.com", signature_verified=True))
        self.assertFalse(authorize_deployment(self.owner, "unknown", domain="dealfonso.com", signature_verified=True))

    def test_invalid_principals_fail_closed(self):
        with self.assertRaises(ValueError):
            Principal("entity_admin", "dealfonso.com")
        with self.assertRaises(ValueError):
            Principal("participant", "dealfonso.com", "pruebas")
        with self.assertRaises(ValueError):
            Principal("domain_owner", "../otra")


if __name__ == "__main__":
    unittest.main()
