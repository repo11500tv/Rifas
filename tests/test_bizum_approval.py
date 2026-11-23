"""Pruebas aisladas de aprobacion administrativa de recargas Bizum."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from platform_app.participant_schema_complete import initialize_participant_schema
from platform_app.participant_topup_admin import bp


class BizumApprovalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="rifas-bizum-test-")
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "rifas.sqlite3"
        with self.db() as con:
            initialize_participant_schema(con)
            con.executescript("""
                CREATE TABLE entity_admins (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active INTEGER NOT NULL
                );
                CREATE TABLE topup_requests (
                    id INTEGER PRIMARY KEY,
                    participant_id INTEGER NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    payment_method TEXT NOT NULL,
                    payment_reference TEXT NOT NULL DEFAULT '',
                    participant_notes TEXT NOT NULL DEFAULT '',
                    admin_notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT,
                    reviewed_by INTEGER,
                    credit_movement_id INTEGER
                );
                INSERT INTO entity_admins VALUES (1,'admin','owner',1);
                INSERT INTO participants
                    (id,name,email,phone,email_verified)
                VALUES (1,'Participante','one@example.invalid','+34600000001',1);
                INSERT INTO topup_requests
                    (id,participant_id,amount_cents,payment_method,payment_reference)
                VALUES (1,1,1200,'bizum','BIZ-001');
            """)
        app = Flask(__name__)
        app.secret_key = "test-secret"
        app.testing = True
        app.register_blueprint(bp)
        self.app = app
        for target in ("platform_app.entity_routes.edb",
                       "platform_app.participant_topup_admin.edb"):
            p = patch(target, side_effect=lambda slug: self.db())
            p.start()
            self.addCleanup(p.stop)
        for target in ("platform_app.entity_routes.get_entity",
                       "platform_app.participant_topup_admin.get_entity"):
            p = patch(target, return_value={"status": "active", "name": "Entidad"})
            p.start()
            self.addCleanup(p.stop)

    def db(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def client(self):
        client = self.app.test_client()
        with client.session_transaction() as s:
            s["entity_slug"] = "alpha"
            s["entity_user"] = "admin"
            s["entity_user_id"] = 1
        return client

    def resolve(self, client, decision="approve", confirmed=True, notes=""):
        return client.post("/e/alpha/administracion/recargas/1/resolver", data={
            "decision": decision,
            "payment_confirmed": "yes" if confirmed else "",
            "admin_notes": notes,
        })

    def snapshot(self):
        with self.db() as con:
            row = con.execute(
                "SELECT status,credit_movement_id FROM topup_requests WHERE id=1"
            ).fetchone()
            movements = con.execute(
                "SELECT amount_cents,reference FROM credit_movements ORDER BY id"
            ).fetchall()
            return row["status"], row["credit_movement_id"], [
                (m["amount_cents"], m["reference"]) for m in movements
            ]

    def test_approval_requires_confirmation_of_received_money(self):
        response = self.resolve(self.client(), confirmed=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.snapshot(), ("pending", None, []))

    def test_approval_creates_one_credit_movement(self):
        response = self.resolve(self.client())
        self.assertEqual(response.status_code, 302)
        status, movement_id, movements = self.snapshot()
        self.assertEqual(status, "approved")
        self.assertIsNotNone(movement_id)
        self.assertEqual(movements, [(1200, "TOPUP-1")])

    def test_repeated_approval_does_not_duplicate_credit(self):
        client = self.client()
        self.assertEqual(self.resolve(client).status_code, 302)
        self.assertEqual(self.resolve(client).status_code, 409)
        self.assertEqual(self.snapshot()[2], [(1200, "TOPUP-1")])

    def test_rejection_requires_reason_and_does_not_credit(self):
        client = self.client()
        self.assertEqual(self.resolve(client, decision="reject").status_code, 400)
        self.assertEqual(self.snapshot(), ("pending", None, []))
        self.assertEqual(self.resolve(client, decision="reject", notes="No recibido").status_code, 302)
        self.assertEqual(self.snapshot(), ("rejected", None, []))

    def test_failed_update_rolls_back_credit_movement(self):
        with self.db() as con:
            con.execute("""CREATE TRIGGER fail_topup_update
                BEFORE UPDATE ON topup_requests
                BEGIN SELECT RAISE(ABORT, 'simulated failure'); END;""")
        with self.assertRaises(sqlite3.DatabaseError):
            self.resolve(self.client())
        self.assertEqual(self.snapshot(), ("pending", None, []))


if __name__ == "__main__":
    unittest.main()
