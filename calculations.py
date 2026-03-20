"""
calculations.py
───────────────────────────────────────────────────────────────────────────────
Core financial calculation logic for the Brokerage & MTF Interest Calculator.

Completely decoupled from the GUI — this module can be imported, unit-tested,
or used from a CLI without any GUI dependency.

Indian Market Charge Rates Applied (NSE Delivery Equity):
  • STT              – 0.1 %   on buy turnover  +  0.1 % on sell turnover
  • Exchange charge  – 0.00297 %  (NSE transaction / turnover fee)
  • Clearing charge  – 0.0003 %   (NSE clearing member fee)
  • GST              – 18 %    on (brokerage + exchange + clearing charges)
  • Stamp duty       – 0.015 % on buy turnover only
  • SEBI fee         – ₹10 per crore of turnover  ≈  0.0001 %

  Rates are indicative. Verify current schedules with your broker / exchange.
"""

from datetime import date, datetime
from typing import Dict


# ─────────────────────────────────────────────────────────────────────────────
# Regulatory Charge Rate Constants  (all expressed as decimal fractions)
# ─────────────────────────────────────────────────────────────────────────────

STT_RATE             = 0.001        # 0.1 %   – Securities Transaction Tax
EXCHANGE_CHARGE_RATE = 0.0000297    # 0.00297% – NSE transaction / turnover charge
CLEARING_CHARGE_RATE = 0.000003     # 0.0003 % – NSE clearing member charge
GST_RATE             = 0.18         # 18 %    – GST on brokerage + exchange + clearing
STAMP_DUTY_RATE      = 0.00015      # 0.015 % – Stamp duty (buy side only, post-2020)
SEBI_RATE            = 0.000001     # ₹10 / crore  ≈  0.0001 %


# ─────────────────────────────────────────────────────────────────────────────
# Input Validation & Date Utilities
# ─────────────────────────────────────────────────────────────────────────────

def parse_buy_date(date_str: str) -> date:
    """
    Parse a 'DD-MM-YYYY' string into a date object.

    Raises:
        ValueError – on invalid format or if the date is in the future.
    """
    try:
        buy_date = datetime.strptime(date_str.strip(), "%d-%m-%Y").date()
    except ValueError:
        raise ValueError(
            f"Invalid date '{date_str}'. Use the format DD-MM-YYYY  (e.g. 01-09-2024)."
        )

    if buy_date > date.today():
        raise ValueError("Buy date cannot be set to a future date.")

    return buy_date


def calculate_holding_days(buy_date: date) -> int:
    """
    Return the exact number of calendar days from buy_date to today.

    MTF interest accrues every calendar day (including weekends and public
    holidays), so no trading-day adjustments are made.
    Returns 0 when buy_date == today (same-day entry).
    """
    return (date.today() - buy_date).days


# ─────────────────────────────────────────────────────────────────────────────
# Core Trade Calculations
# ─────────────────────────────────────────────────────────────────────────────

def calculate_trade_value(buy_price: float, quantity: int) -> float:
    """Total purchase value before any charges."""
    return buy_price * quantity


def calculate_borrowed_amount(total_trade_value: float, own_capital: float) -> float:
    """
    Amount funded via MTF (broker's loan).
    Clamped to zero if own_capital >= total_trade_value (no borrowing needed).
    """
    return max(0.0, total_trade_value - own_capital)


def calculate_mtf_interest(
    borrowed_amount: float,
    annual_rate_pct: float,
    holding_days: int,
) -> float:
    """
    Daily-accrual MTF Interest formula:

        Interest = Borrowed Amount × (Annual Rate / 100) / 365 × Holding Days

    Returns 0.0 if any argument is non-positive (no borrowing / same-day trade).
    """
    if borrowed_amount <= 0 or annual_rate_pct <= 0 or holding_days <= 0:
        return 0.0
    return (borrowed_amount * annual_rate_pct / 100.0 / 365.0) * holding_days


# ─────────────────────────────────────────────────────────────────────────────
# Charge Calculations
# ─────────────────────────────────────────────────────────────────────────────

def _brokerage_rupees(
    trade_value: float,
    brokerage_input: float,
    is_percentage: bool,
) -> float:
    """Convert the user's brokerage input to a ₹ amount for one trade leg."""
    if is_percentage:
        return trade_value * (brokerage_input / 100.0)
    return float(brokerage_input)          # flat ₹ per order


