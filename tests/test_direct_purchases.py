"""Pruebas de compra directa con creditos, sin reservas ni servicios externos."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platform_app.participant_raffle_purchases import bp
from platform_app.participant_schema_complete import initialize_participant_schema
from platform_app.raffle_schema import SCHEMA_RAFFLES
from flask import Flask


class DirectPurchaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "entity.sqlite3"
        with self.connect() as db:
            initialize_participant_schema(db)
            db.executescript(SCHEMA_RAFFLES + """
                CREATE TABLE raffle_purchases (
                    id INTEGER PRIMARY KEY,
                    raffle_id INTEGER NOT NULL,
                    participant_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price_cents INTEGER NOT NULL,
                    total_cents INTEGER NOT NULL,
                    credit_movement_id INTEGER NOT NULL
                );
                CREATE TABLE raffle_numbers (
                    id INTEGER PRIMARY KEY,
                    raffle_id INTEGER NOT NULL,
                    purchase_id INTEGER NOT NULL,
                    participant_id INTEGER NOT NULL,
                    number INTEGER NOT NULL,
                    UNIQUE(raffle_id, number)
                );
                INSERT INTO participants
                    (id,name,email,phone,email_verified)
                VALUES (1,'Participante Uno','one@example.invalid','+34600000001',1),
                       (2,'Participante Dos','two@example.invalid','+34600000002',1);
                INSERT INTO raffles
                    (id,title,number_start,number_end,number_width,
                     donation_cents,status,created_by)
                VALUES (1,'Sorteo de prueba',0,99,2,200,'published','admin');
                INSERT INTO credit_movements
                    (participant_id,amount_cents,movement_type,reference)
                VALUES (1,1000,'topup','test-credit-one'),
                       (2,1000,'topup','test-credit-two');
            """)
        app = Flask(__name__)
        app.secret_key = "isolated-test-key"
        app.testing = True
        app.register_blueprint(bp)
        self.app = app
        self.entity = patch("platform_app.participant_raffle_purchases.active_entity",
                            return_value={"status": "active"})
        self.entity.start()
        self.addCleanup(self.entity.stop)
        self.edb = patch("platform_app.participant_raffle_purchases.edb",
                         side_effect=lambda slug: self.connect())
        self.edb.start()
        self.addCleanup(self.edb.stop)
        self.guard = patch("platform_app.participant_raffle_purchases.member_only",
                           side_effect=lambda fn: fn)
        # The blueprint's member_only decorator was applied at import time.
        # A real session is used, with the underlying entity guard patched.
        self.entity_guard = patch("platform_app.participant_routes.active_entity",
                                  return_value={"status": "active"})
        self.entity_guard.start()
        self.addCleanup(self.entity_guard.stop)
        self.access = patch("platform_app.participant_routes.participant_can_access",
                            return_value=True)
        self.access.start()
        self.addCleanup(self.access.stop)
        self.route_edb = patch("platform_app.participant_routes.edb",
                               side_effect=lambda slug: self.connect())
        self.route_edb.start()
        self.addCleanup(self.route_edb.stop)

    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def client_for(self, participant_id):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session["participant_slug"] = "alpha"
            session["participant_id"] = participant_id
        return client

    def buy(self, client, numbers):
        return client.post("/e/alpha/participantes/sorteos/1/comprar",
                           data={"numbers": [str(n) for n in numbers]})

    def snapshot(self):
        with self.connect() as db:
            purchases = db.execute("SELECT COUNT(*) FROM raffle_purchases").fetchone()[0]
            numbers = [r[0] for r in db.execute(
                "SELECT number FROM raffle_numbers ORDER BY number")]
            balances = [db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM credit_movements "
                "WHERE participant_id=?", (pid,)).fetchone()[0]
                for pid in (1, 2)]
        return purchases, numbers, balances

    def test_success_debits_and_assigns_atomically(self):
        response = self.buy(self.client_for(1), [3, 7])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.snapshot(), (1, [3, 7], [600, 1000]))

    def test_duplicate_number_cannot_be_sold_twice(self):
        self.assertEqual(self.buy(self.client_for(1), [8]).status_code, 302)
        self.assertEqual(self.buy(self.client_for(2), [8]).status_code, 302)
        self.assertEqual(self.snapshot(), (1, [8], [800, 1000]))

    def test_insufficient_balance_leaves_database_unchanged(self):
        self.assertEqual(self.buy(self.client_for(1), [1,2,3,4,5,6]).status_code, 302)
        self.assertEqual(self.snapshot(), (0, [], [1000, 1000]))

    def test_invalid_duplicate_and_out_of_range_inputs(self):
        client = self.client_for(1)
        for numbers in ([2, 2], [-1], [100], []):
            self.assertEqual(self.buy(client, numbers).status_code, 400)
        self.assertEqual(self.snapshot(), (0, [], [1000, 1000]))

    def test_rollback_on_number_insertion_failure(self):
        with self.connect() as db:
            db.execute("""CREATE TRIGGER fail_number BEFORE INSERT ON raffle_numbers
                          BEGIN SELECT RAISE(ABORT, 'simulated failure'); END;""")
        with self.assertRaises(sqlite3.DatabaseError):
            self.buy(self.client_for(1), [12])
        self.assertEqual(self.snapshot(), (0, [], [1000, 1000]))


if __name__ == "__main__":
    unittest.main()
