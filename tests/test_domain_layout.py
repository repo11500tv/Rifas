import tempfile
import unittest
from pathlib import Path

from deployment.domain_layout import validate_path, validate_profile


class DomainLayoutTests(unittest.TestCase):
    def test_confines_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            vhosts = Path(temp) / "var/www/vhosts"
            domain = vhosts / "dealfonso.com"
            domain.mkdir(parents=True)
            inside = domain / "rifas-deployment/staging/control"
            self.assertEqual(validate_path(domain, inside), inside)
            for outside in (Path(temp) / "srv/rifas-deploy/staging",
                            vhosts / "otro.com/rifas", domain / "../otro.com/rifas"):
                with self.assertRaises(ValueError):
                    validate_path(domain, outside)
            (domain / "escape").symlink_to(Path(temp), target_is_directory=True)
            with self.assertRaises(ValueError):
                validate_path(domain, domain / "escape/secret")

    def test_profile_rejects_external_control(self):
        with tempfile.TemporaryDirectory() as temp:
            # La función exige /var/www/vhosts real; probar solo el control
            # de rutas mediante un dominio temporal no es válido.
            with self.assertRaises(ValueError):
                validate_profile({"control_root": "/srv/rifas-deploy/staging/control"}, temp)


if __name__ == "__main__":
    unittest.main()
