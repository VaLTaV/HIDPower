"""Assistente de primeiro uso portátil do HIDPower para escolha da pasta e inicialização."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from app_config import (
    AppConfig,
    append_log,
    get_config_path,
    get_suggested_parent_dir,
    is_ephemeral_exe_dir,
    load_config,
    normalize_hidpower_folder,
    save_config,
    set_active_data_dir,
    set_startup_enabled,
)
from i18n import LANGUAGE_LABELS, normalize_language, tr
from icon_renderer import render_app_badge_image, render_hip_emblem
from monitor_utils import enumerate_monitors, get_primary_monitor

BG_MAIN = "#0F172A"
BG_CARD = "#1E293B"
BG_ELEVATED = "#273549"
BORDER_COLOR = "#334155"
FG_TEXT = "#F8FAFC"
FG_MUTED = "#94A3B8"
ACCENT_BLUE = "#38BDF8"
ACCENT_GREEN = "#22C55E"


@dataclass
class SetupResult:
    """Resultado selecionado pelo usuário no assistente inicial."""

    target_dir: Path
    language: str
    exe_action: str  # "copy" | "move" | "keep"
    enable_startup: bool


class FirstRunWizardDialog:
    """Janela modal para escolher onde criar a pasta portátil HIDPower."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        current_exe: Path | None = None,
        initial_lang: str = "pt-BR",
        show_window: bool = True,
    ) -> None:
        self._root = root
        self._current_exe = current_exe
        self._lang = normalize_language(initial_lang)
        self.result: SetupResult | None = None

        primary = get_primary_monitor(enumerate_monitors())
        self._scale = primary.scale if primary else 1.0
        work_w = (primary.work_rect[2] - primary.work_rect[0]) if primary else 1280
        work_h = (primary.work_rect[3] - primary.work_rect[1]) if primary else 800

        self._lang_var = tk.StringVar(master=root, value=LANGUAGE_LABELS[self._lang])
        self._folder_var = tk.StringVar(
            master=root, value=str(get_suggested_parent_dir())
        )
        if current_exe is not None:
            default_action = "move" if is_ephemeral_exe_dir(current_exe.parent) else "copy"
        else:
            default_action = "keep"
        self._exe_action_var = tk.StringVar(
            master=root,
            value=default_action,
        )
        self._startup_var = tk.BooleanVar(master=root, value=False)
        self._preview_var = tk.StringVar(master=root, value="")

        win = tk.Toplevel(root)
        self._win = win
        if not show_window:
            win.withdraw()
        win.configure(bg=BG_MAIN)
        win.protocol("WM_DELETE_WINDOW", self._on_cancel)

        base_h = 500 if current_exe is not None else 410
        win_w = min(int(round(580 * self._scale)), max(500, work_w - 40))
        win_h = min(int(round(base_h * self._scale)), max(380, work_h - 60))
        x = (work_w - win_w) // 2 + (primary.work_rect[0] if primary else 0)
        y = (work_h - win_h) // 2 + (primary.work_rect[1] if primary else 0)
        win.geometry(f"{win_w}x{win_h}+{x}+{y}")
        win.resizable(False, False)

        self._badge_photo: ImageTk.PhotoImage | None = None
        self._emblem_photo: ImageTk.PhotoImage | None = None
        try:
            self._badge_photo = ImageTk.PhotoImage(
                render_app_badge_image(64), master=win
            )
            win.iconphoto(False, self._badge_photo)
        except Exception:
            pass

        style = ttk.Style(win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Wizard.TCombobox",
            fieldbackground=BG_ELEVATED,
            background=BG_ELEVATED,
            foreground=FG_TEXT,
            arrowcolor=FG_TEXT,
            borderwidth=0,
        )

        # Cabeçalho com emblema HIP + HIDPower + seletor de idioma
        header = tk.Frame(win, bg=BG_MAIN, padx=20, pady=14)
        header.pack(fill=tk.X)

        brand_row = tk.Frame(header, bg=BG_MAIN)
        brand_row.pack(fill=tk.X)

        try:
            emblem_h = max(24, int(round(32 * self._scale)))
            self._emblem_photo = ImageTk.PhotoImage(
                render_hip_emblem(height=emblem_h), master=win
            )
            tk.Label(brand_row, image=self._emblem_photo, bg=BG_MAIN).pack(
                side=tk.LEFT, padx=(0, 10)
            )
        except Exception:
            pass

        tk.Label(
            brand_row,
            text="HIDPower",
            bg=BG_MAIN,
            fg=FG_TEXT,
            font=("Segoe UI", 16, "bold"),
        ).pack(side=tk.LEFT)

        lang_combo = ttk.Combobox(
            brand_row,
            textvariable=self._lang_var,
            values=tuple(LANGUAGE_LABELS.values()),
            width=18,
            state="readonly",
            style="Wizard.TCombobox",
        )
        lang_combo.pack(side=tk.RIGHT)
        lang_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        self._desc_lbl = tk.Label(
            win,
            text="",
            bg=BG_MAIN,
            fg=FG_MUTED,
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            wraplength=int(round(530 * self._scale)),
            anchor="w",
            padx=20,
        )
        self._desc_lbl.pack(fill=tk.X, pady=(0, 10))

        # Card de escolha de diretório
        folder_card = tk.Frame(
            win,
            bg=BG_CARD,
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
        )
        folder_card.pack(fill=tk.X, padx=20, pady=(0, 10))

        self._folder_lbl = tk.Label(
            folder_card,
            text="",
            bg=BG_CARD,
            fg=FG_TEXT,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        self._folder_lbl.pack(fill=tk.X, pady=(0, 6))

        entry_row = tk.Frame(folder_card, bg=BG_CARD)
        entry_row.pack(fill=tk.X)

        entry = tk.Entry(
            entry_row,
            textvariable=self._folder_var,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 8))

        self._btn_browse = tk.Button(
            entry_row,
            text="",
            command=self._on_browse,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            activebackground=BORDER_COLOR,
            activeforeground=FG_TEXT,
            relief=tk.FLAT,
            padx=12,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_browse.pack(side=tk.RIGHT)

        self._preview_lbl = tk.Label(
            folder_card,
            textvariable=self._preview_var,
            bg=BG_CARD,
            fg=ACCENT_BLUE,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=int(round(500 * self._scale)),
            justify=tk.LEFT,
        )
        self._preview_lbl.pack(fill=tk.X, pady=(8, 0))
        self._folder_var.trace_add("write", lambda *_args: self._update_preview())

        # Card opcional de ação para HIDPower.exe
        self._exe_group_lbl: tk.Label | None = None
        self._rb_copy: tk.Radiobutton | None = None
        self._rb_move: tk.Radiobutton | None = None
        self._rb_keep: tk.Radiobutton | None = None

        if current_exe is not None:
            exe_card = tk.Frame(
                win,
                bg=BG_CARD,
                padx=14,
                pady=10,
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
            )
            exe_card.pack(fill=tk.X, padx=20, pady=(0, 10))

            self._exe_group_lbl = tk.Label(
                exe_card,
                text="",
                bg=BG_CARD,
                fg=FG_TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            self._exe_group_lbl.pack(fill=tk.X, pady=(0, 4))

            for attr_name, val in (
                ("_rb_move", "move"),
                ("_rb_copy", "copy"),
                ("_rb_keep", "keep"),
            ):
                rb = tk.Radiobutton(
                    exe_card,
                    text="",
                    variable=self._exe_action_var,
                    value=val,
                    bg=BG_CARD,
                    fg=FG_TEXT,
                    selectcolor=BG_MAIN,
                    activebackground=BG_CARD,
                    activeforeground=FG_TEXT,
                    font=("Segoe UI", 9),
                    anchor="w",
                )
                rb.pack(fill=tk.X, pady=1)
                setattr(self, attr_name, rb)

        # Opção Iniciar com o Windows
        self._chk_startup = tk.Checkbutton(
            win,
            text="",
            variable=self._startup_var,
            bg=BG_MAIN,
            fg=FG_TEXT,
            selectcolor=BG_CARD,
            activebackground=BG_MAIN,
            activeforeground=FG_TEXT,
            font=("Segoe UI", 9),
            anchor="w",
            padx=20,
        )
        self._chk_startup.pack(fill=tk.X, pady=(2, 10))

        # Rodapé com botões
        btn_row = tk.Frame(win, bg=BG_MAIN, padx=20, pady=12)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)

        self._btn_cancel = tk.Button(
            btn_row,
            text="",
            command=self._on_cancel,
            bg=BG_ELEVATED,
            fg=FG_TEXT,
            activebackground=BORDER_COLOR,
            activeforeground=FG_TEXT,
            relief=tk.FLAT,
            padx=14,
            pady=6,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        self._btn_cancel.pack(side=tk.RIGHT, padx=(8, 0))

        self._btn_continue = tk.Button(
            btn_row,
            text="",
            command=self._on_confirm,
            bg=ACCENT_GREEN,
            fg="#052E16",
            activebackground="#4ADE80",
            activeforeground="#052E16",
            relief=tk.FLAT,
            padx=18,
            pady=6,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        self._btn_continue.pack(side=tk.RIGHT)

        self.apply_language(self._lang)
        self._update_preview()
        if show_window:
            win.lift()
            win.focus_force()

    def apply_language(self, lang: str) -> None:
        """Atualiza todos os textos do assistente no idioma escolhido."""
        self._lang = normalize_language(lang)
        self._win.title(tr(self._lang, "setup_title"))
        self._desc_lbl.configure(text=tr(self._lang, "setup_desc"))
        self._folder_lbl.configure(text=tr(self._lang, "setup_folder_label"))
        self._btn_browse.configure(text=tr(self._lang, "setup_browse"))
        if self._exe_group_lbl is not None:
            self._exe_group_lbl.configure(text=tr(self._lang, "setup_exe_group"))
        if self._rb_copy is not None:
            self._rb_copy.configure(text=tr(self._lang, "setup_exe_copy"))
        if self._rb_move is not None:
            self._rb_move.configure(text=tr(self._lang, "setup_exe_move"))
        if self._rb_keep is not None:
            self._rb_keep.configure(text=tr(self._lang, "setup_exe_keep"))
        self._chk_startup.configure(text=tr(self._lang, "setup_startup"))
        self._btn_cancel.configure(text=tr(self._lang, "setup_cancel"))
        self._btn_continue.configure(text=tr(self._lang, "setup_continue"))
        self._update_preview()

    def _on_language_change(self, _event: object = None) -> None:
        label = self._lang_var.get()
        chosen = next(
            (code for code, text in LANGUAGE_LABELS.items() if text == label),
            "pt-BR",
        )
        self.apply_language(chosen)

    def _update_preview(self) -> None:
        raw = self._folder_var.get().strip()
        if not raw:
            base = get_suggested_parent_dir()
        else:
            base = Path(raw)
        final_dir = normalize_hidpower_folder(base)
        self._preview_var.set(tr(self._lang, "setup_preview", path=final_dir))

    def _on_browse(self) -> None:
        initial = self._folder_var.get().strip() or str(get_suggested_parent_dir())
        chosen = filedialog.askdirectory(
            parent=self._win,
            title=tr(self._lang, "setup_browse_title"),
            initialdir=initial if Path(initial).exists() else str(Path.home()),
        )
        if chosen:
            self._folder_var.set(chosen)

    def _on_confirm(self) -> None:
        raw = self._folder_var.get().strip()
        base = Path(raw) if raw else get_suggested_parent_dir()
        target_dir = normalize_hidpower_folder(base)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror(
                tr(self._lang, "setup_err_title"),
                str(exc),
                parent=self._win,
            )
            return

        action = self._exe_action_var.get() if self._current_exe is not None else "keep"
        self.result = SetupResult(
            target_dir=target_dir.resolve(),
            language=self._lang,
            exe_action=action,
            enable_startup=bool(self._startup_var.get()),
        )
        self._win.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self._win.destroy()

    def destroy(self) -> None:
        """Destrói a janela caso ainda exista."""
        if self._win.winfo_exists():
            self._win.destroy()


def apply_first_run_setup(
    result: SetupResult,
    current_exe: Path | None = None,
) -> tuple[Path | None, str | None]:
    """Cria a pasta HIDPower, persiste config inicial e copia/move o executável se solicitado."""
    final_dir = set_active_data_dir(result.target_dir, persist_pointer=True)

    cfg_path = get_config_path()
    if cfg_path.exists():
        cfg = load_config()
        cfg.language = result.language
    else:
        cfg = AppConfig(language=result.language)
    save_config(cfg)
    append_log(f"HIDPower folder configured: {final_dir}")

    if (
        current_exe is not None
        and current_exe.exists()
        and result.exe_action in ("copy", "move")
        and current_exe.parent.resolve() != final_dir.resolve()
    ):
        target_exe = final_dir / current_exe.name
        shutil.copy2(current_exe, target_exe)
        if not (target_exe.is_file() and target_exe.stat().st_size > 0):
            raise OSError(f"Falha ao copiar executável para {target_exe}")
        append_log(f"Executable {result.exe_action} to {target_exe}")
        if result.enable_startup:
            set_startup_enabled(True, exe_override=target_exe)
        old_to_remove = str(current_exe.resolve()) if result.exe_action == "move" else None
        return (target_exe, old_to_remove)

    if result.enable_startup:
        set_startup_enabled(True)
    return (None, None)


def run_first_run_wizard(
    current_exe: Path | None = None,
    initial_lang: str = "pt-BR",
) -> SetupResult | None:
    """Executa o assistente de escolha da pasta HIDPower de forma modal e retorna SetupResult."""
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = FirstRunWizardDialog(
            root,
            current_exe=current_exe,
            initial_lang=initial_lang,
            show_window=True,
        )
        root.wait_window(dialog._win)
        return dialog.result
    finally:
        try:
            root.destroy()
        except Exception:
            pass
