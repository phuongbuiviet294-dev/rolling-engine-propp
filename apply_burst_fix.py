
from pathlib import Path

APP_FILE = "app.py"

path = Path(APP_FILE)

if not path.exists():
    print("ERROR: app.py not found")
    raise SystemExit

text = path.read_text(encoding="utf-8")

# =====================================================
# CONFIG REPLACE
# =====================================================

replacements = {
    "PHASE_STOP_WIN = 44": "PHASE_STOP_WIN = 20",
    "PHASE_STOP_LOSS = -1.0": "PHASE_STOP_LOSS = -8.0",
    "PHASE_LOSS_STREAK_RELOCK = 2": "PHASE_LOSS_STREAK_RELOCK = 999",
    "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK = True": "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK = False",
    "ALLOW_TRADE_WHEN_PHASE_NEGATIVE = False": "ALLOW_TRADE_WHEN_PHASE_NEGATIVE = False",
    "NEGATIVE_PHASE_DOMINANCE_RATIO = 0.67": "NEGATIVE_PHASE_DOMINANCE_RATIO = 0.60",
    "RECENT_PHASE_CHECK = 5": "RECENT_PHASE_CHECK = 6",
    "PHASE_MIN_RECENT_PNL_TO_TRADE = 0.0": "PHASE_MIN_RECENT_PNL_TO_TRADE = 0.0",
    "PHASE_MIN_TOTAL_PNL_TO_TRADE = 0.0": "PHASE_MIN_TOTAL_PNL_TO_TRADE = 0.0",
    "MIN_PHASE_AGE_TO_TRADE = 5": "MIN_PHASE_AGE_TO_TRADE = 2",
    "MAX_PHASE_TRADES = 8": "MAX_PHASE_TRADES = 28",
    "VOTE_DOMINANCE_RATIO = 0.60": "VOTE_DOMINANCE_RATIO = 0.58",
    "MIN_TRADES_PER_WINDOW = 26": "MIN_TRADES_PER_WINDOW = 18",
    "RECENT_WINDOW_SIZE = 33": "RECENT_WINDOW_SIZE = 40",
    "WINDOW_SPACING_MAX = 6": "WINDOW_SPACING_MAX = 4",
    "VALIDATE_MIN_DRAWDOWN = -1.0": "VALIDATE_MIN_DRAWDOWN = -4.0",
    "RELOCK_SCAN_LEN = 18": "RELOCK_SCAN_LEN = 12",
}

for old, new in replacements.items():
    text = text.replace(old, new)

# =====================================================
# PHASE TRADE LOGIC
# =====================================================

old_block = """phase_trade_allowed = (
    signal_group
    and recent_phase_pnl >= PHASE_MIN_RECENT_PNL_TO_TRADE
    and phase_profit_group >= PHASE_MIN_TOTAL_PNL_TO_TRADE
)"""

new_block = """phase_trade_allowed = (
    signal_group
    and phase_profit_total >= PHASE_MIN_TOTAL_PNL_TO_TRADE
)"""

text = text.replace(old_block, new_block)

# =====================================================
# STOP LOSS FIX
# =====================================================

text = text.replace(
    "elif phase_profit_group <= PHASE_STOP_LOSS:",
    "elif phase_profit_total <= PHASE_STOP_LOSS:"
)

# =====================================================
# RELOCK FIX
# =====================================================

text = text.replace(
    "elif phase_consecutive_losses >= PHASE_LOSS_STREAK_RELOCK:",
    """elif (
    phase_consecutive_losses >= 6
    and phase_profit_total < -4
):"""
)

# =====================================================
# SAVE
# =====================================================

output = Path("app_fixed_burst.py")

output.write_text(text, encoding="utf-8")

print("DONE")
print("Created:", output.resolve())
