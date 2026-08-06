from __future__ import annotations

import queue
import threading
from datetime import datetime
from pathlib import Path
from tkinter import END, LEFT, RIGHT, BOTH, X, Y, Listbox, StringVar, Text, Tk, filedialog, messagebox, ttk

from desktop_banks_core import ProcessingResult, process_statement_file
from statements.bank_registry import BANKS, BankProcessor


class MazzorisBanksApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Mazzoris Bancos")
        self.root.geometry("860x620")
        self.root.minsize(760, 540)

        self.banks_by_label = {bank.label: bank for bank in BANKS}
        self.selected_bank = StringVar(value=BANKS[0].label)
        self.output_dir = StringVar(value="")
        self.files: list[Path] = []
        self.results_queue: queue.Queue[ProcessingResult | str] = queue.Queue()
        self.processing = False

        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f3ef")
        style.configure("Header.TFrame", background="#161616")
        style.configure("Title.TLabel", background="#161616", foreground="#f7f3ea", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", background="#161616", foreground="#c9c0b3", font=("Segoe UI", 10))
        style.configure("TLabel", background="#f5f3ef", foreground="#252525", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
        style.configure("Accent.TButton", background="#8f6a3a", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#75552d"), ("disabled", "#bdb5aa")])

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root)
        shell.pack(fill=BOTH, expand=True)

        header = ttk.Frame(shell, style="Header.TFrame", padding=(22, 18))
        header.pack(fill=X)
        ttk.Label(header, text="Mazzoris Bancos", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="Procesamiento local de estados de cuenta", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(shell, padding=18)
        body.pack(fill=BOTH, expand=True)

        controls = ttk.Frame(body)
        controls.pack(fill=X)

        ttk.Label(controls, text="Banco").grid(row=0, column=0, sticky="w")
        bank_combo = ttk.Combobox(
            controls,
            textvariable=self.selected_bank,
            values=[bank.label for bank in BANKS],
            state="readonly",
            width=28,
        )
        bank_combo.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(4, 0))

        ttk.Label(controls, text="Carpeta de salida").grid(row=0, column=1, sticky="w")
        output_entry = ttk.Entry(controls, textvariable=self.output_dir, state="readonly")
        output_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 0))
        ttk.Button(controls, text="Elegir", command=self.choose_output_dir).grid(row=1, column=2, padx=(0, 8), pady=(4, 0))
        ttk.Button(controls, text="Usar origen", command=lambda: self.output_dir.set("")).grid(row=1, column=3, pady=(4, 0))
        controls.columnconfigure(1, weight=1)

        files_frame = ttk.Frame(body)
        files_frame.pack(fill=BOTH, expand=True, pady=(18, 0))

        list_panel = ttk.Frame(files_frame)
        list_panel.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(list_panel, text="PDFs seleccionados").pack(anchor="w")
        list_wrap = ttk.Frame(list_panel)
        list_wrap.pack(fill=BOTH, expand=True, pady=(4, 0))
        self.files_listbox = Listbox(list_wrap, activestyle="none", selectmode="extended", font=("Segoe UI", 10), height=8)
        self.files_listbox.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_wrap, orient="vertical", command=self.files_listbox.yview)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.files_listbox.configure(yscrollcommand=scrollbar.set)

        file_buttons = ttk.Frame(files_frame, padding=(14, 22, 0, 0))
        file_buttons.pack(side=RIGHT, fill=Y)
        ttk.Button(file_buttons, text="Agregar PDFs", command=self.add_pdfs).pack(fill=X)
        ttk.Button(file_buttons, text="Quitar", command=self.remove_selected_files).pack(fill=X, pady=(8, 0))
        ttk.Button(file_buttons, text="Limpiar", command=self.clear_files).pack(fill=X, pady=(8, 0))

        actions = ttk.Frame(body)
        actions.pack(fill=X, pady=(16, 0))
        self.process_button = ttk.Button(actions, text="Procesar", style="Accent.TButton", command=self.start_processing)
        self.process_button.pack(side=LEFT)
        self.progress = ttk.Progressbar(actions, mode="determinate")
        self.progress.pack(side=LEFT, fill=X, expand=True, padx=(12, 0))

        ttk.Label(body, text="Estado").pack(anchor="w", pady=(18, 4))
        self.log_text = Text(body, height=9, wrap="word", font=("Consolas", 9), bg="#ffffff", fg="#222222")
        self.log_text.pack(fill=BOTH, expand=False)
        self._log("Listo.")

    def add_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Selecciona estados de cuenta",
            filetypes=(("PDF", "*.pdf"), ("Todos", "*.*")),
        )
        existing = {path.resolve() for path in self.files}
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if path not in existing:
                self.files.append(path)
                existing.add(path)
        self._refresh_files()

    def remove_selected_files(self) -> None:
        selected = set(self.files_listbox.curselection())
        self.files = [path for index, path in enumerate(self.files) if index not in selected]
        self._refresh_files()

    def clear_files(self) -> None:
        self.files.clear()
        self._refresh_files()

    def choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Selecciona carpeta de salida")
        if path:
            self.output_dir.set(str(Path(path).resolve()))

    def start_processing(self) -> None:
        if self.processing:
            return
        if not self.files:
            messagebox.showwarning("Sin PDFs", "Selecciona al menos un PDF.")
            return

        bank = self._current_bank()
        output_dir = Path(self.output_dir.get()).resolve() if self.output_dir.get() else None
        self.processing = True
        self.process_button.configure(state="disabled")
        self.progress.configure(maximum=len(self.files), value=0)
        self._log(f"Iniciando lote con {len(self.files)} archivo(s) para {bank.label}.")

        worker = threading.Thread(target=self._process_worker, args=(bank, list(self.files), output_dir), daemon=True)
        worker.start()
        self.root.after(100, self._poll_results)

    def _process_worker(self, bank: BankProcessor, files: list[Path], output_dir: Path | None) -> None:
        for path in files:
            self.results_queue.put(process_statement_file(bank, path, output_dir))
        self.results_queue.put("DONE")

    def _poll_results(self) -> None:
        finished = False
        while True:
            try:
                item = self.results_queue.get_nowait()
            except queue.Empty:
                break
            if item == "DONE":
                finished = True
                continue
            if isinstance(item, ProcessingResult):
                self.progress.configure(value=self.progress["value"] + 1)
                status = "OK" if item.success else "ERROR"
                detail = str(item.output_path) if item.success and item.output_path else item.message
                self._log(f"[{status}] {item.source_path.name} -> {detail}")

        if finished:
            self.processing = False
            self.process_button.configure(state="normal")
            self._log("Lote terminado.")
            messagebox.showinfo("Proceso terminado", "Se termino el lote de procesamiento.")
            return

        if self.processing:
            self.root.after(100, self._poll_results)

    def _current_bank(self) -> BankProcessor:
        return self.banks_by_label[self.selected_bank.get()]

    def _refresh_files(self) -> None:
        self.files_listbox.delete(0, END)
        for path in self.files:
            self.files_listbox.insert(END, str(path))

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(END, f"{timestamp}  {message}\n")
        self.log_text.see(END)


def main() -> None:
    root = Tk()
    MazzorisBanksApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
