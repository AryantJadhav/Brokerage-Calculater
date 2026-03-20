"""
main.py
───────────────────────────────────────────────────────────────────────────────
CustomTkinter GUI for the Brokerage & MTF Interest Calculator.

All financial logic lives in calculations.py; this file handles only
layout, user interaction, and result display.

Usage:
    python main.py
"""

import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox
from pathlib import Path
from datetime import datetime

import customtkinter as ctk

import calculations as calc
import stock_loader
import updater
from app_meta import (
    APP_NAME,
    APP_VERSION,
    GITHUB_OWNER,
    GITHUB_REPO,
    INSTALLER_ASSET_KEYWORD,
)

try:
    from tkcalendar import Calendar
except ImportError:
    Calendar = None


# ─────────────────────────────────────────────────────────────────────────────
# Autocomplete entry widget
# ─────────────────────────────────────────────────────────────────────────────

class AutocompleteEntry(ctk.CTkFrame):
    """
    A CTkEntry wrapped in a transparent CTkFrame that pops up a Toplevel
    dropdown with live autocomplete suggestions as the user types.

    Public interface mirrors CTkEntry:  .get()  .delete()  .insert()
    """

    _MAX_ITEMS = 10    # maximum suggestions shown at once
    _ITEM_H    = 33    # height (px) of each suggestion row

    def __init__(
        self,
        parent,
        suggestions: list,
        height: int = 36,
        font=None,
        placeholder_text: str = "",
        **kwargs,
    ) -> None:
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._all_suggestions = suggestions
        self._drop: tk.Toplevel | None = None
        self._btns: list = []
        self._sel_idx: int = -1
        self._updating = False   # guard against recursive trace

        self._var = tk.StringVar()
        self._var.trace_add("write", self._enforce_uppercase)

        self._entry = ctk.CTkEntry(
            self,
            textvariable=self._var,
            height=height,
            font=font,
            placeholder_text=placeholder_text,
        )
        self._entry.pack(fill="both", expand=True)

        self._entry.bind("<KeyRelease>", self._on_keyrelease)
        self._entry.bind("<FocusOut>",   self._on_focusout)
        self._entry.bind("<Escape>",     lambda _: self._close())
        self._entry.bind("<Down>",       self._on_navigate)
        self._entry.bind("<Up>",         self._on_navigate)
        self._entry.bind("<Return>",     self._on_return)

    # ── Uppercase enforcer ────────────────────────────────────────────────────

    def _enforce_uppercase(self, *_) -> None:
        """StringVar write trace – silently converts every character to uppercase."""
        if self._updating:
            return
        val = self._var.get()
        upper = val.upper()
        if val != upper:
            self._updating = True
            try:
                # Preserve cursor position across the replacement
                widget = self._entry._entry  # underlying tk.Entry inside CTkEntry
                cursor = widget.index(tk.INSERT)
                self._var.set(upper)
                widget.icursor(cursor)
            finally:
                self._updating = False

    # ── Public interface ──────────────────────────────────────────────────────

    def get(self) -> str:
        return self._entry.get()

    def delete(self, *args):
        self._entry.delete(*args)

    def insert(self, *args):
        self._entry.insert(*args)

    def configure(self, **kwargs):
        forwarded = {k: kwargs.pop(k) for k in ("placeholder_text", "height", "font") if k in kwargs}
        if forwarded:
            self._entry.configure(**forwarded)
        if kwargs:
            super().configure(**kwargs)

    def set_suggestions(self, suggestions: list) -> None:
        """Hot-swap the autocomplete list (called after background stock load)."""
        self._all_suggestions = suggestions
        # If a dropdown is currently open, rebuild it with the new list
        query = self._entry.get().strip()
        if query and self._drop and self._drop.winfo_exists():
            matches = self._filter(query)
            self._show_dropdown(matches) if matches else self._close()

    # ── Filtering ─────────────────────────────────────────────────────────────

    def _filter(self, query: str) -> list:
        q = query.upper()
        results, seen = [], set()
        # Priority 1 – symbol starts with query
        for sym, name in self._all_suggestions:
            if sym.startswith(q) and sym not in seen:
                results.append((sym, name))
                seen.add(sym)
                if len(results) == self._MAX_ITEMS:
                    return results
        # Priority 2 – company name contains query
        for sym, name in self._all_suggestions:
            if q in name.upper() and sym not in seen:
                results.append((sym, name))
                seen.add(sym)
                if len(results) == self._MAX_ITEMS:
                    break
        return results

    # ── Dropdown lifecycle ────────────────────────────────────────────────────

    def _show_dropdown(self, matches: list) -> None:
        self._close()
        self._sel_idx = -1
        self._btns = []

        x = self._entry.winfo_rootx()
        y = self._entry.winfo_rooty() + self._entry.winfo_height() + 2
        w = self._entry.winfo_width()
        h = len(matches) * self._ITEM_H + 4

        self._drop = tk.Toplevel(self)
        self._drop.wm_overrideredirect(True)
        self._drop.geometry(f"{w}x{h}+{x}+{y}")
        self._drop.configure(bg="#1e293b")
        self._drop.lift()

        for sym, name in matches:
            btn = ctk.CTkButton(
                self._drop,
                text=f"  {sym}  \u2013  {name}",
                anchor="w",
                height=self._ITEM_H - 2,
                fg_color="#1e293b",
                hover_color="#334155",
                text_color="#e2e8f0",
                font=ctk.CTkFont(size=12),
                corner_radius=0,
                border_width=0,
                command=lambda s=sym: self._select(s),
            )
            btn.pack(fill="x", padx=2, pady=1)
            self._btns.append(btn)

    def _close(self) -> None:
        if self._drop and self._drop.winfo_exists():
            self._drop.destroy()
        self._drop = None
        self._sel_idx = -1
        self._btns = []

    def _select(self, symbol: str) -> None:
        self._entry.delete(0, "end")
        self._entry.insert(0, symbol)
        self._close()
        self._entry.focus_set()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_keyrelease(self, event) -> None:
        skip = {"Up", "Down", "Return", "Escape",
                "Left", "Right", "Shift_L", "Shift_R",
                "Control_L", "Control_R", "Tab"}
        if event.keysym in skip:
            return
        query = self._entry.get().strip()
        if not query:
            self._close()
            return
        matches = self._filter(query)
        self._show_dropdown(matches) if matches else self._close()

    def _on_focusout(self, event) -> None:
        # Delay gives the dropdown button click time to register
        self.after(180, self._close)

    def _on_navigate(self, event) -> None:
        if not self._btns:
            return
        n = len(self._btns)
        self._sel_idx = (self._sel_idx + (1 if event.keysym == "Down" else -1)) % n
        for i, btn in enumerate(self._btns):
            btn.configure(fg_color="#334155" if i == self._sel_idx else "#1e293b")

    def _on_return(self, event) -> None:
        if 0 <= self._sel_idx < len(self._btns):
            self._btns[self._sel_idx].invoke()


