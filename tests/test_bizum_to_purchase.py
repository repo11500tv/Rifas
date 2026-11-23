"""Prueba integrada: Bizum manual aprobado -> creditos -> compra inmediata."""

from unittest.mock import patch

from tests.test_bizum_approval import BizumApprovalTest
from platform_app.participant_raffle_purchases import bp as purchase_bp
from platform_app.raffle_schema import SCHEMA_RAFFLES


class BizumToPurchaseTest(BizumApprovalTest):
    def setUp(self):
        super().setUp()
        with self.db() as con:
            con.executescript(SCHEMA_RAFFLES + """
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
                INSERT INTO raffles
                    (id,title,number_start,number_end,number_width,
                     donation_cents,status,created_by)
                VALUES (1,'Sorteo integrado',0,99,2,300,'published','admin');
            """)
        self.app.register_blueprint(purchase_bp)
        for target in ("platform_app.participant_raffle_purchases.edb",
                       "platform_app.participant_routes.edb"):
            p = patch(target, side_effect=lambda slug: self.db())
            p.start()
            self.addCleanup(p.stop)
        p = patch("platform_app.participant_raffle_purchases.active_entity",
                  return_value={"status": "active"})
        p.start()
        self.addCleanup(p.stop)
        p = patch("platform_app.participant_routes.active_entity",
                  return_value={"status": "active"})
        p.start()
        self.addCleanup(p.stop)
        p = patch("platform_app.participant_routes.participant_can_access",
                  return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_bizum_approval_funds_purchase_and_prevents_reuse(self):
        participant = self.app.test_client()
        with participant.session_transaction() as session:
            session["participant_slug"] = "alpha"
            session["participant_id"] = 1

        purchase_url = "/e/alpha/participantes/sorteos/1/comprar"
        payload = {"numbers": ["4", "5"]}
        # Pending Bizum is not spendable.
        self.assertEqual(participant.post(purchase_url, data=payload).status_code, 302)
        with self.db() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM raffle_numbers").fetchone()[0], 0)

        admin = self.client()
        self.assertEqual(self.resolve(admin).status_code, 302)
        self.assertEqual(self.resolve(admin).status_code, 409)

        self.assertEqual(participant.post(purchase_url, data=payload).status_code, 302)
        self.assertEqual(participant.post(purchase_url, data=payload).status_code, 302)
        with self.db() as con:
            self.assertEqual([r[0] for r in con.execute(
                "SELECT number FROM raffle_numbers ORDER BY number")], [4, 5])
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM raffle_purchases").fetchone()[0], 1)
            self.assertEqual(con.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM credit_movements "
                "WHERE participant_id=1").fetchone()[0], 600)
            self.assertEqual(con.execute(
                "SELECT COUNT(*) FROM credit_movements WHERE movement_type='topup'"
            ).fetchone()[0], 1)
