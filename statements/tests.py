import io
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import pandas as pd


from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from desktop_banks_core import build_output_path, process_statement_file, process_statement_files

from .bank_registry import BANKS, BANK_PROCESSORS, BankProcessor
from .intercam import _extract_intercam_row, _intercam_amount_column_centers, parse_intercam_account_summary
from .intercam import _validate_intercam_audit, build_intercam_audit_dataframe
from .utils import (
    BBVA_FOOTER_MAX_TOP,
    INBURSA_DETAIL_MAX_TOP,
    StatementProcessingError,
    _append_bbva_amount,
    _extract_inbursa_row_from_words,
    _inbursa_amount_column_centers,
    _is_bbva_transaction_start,
    parse_banorte_cuenta_cheques_summary_text,
    parse_bbva_summary_text,
    parse_inbursa_summary_text,
)


class BankRegistryTests(SimpleTestCase):
    def test_registry_matches_dashboard_banks(self):
        self.assertEqual(
            [(bank.key, bank.label, bank.slug) for bank in BANKS],
            [
                ("BBVAGEMINI", "BBVA", "bbva"),
                ("LeyeBanorte", "Banorte", "banorte"),
                ("banorteCuentaCheques", "Banorte Cuenta Cheques", "banorte_cuenta_cheques"),
                ("BanamexGemini", "Banamex", "banamex"),
                ("MercaPagoGPT", "Mercado Pago", "mercado_pago"),
                ("Scotiabanck", "Scotiabank", "scotiabank"),
                ("Intercam", "Intercam", "intercam"),
                ("inbursaGemini2.0", "Inbursa", "inbursa"),
            ],
        )

    def test_django_bank_mapping_keeps_legacy_shape(self):
        self.assertEqual(list(BANK_PROCESSORS), [bank.key for bank in BANKS])
        self.assertEqual([data[0] for data in BANK_PROCESSORS.values()], [bank.label for bank in BANKS])