# ─────────────────────────────────────────────────────────────────────────────
# Global theme settings
# ─────────────────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colour palette
C_BG_HEADER = "#0f172a"   # deep navy  – header strip
C_ACCENT    = "#2563eb"   # blue       – primary button
C_HIGHLIGHT = "#f59e0b"   # amber      – break-even price & total cost
C_MUTED     = "#94a3b8"   # slate grey – secondary / label text
C_INFO_BG   = "#1e293b"   # dark blue  – info-box background
C_SEP       = "#334155"   # dim slate  – section separator lines
C_SECTION   = "#60a5fa"   # light blue – section heading text

ANNUAL_MTF_RATE_STATIC = 18.0
BROKERAGE_PCT_INTRADAY = 0.01
BROKERAGE_PCT_DELIVERY = 0.1


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

class BrokerageCalculatorApp(ctk.CTk):
    """Single-window CustomTkinter desktop application."""

    def __init__(self) -> None:
        super().__init__()
        self._logo_photo: tk.PhotoImage | None = None
        self._apply_app_logo()
        self.title(f"{APP_NAME} v{APP_VERSION}  –  NSE Delivery Equity")
        self.geometry("1200x760")
        self.minsize(980, 660)
        # Start with the static fallback list so the window opens instantly;
        # a background thread upgrades to the full NSE list.
        from stock_list import NSE_STOCKS as _fallback
        self._stocks: list[tuple[str, str]] = _fallback
        self._stock_source: str = f"Static list  ({len(_fallback):,} stocks,  loading…)"
        self._build_ui()
        # Kick off background fetch after the window is displayed
        self.after(200, self._start_stock_load)
        # Automatic update check (quiet mode)
        self.after(2500, lambda: self._check_updates(manual=False))

    def _apply_app_logo(self) -> None:
        """Apply app logo as the window/taskbar icon when the PNG is available."""
        logo_png = Path(__file__).parent / "assets" / "app_logo.png"
        if not logo_png.exists():
            return

        try:
            self._logo_photo = tk.PhotoImage(file=str(logo_png))
            self.iconphoto(True, self._logo_photo)
        except tk.TclError:
            # If image loading fails, continue without custom icon.
            self._logo_photo = None

    def _start_stock_load(self) -> None:
        """Fetch/cache stocks in a daemon thread; update autocomplete when done."""
        def _worker():
            stocks, source = stock_loader.load_stocks()
            # Schedule UI update back on the main thread
            self.after(0, lambda: self._on_stocks_loaded(stocks, source))

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_stocks_loaded(
        self, stocks: list[tuple[str, str]], source: str
    ) -> None:
        """Called on the main thread once background stock load completes."""
        if stocks:
            self._stocks = stocks
        self._stock_source = source
        # Push the full list into the autocomplete widget
        stock_entry = self.entries.get("Stock / Scrip Name")
        if stock_entry and isinstance(stock_entry, AutocompleteEntry):
            stock_entry.set_suggestions(self._stocks)
        # Update status label
        if hasattr(self, "_stock_status_var"):
            self._stock_status_var.set(f"●  {source}")

    def _check_updates(self, manual: bool) -> None:
        """Run update check on a background thread to avoid UI freeze."""
        def _worker() -> None:
            result = updater.check_for_update(
                current_version=APP_VERSION,
                github_owner=GITHUB_OWNER,
                github_repo=GITHUB_REPO,
                asset_keyword=INSTALLER_ASSET_KEYWORD,
            )
            self.after(0, lambda: self._handle_update_result(result, manual))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_update_result(self, result: updater.UpdateCheckResult, manual: bool) -> None:
        """Handle update check result on the UI thread."""
        if not result.ok:
            if manual:
                messagebox.showinfo("Update Check", result.error, parent=self)
            return

        if not result.update_available:
            if manual:
                msg = (
                    f"You are up to date.\n\n"
                    f"Current version: v{APP_VERSION}\n"
                    f"Latest version:  {result.latest_version or APP_VERSION}"
                )
                messagebox.showinfo("Update Check", msg, parent=self)
            return

        prompt = (
            f"New version available: {result.latest_version}\n"
            f"Current version: v{APP_VERSION}\n\n"
            f"Do you want to download the latest setup now?"
        )
        open_link = messagebox.askyesno("Update Available", prompt, parent=self)
        if open_link and result.download_url:
            webbrowser.open(result.download_url)

    # ──────────────────────────────────────────────────────────────────────────
    #  Top-level layout
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=0)   # header  – fixed height
        self.grid_rowconfigure(1, weight=1)   # content – stretches
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_header()
        self._build_input_panel()
        self._build_results_panel()

    # ── Header bar ────────────────────────────────────────────────────────────

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=C_BG_HEADER, height=72)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            hdr,
            text="  \u2747  Brokerage & MTF Interest Calculator",
            font=ctk.CTkFont(family="Segoe UI", size=21, weight="bold"),
            text_color="#e2e8f0",
        ).grid(row=0, column=0, padx=22, pady=(14, 2), sticky="w")

        ctk.CTkLabel(
            hdr,
            text="  NSE Delivery Equity  \u00b7  "
                 "STT  \u00b7  Exchange & Clearing  \u00b7  GST  \u00b7  Stamp Duty  \u00b7  SEBI Fee",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=C_MUTED,
        ).grid(row=1, column=0, padx=22, pady=(0, 12), sticky="w")

        ctk.CTkLabel(
            hdr,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#93c5fd",
        ).grid(row=0, column=1, padx=(0, 16), pady=(14, 2), sticky="e")

        ctk.CTkButton(
            hdr,
            text="Check Updates",
            width=128,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color="#0b3b78",
            hover_color="#1d4ed8",
            command=lambda: self._check_updates(manual=True),
        ).grid(row=1, column=1, padx=(0, 16), pady=(0, 10), sticky="e")

    # ── Input Panel (left column) ─────────────────────────────────────────────

    def _build_input_panel(self) -> None:
        self._left = ctk.CTkScrollableFrame(
            self,
            label_text="  Trade Details",
            corner_radius=10,
            label_font=ctk.CTkFont(size=13, weight="bold"),
            label_fg_color="transparent",
            label_text_color=C_SECTION,
        )
        self._left.grid(row=1, column=0, padx=(14, 7), pady=14, sticky="nsew")
        self._left.grid_columnconfigure(0, weight=0, minsize=190)
        self._left.grid_columnconfigure(1, weight=1)
        self._left.grid_columnconfigure(2, weight=0)

        self.entries: dict[str, ctk.CTkEntry] = {}

        # (label, placeholder_text)
        field_defs = [
            ("Stock / Scrip Name",    "e.g. RELIANCE"),
            ("Buy Date (DD-MM-YYYY)", "e.g. 01-09-2024"),
            ("Buy Price (\u20b9)",       "e.g. 2500.00"),
            ("Quantity (Shares)",     "e.g. 100"),
            ("Own Capital Used (\u20b9)", "e.g. 50000.00"),
        ]

        for row_idx, (label_text, placeholder) in enumerate(field_defs):
            ctk.CTkLabel(
                self._left,
                text=label_text,
                font=ctk.CTkFont(size=12),
                text_color=C_MUTED,
                anchor="w",
            ).grid(row=row_idx, column=0, padx=(12, 8), pady=(12, 0), sticky="w")

            if label_text == "Stock / Scrip Name":
                entry = AutocompleteEntry(
                    self._left,
                    suggestions=self._stocks,
                    height=36,
                    font=ctk.CTkFont(size=13),
                    placeholder_text=placeholder,
                )
            else:
                entry = ctk.CTkEntry(
                    self._left,
                    placeholder_text=placeholder,
                    height=36,
                    font=ctk.CTkFont(size=13),
                )
            entry.grid(row=row_idx, column=1, padx=(0, 12), pady=(12, 0), sticky="ew")
            self.entries[label_text] = entry

            if label_text == "Buy Date (DD-MM-YYYY)":
                self._date_picker_btn = ctk.CTkButton(
                    self._left,
                    text="📅",
                    width=36,
                    height=36,
                    font=ctk.CTkFont(size=14),
                    fg_color="#334155",
                    hover_color="#475569",
                    command=self._open_date_picker,
                )
                self._date_picker_btn.grid(row=row_idx, column=2, padx=(0, 10), pady=(12, 0), sticky="w")

        # ── Funding mode selector (MTF vs Cash buy) ─────────────────────────
        funding_row = len(field_defs)

        ctk.CTkLabel(
            self._left,
            text="Funding Mode",
            font=ctk.CTkFont(size=12),
            text_color=C_MUTED,
            anchor="w",
        ).grid(row=funding_row, column=0, padx=(12, 8), pady=(16, 0), sticky="w")

        funding_frame = ctk.CTkFrame(self._left, fg_color="transparent")
        funding_frame.grid(row=funding_row, column=1, padx=(0, 12), pady=(16, 0), sticky="w")

        self._funding_mode = ctk.StringVar(value="mtf")

        ctk.CTkRadioButton(
            funding_frame,
            text="MTF Buy",
            variable=self._funding_mode,
            value="mtf",
            command=self._on_funding_mode_change,
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(0, 20))

        ctk.CTkRadioButton(
            funding_frame,
            text="Cash Buy (No MTF)",
            variable=self._funding_mode,
            value="cash",
            command=self._on_funding_mode_change,
            font=ctk.CTkFont(size=13),
        ).pack(side="left")

        # ── Trade type selector (controls fixed brokerage %) ─────────────────
        trade_type_row = funding_row + 1

        ctk.CTkLabel(
            self._left,
            text="Trade Type",
            font=ctk.CTkFont(size=12),
            text_color=C_MUTED,
            anchor="w",
        ).grid(row=trade_type_row, column=0, padx=(12, 8), pady=(16, 0), sticky="w")

        radio_frame = ctk.CTkFrame(self._left, fg_color="transparent")
        radio_frame.grid(row=trade_type_row, column=1, padx=(0, 12), pady=(16, 0), sticky="w")

        self._trade_type = ctk.StringVar(value="delivery")

        ctk.CTkRadioButton(
            radio_frame,
            text="Intraday  (0.01%)",
            variable=self._trade_type,
            value="intraday",
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(0, 20))

        ctk.CTkRadioButton(
            radio_frame,
            text="Delivery  (0.1%)",
            variable=self._trade_type,
            value="delivery",
            font=ctk.CTkFont(size=13),
        ).pack(side="left")

        ctk.CTkLabel(
            self._left,
            text="MTF Rate is fixed at 18% annually",
            font=ctk.CTkFont(size=11),
            text_color="#93c5fd",
            anchor="w",
        ).grid(row=trade_type_row + 1, column=0, columnspan=2, padx=(12, 8), pady=(8, 0), sticky="w")

        # Initial state of Own Capital field depends on funding mode
        self._on_funding_mode_change()

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = trade_type_row + 2
        btn_frame = ctk.CTkFrame(self._left, fg_color="transparent")
        btn_frame.grid(row=btn_row, column=0, columnspan=2, pady=(24, 10))

        ctk.CTkButton(
            btn_frame,
            text="  \u25b6  Calculate  ",
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=C_ACCENT,
            hover_color="#1d4ed8",
            command=self._on_calculate,
        ).pack(side="left", padx=(0, 12))

        ctk.CTkButton(
            btn_frame,
            text="  \u21ba  Clear All  ",
            height=44,
            font=ctk.CTkFont(size=14),
            fg_color="#374151",
            hover_color="#4b5563",
            command=self._on_clear,
        ).pack(side="left")

        # ── Regulatory charge-rate reference box ──────────────────────────────
        info_row = btn_row + 1

        info_text = (
            "Regulatory Charges Applied  (NSE Delivery Equity)\n"
            "\u2500" * 48 + "\n"
            " \u2022 STT                0.1 %    on buy value + sell value\n"
            " \u2022 Exchange Charge    0.00297 %  NSE turnover fee\n"
            " \u2022 Clearing Charge    0.0003 %\n"
            " \u2022 GST                18 %     on brokerage + exchange\n"
            " \u2022 Stamp Duty         0.015 %  on buy value only\n"
            " \u2022 SEBI Fee           \u20b910 per crore of turnover\n"
            " \u2022 Brokerage         Intraday: 0.01 %  |  Delivery: 0.1 %\n"
            " \u2022 MTF Rate          18 %  (fixed)\n"
            "\n"
            " Rates are indicative. Verify with your broker / NSE schedule."
        )

        info_box = ctk.CTkTextbox(
            self._left,
            height=168,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=C_INFO_BG,
            text_color=C_MUTED,
            activate_scrollbars=False,
            wrap="none",
        )
        info_box.grid(
            row=info_row, column=0, columnspan=2, padx=12, pady=(14, 8), sticky="ew"
        )
        info_box.insert("1.0", info_text)
        info_box.configure(state="disabled")

        # ── Stock data source status ───────────────────────────────────────────
        status_row = info_row + 1
        self._stock_status_var = ctk.StringVar(
            value=f"●  {self._stock_source}"
        )
        ctk.CTkLabel(
            self._left,
            textvariable=self._stock_status_var,
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#64748b",
            anchor="w",
        ).grid(
            row=status_row, column=0, columnspan=2,
            padx=14, pady=(0, 10), sticky="w"
        )

    # ── Results Panel (right column) ──────────────────────────────────────────

    def _build_results_panel(self) -> None:
        self._right = ctk.CTkScrollableFrame(
            self,
            label_text="  Calculation Results",
            corner_radius=10,
            label_font=ctk.CTkFont(size=13, weight="bold"),
            label_fg_color="transparent",
            label_text_color=C_SECTION,
        )
        self._right.grid(row=1, column=1, padx=(7, 14), pady=14, sticky="nsew")
        self._right.grid_columnconfigure(0, weight=1)
        self._right.grid_columnconfigure(1, weight=0, minsize=175)

        # result_key → StringVar (initial value "—")
        self._rvars: dict[str, ctk.StringVar] = {}

        # (section_title, [(display_label, result_key, highlight?)])
        sections = [
            ("TRADE OVERVIEW", [
                ("Stock Name",               "stock_name",        False),
                ("Buy Date",                 "buy_date",          False),
                ("Today's Date",             "today",             False),
                ("Holding Days",             "holding_days",      False),
            ]),
            ("TRADE FINANCIALS", [
                ("Total Trade Value",         "total_trade_value", False),
                ("Own Capital Used",          "own_capital",       False),
                ("Borrowed Amount (MTF)",     "borrowed_amount",   False),
            ]),
            ("BUY-SIDE CHARGES", [
                ("Brokerage",                "buy_brokerage",     False),
                ("STT (0.1 %)",              "buy_stt",           False),
                ("Exchange + Clearing",      "buy_exchange",      False),
                ("GST (18 % on B + E)",      "buy_gst",           False),
                ("Stamp Duty (0.015 %)",     "buy_stamp_duty",    False),
                ("SEBI Fee",                 "buy_sebi",          False),
                ("Total Buy Charges",        "buy_total",         False),
            ]),
            ("MTF INTEREST COST", [
                ("MTF Interest Accrued",      "mtf_interest",      False),
            ]),
            ("SELL-SIDE CHARGES  (at Break-Even Price)", [
                ("Brokerage",                "sell_brokerage",    False),
                ("STT (0.1 %)",              "sell_stt",          False),
                ("Exchange + Clearing",      "sell_exchange",     False),
                ("GST (18 % on B + E)",      "sell_gst",          False),
                ("SEBI Fee",                 "sell_sebi",         False),
                ("Total Sell Charges",       "sell_total",        False),
            ]),
            ("SUMMARY", [
                ("Total Regulatory Charges", "total_charges",     False),
                ("Total Cost of Carrying",   "total_cost",        True),
                ("Break-Even Sell Price",    "breakeven_price",   True),
            ]),
        ]

        current_row = 0
        for section_title, items in sections:
            # Section heading
            ctk.CTkLabel(
                self._right,
                text=section_title,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=C_SECTION,
            ).grid(
                row=current_row, column=0, columnspan=2,
                padx=10, pady=(16, 2), sticky="w"
            )
            current_row += 1

            # Thin separator line
            ctk.CTkFrame(
                self._right, height=1, fg_color=C_SEP
            ).grid(
                row=current_row, column=0, columnspan=2,
                padx=10, sticky="ew"
            )
            current_row += 1

            # Row for each metric
            for label_text, key, highlight in items:
                val_color = C_HIGHLIGHT if highlight else "#e2e8f0"
                val_font  = (
                    ctk.CTkFont(size=13, weight="bold")
                    if highlight
                    else ctk.CTkFont(size=13)
                )

                ctk.CTkLabel(
                    self._right,
                    text=label_text,
                    font=ctk.CTkFont(size=12),
                    text_color=C_MUTED,
                    anchor="w",
                ).grid(
                    row=current_row, column=0,
                    padx=(12, 4), pady=4, sticky="w"
                )

                var = ctk.StringVar(value="\u2014")   # em-dash placeholder
                self._rvars[key] = var

                ctk.CTkLabel(
                    self._right,
                    textvariable=var,
                    font=val_font,
                    text_color=val_color,
                    anchor="e",
                ).grid(
                    row=current_row, column=1,
                    padx=(4, 12), pady=4, sticky="e"
                )

                current_row += 1

    # ──────────────────────────────────────────────────────────────────────────
    #  Event Handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _get_selected_brokerage_pct(self) -> float:
        """Return brokerage percentage based on selected trade type."""
        return (
            BROKERAGE_PCT_INTRADAY
            if self._trade_type.get() == "intraday"
            else BROKERAGE_PCT_DELIVERY
        )

    def _on_funding_mode_change(self) -> None:
        """Toggle MTF-only inputs based on selected funding mode."""
        own_cap_entry = self.entries.get("Own Capital Used (\u20b9)")
        buy_date_entry = self.entries.get("Buy Date (DD-MM-YYYY)")
        if not own_cap_entry or not buy_date_entry:
            return

        if self._funding_mode.get() == "cash":
            own_cap_entry.configure(state="normal")
            own_cap_entry.delete(0, "end")
            own_cap_entry.insert(0, "Auto (full own funds)")
            own_cap_entry.configure(state="disabled")

            # Buy date is not required for Cash Buy. Keep it auto-filled to today.
            buy_date_entry.configure(state="normal")
            buy_date_entry.delete(0, "end")
            buy_date_entry.insert(0, datetime.today().strftime("%d-%m-%Y"))
            buy_date_entry.configure(state="disabled")
            if hasattr(self, "_date_picker_btn"):
                self._date_picker_btn.configure(state="disabled")
        else:
            own_cap_entry.configure(state="normal")
            if own_cap_entry.get().strip() == "Auto (full own funds)":
                own_cap_entry.delete(0, "end")

            buy_date_entry.configure(state="normal")
            if hasattr(self, "_date_picker_btn"):
                self._date_picker_btn.configure(state="normal")

    def _open_date_picker(self) -> None:
        """Open a calendar popup and write selected date in DD-MM-YYYY format."""
        if Calendar is None:
            messagebox.showinfo(
                "Calendar Not Installed",
                "Date picker requires 'tkcalendar'.\n\n"
                "Install it with:\n"
                "pip install tkcalendar",
                parent=self,
            )
            return

        entry = self.entries["Buy Date (DD-MM-YYYY)"]
        current_text = entry.get().strip()
        initial_date = None
        if current_text:
            try:
                initial_date = datetime.strptime(current_text, "%d-%m-%Y").date()
            except ValueError:
                initial_date = None

        popup = ctk.CTkToplevel(self)
        popup.title("Select Buy Date")
        popup.geometry("300x320")
        popup.resizable(False, False)
        popup.transient(self)
        popup.grab_set()

        cal = Calendar(
            popup,
            selectmode="day",
            date_pattern="dd-mm-yyyy",
        )
        cal.pack(fill="both", expand=True, padx=10, pady=10)

        if initial_date is not None:
            try:
                cal.selection_set(initial_date)
            except Exception:
                pass

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        def _apply_date() -> None:
            entry.delete(0, "end")
            entry.insert(0, cal.get_date())
            popup.destroy()

        ctk.CTkButton(
            btn_row,
            text="Select",
            width=100,
            command=_apply_date,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=100,
            fg_color="#374151",
            hover_color="#4b5563",
            command=popup.destroy,
        ).pack(side="left")

    def _on_calculate(self) -> None:
        """Read inputs, validate, run calculations, and populate the results panel."""
        # ── Parse inputs ──────────────────────────────────────────────────────
        is_mtf = self._funding_mode.get() == "mtf"

        try:
            stock_name    = (
                self.entries["Stock / Scrip Name"].get().strip() or "N/A"
            )
            if is_mtf:
                buy_date_str = self.entries["Buy Date (DD-MM-YYYY)"].get().strip()
            else:
                buy_date_str = datetime.today().strftime("%d-%m-%Y")
            buy_price     = float(self.entries["Buy Price (\u20b9)"].get().strip())
            # Accept "100.0" as well as "100" for quantity
            quantity      = int(
                float(self.entries["Quantity (Shares)"].get().strip())
            )
            if is_mtf:
                own_capital = float(
                    self.entries["Own Capital Used (\u20b9)"].get().strip()
                )
                annual_rate = ANNUAL_MTF_RATE_STATIC
            else:
                own_capital = buy_price * quantity
                annual_rate = 0.0
            brokerage_val = self._get_selected_brokerage_pct()
            is_pct        = True

        except ValueError:
            own_cap_line = "  \u2022 Own Capital Used\n" if is_mtf else ""
            messagebox.showerror(
                "Input Error",
                "One or more numeric fields contain invalid values.\n\n"
                "Please check:\n"
                "  \u2022 Buy Price\n"
                "  \u2022 Quantity\n"
                f"{own_cap_line}",
                parent=self,
            )
            return

        # ── Run calculations ──────────────────────────────────────────────────
        try:
            result = calc.run_full_calculation(
                stock_name     = stock_name,
                buy_date_str   = buy_date_str,
                buy_price      = buy_price,
                quantity       = quantity,
                own_capital    = own_capital,
                annual_rate_pct= annual_rate,
                brokerage_input= brokerage_val,
                is_percentage  = is_pct,
            )
        except ValueError as exc:
            messagebox.showerror("Calculation Error", str(exc), parent=self)
            return

        result["is_mtf"] = is_mtf

        self._populate_results(result)

    def _on_clear(self) -> None:
        """Reset all input fields and result labels to their defaults."""
        for entry in self.entries.values():
            entry.configure(state="normal")
            entry.delete(0, "end")

        self._funding_mode.set("mtf")
        self._on_funding_mode_change()
        self._trade_type.set("delivery")

        for var in self._rvars.values():
            var.set("\u2014")

    # ──────────────────────────────────────────────────────────────────────────
    #  Result display
    # ──────────────────────────────────────────────────────────────────────────

    def _populate_results(self, r: dict) -> None:
        """Push calculation results into the right-panel StringVars."""

        def inr(val: float) -> str:
            """Format a float as an Indian-locale ₹ string."""
            return f"\u20b9{val:,.2f}"

        # Overview
        self._rvars["stock_name"].set(r["stock_name"])
        self._rvars["buy_date"].set(r["buy_date"])
        self._rvars["today"].set(r["today"])
        n = r["holding_days"]
        self._rvars["holding_days"].set(f"{n} {'day' if n == 1 else 'days'}")

        # Trade financials
        self._rvars["total_trade_value"].set(inr(r["total_trade_value"]))
        self._rvars["own_capital"].set(inr(r["own_capital"]))
        self._rvars["borrowed_amount"].set(inr(r["borrowed_amount"]))

        # Buy-side charges
        bc = r["buy_charges"]
        self._rvars["buy_brokerage"].set(inr(bc["brokerage"]))
        self._rvars["buy_stt"].set(inr(bc["stt"]))
        self._rvars["buy_exchange"].set(inr(bc["exchange_chg"] + bc["clearing_chg"]))
        self._rvars["buy_gst"].set(inr(bc["gst"]))
        self._rvars["buy_stamp_duty"].set(inr(bc["stamp_duty"]))
        self._rvars["buy_sebi"].set(inr(bc["sebi_fee"]))
        self._rvars["buy_total"].set(inr(bc["total"]))

        # MTF interest
        if r.get("is_mtf", True):
            self._rvars["mtf_interest"].set(inr(r["mtf_interest"]))
        else:
            self._rvars["mtf_interest"].set("Not Applicable (Cash Buy)")

        # Sell-side charges
        sc = r["sell_charges"]
        self._rvars["sell_brokerage"].set(inr(sc["brokerage"]))
        self._rvars["sell_stt"].set(inr(sc["stt"]))
        self._rvars["sell_exchange"].set(inr(sc["exchange_chg"] + sc["clearing_chg"]))
        self._rvars["sell_gst"].set(inr(sc["gst"]))
        self._rvars["sell_sebi"].set(inr(sc["sebi_fee"]))
        self._rvars["sell_total"].set(inr(sc["total"]))

        # Summary
        self._rvars["total_charges"].set(inr(r["total_charges"]))
        self._rvars["total_cost"].set(inr(r["total_cost"]))
        # Show break-even to 4 decimal places for precision
        self._rvars["breakeven_price"].set(
            f"\u20b9{r['breakeven_price']:,.4f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BrokerageCalculatorApp()
    app.mainloop()
