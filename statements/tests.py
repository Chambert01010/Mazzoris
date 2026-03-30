from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from .utils import parse_bbva_summary_text


class BbvaSummaryParsingTests(TestCase):
    def test_parse_bbva_summary_text_extracts_balances_and_totals(self):
        sample = """
        Saldo de Liquidacion Inicial 14,619.00
        Saldo de Operacion Inicial 14,619.00
        Depositos / Abonos (+) 31 1,857,120.35
        Retiros / Cargos (-) 41 1,807,982.30
        Saldo Final (+) 63,757.05
        Saldo de Operacion Final 63,757.05
        """

        summary = parse_bbva_summary_text(sample)

        self.assertEqual(summary["saldo_liquidacion_inicial"], Decimal("14619.00"))
        self.assertEqual(summary["saldo_operacion_inicial"], Decimal("14619.00"))
        self.assertEqual(summary["depositos_abonos"], Decimal("1857120.35"))
        self.assertEqual(summary["depositos_abonos_count"], 31)
        self.assertEqual(summary["retiros_cargos"], Decimal("1807982.30"))
        self.assertEqual(summary["retiros_cargos_count"], 41)
        self.assertEqual(summary["saldo_final"], Decimal("63757.05"))
        self.assertEqual(summary["saldo_operacion_final"], Decimal("63757.05"))


class StatementUploadValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="secret123")
        self.client = Client()
        self.client.login(username="tester", password="secret123")

    def test_rejects_non_pdf_upload(self):
        fake_file = SimpleUploadedFile("archivo.txt", b"texto de prueba", content_type="text/plain")

        response = self.client.post(
            reverse("process_statement", kwargs={"bank_name": "BBVAGEMINI"}),
            {"statement_file": fake_file},
            follow=True,
        )

        self.assertContains(response, "solo se aceptan estados de cuenta en formato PDF", status_code=200)

    def test_rejects_unknown_bank(self):
        fake_pdf = SimpleUploadedFile("archivo.pdf", b"%PDF-1.4", content_type="application/pdf")

        response = self.client.post(
            reverse("process_statement", kwargs={"bank_name": "banco-invalido"}),
            {"statement_file": fake_pdf},
            follow=True,
        )

        self.assertContains(response, "no está soportado", status_code=200)