def calculate_side_charges(
    trade_value: float,
    brokerage_input: float,
    is_percentage: bool,
    is_buy_side: bool,
) -> Dict[str, float]:
    """
    Compute all regulatory + brokerage charges for one leg (buy or sell) of a
    NSE delivery equity trade.

    Returns a dict with individual charge components and a 'total' key.
    Stamp duty is applied only on the buy leg.
    """
    brokerage    = _brokerage_rupees(trade_value, brokerage_input, is_percentage)
    stt          = trade_value * STT_RATE
    exchange_chg = trade_value * EXCHANGE_CHARGE_RATE
    clearing_chg = trade_value * CLEARING_CHARGE_RATE
    sebi_fee     = trade_value * SEBI_RATE
    # GST applies on brokerage + exchange transaction charge + clearing charge
    gst          = (brokerage + exchange_chg + clearing_chg) * GST_RATE
    stamp_duty   = (trade_value * STAMP_DUTY_RATE) if is_buy_side else 0.0

    total = brokerage + stt + exchange_chg + clearing_chg + sebi_fee + gst + stamp_duty

    return {
        "brokerage":    brokerage,
        "stt":          stt,
        "exchange_chg": exchange_chg,
        "clearing_chg": clearing_chg,
        "sebi_fee":     sebi_fee,
        "gst":          gst,
        "stamp_duty":   stamp_duty,
        "total":        total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Break-Even Price (iterative solver)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_breakeven_price(
    buy_price: float,
    quantity: int,
    mtf_interest: float,
    brokerage_input: float,
    is_percentage: bool,
) -> float:
    """
    Solve for the sell price S at which net P&L is exactly ₹0 after all costs.

    The equation to satisfy is:
        S × Q  −  sell_charges(S × Q)
            = buy_price × Q  +  buy_charges(buy_price × Q)  +  mtf_interest

    Because sell charges are a small linear fraction of S, the fixed-point
    iteration converges in < 10 passes to sub-paisa precision.
    """
    buy_value     = buy_price * quantity
    buy_chg_total = calculate_side_charges(
        buy_value, brokerage_input, is_percentage, is_buy_side=True
    )["total"]

    # Total ₹ that the sell leg must recover
    rhs = buy_value + buy_chg_total + mtf_interest

    # Seed: assume zero sell charges initially
    S = rhs / quantity

    for _ in range(100):
        sell_value = S * quantity
        sell_chg   = calculate_side_charges(
            sell_value, brokerage_input, is_percentage, is_buy_side=False
        )["total"]
        S_new = (rhs + sell_chg) / quantity
        if abs(S_new - S) < 0.000_01:      # converge to < ₹0.00001 / share
            break
        S = S_new

    return round(S_new, 4)


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator – single entry-point for the GUI
# ─────────────────────────────────────────────────────────────────────────────

def run_full_calculation(
    stock_name: str,
    buy_date_str: str,
    buy_price: float,
    quantity: int,
    own_capital: float,
    annual_rate_pct: float,
    brokerage_input: float,
    is_percentage: bool,
) -> Dict:
    """
    Validate all inputs, execute every sub-calculation, and return a single
    result dictionary ready for the GUI to display.

    Raises:
        ValueError – for any validation failure (message is user-friendly).
    """
    # ── Numeric guards ────────────────────────────────────────────────────────
    if buy_price <= 0:
        raise ValueError("Buy price must be greater than ₹0.")
    if quantity <= 0:
        raise ValueError("Quantity must be at least 1 share.")
    if own_capital < 0:
        raise ValueError("Own capital cannot be negative.")
    if annual_rate_pct < 0:
        raise ValueError("Annual MTF interest rate cannot be negative.")
    if brokerage_input < 0:
        raise ValueError("Brokerage value cannot be negative.")

    # ── Date parsing & validation ─────────────────────────────────────────────
    buy_date = parse_buy_date(buy_date_str)

    # ── Derived calculations ──────────────────────────────────────────────────
    total_trade_value = calculate_trade_value(buy_price, quantity)

    if own_capital > total_trade_value:
        raise ValueError(
            f"Own capital (₹{own_capital:,.2f}) cannot exceed "
            f"the total trade value (₹{total_trade_value:,.2f})."
        )

    borrowed_amount = calculate_borrowed_amount(total_trade_value, own_capital)
    holding_days    = calculate_holding_days(buy_date)
    mtf_interest    = calculate_mtf_interest(borrowed_amount, annual_rate_pct, holding_days)

    buy_charges     = calculate_side_charges(
        total_trade_value, brokerage_input, is_percentage, is_buy_side=True
    )

    breakeven_price = calculate_breakeven_price(
        buy_price, quantity, mtf_interest, brokerage_input, is_percentage
    )

    # Compute sell-side charges at the break-even price for display purposes
    sell_charges    = calculate_side_charges(
        breakeven_price * quantity, brokerage_input, is_percentage, is_buy_side=False
    )

    total_charges   = buy_charges["total"] + sell_charges["total"]
    total_cost      = mtf_interest + total_charges

    return {
        # ── Meta ──────────────────────────────────────────────────────────────
        "stock_name":        stock_name,
        "buy_date":          buy_date.strftime("%d-%m-%Y"),
        "today":             date.today().strftime("%d-%m-%Y"),
        "holding_days":      holding_days,
        # ── Trade ─────────────────────────────────────────────────────────────
        "buy_price":         round(buy_price, 2),
        "quantity":          quantity,
        "total_trade_value": round(total_trade_value, 2),
        "own_capital":       round(own_capital, 2),
        "borrowed_amount":   round(borrowed_amount, 2),
        "annual_rate_pct":   annual_rate_pct,
        # ── Costs ─────────────────────────────────────────────────────────────
        "mtf_interest":      round(mtf_interest, 2),
        "buy_charges":       {k: round(v, 2) for k, v in buy_charges.items()},
        "sell_charges":      {k: round(v, 2) for k, v in sell_charges.items()},
        "total_charges":     round(total_charges, 2),
        "total_cost":        round(total_cost, 2),
        "breakeven_price":   breakeven_price,
    }
