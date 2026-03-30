from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from .utils import (
    StatementProcessingError,
    process_banorte,
    process_bbva,
    process_inbursa,
    process_scotiabank,
)


BANK_PROCESSORS = {
    "BBVAGEMINI": ("BBVA", process_bbva),
    "LeyeBanorte": ("Banorte", process_banorte),
    "Scotiabanck": ("Scotiabank", process_scotiabank),
    "inbursaGemini2.0": ("Inbursa", process_inbursa),
}
MAX_UPLOAD_SIZE = 15 * 1024 * 1024


def home(request):
    return render(request, "index.html")


@login_required
def dashboard(request):
    return render(request, "dashboard.html", {"bank_options": BANK_PROCESSORS})


@login_required
def process_statement(request, bank_name):
    if request.method != "POST":
        messages.error(request, "El procesamiento solo está disponible mediante carga de archivos.")
        return redirect("dashboard")

    bank_config = BANK_PROCESSORS.get(bank_name)
    if bank_config is None:
        messages.error(request, "El banco seleccionado no está soportado en este momento.")
        return redirect("dashboard")

    uploaded_file = request.FILES.get("statement_file")
    if uploaded_file is None:
        messages.error(request, "Selecciona un archivo PDF antes de continuar.")
        return redirect("dashboard")

    if not uploaded_file.name.lower().endswith(".pdf"):
        messages.error(request, "Por ahora solo se aceptan estados de cuenta en formato PDF.")
        return redirect("dashboard")

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        messages.error(request, "El archivo es demasiado grande. Usa un PDF de hasta 15 MB.")
        return redirect("dashboard")

    bank_label, processor = bank_config
    filename = f"{bank_name}_processed.xlsx"

    try:
        excel_file = processor(uploaded_file)
    except StatementProcessingError as exc:
        messages.error(request, f"No se pudo procesar el PDF de {bank_label}: {exc}")
        return redirect("dashboard")
    except Exception:
        messages.error(request, f"Ocurrió un error inesperado al procesar el estado de cuenta de {bank_label}.")
        return redirect("dashboard")

    response = HttpResponse(
        excel_file,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