class DesktopBanksCoreTests(SimpleTestCase):
    def test_build_output_path_uses_bank_slug_and_selected_folder(self):
        with TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "Estado Marzo.PDF"
            output_dir = Path(tmp_dir) / "salidas"
            expected = output_dir / "Estado Marzo_bbva.xlsx"

            self.assertEqual(build_output_path(source, "bbva", output_dir), expected)

    def test_rejects_non_pdf_file(self):
        with TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "estado.txt"
            source.write_text("texto", encoding="utf-8")
            bank = BankProcessor("fake", "Fake", "fake", lambda handle: io.BytesIO(b"xlsx"))

            result = process_statement_file(bank, source)

            self.assertFalse(result.success)
            self.assertIsNone(result.output_path)
            self.assertIn("PDF", result.message)

    def test_batch_continues_after_processing_error(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            good_pdf = root / "bueno.pdf"
            bad_pdf = root / "malo.pdf"
            output_dir = root / "salidas"
            good_pdf.write_bytes(b"%PDF-1.4")
            bad_pdf.write_bytes(b"%PDF-1.4")
            output_dir.mkdir()

            def processor(handle):
                if Path(handle.name).stem == "malo":
                    raise StatementProcessingError("fallo controlado")
                return io.BytesIO(b"xlsx")

            bank = BankProcessor("fake", "Fake", "fake", processor)

            results = process_statement_files(bank, [good_pdf, bad_pdf], output_dir)

            self.assertEqual([result.success for result in results], [True, False])
            self.assertEqual((output_dir / "bueno_fake.xlsx").read_bytes(), b"xlsx")
            self.assertIn("fallo controlado", results[1].message)


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


    def test_parse_compact_summary_uses_saldo_anterior(self):
        sample = """
        Saldo Anterior 98,778.10
        Depositos / Abonos (+) 87 871,089.41
        Retiros / Cargos (-) 48 938,500.68
        Saldo Final (+) 31,366.83
        """

        summary = parse_bbva_summary_text(sample)

        self.assertEqual(summary["saldo_operacion_inicial"], Decimal("98778.10"))
        self.assertEqual(summary["depositos_abonos_count"], 87)
        self.assertEqual(summary["retiros_cargos_count"], 48)
        self.assertEqual(summary["saldo_final"], Decimal("31366.83"))


class BbvaCompactLayoutTests(SimpleTestCase):
    def test_transaction_starts_with_two_dates_and_no_code(self):
        self.assertTrue(_is_bbva_transaction_start(["03/FEB", "01/FEB", "IVA", "COM.CH", "PAGADO"]))
        self.assertTrue(_is_bbva_transaction_start(["12/ENE", "12/ENE", "DEPOSITO", "EN", "EFECTIVO"]))
        self.assertFalse(_is_bbva_transaction_start(["03/FEB", "DEPOSITO", "EN", "EFECTIVO"]))

    def test_compact_amounts_use_right_edge(self):
        row = {"cargo": None, "abono": None, "saldo_operacion": None, "saldo_liquidacion": None}

        self.assertTrue(_append_bbva_amount(row, "66.24", 395.0, 414.5, compact_layout=True))
        self.assertTrue(_append_bbva_amount(row, "450.00", 440.8, 464.5, compact_layout=True))
        self.assertTrue(_append_bbva_amount(row, "31,366.83", 493.0, 531.0, compact_layout=True))

        self.assertEqual(row["cargo"], "66.24")
        self.assertEqual(row["abono"], "450.00")
        self.assertEqual(row["saldo_operacion"], "31,366.83")

    def test_footer_limit_includes_last_compact_rows(self):
        self.assertEqual(BBVA_FOOTER_MAX_TOP, 750)


class IntercamParsingTests(SimpleTestCase):
    def test_parse_summary_extracts_mxn_account_and_pdf_totals(self):
        sample = """
        ESTADO DE CUENTA ÚNICO
        Período DEL 2026-05-01 AL 2026-05-31
        SERVICIO EMPRESARIAL FX KAPITAL 001-89550-001-8 CLABE 128180018955000185
        Moneda MN
        Saldo Inicial 96.02 MN
        + Depósitos 0.01 MN
        - Retiros 0.01 MN
        Saldo Final 96.02
        Total 0.01 0.01 96.02
        """

        summary = parse_intercam_account_summary(sample)

        self.assertEqual(summary["cuenta"], "001-89550-001-8")
        self.assertEqual(summary["moneda"], "MXN")
        self.assertEqual(summary["saldo_inicial"], Decimal("96.02"))
        self.assertEqual(summary["depositos"], Decimal("0.01"))
        self.assertEqual(summary["retiros"], Decimal("0.01"))
        self.assertEqual(summary["saldo_final"], Decimal("96.02"))
        self.assertEqual(summary["total_saldo"], Decimal("96.02"))

    def test_amount_columns_distinguish_deposit_withdrawal_and_balance(self):
        header = [
            {"text": "DEPÓSITOS", "x0": 399.7, "x1": 446.4},
            {"text": "RETIROS", "x0": 466.4, "x1": 502.0},
            {"text": "SALDO", "x0": 528.7, "x1": 556.7},
        ]
        words = [
            {"text": "29", "x0": 51.7, "x1": 60.0},
            {"text": "638916428", "x0": 78.0, "x1": 113.0},
            {"text": "DESCUENTO", "x0": 150.0, "x1": 200.0},
            {"text": "0.01", "x0": 440.6, "x1": 454.2},
            {"text": "96.02", "x0": 553.7, "x1": 571.2},
        ]

        centers = _intercam_amount_column_centers(header)
        row = _extract_intercam_row(words, centers)

        self.assertEqual(row["deposito_text"], "0.01")
        self.assertIsNone(row["retiro_text"])
        self.assertEqual(row["saldo_text"], "96.02")

    def test_audit_rejects_any_difference(self):
        movements = pd.DataFrame(columns=["CUENTA", "SALDO_PDF", "DIFERENCIA_SALDO"])
        summary = pd.DataFrame([{
            "CUENTA": "001",
            "MONEDA": "MXN",
            "SALDO_INICIAL_PDF": 100.00,
            "DEPOSITOS_PDF": 10.00,
            "RETIROS_PDF": 0.00,
            "SALDO_FINAL_PDF": 110.00,
            "DEPOSITOS_TOTAL_TABLA": 10.00,
            "RETIROS_TOTAL_TABLA": 0.00,
            "SALDO_TOTAL_TABLA": 110.00,
            "DEPOSITOS_EXCEL": 9.00,
            "RETIROS_EXCEL": 0.00,
            "SALDO_FINAL_CALCULADO": 109.00,
        }])

        audit = build_intercam_audit_dataframe(movements, summary)

        with self.assertRaises(StatementProcessingError):
            _validate_intercam_audit(audit)

class InbursaParsingTests(SimpleTestCase):
    def test_parse_summary_extracts_all_required_values(self):
        sample = """
        SALDO ANTERIOR 85,859.67 DIAS DEL PERIODO 30
        ABONOS 296,246.37 TASA BRUTA 6.5957% RENDIMIENTOS 1,600.35
        CARGOS 99,376.10 TASA NETA 6.3603%
        SALDO ACTUAL 282,729.94 I.S.R. 0.9000% COMISIONES EFECTIVAMENTE COBRADAS
        SALDO PROMEDIO 291,164.15 EN EL PERIODO 319.00
        """

        summary = parse_inbursa_summary_text(sample)

        self.assertEqual(summary["saldo_inicial"], Decimal("85859.67"))
        self.assertEqual(summary["abonos"], Decimal("296246.37"))
        self.assertEqual(summary["cargos"], Decimal("99376.10"))
        self.assertEqual(summary["saldo_final"], Decimal("282729.94"))
        self.assertEqual(summary["rendimientos"], Decimal("1600.35"))
        self.assertEqual(summary["comisiones"], Decimal("319.00"))

    def test_row_without_day_carries_previous_day_and_uses_amount_columns(self):
        words = [
            {"text": "ABR.", "x0": 12.0, "x1": 31.6},
            {"text": "3883053619", "x0": 47.4, "x1": 92.4},
            {"text": "DEPOSITO", "x0": 105.0, "x1": 145.2},
            {"text": "SPEI", "x0": 148.0, "x1": 166.6},
            {"text": "610.00", "x0": 464.5, "x1": 490.3},
            {"text": "47,179.54", "x0": 527.6, "x1": 564.6},
        ]

        row, current_day = _extract_inbursa_row_from_words(words, current_day=5)

        self.assertEqual(current_day, 5)
        self.assertEqual(row["day"], 5)
        self.assertEqual(row["referencia"], "3883053619")
        self.assertEqual(row["concepto"], "DEPOSITO SPEI")
        self.assertEqual(row["abono_text"], "610.00")
        self.assertIsNone(row["cargo_text"])
        self.assertEqual(row["saldo_text"], "47,179.54")

    def test_short_charge_uses_right_edge_and_footer_rows_are_included(self):
        words = [
            {"text": "ENE.", "x0": 12.0, "x1": 31.6},
            {"text": "31", "x0": 38.0, "x1": 44.4},
            {"text": "3779725050", "x0": 48.0, "x1": 93.4},
            {"text": "IVA", "x0": 105.0, "x1": 118.0},
            {"text": "44.00", "x0": 396.5, "x1": 417.6},
            {"text": "37,687.03", "x0": 527.4, "x1": 564.6},
        ]

        row, _ = _extract_inbursa_row_from_words(words)

        self.assertEqual(row["cargo_text"], "44.00")
        self.assertIsNone(row["abono_text"])
        self.assertEqual(INBURSA_DETAIL_MAX_TOP, 750)

    def test_shifted_page_uses_its_own_amount_column_headers(self):
        header = [
            {"text": "CARGOS", "x0": 395.4, "x1": 426.9},
            {"text": "ABONOS", "x0": 462.7, "x1": 493.8},
            {"text": "SALDO", "x0": 526.7, "x1": 551.3},
        ]
        words = [
            {"text": "MAY.", "x0": 16.7, "x1": 37.0},
            {"text": "04", "x0": 39.0, "x1": 48.0},
            {"text": "FACTURA", "x0": 72.4, "x1": 112.0},
            {"text": "22,713.61", "x0": 411.7, "x1": 443.1},
            {"text": "235,500.08", "x0": 526.4, "x1": 564.7},
        ]

        centers = _inbursa_amount_column_centers(header)
        row, _ = _extract_inbursa_row_from_words(words, amount_column_centers=centers)

        self.assertEqual(row["cargo_text"], "22,713.61")
        self.assertIsNone(row["abono_text"])
        self.assertEqual(row["saldo_text"], "235,500.08")


class BanorteCuentaChequesSummaryParsingTests(TestCase):
    def test_parse_summary_text_extracts_counts_and_totals(self):
        sample = """
        DEPÓSITOS RETIROS
        OPERACIONES: 9 19
        TOTAL: $1,351,736.44 $1,257,337.03
        """

        summary = parse_banorte_cuenta_cheques_summary_text(sample)

        self.assertEqual(summary["depositos_count"], 9)
        self.assertEqual(summary["retiros_count"], 19)
        self.assertEqual(summary["depositos"], Decimal("1351736.44"))
        self.assertEqual(summary["retiros"], Decimal("1257337.03"))


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
