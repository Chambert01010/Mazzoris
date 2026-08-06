from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from statements.bank_registry import BankProcessor
from statements.utils import StatementProcessingError

LOGGER = logging.getLogger("mazzoris.statement_processing")


def _configure_statement_logger() -> None:
    if LOGGER.handlers:
        return
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.FileHandler(log_dir / "statement_processing.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.propagate = False


@dataclass(frozen=True)
class ProcessingResult:
    source_path: Path
    output_path: Path | None
    success: bool
    message: str


def is_pdf_path(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def build_output_path(pdf_path: Path, bank_slug: str, output_dir: Path | None = None) -> Path:
    base_dir = output_dir if output_dir is not None else pdf_path.parent
    return base_dir / f"{pdf_path.stem}_{bank_slug}.xlsx"


def _excel_bytes(excel_file: object) -> bytes:
    if hasattr(excel_file, "getvalue"):
        return excel_file.getvalue()
    if isinstance(excel_file, bytes):
        return excel_file
    raise TypeError("El procesador no devolvio bytes de Excel.")


def process_statement_file(
    bank: BankProcessor,
    pdf_path: Path,
    output_dir: Path | None = None,
) -> ProcessingResult:
    _configure_statement_logger()
    source = Path(pdf_path).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve() if output_dir is not None else None
    LOGGER.info("Inicio procesamiento local bank=%s source=%s output_dir=%s", bank.key, source, target_dir)

    if not source.exists():
        LOGGER.warning("Archivo inexistente source=%s", source)
        return ProcessingResult(source, None, False, "No existe el archivo.")
    if not is_pdf_path(source):
        LOGGER.warning("Archivo rechazado por extension source=%s", source)
        return ProcessingResult(source, None, False, "Solo se aceptan archivos PDF.")
    if target_dir is not None and not target_dir.exists():
        LOGGER.warning("Carpeta de salida inexistente output_dir=%s", target_dir)
        return ProcessingResult(source, None, False, "No existe la carpeta de salida.")

    output_path = build_output_path(source, bank.slug, target_dir)

    try:
        with source.open("rb") as pdf_file:
            excel_file = bank.processor(pdf_file)
        output_path.write_bytes(_excel_bytes(excel_file))
    except StatementProcessingError as exc:
        LOGGER.exception("Error controlado procesando bank=%s source=%s", bank.key, source)
        return ProcessingResult(source, output_path, False, str(exc))
    except PermissionError:
        LOGGER.exception("No se pudo escribir output=%s", output_path)
        return ProcessingResult(source, output_path, False, "No se pudo escribir el Excel. Cierra el archivo si esta abierto.")
    except Exception as exc:
        LOGGER.exception("Error inesperado procesando bank=%s source=%s", bank.key, source)
        return ProcessingResult(source, output_path, False, f"Error inesperado: {exc}")

    LOGGER.info("Procesamiento local exitoso bank=%s source=%s output=%s", bank.key, source, output_path)
    return ProcessingResult(source, output_path, True, "Excel generado.")


def process_statement_files(
    bank: BankProcessor,
    pdf_paths: Iterable[Path],
    output_dir: Path | None = None,
) -> list[ProcessingResult]:
    return [process_statement_file(bank, Path(path), output_dir) for path in pdf_paths]
