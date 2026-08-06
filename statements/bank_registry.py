from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Callable

from .intercam import process_intercam
from .utils import (
    process_banamex,
    process_banorte,
    process_banorte_cuenta_cheques,
    process_bbva,
    process_inbursa,
    process_mercado_pago,
    process_scotiabank,
)


Processor = Callable[[BinaryIO], object]


@dataclass(frozen=True)
class BankProcessor:
    key: str
    label: str
    slug: str
    processor: Processor


BANKS: tuple[BankProcessor, ...] = (
    BankProcessor("BBVAGEMINI", "BBVA", "bbva", process_bbva),
    BankProcessor("LeyeBanorte", "Banorte", "banorte", process_banorte),
    BankProcessor("banorteCuentaCheques", "Banorte Cuenta Cheques", "banorte_cuenta_cheques", process_banorte_cuenta_cheques),
    BankProcessor("BanamexGemini", "Banamex", "banamex", process_banamex),
    BankProcessor("MercaPagoGPT", "Mercado Pago", "mercado_pago", process_mercado_pago),
    BankProcessor("Scotiabanck", "Scotiabank", "scotiabank", process_scotiabank),
    BankProcessor("Intercam", "Intercam", "intercam", process_intercam),
    BankProcessor("inbursaGemini2.0", "Inbursa", "inbursa", process_inbursa),
)

BANKS_BY_KEY = {bank.key: bank for bank in BANKS}

# Backwards-compatible shape expected by the Django dashboard template.
BANK_PROCESSORS = {bank.key: (bank.label, bank.processor) for bank in BANKS}


def get_bank(key: str) -> BankProcessor | None:
    return BANKS_BY_KEY.get(key)
