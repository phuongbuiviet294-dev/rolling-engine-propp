# ============================================================
# APP V50 SINGLE CLEAN
# Refactor from uploaded app_v50_fix_v7 source
# ============================================================

from __future__ import annotations

import time
import json
import dataclasses
import os
import math
import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Optional, Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V69.5 Profit Guard DAY_SEQ",
    layout="wide"
)


# ============================================================
# CONFIG
# ============================================================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = list(range(6, 23))
TOPN = 3

SIGNAL_HISTORY_LEN = 50
LEADER_HISTORY_LEN = 50
HIT_HISTORY_LEN = 50
GROUP_HISTORY_LEN = 80

COOLDOWN_ROUNDS = 3
MIN_DATA_LEN = 30
LIVE_START_ROUND = 180
KEEP_WIN_ROUNDS = 4
DATASET_RESET_ANCHOR_LEN = 32
LIVE_TIMEZONE = "Asia/Phnom_Penh"
STATE_VERSION = "V69_5_DAY_SEQ_PROFIT_MATCH_FINAL_V3_9"
# V3.5 is a clean state boundary because the dataset model changes from
# CLEAR-B daily replacement to append-only DAY_SEQ. Never import an older
# live ledger into the new DAY_SEQ engine.
COMPATIBLE_STATE_VERSIONS = {STATE_VERSION}

# PROFIT OPTIMIZED BALANCED 2026-07-04
# - Keep relock after 1 real loss.
# - Reduce UCB exploration to avoid testing weak windows too aggressively.
# - Shorten cooldown/blacklist to reduce FORCE_ANY_WINDOW_NO_DEADLOCK.
# - Moderate READY gates: still requires quality, but less WAIT starvation.

# PROFIT OPTIMIZED CONFIG V51
# Goal:
# - trade more when real window is positive
# - reduce over-wait from high consensus
# - avoid gap delay
# - relock quickly after 2 losses

# Persistent live state.
# Priority:
# 1) Google Sheet state backend if Streamlit secrets are configured.
# 2) Local JSON fallback.
#
# Optional Streamlit secrets:
# [v50_state]
# backend = "gsheet"
# sheet_id = "YOUR_STATE_SHEET_ID"
# worksheet = "state"
#
# [gcp_service_account]
# type = "service_account"
# project_id = "..."
# private_key_id = "..."
# private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
# client_email = "..."
# client_id = "..."
# auth_uri = "https://accounts.google.com/o/oauth2/auth"
# token_uri = "https://oauth2.googleapis.com/token"
# auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
# client_x509_cert_url = "..."
STATE_FILE = os.environ.get("V69_STATE_FILE", "v69_live_state.json")
# Durable local mirror / WAL. Written BEFORE remote Google State so an ambiguous
# remote write cannot cause a restart to replay a round from an older state.
STATE_WAL_FILE = os.environ.get("V69_STATE_WAL_FILE", STATE_FILE + ".wal")
STATE_WORKSHEET_DEFAULT = "state_v69"

# V50 profit protection tuning
LIVE_LOSS_COOLDOWN_ROUNDS = 2
LOCK_MIN_PROFIT20 = 0.0
LOCK_MAX_LOSS_STREAK = 1
LIVE_RELOCK_PROFIT_STOP = 0.0
LIVE_RELOCK_LOSS_STREAK = 2

# Shadow live scoring per window from LIVE_START_ROUND.
# Window selection will prefer live performance, not only historical profit.
LEADER_MIN_LIVE_WR20 = 0.36
LEADER_MIN_LIVE_PROFIT20 = 0.0
CANDIDATE_MIN_LIVE_PROFIT20 = 0.0
CANDIDATE_MIN_LIVE_WR20 = 0.38
CANDIDATE_MAX_LIVE_LOSS_STREAK = 1

# Real trade-aware relock.
# After a window has real trades, relock uses REAL performance first.
REAL_MIN_TRADE_COUNT_FOR_LOCK = 1
REAL_MIN_PROFIT_FOR_LOCK = 0.0
REAL_MAX_LOSS_STREAK_FOR_LOCK = 0
REAL_MIN_WR_FOR_LOCK = 0.34

# V4 fallback/anti-deadlock.
# If no real-positive window exists, use short-term candidate score
# so the engine can continue testing instead of WAIT forever.
FALLBACK_MIN_PROFIT20 = 0.0
FALLBACK_MIN_WR20 = 0.36
FALLBACK_MAX_LOSS_STREAK = 1
TRADE_GAP_ROUNDS = 0
LOW_WR_CONSENSUS_READY = 0.50
LOW_WR_LEVEL = 0.50
MAX_WINDOW_LOSS_STREAK_FOR_TOP = 5

# V52 anti-zigzag: after a window loses / turns negative, do not select it again soon.
WINDOW_COOLDOWN_ROUNDS = 2
BLACKLIST_REAL_NEGATIVE = True

PROFIT10_STOP = -2.0
WR20_STOP = 0.35
DRAWDOWN_STOP = -5.0
FLIPRATE_STOP = 0.65

CONSENSUS_READY = 0.50
STABILITY_READY = 0.45

# V53 defensive gates
MIN_CONFIDENCE_READY = 0.46
SAFE_DRAWDOWN_FROM_PEAK = -4.0
SAFE_MODE_ROUNDS = 2

# V60 Long Term Stable Live: avoid trade starvation.
REAL_SHADOW_BLEND_MIN_TRADES = 10
REAL_SHADOW_BLEND_FULL_TRADES = 30
MIN_SHADOW_PROFIT20_FOR_TEST = 1.0
MIN_SHADOW_WR20_FOR_TEST = 0.38
MAX_REAL_NEGATIVE_SOFT = -2.0

# V54 long-run controls
RISK_PAUSE_ROUNDS = 3
BLACKLIST_DURATION_ROUNDS = 5

# V69.2: sample-aware lock coherence guard.
# When the locked window has fewer than 2 live observations and Top3 has
# strong majority against the lock prediction, do not open a trade.
COHERENCE_MIN_LIVE_SAMPLES = 2
COHERENCE_DEFENSIVE_LIVE_SAMPLES = 5
COHERENCE_DEFENSIVE_HEALTH20_MAX = 0.50
COHERENCE_DEFENSIVE_STABILITY_MIN = 0.65
COHERENCE_MIN_CONSENSUS = 2.0 / 3.0

WINDOW_SELECTION_MODE = "shadow"  # "ucb" or "score"
UCB_EXPLORATION_C = 0.22
MIN_TRADES_FOR_PROTECTION = 6

# Daily Stop Guard - protect against deep negative days.
# These guards only block opening NEW trades. Pending trades still settle normally.
DAILY_STOP_LOSS = -2.5

# V3.4: live daily-history + adaptive coherence.
# Daily history is read from columns D:E of the same Google Sheet.
# D = completed calendar date, E = daily profit (may be formatted as 3,5).
# Number input supports both the legacy single `number` column and the
# horizontal date-column matrix shown in the live Google Sheet.
# V3.3: multi-day low-confidence filter. Only suppress low-confidence entries
# after a sustained negative daily regime; settled history is used only.
MULTI_DAY_CONF_FILTER = True
MULTI_DAY_NEG_DAY_STREAK = 3
MULTI_DAY_LOSS_COUNT = 2
MULTI_DAY_CONF_MAX = 0.54
ADAPTIVE_COH = True
NORMAL_COH = 5
BAD_REGIME_COH = 6
DAILY_MAX_LOSS_STREAK = 5
DAILY_MAX_DRAWDOWN = -15.0
DAILY_PROFIT_LOCK = 30.5

# Optional local CSV replay input. If set, load_numbers() reads this file instead of Google Sheet.
INPUT_CSV_PATH = os.environ.get("V54_INPUT_CSV", "").strip()


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class TradeRecord:
    round_id: int
    predict: int
    locked_window: Optional[int] = None
    actual: Optional[int] = None
    hit: Optional[int] = None
    profit: float = 0.0
    status: str = "PENDING"
    settle_round: Optional[int] = None


@dataclass
class SignalRecord:
    state: str = "WAIT"
    next_group: Optional[int] = None

    # Shadow/live performance after LIVE_START_ROUND.
    live_hit_history: deque = field(default_factory=lambda: deque(maxlen=50))
    live_profit20: float = 0.0
    live_profit50: float = 0.0
    live_profit_total: float = 0.0
    live_loss_streak: int = 0
    live_score: float = 0.0
    live_wr20: float = 0.0
    regime: str = "NORMAL"
    top_n: int = TOPN
    health20: float = 0.0
    health50: float = 0.0
    consensus: float = 0.0
    stability: float = 0.0
    momentum: float = 0.0
    required_consensus: float = CONSENSUS_READY
    top_profit20: float = 0.0
    leader_window: Optional[int] = None
    leader_wr20: float = 0.0
    leader_loss_streak: int = 0
    locked_window: Optional[int] = None
    lock_reason: str = ""
    state_version: str = STATE_VERSION
    locked_live_profit: float = 0.0
    locked_live_loss_streak: int = 0
    shadow_live_profit20: float = 0.0
    shadow_live_wr20: float = 0.0
    real_window_profit: float = 0.0
    real_window_wr: float = 0.0
    real_window_trade_count: int = 0
    real_window_loss_streak: int = 0

    locked_live_profit: float = 0.0
    locked_live_loss_streak: int = 0
    locked_live_win: int = 0
    locked_live_loss: int = 0

    # Real performance per locked window.
    # Example:
    # {
    #   6: {"trade_count": 2, "profit": 1.5, "win": 1, "loss": 1, "loss_streak": 0}
    # }
    window_real_stats: dict = field(default_factory=dict)
    cooled_windows: dict = field(default_factory=dict)
    pending_confidence: float = 0.0
    pending_target_round: int = 0
    peak_equity: float = 0.0
    last_safe_trigger_peak: float = 0.0
    risk_pause_counter: int = 0
    last_risk_trigger_trade_count: int = -1
    blacklisted_windows: dict = field(default_factory=dict)
    last_decision_confidence: float = 0.0
    daily_stop_active: bool = False
    daily_stop_reason: str = ""



@dataclass
class WindowRecord:
    hit_history: deque = field(default_factory=lambda: deque(maxlen=HIT_HISTORY_LEN))
    group_history: deque = field(default_factory=lambda: deque(maxlen=GROUP_HISTORY_LEN))
    profit20: float = 0.0
    profit50: float = 0.0
    loss_streak: int = 0
    score: float = 0.0
    next_group: Optional[int] = None



    # Shadow/live performance after LIVE_START_ROUND.
    live_hit_history: deque = field(default_factory=lambda: deque(maxlen=50))
    live_profit20: float = 0.0
    live_profit50: float = 0.0
    live_profit_total: float = 0.0
    live_loss_streak: int = 0
    live_score: float = 0.0
    live_wr20: float = 0.0
@dataclass
class EngineContext:
    trade_history: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    signal_history: deque = field(default_factory=lambda: deque(maxlen=SIGNAL_HISTORY_LEN))
    signal_flip_history: deque = field(default_factory=lambda: deque(maxlen=SIGNAL_HISTORY_LEN))
    leader_history: deque = field(default_factory=lambda: deque(maxlen=LEADER_HISTORY_LEN))

    pending_trade: Optional[int] = None
    pending_round: int = 0
    pending_index: Optional[int] = None
    pending_locked_window: Optional[int] = None
    trade_state: str = "IDLE"

    # Explicit persisted settlement checkpoint.
    last_result_round: int = -1
    last_result_open_round: int = -1
    last_result_predict: Optional[int] = None
    last_result_actual: Optional[int] = None
    last_result_hit: Optional[int] = None
    last_result_profit: float = 0.0
    last_result_status: str = ""

    last_length: int = 0
    last_open_round: int = -1
    last_settle_round: int = -1
    last_window_round: int = -1
    last_signal_round: int = -1

    # V3.4.8: actual decision made on the last processed round.
    last_decision_round: int = -1
    last_decision_state: str = "WAIT"
    last_decision_next_group: Optional[int] = None

    cooldown_counter: int = 0
    cooldown_loss_streak_marker: int = -1
    safe_mode_counter: int = 0
    protection_reason: str = ""
    open_reason: str = ""
    locked_window: Optional[int] = None
    lock_reason: str = ""
    state_version: str = STATE_VERSION
    live_day_id: str = ""
    # V3.5: explicit monotonic day sequence from Sheet column C.
    live_day_seq: int = 0
    live_day_date: str = ""
    daily_profit_history: list = field(default_factory=list)
    # V3.4.12: compact per-round audit trail for the current live dataset.
    round_log: list = field(default_factory=list)
    # V3.4.14: durable per-round transaction marker.
    round_txn_round: int = -1
    round_txn_phase: str = "IDLE"
    round_txn_opened: bool = False
    round_txn_settled: bool = False
    round_txn_signal: dict = field(default_factory=dict)

    # V3.4.4 persistent ledger integrity / revision checkpoint.
    # A new state version intentionally forces a clean replay of the current
    # live Number stream instead of trusting an older/stale V58/V3.x ledger.
    state_revision: int = 0
    ledger_trade_count: int = 0
    ledger_settled_count: int = 0
    ledger_profit: float = 0.0
    ledger_checksum: str = ""
    ledger_frontier_round: int = 0

    locked_live_profit: float = 0.0
    locked_live_loss_streak: int = 0
    locked_live_win: int = 0
    locked_live_loss: int = 0

    # Real performance per locked window.
    # Example:
    # {
    #   6: {"trade_count": 2, "profit": 1.5, "win": 1, "loss": 1, "loss_streak": 0}
    # }
    window_real_stats: dict = field(default_factory=dict)
    cooled_windows: dict = field(default_factory=dict)
    pending_confidence: float = 0.0
    pending_target_round: int = 0
    peak_equity: float = 0.0
    last_safe_trigger_peak: float = 0.0
    risk_pause_counter: int = 0
    last_risk_trigger_trade_count: int = -1
    blacklisted_windows: dict = field(default_factory=dict)
    last_decision_confidence: float = 0.0




# ============================================================
# CONTEXT MIGRATION / COMPATIBILITY
# ============================================================

def ensure_ctx_fields(ctx: EngineContext) -> EngineContext:
    """Make old session/state objects compatible with newer code."""
    if not hasattr(ctx, "cooled_windows") or ctx.cooled_windows is None:
        ctx.cooled_windows = {}

    if not hasattr(ctx, "window_real_stats") or ctx.window_real_stats is None:
        ctx.window_real_stats = {}

    if not hasattr(ctx, "pending_locked_window"):
        ctx.pending_locked_window = None

    if not hasattr(ctx, "locked_live_profit"):
        ctx.locked_live_profit = 0.0
    if not hasattr(ctx, "locked_live_loss_streak"):
        ctx.locked_live_loss_streak = 0
    if not hasattr(ctx, "locked_live_win"):
        ctx.locked_live_win = 0
    if not hasattr(ctx, "locked_live_loss"):
        ctx.locked_live_loss = 0
    if not hasattr(ctx, "safe_mode_counter"):
        ctx.safe_mode_counter = 0
    ctx.state_version = STATE_VERSION

    if not hasattr(ctx, "pending_confidence"):
        ctx.pending_confidence = 0.0
    if not hasattr(ctx, "pending_target_round"):
        ctx.pending_target_round = 0
    if not hasattr(ctx, "last_result_round"):
        ctx.last_result_round = -1
    if not hasattr(ctx, "last_result_open_round"):
        ctx.last_result_open_round = -1
    if not hasattr(ctx, "last_result_predict"):
        ctx.last_result_predict = None
    if not hasattr(ctx, "last_result_actual"):
        ctx.last_result_actual = None
    if not hasattr(ctx, "last_result_hit"):
        ctx.last_result_hit = None
    if not hasattr(ctx, "last_result_profit"):
        ctx.last_result_profit = 0.0
    if not hasattr(ctx, "last_result_status"):
        ctx.last_result_status = ""
    if not hasattr(ctx, "peak_equity"):
        ctx.peak_equity = max([0.0] + list(getattr(ctx, "equity_curve", [])))
    if not hasattr(ctx, "last_safe_trigger_peak"):
        ctx.last_safe_trigger_peak = 0.0
    if not hasattr(ctx, "risk_pause_counter"):
        ctx.risk_pause_counter = 0
    if not hasattr(ctx, "last_risk_trigger_trade_count"):
        ctx.last_risk_trigger_trade_count = -1
    if not hasattr(ctx, "blacklisted_windows") or ctx.blacklisted_windows is None:
        ctx.blacklisted_windows = {}
    if not hasattr(ctx, "last_decision_confidence"):
        ctx.last_decision_confidence = 0.0
    if not hasattr(ctx, "last_decision_round"):
        ctx.last_decision_round = -1
    if not hasattr(ctx, "last_decision_state"):
        ctx.last_decision_state = "WAIT"
    if not hasattr(ctx, "last_decision_next_group"):
        ctx.last_decision_next_group = None
    if not hasattr(ctx, "daily_stop_active"):
        ctx.daily_stop_active = False
    if not hasattr(ctx, "daily_stop_reason"):
        ctx.daily_stop_reason = ""
    if not hasattr(ctx, "keep_win_lock_until"):
        ctx.keep_win_lock_until = 0
    if not hasattr(ctx, "dataset_anchor_signature"):
        ctx.dataset_anchor_signature = ""
    if not hasattr(ctx, "live_day_id"):
        ctx.live_day_id = ""
    if not hasattr(ctx, "live_day_seq"):
        ctx.live_day_seq = 0
    if not hasattr(ctx, "live_day_date"):
        ctx.live_day_date = ""
    if not hasattr(ctx, "daily_profit_history") or ctx.daily_profit_history is None:
        ctx.daily_profit_history = []
    ctx.daily_profit_history = list(ctx.daily_profit_history)[-10:]
    if not hasattr(ctx, "round_log") or ctx.round_log is None:
        ctx.round_log = []
    ctx.round_log = list(ctx.round_log)[-300:]
    if not hasattr(ctx, "state_revision"):
        ctx.state_revision = 0
    if not hasattr(ctx, "ledger_trade_count"):
        ctx.ledger_trade_count = 0
    if not hasattr(ctx, "ledger_settled_count"):
        ctx.ledger_settled_count = 0
    if not hasattr(ctx, "ledger_profit"):
        ctx.ledger_profit = 0.0
    if not hasattr(ctx, "ledger_checksum"):
        ctx.ledger_checksum = ""
    if not hasattr(ctx, "ledger_frontier_round"):
        ctx.ledger_frontier_round = 0

    # Normalize keys loaded from JSON/Google Sheet.
    normalized_stats = {}
    for k, v in getattr(ctx, "window_real_stats", {}).items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        normalized_stats[kk] = v
    ctx.window_real_stats = normalized_stats

    normalized_cool = {}
    for k, v in getattr(ctx, "cooled_windows", {}).items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        try:
            vv = int(v)
        except Exception:
            vv = 0
        normalized_cool[kk] = vv
    ctx.cooled_windows = normalized_cool

    normalized_blacklist = {}
    for k, v in getattr(ctx, "blacklisted_windows", {}).items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        try:
            vv = int(v)
        except Exception:
            vv = 0
        normalized_blacklist[kk] = vv
    ctx.blacklisted_windows = normalized_blacklist

    return ctx


# ============================================================
# SESSION HELPERS
# ============================================================

def get_ctx() -> EngineContext:
    if "v50_ctx" not in st.session_state:
        st.session_state.v50_ctx = EngineContext()
    return st.session_state.v50_ctx


def get_window_state() -> dict[int, WindowRecord]:
    if "v50_window_state" not in st.session_state:
        st.session_state.v50_window_state = {
            w: WindowRecord()
            for w in WINDOWS
        }
    return st.session_state.v50_window_state


ctx = get_ctx()
window_state = get_window_state()


# ============================================================
# DATA LOADER
# ============================================================

def _load_live_sheet_df() -> pd.DataFrame:
    if INPUT_CSV_PATH:
        try:
            return pd.read_csv(INPUT_CSV_PATH)
        except Exception as e:
            st.error(f"Load local CSV error: {e}")
            st.stop()
    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv"
        f"&cache={time.time()}"
    )
    try:
        return pd.read_csv(url)
    except Exception as e:
        st.error(f"Load sheet error: {e}")
        st.stop()


def _parse_number_value(raw: Any) -> Optional[int]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    try:
        x = int(float(s.replace(",", ".")))
    except Exception:
        return None
    return x if 1 <= x <= 12 else None


def _parse_profit_value(raw: Any) -> Optional[float]:
    """Parse Sheet profit safely; e.g. '3,5' must become 3.5."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, (int, float)):
        try:
            return float(raw)
        except Exception:
            return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    # Handle both Vietnamese decimal comma and normal decimal point.
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _parse_date_value(raw: Any) -> Optional[datetime.date]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        dt = pd.to_datetime(raw, errors="coerce", dayfirst=False)
        if not pd.isna(dt):
            return dt.date()
    except Exception:
        pass
    return None


def _get_daily_history_from_df(df: pd.DataFrame) -> list[dict]:
    """Read D:E from the live sheet as completed daily history.

    The screenshot/layout uses D for date and E for daily profit, while the
    header labels may be numeric rather than named 'date'/'profit'. Therefore
    this intentionally uses physical columns D/E (indexes 3/4), not names.
    Duplicate dates are collapsed to the last non-empty profit value.
    """
    if df.shape[1] < 5:
        return []
    date_col = df.iloc[:, 3]
    profit_col = df.iloc[:, 4]
    by_day: dict[str, float] = {}
    for d_raw, p_raw in zip(date_col.tolist(), profit_col.tolist()):
        d = _parse_date_value(d_raw)
        p = _parse_profit_value(p_raw)
        if d is None or p is None:
            continue
        by_day[d.isoformat()] = round(float(p), 2)
    return [
        {"day_id": k, "profit": v}
        for k, v in sorted(by_day.items())
    ]


def _find_horizontal_number_column(df: pd.DataFrame, target_day_id: str) -> Optional[int]:
    """Find today's Number column in the horizontal date matrix.

    Current Google-Sheet export layout:
      A = round
      B = number (legacy/current input column; often empty in the exported
          historical matrix)
      D = calendar date for each round row
      E = daily profit
      H:... = one Number column per calendar day

    The horizontal header is displayed as day-of-month values such as
    2,3,...,30,1.  F/G are blank spacer columns in the user's Sheet, so the
    old implementation must NOT assume the matrix starts at column F.

    Mapping is therefore based on the actual numeric header columns and the
    ordered unique dates in physical column D.  A full-date header, when
    present, always takes precedence.
    """
    if df.shape[1] <= 5:
        return None

    target = pd.to_datetime(target_day_id).date()

    # 1) Prefer explicit/full-date headers if the Sheet uses them.
    for j in range(5, df.shape[1]):
        raw = df.columns[j]
        d = _parse_date_value(raw)
        if d == target:
            return j

    # 2) Current layout: numeric day-of-month headers.  Do not assume the
    # first matrix column is F; skip blank spacer columns automatically.
    numeric_header_cols: list[tuple[int, int]] = []
    for j in range(5, df.shape[1]):
        raw = df.columns[j]
        try:
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            s = str(raw).strip()
            if not s:
                continue
            # Only accept integer day headers 1..31; this excludes values such
            # as the E1 profit summary/header (20.5) even if columns shift.
            f = float(s.replace(",", "."))
            day_num = int(f)
            if abs(f - day_num) < 1e-9 and 1 <= day_num <= 31:
                numeric_header_cols.append((j, day_num))
        except Exception:
            continue

    if not numeric_header_cols:
        return None

    # Ordered unique calendar dates from D.  In this Sheet, the first N dates
    # correspond one-to-one with the N horizontal Number columns.
    dates: list[datetime.date] = []
    if df.shape[1] > 3:
        for raw in df.iloc[:, 3].tolist():
            d = _parse_date_value(raw)
            if d is not None and d not in dates:
                dates.append(d)

    max_pairs = min(len(numeric_header_cols), len(dates))
    for offset in range(max_pairs):
        col_idx, header_day = numeric_header_cols[offset]
        mapped_date = dates[offset]
        # Guard against a malformed/misaligned Sheet. Never accept a column
        # if its displayed day does not agree with the date row it represents.
        if mapped_date.day != header_day:
            continue
        if mapped_date == target:
            return col_idx

    # 3) Safe fallback for a rolling matrix when D contains more historical
    # dates than the horizontal matrix: find a unique date with the same
    # day-of-month and use the corresponding numeric header only when the
    # surrounding date sequence confirms the position.
    candidates = [i for i, d in enumerate(dates) if d == target]
    if len(candidates) == 1:
        offset = candidates[0]
        if offset < len(numeric_header_cols):
            col_idx, header_day = numeric_header_cols[offset]
            if header_day == target.day:
                return col_idx

    return None

def _read_contiguous_number_column(df: pd.DataFrame, col_idx: int, skip_first_data_row: bool = False) -> list[int]:
    nums = []
    values = df.iloc[:, col_idx].tolist()
    if skip_first_data_row:
        values = values[1:]
    for raw in values:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
            break
        x = _parse_number_value(raw)
        if x is None:
            break
        nums.append(x)
    return nums


def _normalize_day_seq(raw: Any) -> Optional[int]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    try:
        x = int(float(s.replace(",", ".")))
    except Exception:
        return None
    return x if x >= 1 else None


def _load_day_seq_sheet_snapshot() -> tuple[pd.DataFrame, int, str, list[int]]:
    """Read the new append-only DAY_SEQ Sheet format.

    Contract:
      A = round
      B = number
      C = day_seq (1,2,3,... monotonic)
      D = date
      E = daily_profit

    The highest valid day_seq is the live/current day. Historical rows remain
    in the Sheet and are never used as the current Number stream.
    """
    df = _load_live_sheet_df()
    if df.shape[1] < 5:
        st.error("Sheet must contain A:E = round, number, day_seq, date, daily_profit.")
        st.stop()

    # Physical columns are authoritative; do not depend on localized headers.
    c_round = df.iloc[:, 0]
    c_number = df.iloc[:, 1]
    c_seq = df.iloc[:, 2]
    c_date = df.iloc[:, 3]

    seqs = [_normalize_day_seq(x) for x in c_seq.tolist()]
    valid = [x for x in seqs if x is not None]
    if not valid:
        st.warning("Waiting DAY_SEQ data...")
        return df, 0, "", []

    current_seq = max(valid)
    mask = [x == current_seq for x in seqs]
    idxs = [i for i, ok in enumerate(mask) if ok]
    if not idxs:
        st.warning("Current DAY_SEQ has no rows.")
        return df, current_seq, "", []

    # Strictly preserve Sheet row order. Current day must start at round 1 and
    # rounds must be contiguous 1..N. This catches accidental sorting/mixing.
    nums: list[int] = []
    rounds: list[int] = []
    dates: list[str] = []
    for pos, i in enumerate(idxs, start=1):
        raw_r = c_round.iloc[i]
        raw_n = c_number.iloc[i]
        try:
            rr = int(float(str(raw_r).replace(",", ".")))
        except Exception:
            rr = -1
        n = _parse_number_value(raw_n)
        if rr != pos or n is None:
            # Current day may be partially filled, but it must still be a
            # contiguous prefix starting from round 1.
            break
        rounds.append(rr)
        nums.append(n)
        d = _parse_date_value(c_date.iloc[i])
        dates.append(d.isoformat() if d is not None else "")

    if nums:
        bad_dates = {d for d in dates if d}
        if len(bad_dates) > 1:
            st.error(f"DAY_SEQ {current_seq} has multiple dates: {sorted(bad_dates)}")
            st.stop()
        day_date = next(iter(bad_dates), "")
    else:
        day_date = ""

    return df, current_seq, day_date, nums


def load_numbers() -> list[int]:
    """Load ONLY the highest DAY_SEQ contiguous Number prefix."""
    _df, _seq, _date, nums = _load_day_seq_sheet_snapshot()
    return nums


def get_current_sheet_day_seq() -> int:
    """Return the highest DAY_SEQ currently present in the live Sheet."""
    _df, seq, _date, _nums = _load_day_seq_sheet_snapshot()
    return int(seq)


def get_current_sheet_day_info() -> tuple[int, str]:
    """Return (highest DAY_SEQ, date) from the current Sheet."""
    _df, seq, day_date, _nums = _load_day_seq_sheet_snapshot()
    return int(seq), str(day_date or "")


def _parse_daily_profit_v35(raw: Any) -> Optional[float]:
    """Parse daily P/L without allowing date-formatted cells to become P/L.

    Google Sheets should keep column E as Number. If an imported Excel snapshot
    contains a date object in E, it is treated as invalid rather than guessed.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, (pd.Timestamp, datetime)):
        return None
    return _parse_profit_value(raw)


def _get_daily_history_from_df_v35(df: pd.DataFrame, current_seq: int) -> list[dict]:
    """Read completed P/L by DAY_SEQ, not by calendar date.

    A day's P/L is the last non-empty value in physical column E for that
    DAY_SEQ. Only DAY_SEQ values strictly below current_seq are considered
    completed history.
    """
    if df.shape[1] < 5:
        return []
    rows: dict[int, dict] = {}
    for i in range(len(df)):
        seq = _normalize_day_seq(df.iloc[i, 2])
        if seq is None or seq >= current_seq:
            continue
        p = _parse_daily_profit_v35(df.iloc[i, 4])
        if p is None:
            continue
        d = _parse_date_value(df.iloc[i, 3])
        rows[seq] = {"day_seq": seq, "day_id": d.isoformat() if d else str(seq), "profit": round(float(p), 2)}
    return [rows[k] for k in sorted(rows)]


@st.cache_data(ttl=5)
def load_daily_profit_history_from_sheet() -> list[dict]:
    try:
        df = _load_live_sheet_df()
        seqs = [_normalize_day_seq(x) for x in df.iloc[:, 2].tolist()] if df.shape[1] >= 3 else []
        current_seq = max([x for x in seqs if x is not None], default=0)
        return _get_daily_history_from_df_v35(df, current_seq)
    except Exception:
        return []


def _merge_sheet_daily_history_into_ctx(ctx: EngineContext) -> EngineContext:
    ensure_ctx_fields(ctx)
    merged: dict[int, dict] = {}
    for item in list(getattr(ctx, "daily_profit_history", []) or []):
        if not isinstance(item, dict):
            continue
        try:
            seq = int(item.get("day_seq"))
            merged[seq] = {"day_seq": seq, "day_id": str(item.get("day_id", seq)), "profit": round(float(item.get("profit", 0.0)), 2)}
        except Exception:
            continue
    for item in load_daily_profit_history_from_sheet():
        try:
            seq = int(item["day_seq"])
            merged[seq] = item
        except Exception:
            continue
    current_seq, _day_date = get_current_sheet_day_info()
    ctx.daily_profit_history = [merged[k] for k in sorted(merged) if k < current_seq][-10:]
    return ctx


def current_live_day_id() -> str:
    """Compatibility helper; V3.5 day boundaries are controlled by DAY_SEQ."""
    try:
        _seq, day_date = get_current_sheet_day_info()
        return day_date or ""
    except Exception:
        return ""


def load_data() -> tuple[list[int], list[int], int, int]:
    numbers = load_numbers()
    if len(numbers) < MIN_DATA_LEN:
        st.warning("Waiting data...")
        st.stop()
    groups = build_groups(numbers)
    return numbers, groups, groups[-1], len(numbers)


def group_of(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def build_groups(numbers: list[int]) -> list[int]:
    return [group_of(x) for x in numbers]


def make_numbers_signature(numbers: list[int], length: Optional[int] = None) -> str:
    if length is None:
        length = len(numbers)
    length = max(0, min(int(length), len(numbers)))
    payload = ",".join(str(int(x)) for x in numbers[:length])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_round_time_display_only(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "--:--"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%H:%M")
    except Exception:
        pass
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return "--:--"
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*$", s)
    if m:
        return f"{int(m.group(1))%24:02d}:{int(m.group(2))%60:02d}"
    try:
        v=float(s)
        if 0<=v<1:
            total=int(round(v*24*60))%(24*60)
            return f"{total//60:02d}:{total%60:02d}"
    except Exception: pass
    return s


def get_current_target_time_display_only(current_round: int) -> tuple[str, str]:
    # V3.5: UI-only placeholder. Round labels are not part of the trading input.
    return "--:--", "--:--"


# ============================================================
# WINDOW ENGINE
# ============================================================

class WindowEngine:
    def __init__(self, ctx: EngineContext, state: dict[int, WindowRecord]):
        self.ctx = ctx
        self.state = state

    def _calc_profit(self, hits: list[int]) -> float:
        return round(
            sum(WIN_GROUP if x else LOSS_GROUP for x in hits),
            2
        )

    def _ensure_live_fields(self, stt: WindowRecord) -> None:
        if not hasattr(stt, "live_hit_history"):
            stt.live_hit_history = deque(maxlen=50)
        if not hasattr(stt, "live_profit20"):
            stt.live_profit20 = 0.0
        if not hasattr(stt, "live_profit50"):
            stt.live_profit50 = 0.0
        if not hasattr(stt, "live_profit_total"):
            stt.live_profit_total = 0.0
        if not hasattr(stt, "live_loss_streak"):
            stt.live_loss_streak = 0
        if not hasattr(stt, "live_score"):
            stt.live_score = 0.0
        if not hasattr(stt, "live_wr20"):
            stt.live_wr20 = 0.0

    def update_one_round(self, actual_group: int, round_id: int) -> None:
        if round_id == self.ctx.last_window_round:
            return

        for w, stt in self.state.items():
            self._ensure_live_fields(stt)

            # 1) Settle previous prediction for this window against actual.
            if stt.next_group is not None:
                hit = int(stt.next_group == actual_group)
                stt.hit_history.append(hit)

                tail20 = list(stt.hit_history)[-20:]
                tail50 = list(stt.hit_history)[-50:]

                stt.profit20 = self._calc_profit(tail20)
                stt.profit50 = self._calc_profit(tail50)

                if hit:
                    stt.loss_streak = 0
                else:
                    stt.loss_streak = int(stt.loss_streak) + 1

                # Shadow/live performance starts from trades that would settle after LIVE_START_ROUND.
                # This gives each window a fair live score, even when it was not actually selected.
                if round_id > LIVE_START_ROUND:
                    stt.live_hit_history.append(hit)
                    live_tail20 = list(stt.live_hit_history)[-20:]
                    live_tail50 = list(stt.live_hit_history)[-50:]

                    stt.live_profit20 = self._calc_profit(live_tail20)
                    stt.live_profit50 = self._calc_profit(live_tail50)
                    stt.live_profit_total = round(
                        stt.live_profit_total + (WIN_GROUP if hit else LOSS_GROUP),
                        2
                    )
                    stt.live_wr20 = (
                        round(sum(live_tail20) / len(live_tail20), 3)
                        if live_tail20 else 0.0
                    )

                    if hit:
                        stt.live_loss_streak = 0
                    else:
                        stt.live_loss_streak = int(stt.live_loss_streak) + 1

                    stt.live_score = round(
                        stt.live_profit20 +
                        0.30 * stt.live_profit50 -
                        stt.live_loss_streak,
                        3
                    )

            # 2) Update raw group history.
            stt.group_history.append(actual_group)

            # 3) Cycle prediction: next group = group from w rounds ago.
            if len(stt.group_history) >= w:
                stt.next_group = list(stt.group_history)[-w]
            else:
                stt.next_group = None

            # 4) Historical score.
            stt.score = round(
                float(stt.profit20) +
                0.30 * float(stt.profit50) -
                float(stt.loss_streak),
                3
            )

        top = self.get_top_windows(1)
        if top:
            self.ctx.leader_history.append(top[0][0])

        self.ctx.last_window_round = round_id

    def get_top_windows(self, top_n: int = TOPN) -> list[tuple[int, WindowRecord]]:
        # Prefer windows with good shadow-live performance after LIVE_START_ROUND.
        for stt in self.state.values():
            self._ensure_live_fields(stt)

        has_live = any(len(stt.live_hit_history) > 0 for stt in self.state.values())

        if has_live:
            valid_rows = [
                (w, stt)
                for w, stt in self.state.items()
                if (
                    int(stt.live_loss_streak) <= MAX_WINDOW_LOSS_STREAK_FOR_TOP
                    and stt.next_group is not None
                )
            ]

            rows_source = valid_rows if valid_rows else [
                (w, stt)
                for w, stt in self.state.items()
                if stt.next_group is not None
            ]

            rows = sorted(
                rows_source,
                key=lambda x: (
                    x[1].live_score,
                    x[1].live_profit20,
                    x[1].live_wr20,
                    x[1].score,
                ),
                reverse=True
            )

            return rows[:top_n]

        # Warm-up fallback: use historical score.
        valid_rows = [
            (w, stt)
            for w, stt in self.state.items()
            if int(stt.loss_streak) <= MAX_WINDOW_LOSS_STREAK_FOR_TOP
        ]

        rows_source = valid_rows if valid_rows else list(self.state.items())

        rows = sorted(
            rows_source,
            key=lambda x: x[1].score,
            reverse=True
        )
        return rows[:top_n]

    def get_consensus(
        self,
        top_rows: Optional[list[tuple[int, WindowRecord]]] = None
    ) -> tuple[Optional[int], float]:
        if top_rows is None:
            top_rows = self.get_top_windows(TOPN)

        preds = [
            stt.next_group
            for _, stt in top_rows
            if stt.next_group is not None
        ]

        if not preds:
            return None, 0.0

        group, count = Counter(preds).most_common(1)[0]
        return group, round(count / len(preds), 3)

    def get_health(self) -> tuple[float, float]:
        total = len(WINDOWS)
        if total == 0:
            return 0.0, 0.0

        positive20 = sum(
            1 for w in WINDOWS
            if self.state[w].profit20 > 0
        )
        positive50 = sum(
            1 for w in WINDOWS
            if self.state[w].profit50 > 0
        )

        return (
            round(positive20 / total, 3),
            round(positive50 / total, 3)
        )

    def get_leader_change_rate(self) -> float:
        history = list(self.ctx.leader_history)
        if len(history) < 2:
            return 0.0

        changes = sum(
            1
            for i in range(1, len(history))
            if history[i] != history[i - 1]
        )

        return round(changes / (len(history) - 1), 3)

    def get_stability(self) -> float:
        return round(
            max(0.0, 1.0 - self.get_leader_change_rate()),
            3
        )


# ============================================================
# SIGNAL ENGINE
# ============================================================

class SignalEngine:
    def __init__(self, ctx: EngineContext, window_engine: WindowEngine):
        self.ctx = ctx
        self.window_engine = window_engine

    def get_momentum(self, top_rows: list[tuple[int, WindowRecord]]) -> float:
        if not top_rows:
            return 0.0

        value = sum(
            stt.profit20 - stt.profit50
            for _, stt in top_rows
        ) / len(top_rows)

        return round(float(value), 3)

    def get_regime(
        self,
        consensus: float,
        stability: float,
        momentum: float
    ) -> str:
        if consensus < CONSENSUS_READY:
            return "CHAOS"
        if stability < STABILITY_READY:
            return "CHAOS"
        if momentum > 2:
            return "TREND"
        return "NORMAL"

    def get_confidence_score(self, signal: SignalRecord) -> float:
        # Leader-driven confidence:
        # leader WR20 is more important than Top5 majority consensus.
        score = (
            0.40 * signal.leader_wr20 +
            0.30 * signal.stability +
            0.20 * signal.health20 +
            0.10 * signal.consensus
        )
        return round(score, 3)

    def get_confidence_level(self, score: float) -> str:
        if score >= 0.90:
            return "VERY HIGH"
        if score >= 0.80:
            return "HIGH"
        if score >= 0.70:
            return "NORMAL"
        if score >= 0.60:
            return "LOW"
        return "DANGER"

    def get_real_stats(self, window_id: Optional[int]) -> dict:
        return get_history_real_stats(self.ctx, window_id)

    def is_window_cooled(self, window_id: int, current_round: Optional[int] = None) -> bool:
        ensure_ctx_fields(self.ctx)

        if current_round is None:
            current_round = self.ctx.last_length

        try:
            w = int(window_id)
        except Exception:
            w = window_id

        until_round = int(self.ctx.cooled_windows.get(w, 0))
        return current_round < until_round

    def cool_window(self, window_id: Optional[int], reason: str = "") -> None:
        ensure_ctx_fields(self.ctx)

        if window_id is None:
            return
        try:
            w = int(window_id)
        except Exception:
            w = window_id

        self.ctx.cooled_windows[w] = int(self.ctx.last_length + WINDOW_COOLDOWN_ROUNDS)

    def is_window_blacklisted(self, window_id: int, current_round: Optional[int] = None) -> bool:
        ensure_ctx_fields(self.ctx)
        if current_round is None:
            current_round = self.ctx.last_length
        try:
            w = int(window_id)
        except Exception:
            w = window_id
        until_round = int(getattr(self.ctx, "blacklisted_windows", {}).get(w, 0))
        return current_round < until_round

    def blacklist_window(self, window_id: Optional[int], current_round: Optional[int] = None) -> None:
        ensure_ctx_fields(self.ctx)
        if window_id is None:
            return
        if current_round is None:
            current_round = self.ctx.last_length
        try:
            w = int(window_id)
        except Exception:
            w = window_id
        self.ctx.blacklisted_windows[w] = int(current_round + BLACKLIST_DURATION_ROUNDS)

    def known_bad_window(self, window_id: int) -> bool:
        """V55: negative RealStats is a penalty, not a permanent ban."""
        stat = self.get_real_stats(window_id)

        if self.is_window_cooled(window_id):
            return True

        if self.is_window_blacklisted(window_id):
            return True

        if stat["trade_count"] >= 3 and stat["profit"] <= MAX_REAL_NEGATIVE_SOFT and stat["loss_streak"] >= 2:
            return True

        return False

    def shadow_candidate_score(self, obj: WindowRecord) -> float:
        hits20 = list(obj.hit_history)[-20:]
        wr20 = round(sum(hits20) / len(hits20), 3) if hits20 else 0.0
        return round(
            1.20 * obj.live_profit20
            + 8.00 * obj.live_wr20
            + 0.80 * obj.profit20
            + 3.00 * wr20
            - 2.00 * int(obj.live_loss_streak)
            - 1.50 * int(obj.loss_streak),
            3
        )

    def hybrid_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        stat = self.get_real_stats(window_id)
        trades = int(stat["trade_count"])

        real_score = (
            4.00 * stat["profit"]
            + 6.00 * stat["wr"]
            - 3.00 * stat["loss_streak"]
            + 0.05 * trades
        )
        shadow_score = self.shadow_candidate_score(obj)

        if trades <= 0:
            real_weight = 0.0
        elif trades < REAL_SHADOW_BLEND_MIN_TRADES:
            real_weight = 0.35
        elif trades < REAL_SHADOW_BLEND_FULL_TRADES:
            real_weight = 0.60
        else:
            real_weight = 0.85

        score = real_weight * real_score + (1.0 - real_weight) * shadow_score

        if trades > 0 and stat["profit"] < 0:
            score -= min(3.0, abs(stat["profit"]) * 0.8)

        return round(score, 3)

    def real_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        stat = self.get_real_stats(window_id)
        score = (
            4.00 * stat["profit"]
            + 6.00 * stat["wr"]
            - 3.00 * stat["loss_streak"]
            + 0.30 * obj.live_profit20
            + 0.10 * obj.profit20
        )
        return round(score, 3)

    def candidate_score(self, obj: WindowRecord) -> float:
        return self.shadow_candidate_score(obj)

    def ucb_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        stat = self.get_real_stats(window_id)
        total_real_trades = sum(int(s.get("trade_count", 0)) for s in self.ctx.window_real_stats.values())
        n = max(1, int(stat.get("trade_count", 0)))

        real_mean = float(stat.get("profit", 0.0)) / n if stat.get("trade_count", 0) else 0.0
        shadow_hits = list(obj.live_hit_history)[-20:]
        shadow_wr = round(sum(shadow_hits) / len(shadow_hits), 3) if shadow_hits else obj.live_wr20
        shadow_mean = (shadow_wr * WIN_GROUP) - ((1.0 - shadow_wr) * abs(LOSS_GROUP))

        optimism = UCB_EXPLORATION_C * math.sqrt(math.log(max(total_real_trades + len(WINDOWS), 2)) / n)
        penalty = 0.25 * int(obj.live_loss_streak) + 0.15 * int(obj.loss_streak)
        return round(0.70 * real_mean + 0.30 * shadow_mean + optimism - penalty, 3)

    def selection_score(self, window_id: int, obj: WindowRecord) -> float:
        if WINDOW_SELECTION_MODE.lower() == "ucb":
            return self.ucb_candidate_score(window_id, obj)
        return self.candidate_score(obj)

    def choose_relock_candidate(
        self,
        top_rows: list[tuple[int, WindowRecord]]
    ) -> tuple[Optional[int], Optional[WindowRecord], str]:
        # ====================================================
        # 1) Prefer REAL positive windows
        # ====================================================
        real_candidates = []

        for w, obj in self.window_engine.state.items():
            if obj.next_group is None:
                continue
            if self.known_bad_window(w):
                continue

            stat = self.get_real_stats(w)

            if stat["trade_count"] < REAL_MIN_TRADE_COUNT_FOR_LOCK:
                continue
            if stat["profit"] < REAL_MIN_PROFIT_FOR_LOCK:
                continue
            if stat["wr"] < REAL_MIN_WR_FOR_LOCK and obj.live_wr20 < MIN_SHADOW_WR20_FOR_TEST:
                continue
            if stat["loss_streak"] > REAL_MAX_LOSS_STREAK_FOR_LOCK:
                continue
            if int(obj.loss_streak) > LOCK_MAX_LOSS_STREAK:
                continue

            real_candidates.append(
                (
                    self.real_candidate_score(w, obj),
                    stat["profit"],
                    stat["wr"],
                    -stat["loss_streak"],
                    w,
                    obj,
                )
            )

        if real_candidates:
            real_candidates.sort(reverse=True)
            _, _, _, _, w, obj = real_candidates[0]
            return w, obj, "RELOCK_BY_REAL_POSITIVE_WINDOW"

        # ====================================================
        # 2) Fallback: short-term candidate score
        # ====================================================
        # Important: do not return None just because no real-positive
        # candidate exists. Otherwise engine gets stuck after one loss.
        fallback_candidates = []

        for w, obj in self.window_engine.state.items():
            if obj.next_group is None:
                continue
            if self.known_bad_window(w):
                continue

            hits20 = list(obj.hit_history)[-20:]
            wr20 = round(sum(hits20) / len(hits20), 3) if hits20 else 0.0

            if obj.profit20 <= FALLBACK_MIN_PROFIT20 and obj.live_profit20 < MIN_SHADOW_PROFIT20_FOR_TEST:
                continue
            if wr20 < FALLBACK_MIN_WR20 and obj.live_wr20 < MIN_SHADOW_WR20_FOR_TEST:
                continue
            if int(obj.loss_streak) > FALLBACK_MAX_LOSS_STREAK:
                continue

            fallback_candidates.append(
                (
                    self.selection_score(w, obj),
                    obj.profit20,
                    wr20,
                    -int(obj.loss_streak),
                    w,
                    obj,
                )
            )

        if fallback_candidates:
            fallback_candidates.sort(reverse=True)
            _, _, _, _, w, obj = fallback_candidates[0]
            return w, obj, "RELOCK_BY_SHORT_TERM_FALLBACK"

        # ====================================================
        # 3) Last resort: current TopN best score, but avoid known bad real windows
        # ====================================================
        for w, obj in top_rows:
            known_bad = self.known_bad_window(w)
            if obj.next_group is not None and not known_bad:
                return w, obj, "FORCE_TOP_WINDOW_NO_DEADLOCK"

        # Absolute final fallback: any untested or not-bad window with next_group
        for w, obj in self.window_engine.state.items():
            known_bad = self.known_bad_window(w)
            if obj.next_group is not None and not known_bad:
                return w, obj, "FORCE_ANY_WINDOW_NO_DEADLOCK"

        # If all windows are known bad, pick the least bad by candidate score instead of deadlocking.
        emergency = []
        for w, obj in self.window_engine.state.items():
            if obj.next_group is None:
                continue
            if self.is_window_cooled(w):
                continue
            emergency.append((self.selection_score(w, obj), w, obj))

        if emergency:
            emergency.sort(reverse=True)
            _, w, obj = emergency[0]
            return w, obj, "EMERGENCY_LEAST_BAD_UNCOOLED"

        return None, None, "NO_SAFE_CANDIDATE"

        return None, None, "NO_VALID_CANDIDATE"

    def build_signal_snapshot(self, round_id: int) -> SignalRecord:
        """Display-only signal.

        IMPORTANT:
        This function must not mutate ctx.locked_window, ctx.lock_reason,
        cooldown, blacklist, signal_history, or any trading state.
        It is used only by the dashboard when no new round appears.
        """
        top_rows = self.window_engine.get_top_windows(TOPN)
        _, consensus = self.window_engine.get_consensus(top_rows)

        health20, health50 = self.window_engine.get_health()
        stability = self.window_engine.get_stability()
        momentum = self.get_momentum(top_rows)

        locked_window = self.ctx.locked_window
        locked_obj = None
        if locked_window is not None:
            locked_obj = self.window_engine.state.get(locked_window)

        if locked_obj is None:
            # Snapshot fallback only; do not apply relock.
            for w, obj in top_rows:
                if obj.next_group is not None:
                    locked_window, locked_obj = w, obj
                    break

        next_group = locked_obj.next_group if locked_obj is not None else None

        if locked_obj is not None and len(locked_obj.live_hit_history) > 0:
            leader_wr20 = locked_obj.live_wr20
            top_profit20 = locked_obj.live_profit20
        else:
            hits20 = list(locked_obj.hit_history)[-20:] if locked_obj is not None else []
            leader_wr20 = round(sum(hits20) / len(hits20), 3) if hits20 else 0.0
            top_profit20 = locked_obj.profit20 if locked_obj is not None else 0.0

        leader_loss_streak = int(locked_obj.loss_streak) if locked_obj is not None else 0
        real_locked_stat = self.get_real_stats(locked_window)

        wr20 = TradeEngine(self.ctx).get_winrate(20)
        required_consensus = CONSENSUS_READY
        if wr20 > 0 and wr20 < LOW_WR_LEVEL:
            required_consensus = LOW_WR_CONSENSUS_READY

        if stability < STABILITY_READY:
            regime = "CHAOS"
        elif locked_obj is not None and locked_obj.profit20 > 0 and leader_wr20 >= 0.35:
            regime = "TREND"
        else:
            regime = "NORMAL"

        state = "WAIT"
        if round_id >= LIVE_START_ROUND and locked_obj is not None and next_group is not None:
            if (
                not (len(locked_obj.live_hit_history) > 0 and locked_obj.live_profit20 <= LEADER_MIN_LIVE_PROFIT20)
                and not (len(locked_obj.live_hit_history) > 0 and locked_obj.live_wr20 < LEADER_MIN_LIVE_WR20)
                and not (locked_obj.profit20 <= LOCK_MIN_PROFIT20)
                and not (leader_wr20 < FALLBACK_MIN_WR20)
                and not (leader_loss_streak > LOCK_MAX_LOSS_STREAK)
                and not (stability < STABILITY_READY)
            ):
                real_ok = (
                    real_locked_stat["trade_count"] >= 1
                    and real_locked_stat["profit"] > 0
                    and real_locked_stat["wr"] >= REAL_MIN_WR_FOR_LOCK
                    and real_locked_stat["loss_streak"] <= REAL_MAX_LOSS_STREAK_FOR_LOCK
                )
                if real_ok or consensus >= required_consensus or leader_wr20 >= 0.50:
                    state = "READY"

        return SignalRecord(
            state=state,
            next_group=next_group,
            regime=regime,
            top_n=TOPN,
            health20=health20,
            health50=health50,
            consensus=consensus,
            stability=stability,
            momentum=momentum,
            required_consensus=required_consensus,
            top_profit20=top_profit20,
            leader_window=locked_window,
            leader_wr20=leader_wr20,
            leader_loss_streak=leader_loss_streak,
            locked_window=self.ctx.locked_window,
            lock_reason=self.ctx.lock_reason,
            locked_live_profit=self.ctx.locked_live_profit,
            locked_live_loss_streak=self.ctx.locked_live_loss_streak,
            shadow_live_profit20=(locked_obj.live_profit20 if locked_obj is not None else 0.0),
            shadow_live_wr20=(locked_obj.live_wr20 if locked_obj is not None else 0.0),
            real_window_profit=real_locked_stat["profit"],
            real_window_wr=real_locked_stat["wr"],
            real_window_trade_count=real_locked_stat["trade_count"],
            real_window_loss_streak=real_locked_stat["loss_streak"],
        )

    def get_dynamic_coherence_samples(self, signal: SignalRecord) -> int:
        """V69.3: choose COH2/COH6 from current observed regime only.

        COH2 remains the default.  COH6 is enabled only when the current
        window landscape is low-health but stable.  All inputs are calculated
        from data already settled/current at the decision round; no future
        round is referenced.
        """
        health20 = float(getattr(signal, "health20", 0.0) or 0.0)
        stability = float(getattr(signal, "stability", 0.0) or 0.0)

        if (
            health20 < COHERENCE_DEFENSIVE_HEALTH20_MAX
            and stability >= COHERENCE_DEFENSIVE_STABILITY_MIN
        ):
            return COHERENCE_DEFENSIVE_LIVE_SAMPLES

        return COHERENCE_MIN_LIVE_SAMPLES

    def apply_sample_aware_coherence(
        self,
        signal: SignalRecord,
        min_live_samples: Optional[int] = None
    ) -> SignalRecord:
        """V69.3: sample-aware coherence with adaptive COH2/COH6.

        COH2 is the normal default.  In the defensive low-health/stable
        regime, COH6 is used while the locked window has fewer than 6
        shadow/live observations.  Established locks are unchanged.
        """
        if signal.locked_window is None or signal.next_group is None:
            return signal

        if min_live_samples is None:
            min_live_samples = self.get_dynamic_coherence_samples(signal)

        # V3.4 adaptive coherence: when the completed 3-day history is
        # negative and the current day has already suffered two consecutive
        # settled losses, require one extra live confirmation sample.
        # This is evaluated only from information available before the new
        # entry, so it is safe for progressive live execution.
        if ADAPTIVE_COH and is_bad_multi_day_regime(self.ctx):
            min_live_samples = max(int(min_live_samples), BAD_REGIME_COH)

        min_live_samples = max(
            COHERENCE_MIN_LIVE_SAMPLES,
            int(min_live_samples)
        )

        obj = self.window_engine.state.get(signal.locked_window)
        live_n = len(obj.live_hit_history) if obj is not None else 0
        if live_n >= min_live_samples:
            return signal

        top_rows = self.window_engine.get_top_windows(TOPN)
        consensus_group, consensus = self.window_engine.get_consensus(top_rows)

        if (
            consensus_group is not None
            and consensus >= COHERENCE_MIN_CONSENSUS
            and consensus_group != signal.next_group
        ):
            signal.state = "WAIT"
            signal.next_group = None
            self.ctx.protection_reason = "WEAK_LOCK_CONSENSUS_CONFLICT"

        return signal

    def build_signal(self, round_id: int) -> SignalRecord:
        top_rows = self.window_engine.get_top_windows(TOPN)

        # Consensus is only market confirmation. Prediction follows locked window.
        _, consensus = self.window_engine.get_consensus(top_rows)

        health20, health50 = self.window_engine.get_health()
        stability = self.window_engine.get_stability()
        momentum = self.get_momentum(top_rows)

        # ====================================================
        # LOCK / RELOCK LEADER WINDOW
        # ====================================================
        locked_window = self.ctx.locked_window
        locked_obj = None
        relock_needed = False
        lock_reason = "KEEP_LOCK"

        if locked_window is not None:
            locked_obj = self.window_engine.state.get(locked_window)

        keep_win_lock = (
            int(getattr(self.ctx, "keep_win_lock_until", 0) or 0) >= int(round_id)
            and locked_obj is not None
            and locked_obj.next_group is not None
        )

        if locked_obj is None:
            relock_needed = True
            lock_reason = "NO_LOCK"
        elif keep_win_lock:
            relock_needed = False
            lock_reason = "KEEP_AFTER_WIN_5R"
        elif (
            len(locked_obj.live_hit_history) > 0
            and int(locked_obj.live_loss_streak) >= LIVE_RELOCK_LOSS_STREAK
        ):
            relock_needed = True
            lock_reason = "REAL_2_LOSS_RELOCK"
        elif locked_obj.next_group is None:
            relock_needed = True
            lock_reason = "LOCK_NO_NEXT"
        else:
            real_stat = self.get_real_stats(locked_window)
            if (
                real_stat["trade_count"] >= REAL_MIN_TRADE_COUNT_FOR_LOCK
                and (
                    real_stat["profit"] < REAL_MIN_PROFIT_FOR_LOCK
                    or real_stat["loss_streak"] >= LIVE_RELOCK_LOSS_STREAK
                )
            ):
                relock_needed = True
                lock_reason = "LOCK_REAL_PERFORMANCE_BAD"

        # V52 cool current bad lock before selecting a new candidate.
        if relock_needed and locked_window is not None:
            self.cool_window(locked_window, lock_reason)

        if relock_needed:
            candidate_w, candidate_obj, candidate_reason = self.choose_relock_candidate(top_rows)

            if candidate_obj is not None:
                locked_window, locked_obj = candidate_w, candidate_obj
                self.ctx.locked_window = locked_window

                # Reset real trade stats for the newly locked window.
                self.ctx.locked_live_profit = 0.0
                self.ctx.locked_live_loss_streak = 0
                self.ctx.locked_live_win = 0
                self.ctx.locked_live_loss = 0

                lock_reason = f"{candidate_reason}_{lock_reason}"
            else:
                locked_window, locked_obj = None, None
                self.ctx.locked_window = None
                lock_reason = candidate_reason

        self.ctx.lock_reason = lock_reason

        next_group = locked_obj.next_group if locked_obj is not None else None
        top_profit20 = (
            locked_obj.live_profit20
            if locked_obj is not None and len(locked_obj.live_hit_history) > 0
            else (locked_obj.profit20 if locked_obj is not None else 0.0)
        )
        leader_window = locked_window
        leader_loss_streak = int(locked_obj.loss_streak) if locked_obj is not None else 0

        if locked_obj is not None and len(locked_obj.live_hit_history) > 0:
            leader_wr20 = locked_obj.live_wr20
        else:
            hits20 = list(locked_obj.hit_history)[-20:] if locked_obj is not None else []
            leader_wr20 = round(sum(hits20) / len(hits20), 3) if hits20 else 0.0

        real_locked_stat = self.get_real_stats(locked_window)

        # Dynamic READY rule.
        wr20 = TradeEngine(self.ctx).get_winrate(20)
        required_consensus = CONSENSUS_READY
        if wr20 > 0 and wr20 < LOW_WR_LEVEL:
            required_consensus = LOW_WR_CONSENSUS_READY

        if stability < STABILITY_READY:
            regime = "CHAOS"
        elif locked_obj is not None and locked_obj.profit20 > 0 and leader_wr20 >= 0.35:
            regime = "TREND"
        else:
            regime = "NORMAL"

        state = "WAIT"
        if round_id < LIVE_START_ROUND:
            state = "WAIT"
        elif locked_obj is None:
            state = "WAIT"
        elif next_group is None:
            state = "WAIT"
        elif len(locked_obj.live_hit_history) > 0 and locked_obj.live_profit20 <= LEADER_MIN_LIVE_PROFIT20:
            state = "WAIT"
        elif len(locked_obj.live_hit_history) > 0 and locked_obj.live_wr20 < LEADER_MIN_LIVE_WR20:
            state = "WAIT"
        elif locked_obj.profit20 <= LOCK_MIN_PROFIT20:
            state = "WAIT"
        elif leader_wr20 < FALLBACK_MIN_WR20:
            state = "WAIT"
        elif leader_loss_streak > LOCK_MAX_LOSS_STREAK:
            state = "WAIT"
        elif stability < STABILITY_READY:
            state = "WAIT"
        else:
            # Profit optimized:
            # If real performance of locked window is positive, allow READY even
            # when TopN consensus is not high. Consensus is only a market filter.
            real_ok = (
                real_locked_stat["trade_count"] >= 1
                and real_locked_stat["profit"] > 0
                and real_locked_stat["wr"] >= REAL_MIN_WR_FOR_LOCK
                and real_locked_stat["loss_streak"] <= REAL_MAX_LOSS_STREAK_FOR_LOCK
            )

            if real_ok or consensus >= required_consensus or leader_wr20 >= 0.50:
                state = "READY"

        signal = SignalRecord(
            state=state,
            next_group=next_group,
            regime=regime,
            top_n=TOPN,
            health20=health20,
            health50=health50,
            consensus=consensus,
            stability=stability,
            momentum=momentum,
            required_consensus=required_consensus,
            top_profit20=top_profit20,
            leader_window=leader_window,
            leader_wr20=leader_wr20,
            leader_loss_streak=leader_loss_streak,
            locked_window=self.ctx.locked_window,
            lock_reason=self.ctx.lock_reason,
            locked_live_profit=self.ctx.locked_live_profit,
            locked_live_loss_streak=self.ctx.locked_live_loss_streak,
            shadow_live_profit20=(locked_obj.live_profit20 if locked_obj is not None else 0.0),
            shadow_live_wr20=(locked_obj.live_wr20 if locked_obj is not None else 0.0),
            real_window_profit=real_locked_stat["profit"],
            real_window_wr=real_locked_stat["wr"],
            real_window_trade_count=real_locked_stat["trade_count"],
            real_window_loss_streak=real_locked_stat["loss_streak"],
        )

        if round_id != self.ctx.last_signal_round and next_group is not None:
            self.ctx.signal_history.append(next_group)
            self.ctx.signal_flip_history.append(next_group)
            self.ctx.last_signal_round = round_id

        return signal


# ============================================================
# TRADE ENGINE
# ============================================================

class TradeEngine:
    def __init__(self, ctx: EngineContext):
        self.ctx = ctx

    def update_equity(self, profit: float) -> None:
        equity = 0.0 if not self.ctx.equity_curve else self.ctx.equity_curve[-1]
        equity += profit
        self.ctx.equity_curve.append(round(equity, 2))

    def open_trade(self, signal: SignalRecord, round_id: int, confidence_score: float = 0.0) -> None:
        self.ctx.open_reason = ""

        if round_id < LIVE_START_ROUND:
            self.ctx.open_reason = "BEFORE_LIVE_START"
            return

        # Avoid over-trading: after a settled trade, wait TRADE_GAP_ROUNDS
        # before opening a new one.
        if (
            self.ctx.last_settle_round > 0
            and round_id - self.ctx.last_settle_round < TRADE_GAP_ROUNDS
        ):
            self.ctx.open_reason = "TRADE_GAP"
            return

        if signal.state != "READY":
            self.ctx.open_reason = "SIGNAL_WAIT"
            return
        if signal.next_group is None:
            self.ctx.open_reason = "NO_NEXT_GROUP"
            return
        if self.ctx.pending_trade is not None:
            self.ctx.open_reason = "HAS_PENDING"
            return
        if round_id == self.ctx.last_open_round:
            self.ctx.open_reason = "DUPLICATE_OPEN"
            return

        frozen_window = self.ctx.locked_window

        record = TradeRecord(
            round_id=round_id,
            predict=signal.next_group,
            locked_window=frozen_window,
            actual=None,
            hit=None,
            profit=0.0,
            status="PENDING",
            settle_round=None
        )

        self.ctx.trade_history.append(record)
        self.ctx.pending_index = len(self.ctx.trade_history) - 1
        self.ctx.pending_locked_window = frozen_window
        self.ctx.pending_target_round = round_id + 1
        self.ctx.pending_trade = signal.next_group
        self.ctx.pending_confidence = float(confidence_score)
        self.ctx.pending_round = round_id
        self.ctx.trade_state = "PENDING"
        self.ctx.last_open_round = round_id
        self.ctx.open_reason = "OPENED"

    def settle_trade(self, actual_group: int, current_round: int) -> bool:
        if self.ctx.pending_trade is None:
            return False
        target_round = int(getattr(self.ctx, "pending_target_round", 0) or (self.ctx.pending_round + 1))
        # Settle ONLY against the exact target round. Never settle an old
        # pending trade against a later round after downtime/multiple rows.
        if current_round != target_round:
            return False
        if current_round == self.ctx.last_settle_round:
            return False

        predict = self.ctx.pending_trade
        hit = int(predict == actual_group)
        profit = WIN_GROUP if hit else LOSS_GROUP

        if self.ctx.pending_index is not None and 0 <= self.ctx.pending_index < len(self.ctx.trade_history):
            record = self.ctx.trade_history[self.ctx.pending_index]
            if str(getattr(record, "status", "PENDING")) != "PENDING" or getattr(record, "hit", None) is not None:
                return False
            record.actual = actual_group
            record.hit = hit
            record.profit = profit
            record.status = "WIN" if hit else "LOSS"
            record.settle_round = current_round
        else:
            record = TradeRecord(
                round_id=self.ctx.pending_round,
                predict=predict,
                locked_window=self.ctx.pending_locked_window,
                actual=actual_group,
                hit=hit,
                profit=profit,
                status="WIN" if hit else "LOSS",
                settle_round=current_round
            )
            self.ctx.trade_history.append(record)

        self.update_equity(profit)

        # Trade-aware stats for currently locked window.
        # If locked window loses real trades, force relock on next signal.
        trade_window = record.locked_window

        if trade_window is not None:
            w = int(trade_window)
            if w not in self.ctx.window_real_stats:
                self.ctx.window_real_stats[w] = {
                    "trade_count": 0,
                    "profit": 0.0,
                    "win": 0,
                    "loss": 0,
                    "loss_streak": 0,
                }

            stat = self.ctx.window_real_stats[w]
            stat["trade_count"] += 1
            stat["profit"] = round(float(stat["profit"]) + profit, 2)

            if hit:
                stat["win"] += 1
                stat["loss_streak"] = 0
            else:
                stat["loss"] += 1
                stat["loss_streak"] += 1

        if record.locked_window == self.ctx.locked_window:
            self.ctx.locked_live_profit = round(self.ctx.locked_live_profit + profit, 2)

            if hit:
                self.ctx.locked_live_loss_streak = 0
                self.ctx.locked_live_win += 1
            else:
                self.ctx.locked_live_loss_streak += 1
                self.ctx.locked_live_loss += 1

        self.ctx.last_result_round = int(current_round)
        self.ctx.last_result_open_round = int(record.round_id)
        self.ctx.last_result_predict = int(record.predict)
        self.ctx.last_result_actual = int(record.actual)
        self.ctx.last_result_hit = int(record.hit)
        self.ctx.last_result_profit = float(record.profit)
        self.ctx.last_result_status = str(record.status)

        self.ctx.pending_trade = None
        self.ctx.pending_confidence = 0.0
        self.ctx.pending_round = 0
        self.ctx.pending_index = None
        self.ctx.pending_locked_window = None
        self.ctx.pending_confidence = 0.0
        self.ctx.pending_target_round = 0
        self.ctx.trade_state = "IDLE"
        self.ctx.last_settle_round = current_round

        # V67: a real WIN confirms the locked window. Keep that same window
        # for the next 5 decision rounds instead of allowing shadow statistics
        # to immediately trigger a relock. LOSS keeps the existing protection.
        if hit:
            self.ctx.keep_win_lock_until = int(current_round + KEEP_WIN_ROUNDS)
        else:
            self.ctx.keep_win_lock_until = 0

        # Keep real stats/equity aligned with trade_history as source of truth.
        rebuild_real_stats_from_history(self.ctx)
        refresh_ledger_checkpoint(self.ctx)

        # V52: cool losing trade window immediately to avoid repeated losses.
        if hit == 0 and record.locked_window is not None:
            try:
                w = int(record.locked_window)
            except Exception:
                w = record.locked_window
            ensure_ctx_fields(self.ctx)
            self.ctx.cooled_windows[w] = int(current_round + WINDOW_COOLDOWN_ROUNDS)

            # V62 audited rule:
            # A single REAL loss only cools the window; blacklist requires 2 consecutive REAL losses.
            # Blacklist is temporary and only for stronger losers.
            if not hasattr(self.ctx, "blacklisted_windows") or self.ctx.blacklisted_windows is None:
                self.ctx.blacklisted_windows = {}

            stat = get_history_real_stats(self.ctx, w)
            # Blacklist only after 2 consecutive losses for THIS traded window.
            if stat["loss_streak"] >= LIVE_RELOCK_LOSS_STREAK:
                self.ctx.blacklisted_windows[w] = int(current_round + BLACKLIST_DURATION_ROUNDS)

        # Settlement is a completed state transition. Return True so the live
        # transaction layer can persist the updated Trade History immediately.
        return True

    def get_total_profit(self) -> float:
        return round(
            sum(x.profit for x in self.ctx.trade_history if x.hit is not None),
            2
        )

    def get_profit(self, n: int) -> float:
        trades = [x for x in self.ctx.trade_history if x.hit is not None][-n:]
        return round(
            sum(x.profit for x in trades),
            2
        )

    def get_winrate(self, n: int = 20) -> float:
        trades = [x for x in self.ctx.trade_history if x.hit is not None][-n:]
        if not trades:
            return 0.0
        return round(
            sum(int(x.hit) for x in trades) / len(trades),
            3
        )

    def get_loss_streak(self) -> int:
        streak = 0
        for x in reversed(self.ctx.trade_history):
            if x.hit is None:
                continue
            if x.hit == 0:
                streak += 1
            else:
                break
        return streak

    def get_drawdown(self) -> float:
        if not self.ctx.equity_curve:
            return 0.0

        peak = 0.0
        drawdown = 0.0

        for equity in self.ctx.equity_curve:
            peak = max(peak, equity)
            drawdown = min(drawdown, equity - peak)

        return round(drawdown, 2)


    def get_daily_equity_current(self) -> float:
        if not self.ctx.equity_curve:
            return 0.0
        return round(float(self.ctx.equity_curve[-1]), 2)

    def get_daily_equity_peak(self) -> float:
        if not self.ctx.equity_curve:
            return 0.0
        return round(max([0.0] + [float(x) for x in self.ctx.equity_curve]), 2)

    def get_daily_pullback_from_peak(self) -> float:
        current = self.get_daily_equity_current()
        peak = self.get_daily_equity_peak()
        return round(current - peak, 2)

    def daily_stop_status(self) -> tuple[bool, str]:
        """Return whether new trades should be blocked for the current day.

        This guard is designed for a daily sheet reset workflow. It uses the
        current day's trade_history/equity_curve only. It does NOT block pending
        settlement; it only blocks opening the next trade.
        """
        total_profit = self.get_total_profit()
        loss_streak = self.get_loss_streak()
        drawdown = self.get_drawdown()
        pullback = self.get_daily_pullback_from_peak()

        if total_profit <= DAILY_STOP_LOSS:
            return True, "DAILY_STOP_LOSS"

        if loss_streak >= DAILY_MAX_LOSS_STREAK:
            return True, "DAILY_MAX_LOSS_STREAK"

        if drawdown <= DAILY_MAX_DRAWDOWN or pullback <= DAILY_MAX_DRAWDOWN:
            return True, "DAILY_MAX_DRAWDOWN"

        if total_profit >= DAILY_PROFIT_LOCK:
            return True, "DAILY_PROFIT_LOCK"

        return False, ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "trade_state": self.ctx.trade_state,
            "profit10": self.get_profit(10),
            "profit20": self.get_profit(20),
            "profit50": self.get_profit(50),
            "total_profit": self.get_total_profit(),
            "wr20": self.get_winrate(20),
            "drawdown": self.get_drawdown(),
            "pending_trade": self.ctx.pending_trade,
            "trade_count": len([x for x in self.ctx.trade_history if x.hit is not None]),
            "daily_stop_active": getattr(self.ctx, "daily_stop_active", False),
            "daily_stop_reason": getattr(self.ctx, "daily_stop_reason", ""),
        }


# ============================================================
# PROTECTION ENGINE
# ============================================================

class ProtectionEngine:
    def __init__(self, ctx: EngineContext, trade_engine: TradeEngine):
        self.ctx = ctx
        self.trade_engine = trade_engine

    def get_flip_rate(self) -> float:
        history = list(self.ctx.signal_flip_history)
        if len(history) < 2:
            return 0.0

        flips = sum(
            1
            for i in range(1, len(history))
            if history[i] != history[i - 1]
        )

        return round(flips / (len(history) - 1), 3)

    def profit_protection(self) -> bool:
        # Risk protection is a temporary pause, not a permanent hard stop.
        self.ctx.protection_reason = ""
        ensure_ctx_fields(self.ctx)

        trade_count = len([x for x in self.ctx.trade_history if x.hit is not None])
        if trade_count < MIN_TRADES_FOR_PROTECTION:
            return False

        reason = ""
        if self.trade_engine.get_profit(10) <= PROFIT10_STOP:
            reason = "PROFIT10_STOP"
        elif self.trade_engine.get_winrate(20) <= WR20_STOP:
            reason = "WR20_STOP"
        elif self.trade_engine.get_drawdown() <= DRAWDOWN_STOP:
            reason = "DRAWDOWN_STOP"
        elif self.get_flip_rate() >= FLIPRATE_STOP:
            reason = "FLIPRATE_STOP"

        if not reason:
            return False

        # Trigger risk pause only once for each new settled trade count.
        if self.ctx.last_risk_trigger_trade_count == trade_count:
            return self.ctx.risk_pause_counter > 0

        self.ctx.risk_pause_counter = max(int(self.ctx.risk_pause_counter), RISK_PAUSE_ROUNDS)
        self.ctx.last_risk_trigger_trade_count = trade_count
        self.ctx.protection_reason = reason
        return True

    def cooldown_engine(self) -> bool:
        loss_streak = self.trade_engine.get_loss_streak()

        # Nếu đã có WIN thì reset mốc cooldown.
        if loss_streak == 0:
            self.ctx.cooldown_loss_streak_marker = -1

        # Protection threshold is exactly 2 consecutive settled losses.
        # Trigger once per streak level so the pause does not retrigger every rerun.
        if (
            loss_streak >= 2
            and self.ctx.cooldown_counter == 0
            and self.ctx.cooldown_loss_streak_marker != loss_streak
        ):
            self.ctx.cooldown_counter = LIVE_LOSS_COOLDOWN_ROUNDS
            self.ctx.cooldown_loss_streak_marker = loss_streak

        if self.ctx.cooldown_counter > 0:
            self.ctx.cooldown_counter -= 1
            return True

        return False

    def safe_mode_engine(self) -> bool:
        """Pause trading when equity pulls back from a fresh peak; do not re-trigger on same peak."""
        ensure_ctx_fields(self.ctx)
        equity = list(self.ctx.equity_curve)
        if len(equity) < 3:
            return False

        current = equity[-1]
        self.ctx.peak_equity = max(float(getattr(self.ctx, "peak_equity", 0.0)), current, 0.0)
        pullback = round(current - self.ctx.peak_equity, 2)

        if (
            pullback <= SAFE_DRAWDOWN_FROM_PEAK
            and self.ctx.safe_mode_counter == 0
            and self.ctx.last_safe_trigger_peak < self.ctx.peak_equity
        ):
            self.ctx.safe_mode_counter = SAFE_MODE_ROUNDS
            self.ctx.last_safe_trigger_peak = self.ctx.peak_equity

        if self.ctx.safe_mode_counter > 0:
            self.ctx.safe_mode_counter -= 1
            return True

        return False

    def adaptive_ready_wait(self, signal: SignalRecord, confidence_score: float) -> str:
        self.ctx.protection_reason = ""

        if signal.state != "READY":
            self.ctx.protection_reason = "SIGNAL_NOT_READY"
            return "WAIT"

        ensure_ctx_fields(self.ctx)
        daily_stop, daily_reason = self.trade_engine.daily_stop_status()
        if daily_stop:
            self.ctx.daily_stop_active = True
            self.ctx.daily_stop_reason = daily_reason
            self.ctx.protection_reason = daily_reason
            return "WAIT"
        self.ctx.daily_stop_active = False
        self.ctx.daily_stop_reason = ""

        if self.ctx.risk_pause_counter > 0:
            self.ctx.risk_pause_counter -= 1
            self.ctx.protection_reason = "RISK_PAUSE"
            return "WAIT"

        if self.profit_protection():
            return "WAIT"

        if self.cooldown_engine():
            self.ctx.protection_reason = "COOLDOWN"
            return "WAIT"

        if self.safe_mode_engine():
            self.ctx.protection_reason = "SAFE_MODE_DRAWDOWN"
            return "WAIT"

        if confidence_score < MIN_CONFIDENCE_READY:
            self.ctx.protection_reason = "LOW_CONFIDENCE"
            return "WAIT"

        self.ctx.protection_reason = "ALLOW"
        return "READY"


# ============================================================
# DASHBOARD
# ============================================================

class Dashboard:
    def __init__(
        self,
        ctx: EngineContext,
        window_engine: WindowEngine,
        signal_engine: SignalEngine,
        trade_engine: TradeEngine,
        protection_engine: ProtectionEngine
    ):
        self.ctx = ctx
        self.window_engine = window_engine
        self.signal_engine = signal_engine
        self.trade_engine = trade_engine
        self.protection_engine = protection_engine

    def render_header(self) -> None:
        st.title("🚀 V69.4 V3.4.12 LIVE ROUND AUDIT — BUILD 2026-10-02")
        st.caption("BUILD CHECK: V3.4.11 | STATE RESET BOUNDARY: 3.4.11 | LIVE INPUT: GOOGLE SHEET COLUMN B")

    def render_signal(self, signal: SignalRecord, confidence_score: float) -> None:
        color = "#00aa00" if signal.state == "READY" else "#555555"

        current_round = self.ctx.last_length
        target_round = current_round + 1

        # UI-only time labels. These values never enter the trading engine.
        current_time, target_time = get_current_target_time_display_only(current_round)

        title = "CURRENT SIGNAL" if signal.state == "READY" else "NO TRADE"
        action = (
            f"BET GROUP = {signal.next_group}"
            if signal.state == "READY" and signal.next_group is not None
            else f"NEXT GROUP = {signal.next_group}"
        )

        st.markdown(
            f"""
<div style="
background:{color};
padding:20px;
border-radius:15px;
text-align:center;
color:white;
font-size:28px;
font-weight:bold;
">
{title}<br>
STATE = {signal.state}<br>
CURRENT ROUND = {current_round} → TARGET ROUND = {target_round}<br>
CURRENT TIME = {current_time} → TARGET TIME = {target_time}<br>
{action}<br>
CONF = {confidence_score:.2f}
</div>
""",
            unsafe_allow_html=True
        )

    def render_market(self, signal: SignalRecord) -> None:
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12 = st.columns(12)
        c1.metric("Regime", signal.regime)
        c2.metric("Locked W", signal.locked_window)
        c3.metric("Lock Reason", signal.lock_reason)
        c4.metric("Real W Profit", round(signal.real_window_profit, 2))
        c5.metric("Real W WR", round(signal.real_window_wr, 3))
        c6.metric("Real W Trades", signal.real_window_trade_count)
        c7.metric("Real W LS", signal.real_window_loss_streak)
        c8.metric("Shadow P20", round(signal.shadow_live_profit20, 2))
        c9.metric("Shadow WR20", round(signal.shadow_live_wr20, 3))
        c10.metric("Consensus", round(signal.consensus, 3))
        c11.metric("Req Cons", round(signal.required_consensus, 3))
        c12.metric("Stability", round(signal.stability, 3))

    def render_profit(self) -> None:
        snap = self.trade_engine.snapshot()

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Total Profit", snap["total_profit"])
        c2.metric("Profit20", snap["profit20"])
        c3.metric("WR20", snap["wr20"])
        c4.metric("Drawdown", snap["drawdown"])
        c5.metric("Daily Stop", "ON" if snap.get("daily_stop_active") else "OFF")
        c6.metric("Stop Reason", snap.get("daily_stop_reason", ""))

    def render_risk(self) -> None:
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
        c1.metric("FlipRate", self.protection_engine.get_flip_rate())
        c2.metric("LossStreak", self.trade_engine.get_loss_streak())
        c3.metric("Cooldown", self.ctx.cooldown_counter)
        c4.metric("SafeMode", getattr(self.ctx, "safe_mode_counter", 0))
        c5.metric("RiskPause", getattr(self.ctx, "risk_pause_counter", 0))
        c6.metric("Live From", LIVE_START_ROUND)
        c7.metric("Wait Reason", self.ctx.protection_reason)
        c8.metric("Open Reason", self.ctx.open_reason)

    def render_last_result(self) -> None:
        st.subheader("Last Result")

        settled = [
            x
            for x in self.ctx.trade_history
            if x.hit is not None
        ]

        if not settled:
            st.info("No settled trade yet.")
            return

        last = settled[-1]

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Open Round", last.round_id)
        c2.metric("Settle Round", last.settle_round)
        c3.metric("Predict", last.predict)
        c4.metric("Actual", last.actual)
        c5.metric("Result", last.status)
        c6.metric("Profit", last.profit)

    def render_current_trade(self) -> None:
        st.subheader("Current Trade")

        if self.ctx.pending_trade is None:
            st.info("No pending trade. Follow the main signal panel.")
            return

        target_round = self.ctx.pending_round + 1

        display_pending_window = self.ctx.pending_locked_window
        if display_pending_window is None and self.ctx.pending_index is not None:
            try:
                display_pending_window = self.ctx.trade_history[self.ctx.pending_index].locked_window
            except Exception:
                display_pending_window = self.ctx.locked_window

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Open Round", self.ctx.pending_round)
        c2.metric("Target Round", target_round)
        c3.metric("Locked Window", display_pending_window)
        c4.metric("Bet Group", self.ctx.pending_trade)
        c5.metric("Open CONF", round(float(getattr(self.ctx, "pending_confidence", 0.0)), 3))
        c6.metric("Status", "WAIT RESULT")

        st.caption(
            f"This pending trade was opened after round {self.ctx.pending_round}. "
            f"It will be settled when round {target_round} appears."
        )

    def render_profit_config(self) -> None:
        with st.expander("Profit Optimized Config"):
            st.json(
                {
                    "CONSENSUS_READY": CONSENSUS_READY,
                    "LOW_WR_CONSENSUS_READY": LOW_WR_CONSENSUS_READY,
                    "TRADE_GAP_ROUNDS": TRADE_GAP_ROUNDS,
                    "REAL_MIN_WR_FOR_LOCK": REAL_MIN_WR_FOR_LOCK,
                    "REAL_MAX_LOSS_STREAK_FOR_LOCK": REAL_MAX_LOSS_STREAK_FOR_LOCK,
                    "FALLBACK_MIN_WR20": FALLBACK_MIN_WR20,
                    "FALLBACK_MAX_LOSS_STREAK": FALLBACK_MAX_LOSS_STREAK,
                    "LIVE_RELOCK_LOSS_STREAK": LIVE_RELOCK_LOSS_STREAK,
                    "LOCK_MAX_LOSS_STREAK": LOCK_MAX_LOSS_STREAK,
                    "LEADER_MIN_LIVE_WR20": LEADER_MIN_LIVE_WR20,
                    "WINDOW_COOLDOWN_ROUNDS": WINDOW_COOLDOWN_ROUNDS,
                    "BLACKLIST_REAL_NEGATIVE": BLACKLIST_REAL_NEGATIVE,
                    "TOPN": TOPN,
                    "MIN_CONFIDENCE_READY": MIN_CONFIDENCE_READY,
                    "BLACKLIST_DURATION_ROUNDS": BLACKLIST_DURATION_ROUNDS,
                    "WINDOW_SELECTION_MODE": WINDOW_SELECTION_MODE,
                    "REAL_SHADOW_BLEND_MIN_TRADES": REAL_SHADOW_BLEND_MIN_TRADES,
                    "SAFE_DRAWDOWN_FROM_PEAK": SAFE_DRAWDOWN_FROM_PEAK,
                    "SAFE_MODE_ROUNDS": SAFE_MODE_ROUNDS,
                    "RISK_PAUSE_ROUNDS": RISK_PAUSE_ROUNDS,
                    "BLACKLIST_DURATION_ROUNDS": BLACKLIST_DURATION_ROUNDS,
                    "WINDOW_SELECTION_MODE": WINDOW_SELECTION_MODE,
                    "UCB_EXPLORATION_C": UCB_EXPLORATION_C,
                    "MIN_TRADES_FOR_PROTECTION": MIN_TRADES_FOR_PROTECTION,
                    "COHERENCE_MIN_LIVE_SAMPLES": COHERENCE_MIN_LIVE_SAMPLES,
                    "COHERENCE_DEFENSIVE_LIVE_SAMPLES": COHERENCE_DEFENSIVE_LIVE_SAMPLES,
                    "COHERENCE_DEFENSIVE_HEALTH20_MAX": COHERENCE_DEFENSIVE_HEALTH20_MAX,
                    "COHERENCE_DEFENSIVE_STABILITY_MIN": COHERENCE_DEFENSIVE_STABILITY_MIN,
                    "DAILY_STOP_LOSS": DAILY_STOP_LOSS,
                    "DAILY_MAX_LOSS_STREAK": DAILY_MAX_LOSS_STREAK,
                    "DAILY_MAX_DRAWDOWN": DAILY_MAX_DRAWDOWN,
                    "DAILY_PROFIT_LOCK": DAILY_PROFIT_LOCK,
                }
            )

    def render_top_windows(self) -> None:
        rows = self.window_engine.get_top_windows(TOPN)
        data = []

        for rank, (w, obj) in enumerate(rows, start=1):
            hits = list(obj.hit_history)
            hit20 = hits[-20:]
            hit50 = hits[-50:]

            wr20 = round(sum(hit20) / len(hit20), 3) if hit20 else 0.0
            wr50 = round(sum(hit50) / len(hit50), 3) if hit50 else 0.0

            data.append(
                {
                    "Rank": rank,
                    "Window": int(w),
                    "Score": round(float(obj.score), 2),
                    "Profit20": round(float(obj.profit20), 2),
                    "Profit50": round(float(obj.profit50), 2),
                    "WR20": wr20,
                    "WR50": wr50,
                    "LiveScore": round(float(obj.live_score), 2),
                    "LiveP20": round(float(obj.live_profit20), 2),
                    "LiveP50": round(float(obj.live_profit50), 2),
                    "LiveWR20": round(float(obj.live_wr20), 3),
                    "LiveLS": int(obj.live_loss_streak),
                    "CandidateScore": self.signal_engine.candidate_score(obj),
                    "RealScore": self.signal_engine.real_candidate_score(w, obj),
                    "RealProfit": self.signal_engine.get_real_stats(w)["profit"],
                    "RealWR": self.signal_engine.get_real_stats(w)["wr"],
                    "RealTrades": self.signal_engine.get_real_stats(w)["trade_count"],
                    "RealLS": self.signal_engine.get_real_stats(w)["loss_streak"],
                    "LossStreak": int(obj.loss_streak),
                    "Next": obj.next_group,
                    "HitLen": len(obj.hit_history),
                    "GroupLen": len(obj.group_history),
                    "Cooled": self.signal_engine.is_window_cooled(w),
                    "Blacklisted": self.signal_engine.is_window_blacklisted(w),
                    "UCBScore": self.signal_engine.ucb_candidate_score(w, obj),
                    "Filtered": int(obj.loss_streak) > MAX_WINDOW_LOSS_STREAK_FOR_TOP,
                    "Locked": int(w) == self.ctx.locked_window,
                }
            )

        st.subheader("Top Windows")
        df = pd.DataFrame(data)
        if not df.empty:
            df = df[
                [
                    "Rank",
                    "Window",
                    "Score",
                    "Profit20",
                    "Profit50",
                    "WR20",
                    "WR50",
                    "LiveScore",
                    "LiveP20",
                    "LiveP50",
                    "LiveWR20",
                    "LiveLS",
                    "CandidateScore",
                    "RealScore",
                    "RealProfit",
                    "RealWR",
                    "RealTrades",
                    "RealLS",
                    "LossStreak",
                    "Next",
                    "HitLen",
                    "GroupLen",
                    "Cooled",
                    "Blacklisted",
                    "UCBScore",
                    "Filtered",
                    "Locked",
                ]
            ]
        st.dataframe(df, use_container_width=True, hide_index=True)

    def render_state_debug(self) -> None:
        with st.expander("State Debug"):
            st.json(
                {
                    "last_length": self.ctx.last_length,
                    "data_length": getattr(self.ctx, "data_length", 0),
                    "data_signature_short": str(getattr(self.ctx, "data_signature", ""))[:12],
                    "pending_trade": self.ctx.pending_trade,
                    "pending_round": self.ctx.pending_round,
                    "pending_locked_window": self.ctx.pending_locked_window,
                    "current_locked_window": self.ctx.locked_window,
                    "last_open_round": self.ctx.last_open_round,
                    "last_settle_round": self.ctx.last_settle_round,
                    "trade_state": self.ctx.trade_state,
                    "trade_count": len([x for x in self.ctx.trade_history if x.hit is not None]),
                    "real_stats_keys": list(self.ctx.window_real_stats.keys()),
                    "cooled_windows": getattr(self.ctx, "cooled_windows", {}),
                    "safe_mode_counter": getattr(self.ctx, "safe_mode_counter", 0),
                    "state_version": getattr(self.ctx, "state_version", ""),
                    "risk_pause_counter": getattr(self.ctx, "risk_pause_counter", 0),
                    "peak_equity": getattr(self.ctx, "peak_equity", 0.0),
                    "last_safe_trigger_peak": getattr(self.ctx, "last_safe_trigger_peak", 0.0),
                    "blacklisted_windows": getattr(self.ctx, "blacklisted_windows", {}),
                    "last_decision_confidence": getattr(self.ctx, "last_decision_confidence", 0.0),
                    "daily_stop_active": getattr(self.ctx, "daily_stop_active", False),
                    "daily_stop_reason": getattr(self.ctx, "daily_stop_reason", ""),
                }
            )

    def render_real_stats_summary(self) -> None:
        with st.expander("Real Stats Summary - Source of Truth"):
            rows = []
            for w, stat in sorted(self.ctx.window_real_stats.items(), key=lambda x: int(x[0])):
                trades = int(stat.get("trade_count", 0))
                win = int(stat.get("win", 0))
                rows.append(
                    {
                        "Window": int(w),
                        "RealTrades": trades,
                        "RealProfit": round(float(stat.get("profit", 0.0)), 2),
                        "RealWR": round(win / trades, 3) if trades else 0.0,
                        "RealLS": int(stat.get("loss_streak", 0)),
                        "Win": win,
                        "Loss": int(stat.get("loss", 0)),
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    def render_trade_history(self) -> None:
        st.subheader("Trade History")

        if getattr(self.ctx, "last_result_round", -1) >= 0:
            st.caption(
                f"LAST SETTLED | round={self.ctx.last_result_round} | "
                f"open={self.ctx.last_result_open_round} | "
                f"predict={self.ctx.last_result_predict} -> actual={self.ctx.last_result_actual} | "
                f"{self.ctx.last_result_status} | profit={self.ctx.last_result_profit:+.1f}"
            )

        refresh_ledger_checkpoint(self.ctx)
        integrity = ledger_integrity_report(self.ctx)
        audit_integrity = round_audit_integrity_report(self.ctx)
        st.caption(
            f"LEDGER | trades={integrity['trade_count']} | settled={integrity['settled_count']} | "
            f"pending={integrity['pending_count']} | profit={integrity['profit']:+.1f} | "
            f"frontier={self.ctx.last_length} | revision={getattr(self.ctx, 'state_revision', 0)}"
        )
        if not integrity["ok"]:
            st.error("LEDGER INTEGRITY: " + ", ".join(integrity["errors"]))

        if not self.ctx.trade_history:
            st.info("No trades")
            return

        df = pd.DataFrame(
            [
                {
                    "open_round": x.round_id,
                    "settle_round": x.settle_round,
                    "locked_window": x.locked_window,
                    "predict": x.predict,
                    "actual": x.actual,
                    "hit": x.hit,
                    "profit": x.profit,
                    "status": x.status,
                    "settled": bool(x.hit is not None and x.settle_round is not None),
                }
                for x in self.ctx.trade_history
            ]
        )

        st.dataframe(df.tail(50), use_container_width=True)

        with st.expander("Round Audit Log - every processed round"):
            audit_rows = list(getattr(self.ctx, "round_log", []) or [])
            if audit_rows:
                st.dataframe(pd.DataFrame(audit_rows[-100:]), use_container_width=True, hide_index=True)
                audit_check = round_audit_integrity_report(self.ctx)
                if not audit_check["ok"]:
                    st.error("ROUND AUDIT INTEGRITY: " + "; ".join(audit_check["errors"]))
            else:
                st.info("No round audit yet")

    def render_equity(self) -> None:
        st.subheader("Equity Curve")

        if not self.ctx.equity_curve:
            return

        df = pd.DataFrame({"equity": self.ctx.equity_curve})
        st.line_chart(df)

    def render_window_debug(self) -> None:
        with st.expander("Window Debug - All Windows"):
            rows = []
            for w, obj in self.window_engine.state.items():
                hits = list(obj.hit_history)
                hit20 = hits[-20:]
                hit50 = hits[-50:]
                rows.append(
                    {
                        "Window": int(w),
                        "Score": round(float(obj.score), 2),
                        "Profit20": round(float(obj.profit20), 2),
                        "Profit50": round(float(obj.profit50), 2),
                        "WR20": round(sum(hit20) / len(hit20), 3) if hit20 else 0.0,
                        "WR50": round(sum(hit50) / len(hit50), 3) if hit50 else 0.0,
                        "LiveScore": round(float(obj.live_score), 2),
                        "LiveP20": round(float(obj.live_profit20), 2),
                        "LiveWR20": round(float(obj.live_wr20), 3),
                        "LiveLS": int(obj.live_loss_streak),
                        "CandidateScore": self.signal_engine.candidate_score(obj),
                        "RealScore": self.signal_engine.real_candidate_score(w, obj),
                        "RealProfit": self.signal_engine.get_real_stats(w)["profit"],
                        "RealWR": self.signal_engine.get_real_stats(w)["wr"],
                        "RealTrades": self.signal_engine.get_real_stats(w)["trade_count"],
                        "RealLS": self.signal_engine.get_real_stats(w)["loss_streak"],
                        "LossStreak": int(obj.loss_streak),
                        "Next": obj.next_group,
                        "Cooled": self.signal_engine.is_window_cooled(w),
                        "Blacklisted": self.signal_engine.is_window_blacklisted(w),
                        "UCBScore": self.signal_engine.ucb_candidate_score(w, obj),
                        "UseInTop": int(obj.live_loss_streak) <= MAX_WINDOW_LOSS_STREAK_FOR_TOP,
                    }
                )

            df = pd.DataFrame(rows).sort_values(
                ["UseInTop", "Score"],
                ascending=[False, False]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

    def render_debug(self, signal: SignalRecord, confidence_score: float) -> None:
        with st.expander("Debug"):
            st.json(
                {
                    "trade_count": len(self.ctx.trade_history),
                    "trade_state": self.ctx.trade_state,
                    "pending_trade": self.ctx.pending_trade,
                    "equity": self.trade_engine.get_total_profit(),
                    "flip_rate": self.protection_engine.get_flip_rate(),
                    "confidence": confidence_score,
                    "signal_state": signal.state,
                    "protection_reason": self.ctx.protection_reason,
                }
            )




# ============================================================
# PERSISTENT STATE HELPERS
# ============================================================


def get_state_backend_config() -> dict:
    try:
        cfg = dict(st.secrets.get("v50_state", {}))
    except Exception:
        cfg = {}

    backend = str(cfg.get("backend", "local")).lower().strip()
    sheet_id = str(cfg.get("sheet_id", "")).strip()
    worksheet = str(cfg.get("worksheet", STATE_WORKSHEET_DEFAULT)).strip()

    return {
        "backend": backend,
        "sheet_id": sheet_id,
        "worksheet": worksheet,
    }


def get_gsheet_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except Exception:
        return None

    try:
        sa_info = dict(st.secrets["gcp_service_account"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = Credentials.from_service_account_info(
            sa_info,
            scopes=scopes,
        )
        return gspread.authorize(credentials)
    except Exception as e:
        st.warning(f"Google state auth error, fallback local: {e}")
        return None


def load_state_from_gsheet() -> dict | None:
    cfg = get_state_backend_config()

    if cfg["backend"] != "gsheet" or not cfg["sheet_id"]:
        return None

    client = get_gsheet_client()
    if client is None:
        return None

    try:
        sh = client.open_by_key(cfg["sheet_id"])
        try:
            ws = sh.worksheet(cfg["worksheet"])
        except Exception:
            ws = sh.add_worksheet(
                title=cfg["worksheet"],
                rows=10,
                cols=2,
            )
            ws.update("A1", [["{}"]])

        raw = ws.acell("A1").value
        if not raw:
            return {}

        return json.loads(raw)
    except Exception as e:
        # Google State is authoritative when configured. A remote read failure
        # MUST NOT be represented as an empty state: empty state would look like
        # a fresh engine and could replay the current day, duplicating trades.
        # Return an explicit sentinel so load_live_state() can stop safely.
        return {"__STATE_LOAD_ERROR__": str(e)}


def serialize_live_state(ctx: EngineContext) -> dict:
    """Serialize EngineContext into the single persistent V3 state payload."""
    return {
        "trade_history": [trade_record_to_dict(x) for x in ctx.trade_history],
        "equity_curve": list(ctx.equity_curve),
        "signal_history": list(ctx.signal_history),
        "signal_flip_history": list(ctx.signal_flip_history),
        "leader_history": list(ctx.leader_history),
        "pending_trade": ctx.pending_trade,
        "pending_round": ctx.pending_round,
        "pending_index": ctx.pending_index,
        "pending_locked_window": ctx.pending_locked_window,
        "pending_confidence": ctx.pending_confidence,
        "pending_target_round": ctx.pending_target_round,
        "trade_state": ctx.trade_state,
        "last_result_round": getattr(ctx, "last_result_round", -1),
        "last_result_open_round": getattr(ctx, "last_result_open_round", -1),
        "last_result_predict": getattr(ctx, "last_result_predict", None),
        "last_result_actual": getattr(ctx, "last_result_actual", None),
        "last_result_hit": getattr(ctx, "last_result_hit", None),
        "last_result_profit": getattr(ctx, "last_result_profit", 0.0),
        "last_result_status": getattr(ctx, "last_result_status", ""),
        "last_length": ctx.last_length,
        "last_open_round": ctx.last_open_round,
        "last_settle_round": ctx.last_settle_round,
        "last_window_round": ctx.last_window_round,
        "last_signal_round": ctx.last_signal_round,
        "cooldown_counter": ctx.cooldown_counter,
        "cooldown_loss_streak_marker": ctx.cooldown_loss_streak_marker,
        "safe_mode_counter": ctx.safe_mode_counter,
        "peak_equity": ctx.peak_equity,
        "last_safe_trigger_peak": ctx.last_safe_trigger_peak,
        "risk_pause_counter": ctx.risk_pause_counter,
        "last_risk_trigger_trade_count": ctx.last_risk_trigger_trade_count,
        "last_decision_confidence": ctx.last_decision_confidence,
        "last_decision_round": getattr(ctx, "last_decision_round", -1),
        "last_decision_state": getattr(ctx, "last_decision_state", "WAIT"),
        "last_decision_next_group": getattr(ctx, "last_decision_next_group", None),
        "daily_stop_active": ctx.daily_stop_active,
        "daily_stop_reason": ctx.daily_stop_reason,
        "keep_win_lock_until": ctx.keep_win_lock_until,
        "dataset_anchor_signature": ctx.dataset_anchor_signature,
        "live_day_id": ctx.live_day_id,
        "live_day_seq": int(getattr(ctx, "live_day_seq", 0) or 0),
        "live_day_date": str(getattr(ctx, "live_day_date", "") or ""),
        "daily_profit_history": list(getattr(ctx, "daily_profit_history", [])),
        "round_log": list(getattr(ctx, "round_log", []))[-300:],
        "round_txn_round": int(getattr(ctx, "round_txn_round", -1)),
        "round_txn_phase": str(getattr(ctx, "round_txn_phase", "IDLE")),
        "round_txn_opened": bool(getattr(ctx, "round_txn_opened", False)),
        "round_txn_settled": bool(getattr(ctx, "round_txn_settled", False)),
        "round_txn_signal": dict(getattr(ctx, "round_txn_signal", {}) or {}),
        "state_revision": int(getattr(ctx, "state_revision", 0)),
        "ledger_trade_count": int(getattr(ctx, "ledger_trade_count", 0)),
        "ledger_settled_count": int(getattr(ctx, "ledger_settled_count", 0)),
        "ledger_profit": float(getattr(ctx, "ledger_profit", 0.0)),
        "ledger_checksum": str(getattr(ctx, "ledger_checksum", "")),
        "ledger_frontier_round": int(getattr(ctx, "ledger_frontier_round", 0)),
        "protection_reason": ctx.protection_reason,
        "open_reason": ctx.open_reason,
        "locked_window": ctx.locked_window,
        "lock_reason": ctx.lock_reason,
        "locked_live_profit": ctx.locked_live_profit,
        "locked_live_loss_streak": ctx.locked_live_loss_streak,
        "locked_live_win": ctx.locked_live_win,
        "locked_live_loss": ctx.locked_live_loss,
        "window_real_stats": {str(k): v for k, v in ctx.window_real_stats.items()},
        "cooled_windows": {str(k): int(v) for k, v in ctx.cooled_windows.items()},
        "blacklisted_windows": {str(k): int(v) for k, v in getattr(ctx, "blacklisted_windows", {}).items()},
        "state_version": getattr(ctx, "state_version", STATE_VERSION),
        "hybrid_initialized": getattr(ctx, "hybrid_initialized", False),
        "data_signature": getattr(ctx, "data_signature", ""),
        "data_length": getattr(ctx, "data_length", 0),
    }


def save_state_to_gsheet(data: dict) -> bool:
    cfg = get_state_backend_config()

    if cfg["backend"] != "gsheet" or not cfg["sheet_id"]:
        return False

    client = get_gsheet_client()
    if client is None:
        return False

    payload = json.dumps(data, ensure_ascii=False)
    try:
        sh = client.open_by_key(cfg["sheet_id"])
        try:
            ws = sh.worksheet(cfg["worksheet"])
        except Exception:
            ws = sh.add_worksheet(
                title=cfg["worksheet"],
                rows=10,
                cols=2,
            )

        # Full-state replacement is idempotent: retrying the same revision is safe.
        ws.update("A1", [[payload]])
        ws.update("B1", [[time.strftime("%Y-%m-%d %H:%M:%S")]])

        # Critical: an update timeout is ambiguous. Read the cell back and require
        # an exact payload match before acknowledging the save to the engine.
        verify = ws.acell("A1").value
        if verify != payload:
            st.warning("Google State write verification failed: payload mismatch")
            return False
        return True
    except Exception as e:
        st.warning(f"Save Google state error: {e}")
        return False



def delete_state_from_gsheet() -> bool:
    cfg = get_state_backend_config()

    if cfg["backend"] != "gsheet" or not cfg["sheet_id"]:
        return False

    client = get_gsheet_client()
    if client is None:
        return False

    try:
        sh = client.open_by_key(cfg["sheet_id"])
        try:
            ws = sh.worksheet(cfg["worksheet"])
        except Exception:
            return False

        ws.update("A1", [["{}"]])
        ws.update("B1", [[time.strftime("%Y-%m-%d %H:%M:%S")]])
        return True
    except Exception as e:
        st.warning(f"Delete Google state error: {e}")
        return False


def trade_record_to_dict(x: TradeRecord) -> dict:
    open_round = getattr(x, "round_id", getattr(x, "open_round", 0))
    return {
        "round_id": open_round,
        "open_round": open_round,
        "predict": x.predict,
        "locked_window": getattr(x, "locked_window", None),
        "actual": x.actual,
        "hit": x.hit,
        "profit": x.profit,
        "status": x.status,
        "settle_round": x.settle_round,
    }


def trade_record_from_dict(d: dict) -> TradeRecord:
    round_id = d.get("round_id", d.get("open_round", 0))
    return TradeRecord(
        round_id=int(round_id or 0),
        predict=int(d.get("predict")) if d.get("predict") is not None else 0,
        locked_window=d.get("locked_window"),
        actual=d.get("actual"),
        hit=d.get("hit"),
        profit=float(d.get("profit", 0.0)),
        status=d.get("status", "PENDING"),
        settle_round=d.get("settle_round"),
    )


def _ledger_checksum(ctx: EngineContext) -> str:
    """Stable checksum of the persisted trade ledger, including PENDING."""
    rows = []
    for rec in list(getattr(ctx, "trade_history", []) or []):
        rows.append({
            "open_round": int(getattr(rec, "round_id", 0) or 0),
            "settle_round": int(getattr(rec, "settle_round", 0) or 0),
            "window": getattr(rec, "locked_window", None),
            "predict": getattr(rec, "predict", None),
            "actual": getattr(rec, "actual", None),
            "hit": getattr(rec, "hit", None),
            "profit": round(float(getattr(rec, "profit", 0.0) or 0.0), 2),
            "status": str(getattr(rec, "status", "")),
        })
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh_ledger_checkpoint(ctx: EngineContext) -> None:
    """Recompute all derived Profit/ledger metadata from trade_history."""
    ensure_ctx_fields(ctx)
    settled = [x for x in ctx.trade_history if getattr(x, "hit", None) is not None]
    ctx.ledger_trade_count = len(ctx.trade_history)
    ctx.ledger_settled_count = len(settled)
    ctx.ledger_profit = round(sum(float(x.profit) for x in settled), 2)
    ctx.ledger_checksum = _ledger_checksum(ctx)
    ctx.ledger_frontier_round = int(getattr(ctx, "last_length", 0) or 0)


def ledger_integrity_report(ctx: EngineContext) -> dict:
    """Validate ledger/state consistency without changing trading decisions."""
    ensure_ctx_fields(ctx)
    history = list(getattr(ctx, "trade_history", []) or [])
    settled = [x for x in history if getattr(x, "hit", None) is not None]
    pending = [x for x in history if getattr(x, "hit", None) is None]
    errors = []
    keys = set()
    for rec in history:
        key = (int(getattr(rec, "round_id", 0) or 0), int(getattr(rec, "settle_round", 0) or 0), str(getattr(rec, "status", "")))
        if key in keys:
            errors.append("DUPLICATE_LEDGER_RECORD")
        keys.add(key)
        if getattr(rec, "hit", None) is not None:
            if getattr(rec, "settle_round", None) is None:
                errors.append("SETTLED_WITHOUT_SETTLE_ROUND")
            if str(getattr(rec, "status", "")) not in {"WIN", "LOSS"}:
                errors.append("SETTLED_BAD_STATUS")
            expected = WIN_GROUP if int(rec.hit) == 1 else LOSS_GROUP
            if round(float(rec.profit), 2) != round(float(expected), 2):
                errors.append("PROFIT_NOT_MATCHING_HIT")
    expected_profit = round(sum(float(x.profit) for x in settled), 2)
    if round(float(getattr(ctx, "ledger_profit", 0.0)), 2) != expected_profit:
        errors.append("LEDGER_PROFIT_STALE")
    if int(getattr(ctx, "ledger_settled_count", 0)) != len(settled):
        errors.append("LEDGER_COUNT_STALE")
    if int(getattr(ctx, "ledger_trade_count", 0)) != len(history):
        errors.append("LEDGER_TRADE_COUNT_STALE")
    if ctx.equity_curve:
        if round(float(ctx.equity_curve[-1]), 2) != expected_profit:
            errors.append("EQUITY_STALE")
    elif settled:
        errors.append("EQUITY_MISSING")
    checksum = _ledger_checksum(ctx)
    if getattr(ctx, "ledger_checksum", "") and ctx.ledger_checksum != checksum:
        errors.append("LEDGER_CHECKSUM_MISMATCH")
    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "trade_count": len(history),
        "settled_count": len(settled),
        "pending_count": len(pending),
        "profit": expected_profit,
        "last_settle_round": max([int(getattr(x, "settle_round", 0) or 0) for x in settled] + [-1]),
    }


def rebuild_real_stats_from_history(ctx: EngineContext) -> None:
    """Rebuild real performance from settled trade_history.

    This is critical because JSON/Google Sheet state may be stale or may
    have string keys. Trade history is the source of truth.
    """
    stats = {}
    equity = []
    total = 0.0

    for rec in ctx.trade_history:
        if rec.hit is None:
            continue

        profit = float(rec.profit)
        total = round(total + profit, 2)
        equity.append(total)

        w = rec.locked_window
        if w is None:
            continue

        try:
            w = int(w)
        except Exception:
            pass

        if w not in stats:
            stats[w] = {
                "trade_count": 0,
                "profit": 0.0,
                "win": 0,
                "loss": 0,
                "loss_streak": 0,
            }

        stt = stats[w]
        stt["trade_count"] += 1
        stt["profit"] = round(float(stt["profit"]) + profit, 2)

        if int(rec.hit) == 1:
            stt["win"] += 1
            stt["loss_streak"] = 0
        else:
            stt["loss"] += 1
            stt["loss_streak"] += 1

    ctx.window_real_stats = stats
    ctx.equity_curve = equity


def get_history_real_stats(ctx: EngineContext, window_id: Optional[int]) -> dict:
    if window_id is None:
        return {"trade_count": 0, "profit": 0.0, "win": 0, "loss": 0, "loss_streak": 0, "wr": 0.0}

    try:
        key = int(window_id)
    except Exception:
        key = window_id

    stat = ctx.window_real_stats.get(key, ctx.window_real_stats.get(str(window_id), None))
    if stat is None:
        return {"trade_count": 0, "profit": 0.0, "win": 0, "loss": 0, "loss_streak": 0, "wr": 0.0}

    trades = int(stat.get("trade_count", 0))
    win = int(stat.get("win", 0))
    wr = round(win / trades, 3) if trades else 0.0
    return {
        "trade_count": trades,
        "profit": round(float(stat.get("profit", 0.0)), 2),
        "win": win,
        "loss": int(stat.get("loss", 0)),
        "loss_streak": int(stat.get("loss_streak", 0)),
        "wr": wr,
    }



def signal_to_txn_dict(signal: SignalRecord, confidence: float) -> dict:
    """Persist the COMPLETE SignalRecord needed to resume deterministically.

    build_signal() is state-mutating, so after SIGNAL_READY a restart must not
    reconstruct a reduced/default SignalRecord.  Every field consumed by
    adaptive_ready_wait(), open_trade(), confidence/protection logic, or the
    dashboard is therefore persisted.
    """
    out = {}
    for f in dataclasses.fields(SignalRecord):
        value = getattr(signal, f.name)
        if isinstance(value, deque):
            value = list(value)
        elif isinstance(value, dict):
            value = dict(value)
        out[f.name] = value
    out["decision_confidence"] = float(confidence)
    return out

def signal_from_txn_dict(data: dict) -> SignalRecord:
    kwargs = {}
    for f in dataclasses.fields(SignalRecord):
        if f.name not in data:
            continue
        value = data[f.name]
        if f.name == "live_hit_history":
            value = deque(value or [], maxlen=50)
        kwargs[f.name] = value
    sig = SignalRecord(**kwargs)
    sig.decision_confidence = float(data.get("decision_confidence", 0.0) or 0.0)
    return sig


def append_round_audit(ctx: EngineContext, round_id: int, number: int, group: int,
                      signal: Optional[SignalRecord] = None,
                      settled: Optional[TradeRecord] = None) -> None:
    """Persist one idempotent record for the exact processed round.

    A single round may BOTH settle the previous trade and open a new trade.
    Therefore settlement and opening are resolved independently; never use the
    newest trade with the same round_id for both events.
    """
    ensure_ctx_fields(ctx)
    signal_state = getattr(signal, "state", None) if signal is not None else None
    next_group = getattr(signal, "next_group", None) if signal is not None else None
    confidence = getattr(signal, "decision_confidence", None) if signal is not None else None

    open_this = bool(getattr(ctx, "last_open_round", -1) == round_id)
    settle_this = bool(getattr(ctx, "last_result_round", -1) == round_id)

    open_rec = None
    settle_rec = None
    for x in reversed(list(getattr(ctx, "trade_history", []) or [])):
        try:
            if open_rec is None and int(getattr(x, "round_id", -1)) == int(round_id):
                open_rec = x
            if settle_rec is None and int(getattr(x, "settle_round", -1) or -1) == int(round_id):
                if getattr(x, "hit", None) is not None:
                    settle_rec = x
        except Exception:
            continue
        if open_rec is not None and settle_rec is not None:
            break
    if settle_rec is None and settled is not None:
        settle_rec = settled

    decision = (str(getattr(ctx, "last_decision_state", "WAIT") or "WAIT")
                if getattr(ctx, "last_decision_round", -1) == round_id else "WARMUP")
    row = {
        "r": int(round_id),
        "n": int(number),
        "g": int(group),
        "phase": "COMPLETE",
        "decision": decision,
        "signal": str(signal_state or ""),
        "predict": int(getattr(open_rec, "predict", next_group)) if (open_this and open_rec is not None and getattr(open_rec, "predict", None) is not None) else (int(next_group) if next_group is not None and open_this else None),
        "window": int(getattr(open_rec, "locked_window", getattr(ctx, "locked_window", 0)) or 0) if (open_this and open_rec is not None) else None,
        "confidence": round(float(confidence), 4) if confidence is not None else None,
        "reason": str(getattr(ctx, "protection_reason", "") or getattr(ctx, "open_reason", "") or "") if getattr(ctx, "last_decision_round", -1) == round_id else "WARMUP",
        "open_this_round": open_this,
        "open_round": int(getattr(open_rec, "round_id", round_id)) if open_this and open_rec is not None else None,
        "pending_target": int(getattr(ctx, "pending_target_round", 0)) if open_this and getattr(ctx, "pending_target_round", 0) else None,
        "settle_this_round": settle_this,
        "settle_round": int(round_id) if settle_this else None,
        "settle_open_round": int(getattr(settle_rec, "round_id", 0)) if settle_this and settle_rec is not None else None,
        "settle_predict": int(getattr(settle_rec, "predict")) if settle_this and settle_rec is not None and getattr(settle_rec, "predict", None) is not None else None,
        "settle_window": int(getattr(settle_rec, "locked_window")) if settle_this and settle_rec is not None and getattr(settle_rec, "locked_window", None) is not None else None,
        "actual": int(getattr(settle_rec, "actual")) if settle_this and settle_rec is not None and getattr(settle_rec, "actual", None) is not None else None,
        "result": str(getattr(settle_rec, "status", "")) if settle_this and settle_rec is not None else "",
        "profit": round(float(getattr(settle_rec, "profit", 0.0)), 2) if settle_this and settle_rec is not None else None,
        "equity": round(float(ctx.equity_curve[-1]), 2) if ctx.equity_curve else 0.0,
        "frontier": int(getattr(ctx, "last_length", 0) or 0),
    }
    logs = list(getattr(ctx, "round_log", []) or [])
    replaced = False
    for i, old in enumerate(logs):
        try:
            if int(old.get("r", -1)) == int(round_id):
                logs[i] = row
                replaced = True
                break
        except Exception:
            pass
    if not replaced:
        logs.append(row)
    logs.sort(key=lambda x: int(x.get("r", 0)))
    ctx.round_log = logs[-300:]


def round_audit_integrity_report(ctx: EngineContext) -> dict:
    """Cross-check persisted per-round audit against the trade ledger.

    This is diagnostic/recovery protection only; it never changes trading
    decisions.  It catches missing/duplicate round markers and OPEN/SETTLE
    mismatches before a live resume can silently continue from bad history.
    """
    ensure_ctx_fields(ctx)
    logs = list(getattr(ctx, "round_log", []) or [])
    trades = list(getattr(ctx, "trade_history", []) or [])
    errors = []
    by_round = {}
    for row in logs:
        try:
            r = int(row.get("r", -1))
        except Exception:
            continue
        if r in by_round:
            errors.append(f"duplicate_round:{r}")
        by_round[r] = row

    # Trade OPEN events must have exactly one matching audit OPEN marker.
    for rec in trades:
        try:
            r = int(getattr(rec, "round_id", -1))
        except Exception:
            continue
        row = by_round.get(r)
        if row is None:
            continue  # The current transaction may not have committed its audit yet.
        if getattr(rec, "predict", None) is not None and row.get("open_this_round"):
            if row.get("predict") != int(rec.predict):
                errors.append(f"open_predict_mismatch:{r}")
        if getattr(rec, "locked_window", None) is not None and row.get("open_this_round"):
            try:
                if int(row.get("window")) != int(rec.locked_window):
                    errors.append(f"open_window_mismatch:{r}")
            except Exception:
                errors.append(f"open_window_invalid:{r}")

    # Every settled trade must match the audit row for its settle round.
    for rec in trades:
        if getattr(rec, "hit", None) is None or getattr(rec, "settle_round", None) is None:
            continue
        try:
            sr = int(rec.settle_round)
        except Exception:
            continue
        row = by_round.get(sr)
        if row is None:
            continue
        if not row.get("settle_this_round"):
            errors.append(f"missing_settle_marker:{sr}")
            continue
        if row.get("settle_open_round") != int(getattr(rec, "round_id", 0)):
            errors.append(f"settle_open_round_mismatch:{sr}")
        try:
            if round(float(row.get("profit")), 2) != round(float(getattr(rec, "profit", 0.0)), 2):
                errors.append(f"settle_profit_mismatch:{sr}")
        except Exception:
            errors.append(f"settle_profit_invalid:{sr}")

    frontier = int(getattr(ctx, "last_length", 0) or 0)
    if logs:
        max_logged = max(int(x.get("r", 0)) for x in logs if isinstance(x, dict))
        if max_logged > frontier:
            errors.append(f"audit_ahead_of_frontier:{max_logged}>{frontier}")

    return {"ok": not errors, "errors": errors, "round_count": len(logs), "frontier": frontier}


def save_live_state(ctx: EngineContext) -> None:
    ensure_ctx_fields(ctx)
    refresh_ledger_checkpoint(ctx)
    ctx.state_revision = int(getattr(ctx, "state_revision", 0) or 0) + 1
    data = serialize_live_state(ctx)
    cfg = get_state_backend_config()

    # Durable local WAL is written FIRST. If the remote write times out after
    # actually committing, restart can recover the exact newer revision instead
    # of replaying the round from an older Google State snapshot.
    try:
        wal_tmp = STATE_WAL_FILE + ".tmp"
        with open(wal_tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(wal_tmp, STATE_WAL_FILE)
    except Exception as e:
        st.error(f"Durable WAL write failed: {e}")
        st.stop()

    if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        if save_state_to_gsheet(data):
            return
        st.error(
            "LIVE STATE SAVE FAILED: Google State write could not be verified. "
            "The durable WAL has the current state; processing is stopped."
        )
        st.stop()

    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        st.error(f"Save local state error: {e}")
        st.stop()


def load_live_state() -> EngineContext:
    cfg = get_state_backend_config()

    # When Google State is configured, it remains the remote source of truth,
    # but the durable local WAL is a recovery mirror for ambiguous/failed remote
    # writes. Never silently fall back to an unrelated old local state file.
    data = load_state_from_gsheet() if cfg["backend"] == "gsheet" and cfg["sheet_id"] else None

    wal_data = None
    try:
        if os.path.exists(STATE_WAL_FILE):
            with open(STATE_WAL_FILE, "r", encoding="utf-8") as f:
                wal_data = json.load(f)
    except Exception:
        wal_data = None

    def _valid_state(x):
        return (isinstance(x, dict) and bool(x) and
                str(x.get("state_version", "")) in COMPATIBLE_STATE_VERSIONS)

    if isinstance(data, dict) and "__STATE_LOAD_ERROR__" in data:
        # Remote read failed. A previously durable WAL is safer than replaying
        # from an older state file, so recover from the highest valid revision.
        if _valid_state(wal_data):
            data = wal_data
        else:
            st.error(
                "LIVE STATE LOAD FAILED: Google State could not be read and no "
                "valid durable WAL is available. Processing is stopped."
            )
            st.stop()

    elif _valid_state(data) and _valid_state(wal_data):
        # Prefer the highest committed local revision if it is ahead of Google.
        # This covers a remote write that succeeded but whose response timed out.
        if int(wal_data.get("state_revision", 0) or 0) > int(data.get("state_revision", 0) or 0):
            data = wal_data

    elif cfg["backend"] == "gsheet" and cfg["sheet_id"] and _valid_state(wal_data):
        # Google returned a non-current/empty/corrupt payload, but the durable WAL
        # contains a valid state for THIS engine version. Never discard the WAL and
        # start a fresh context: that would replay old rounds or lose the ledger.
        data = wal_data

    elif data is None and cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        # Configured remote backend must not silently use STATE_FILE.
        if _valid_state(wal_data):
            data = wal_data
        else:
            st.error("LIVE STATE LOAD FAILED: no valid Google State/WAL available.")
            st.stop()

    elif data is None:
        if not os.path.exists(STATE_FILE):
            return EngineContext()
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return EngineContext()

    if not isinstance(data, dict) or not data:
        return EngineContext()

    # V69 is a deliberate clean live-state boundary. Never import V68/V67
    # trade ledger, lock, pending trade, or daily protection into V69.
    # This prevents cross-version/cross-day contamination.
    if str(data.get("state_version", "")) not in COMPATIBLE_STATE_VERSIONS:
        return EngineContext()

    ctx = EngineContext()

    ctx.trade_history = [
        trade_record_from_dict(x)
        for x in data.get("trade_history", [])
    ]
    ctx.equity_curve = list(data.get("equity_curve", []))
    ctx.signal_history.extend(data.get("signal_history", []))
    ctx.signal_flip_history.extend(data.get("signal_flip_history", []))
    ctx.leader_history.extend(data.get("leader_history", []))

    ctx.pending_trade = data.get("pending_trade")
    ctx.pending_round = int(data.get("pending_round", 0))
    ctx.pending_index = data.get("pending_index")
    ctx.pending_locked_window = data.get("pending_locked_window")
    ctx.pending_confidence = float(data.get("pending_confidence", 0.0))
    ctx.pending_target_round = int(data.get("pending_target_round", 0))
    ctx.trade_state = data.get("trade_state", "IDLE")
    ctx.last_result_round = int(data.get("last_result_round", -1))
    ctx.last_result_open_round = int(data.get("last_result_open_round", -1))
    ctx.last_result_predict = data.get("last_result_predict")
    ctx.last_result_actual = data.get("last_result_actual")
    ctx.last_result_hit = data.get("last_result_hit")
    ctx.last_result_profit = float(data.get("last_result_profit", 0.0))
    ctx.last_result_status = str(data.get("last_result_status", ""))

    ctx.last_length = int(data.get("last_length", 0))
    ctx.last_open_round = int(data.get("last_open_round", -1))
    ctx.last_settle_round = int(data.get("last_settle_round", -1))
    ctx.last_window_round = int(data.get("last_window_round", -1))
    ctx.last_signal_round = int(data.get("last_signal_round", -1))

    ctx.cooldown_counter = int(data.get("cooldown_counter", 0))
    ctx.cooldown_loss_streak_marker = int(data.get("cooldown_loss_streak_marker", -1))
    ctx.safe_mode_counter = int(data.get("safe_mode_counter", 0))
    ctx.peak_equity = float(data.get("peak_equity", 0.0))
    ctx.last_safe_trigger_peak = float(data.get("last_safe_trigger_peak", 0.0))
    ctx.risk_pause_counter = int(data.get("risk_pause_counter", 0))
    ctx.last_risk_trigger_trade_count = int(data.get("last_risk_trigger_trade_count", -1))
    ctx.last_decision_confidence = float(data.get("last_decision_confidence", 0.0))
    ctx.last_decision_round = int(data.get("last_decision_round", -1))
    ctx.last_decision_state = str(data.get("last_decision_state", "WAIT"))
    ctx.last_decision_next_group = data.get("last_decision_next_group")
    ctx.daily_stop_active = bool(data.get("daily_stop_active", False))
    ctx.daily_stop_reason = str(data.get("daily_stop_reason", ""))
    ctx.keep_win_lock_until = int(data.get("keep_win_lock_until", 0) or 0)
    ctx.dataset_anchor_signature = str(data.get("dataset_anchor_signature", "") or "")
    ctx.live_day_id = str(data.get("live_day_id", "") or "")
    ctx.live_day_seq = int(data.get("live_day_seq", 0) or 0)
    ctx.live_day_date = str(data.get("live_day_date", "") or "")
    ctx.daily_profit_history = list(data.get("daily_profit_history", []))
    ctx.round_log = list(data.get("round_log", []))[-300:]
    ctx.round_txn_round = int(data.get("round_txn_round", -1) or -1)
    ctx.round_txn_phase = str(data.get("round_txn_phase", "IDLE") or "IDLE")
    ctx.round_txn_opened = bool(data.get("round_txn_opened", False))
    ctx.round_txn_settled = bool(data.get("round_txn_settled", False))
    ctx.round_txn_signal = dict(data.get("round_txn_signal", {}) or {})
    ctx.state_revision = int(data.get("state_revision", 0) or 0)
    ctx.ledger_trade_count = int(data.get("ledger_trade_count", 0) or 0)
    ctx.ledger_settled_count = int(data.get("ledger_settled_count", 0) or 0)
    ctx.ledger_profit = float(data.get("ledger_profit", 0.0) or 0.0)
    ctx.ledger_checksum = str(data.get("ledger_checksum", "") or "")
    ctx.ledger_frontier_round = int(data.get("ledger_frontier_round", 0) or 0)

    ctx.protection_reason = data.get("protection_reason", "")
    ctx.open_reason = data.get("open_reason", "")

    ctx.locked_window = data.get("locked_window")
    ctx.lock_reason = data.get("lock_reason", "")

    ctx.locked_live_profit = float(data.get("locked_live_profit", 0.0))
    ctx.locked_live_loss_streak = int(data.get("locked_live_loss_streak", 0))
    ctx.locked_live_win = int(data.get("locked_live_win", 0))
    ctx.locked_live_loss = int(data.get("locked_live_loss", 0))

    raw_real_stats = data.get("window_real_stats", {})
    ctx.window_real_stats = {}
    for k, v in raw_real_stats.items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        ctx.window_real_stats[kk] = v

    # Trade history is the source of truth for real stats/equity.
    # Rebuild every load to avoid stale/corrupt window_real_stats.
    rebuild_real_stats_from_history(ctx)
    # Derived Profit/equity/window stats are rebuilt from the ledger. The ledger
    # itself is never reconstructed from cached Profit fields.
    refresh_ledger_checkpoint(ctx)

    raw_cooled_windows = data.get("cooled_windows", {})
    ctx.cooled_windows = {}
    for k, v in raw_cooled_windows.items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        ctx.cooled_windows[kk] = int(v)

    raw_blacklisted_windows = data.get("blacklisted_windows", {})
    ctx.blacklisted_windows = {}
    for k, v in raw_blacklisted_windows.items():
        try:
            kk = int(k)
        except Exception:
            kk = k
        ctx.blacklisted_windows[kk] = int(v)

    ctx.hybrid_initialized = bool(data.get("hybrid_initialized", False))
    ctx.data_signature = str(data.get("data_signature", ""))
    ctx.data_length = int(data.get("data_length", ctx.last_length))

    return ensure_ctx_fields(ctx)


# ============================================================
# TRUE LIVE SESSION STATE
# ============================================================

def get_live_ctx() -> EngineContext:
    # V3.4.6: persistent state is authoritative on EVERY Streamlit rerun.
    # Do not reuse a potentially stale in-memory session copy. The live page
    # is browser-refreshed repeatedly, and the persisted ledger must be the
    # same source used for settlement, profit, and window selection.
    loaded = ensure_ctx_fields(load_live_state())
    st.session_state.v50_true_live_ctx = loaded
    return _merge_sheet_daily_history_into_ctx(loaded)



def get_live_window_state() -> dict[int, WindowRecord]:
    if "v50_true_live_window_state" not in st.session_state:
        st.session_state.v50_true_live_window_state = {
            w: WindowRecord()
            for w in WINDOWS
        }
    return st.session_state.v50_true_live_window_state


def carry_forward_daily_profit_history(ctx: EngineContext) -> list:
    """Carry completed prior-day P/L across a manual day reset.

    Only the previous completed dataset is appended, and only when the day id
    changes. This avoids duplicate history if an operator resets/restarts on
    the same day.
    """
    ensure_ctx_fields(ctx)
    hist = list(getattr(ctx, "daily_profit_history", []) or [])
    old_day = str(getattr(ctx, "live_day_id", "") or "")
    today = current_live_day_id()
    if old_day and old_day != today:
        settled = [x for x in ctx.trade_history if getattr(x, "hit", None) is not None]
        if settled:
            profit = round(sum(float(x.profit) for x in settled), 2)
            hist.append({"day_id": old_day, "profit": profit})
    return hist[-10:]


def current_day_loss_streak(ctx: EngineContext) -> int:
    """Count consecutive settled losses in the current live dataset."""
    streak = 0
    for rec in reversed(list(getattr(ctx, "trade_history", []) or [])):
        if getattr(rec, "hit", None) is None:
            continue
        if str(getattr(rec, "status", "")) == "LOSS":
            streak += 1
        else:
            break
    return streak


def is_bad_multi_day_regime(ctx: EngineContext) -> bool:
    """V3.4: negative prior-3-day history + 2 current-day losses."""
    hist = list(getattr(ctx, "daily_profit_history", []) or [])
    if len(hist) < MULTI_DAY_NEG_DAY_STREAK:
        return False
    try:
        prior = hist[-MULTI_DAY_NEG_DAY_STREAK:]
        profits = [
            float(x.get("profit", 0.0)) if isinstance(x, dict) else float(x)
            for x in prior
        ]
    except Exception:
        return False
    if not all(p < 0 for p in profits):
        return False
    return current_day_loss_streak(ctx) >= MULTI_DAY_LOSS_COUNT


def multi_day_low_confidence_filter(ctx: EngineContext, confidence: float) -> bool:
    """Return True when a new entry should be suppressed by V3.3.

    Uses only information available before the current trade: completed prior
    day P/L, current day's settled loss count, and current signal confidence.
    """
    if not MULTI_DAY_CONF_FILTER:
        return False
    hist = list(getattr(ctx, "daily_profit_history", []) or [])
    if len(hist) < MULTI_DAY_NEG_DAY_STREAK:
        return False
    prior = hist[-MULTI_DAY_NEG_DAY_STREAK:]
    try:
        prior_profits = [float(x.get("profit", 0.0)) if isinstance(x, dict) else float(x) for x in prior]
    except Exception:
        return False
    if not all(p < 0 for p in prior_profits):
        return False
    settled = [x for x in ctx.trade_history if getattr(x, "hit", None) is not None]
    losses = sum(1 for x in settled if getattr(x, "status", "") == "LOSS")
    return losses >= MULTI_DAY_LOSS_COUNT and float(confidence) < MULTI_DAY_CONF_MAX


def reset_live_state_button() -> None:
    with st.sidebar:
        st.subheader("Live Control")
        cfg = get_state_backend_config()
        if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
            st.caption(f"State backend: Google Sheet / worksheet={cfg['worksheet']}")
        else:
            st.caption(f"State backend: local file {STATE_FILE}")
        if st.button("REBUILD TRADE HISTORY FROM CURRENT B"):
            # Explicit recovery path: discard only the current live ledger/state
            # and replay the currently loaded Google Sheet column B from the
            # live-start frontier. This is useful when an old deployment has
            # advanced last_length but lost its Trade History.
            old_ctx = ensure_ctx_fields(get_live_ctx())
            blank_ctx = ensure_ctx_fields(EngineContext())
            blank_ctx.daily_profit_history = list(getattr(old_ctx, "daily_profit_history", []) or [])[-10:]
            blank_ctx.live_day_id = current_live_day_id()
            blank_ctx.protection_reason = "MANUAL_REBUILD_LEDGER_FROM_CURRENT_B"
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""
            cfg_rebuild = get_state_backend_config()
            if cfg_rebuild["backend"] == "gsheet" and cfg_rebuild["sheet_id"]:
                if not save_state_to_gsheet(serialize_live_state(blank_ctx)):
                    st.error("REBUILD stopped: Google State could not be cleared safely.")
                    st.stop()
            else:
                try:
                    if os.path.exists(STATE_FILE):
                        os.remove(STATE_FILE)
                except Exception as e:
                    st.error(f"REBUILD stopped: cannot remove local state: {e}")
                    st.stop()
            st.session_state.v50_true_live_ctx = blank_ctx
            st.session_state.v50_true_live_window_state = {w: WindowRecord() for w in WINDOWS}
            st.rerun()

        if st.button("Reset Live State"):
            old_ctx_for_history = ensure_ctx_fields(get_live_ctx())
            carry_history = carry_forward_daily_profit_history(old_ctx_for_history)
            # Manual reset MUST use the same atomic-safe path as automatic
            # daily reset. Never delete remotely and rerun blindly: if the
            # Google State write fails, old state could be loaded again.
            blank_ctx = ensure_ctx_fields(EngineContext())
            blank_ctx.daily_profit_history = carry_history
            blank_ctx.live_day_id = current_live_day_id()
            blank_ctx.protection_reason = "MANUAL_RESET"
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""

            cfg2 = get_state_backend_config()
            if cfg2["backend"] == "gsheet" and cfg2["sheet_id"]:
                if not save_state_to_gsheet(serialize_live_state(blank_ctx)):
                    st.error(
                        "MANUAL RESET stopped: Google State could not be reset safely. "
                        "Fix the Google connection and try again. Old state was not touched."
                    )
                    st.stop()
            else:
                try:
                    if os.path.exists(STATE_FILE):
                        os.remove(STATE_FILE)
                except Exception as e:
                    st.error(f"MANUAL RESET stopped: cannot remove local state: {e}")
                    st.stop()

            st.session_state.pop("v69_reset_required", None)
            st.session_state.pop("v69_reset_reason", None)
            st.session_state.v50_true_live_ctx = blank_ctx
            st.session_state.v50_true_live_window_state = {
                w: WindowRecord() for w in WINDOWS
            }
            st.rerun()


# ============================================================
# ENGINE MANAGER
# ============================================================

class EngineManager:
    def __init__(self) -> None:
        reset_live_state_button()

        self.ctx = ensure_ctx_fields(get_live_ctx())
        self.window_state = get_live_window_state()

        # V3.5: the Sheet is append-only. DAY_SEQ is the only day boundary.
        raw_df, sheet_day_seq, sheet_day_date, raw_numbers = _load_day_seq_sheet_snapshot()
        if sheet_day_seq <= 0:
            st.warning("Waiting for DAY_SEQ...")
            st.stop()
        self.maybe_auto_reset_for_new_day(sheet_day_seq, sheet_day_date)

        self.numbers, self.groups, self.actual_group, self.round_id = load_data()

        self.window_engine = WindowEngine(self.ctx, self.window_state)
        self.trade_engine = TradeEngine(self.ctx)
        self.signal_engine = SignalEngine(self.ctx, self.window_engine)
        self.protection_engine = ProtectionEngine(self.ctx, self.trade_engine)
        self.dashboard = Dashboard(self.ctx, self.window_engine, self.signal_engine, self.trade_engine, self.protection_engine)

        # Legacy dataset replacement protection is intentionally disabled in
        # V3.5. DAY_SEQ already identifies the active dataset.
        resume_target = int(getattr(self.ctx, "last_length", 0) or 0)
        txn_round = int(getattr(self.ctx, "round_txn_round", -1) or -1)
        txn_phase = str(getattr(self.ctx, "round_txn_phase", "") or "")
        if txn_round > resume_target and txn_phase in {
            "WARMUP_UPDATED", "WARMUP_COMPLETE", "WINDOW_UPDATED", "SIGNAL_READY", "DECISION_READY", "OPENED", "COMPLETE"
        }:
            resume_target = txn_round
        if resume_target > 0:
            self.rebuild_windows_to_length(resume_target)

    def maybe_auto_reset_for_new_day(self, sheet_day_seq: int, sheet_day_date: str) -> None:
        """DAY_SEQ-driven daily boundary. No CLEAR B and no server-date reset."""
        ensure_ctx_fields(self.ctx)
        state_seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)
        sheet_day_seq = int(sheet_day_seq or 0)
        if sheet_day_seq <= 0:
            st.stop()

        if state_seq == 0:
            # New V3.5 state starts from the current highest DAY_SEQ.
            self.ctx.live_day_seq = sheet_day_seq
            self.ctx.live_day_date = str(sheet_day_date or "")
            self.ctx.live_day_id = str(sheet_day_date or "")
            _merge_sheet_daily_history_into_ctx(self.ctx)
            save_live_state(self.ctx)
            return

        if sheet_day_seq < state_seq:
            st.error(f"DAY_SEQ REGRESSION: STATE={state_seq}, SHEET={sheet_day_seq}. Engine stopped.")
            st.stop()

        if sheet_day_seq == state_seq:
            if sheet_day_date and str(getattr(self.ctx, "live_day_date", "") or "") not in ("", sheet_day_date):
                st.error(f"DAY_SEQ {state_seq} has date changed: STATE={self.ctx.live_day_date}, SHEET={sheet_day_date}.")
                st.stop()
            self.ctx.live_day_date = str(sheet_day_date or getattr(self.ctx, "live_day_date", "") or "")
            self.ctx.live_day_id = self.ctx.live_day_date
            _merge_sheet_daily_history_into_ctx(self.ctx)
            return

        # Only +1 is accepted. Missing DAY_SEQ means the operator has not
        # completed/started the intermediate day and the engine must not guess.
        if sheet_day_seq != state_seq + 1:
            st.error(f"DAY_SEQ SKIPPED: STATE={state_seq}, SHEET={sheet_day_seq}. Expected {state_seq + 1}.")
            st.stop()

        self.reset_context_for_new_day(sheet_day_seq, sheet_day_date)

    def reset_context_for_new_day(self, new_day_seq: int, new_day_date: str) -> None:
        # PROFIT-MATCH RULE:
        # A trade opened on the final round of DAY_SEQ N has no target round
        # inside that completed daily dataset. Historical live behavior starts
        # DAY_SEQ N+1 from a clean trade state, so unresolved end-of-day PENDING
        # trades are intentionally discarded at the boundary. Do NOT carry them
        # into round 1 of the next DAY_SEQ; doing so changes daily P/L and breaks
        # the audited +46.5 historical result.
        """Atomically start the next DAY_SEQ while preserving daily history."""
        cfg = get_state_backend_config()
        old_ctx = self.ctx
        _merge_sheet_daily_history_into_ctx(old_ctx)
        blank_ctx = ensure_ctx_fields(EngineContext())
        blank_ctx.daily_profit_history = list(getattr(old_ctx, "daily_profit_history", []) or [])[-10:]
        blank_ctx.live_day_seq = int(new_day_seq)
        blank_ctx.live_day_date = str(new_day_date or "")
        blank_ctx.live_day_id = blank_ctx.live_day_date
        blank_ctx.protection_reason = f"AUTO_NEW_DAY_SEQ_{new_day_seq}"
        blank_ctx.state_version = STATE_VERSION
        blank_ctx.hybrid_initialized = False
        blank_ctx.last_length = 0
        blank_ctx.data_length = 0
        blank_ctx.data_signature = ""
        blank_ctx.dataset_anchor_signature = ""
        blank_ctx.state_revision = int(getattr(old_ctx, "state_revision", 0) or 0) + 1

        payload = serialize_live_state(blank_ctx)
        try:
            wal_tmp = STATE_WAL_FILE + ".tmp"
            with open(wal_tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush(); os.fsync(f.fileno())
            os.replace(wal_tmp, STATE_WAL_FILE)
        except Exception as e:
            st.error(f"NEW DAY SEQ reset stopped: WAL write failed: {e}")
            st.stop()

        if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
            if not save_state_to_gsheet(payload):
                st.error("NEW DAY SEQ reset stopped: Google State write failed.")
                st.stop()
        else:
            try:
                save_live_state(blank_ctx)
            except Exception as e:
                st.error(f"NEW DAY SEQ reset stopped: local state write failed: {e}")
                st.stop()

        st.session_state.v50_true_live_ctx = blank_ctx
        st.session_state.v50_true_live_window_state = {w: WindowRecord() for w in WINDOWS}
        st.rerun()

    def maybe_auto_reset_for_new_dataset(self) -> None:
        # V3.5: disabled. DAY_SEQ is the explicit dataset boundary.
        return

    def rebuild_windows_to_length(self, target: int) -> None:
        # Window state is derived from number history, so rebuild it safely on every app start.
        # Trade history is NOT replayed here.
        target = min(int(target), len(self.groups))
        if target <= 0:
            return

        # Reset derived window state and derived leader history.
        for w in WINDOWS:
            self.window_state[w] = WindowRecord()

        self.ctx.leader_history = deque(maxlen=LEADER_HISTORY_LEN)
        self.ctx.last_window_round = -1

        for idx in range(1, target + 1):
            self.window_engine.update_one_round(self.groups[idx - 1], idx)

        self.ctx.last_window_round = target

    def rebuild_windows_to_last_length(self) -> None:
        self.rebuild_windows_to_length(int(getattr(self.ctx, "last_length", 0) or 0))

    def _apply_decision(self, signal: SignalRecord, idx: int, confidence: float) -> None:
        # V3.4.24: split protection/decision from OPEN into a durable phase.
        # adaptive_ready_wait() mutates protection counters; therefore a crash after
        # that mutation but before OPEN must never re-run it. Persist DECISION_READY
        # first, then perform OPEN. If OPEN itself crashes, no save has happened after
        # the in-memory mutation, so restart safely retries only OPEN.
        signal.state = self.protection_engine.adaptive_ready_wait(
            signal, confidence
        )

        if multi_day_low_confidence_filter(self.ctx, confidence):
            self.ctx.protection_reason = "MULTI_DAY_LOW_CONF_FILTER"
            signal.state = "WAIT"

        self.ctx.last_decision_round = idx
        self.ctx.last_decision_state = str(signal.state or "WAIT")
        self.ctx.last_decision_next_group = None
        snap = dict(getattr(self.ctx, "round_txn_signal", {}) or {})
        snap["decision_state"] = str(signal.state or "WAIT")
        snap["decision_confidence"] = float(confidence)
        self.ctx.round_txn_signal = snap
        self.ctx.round_txn_phase = "DECISION_READY"
        save_live_state(self.ctx)

        # Only READY reaches OPEN. WAIT is already durably committed as a decision.
        if str(signal.state or "WAIT") == "WAIT":
            return

        before = len(self.ctx.trade_history)
        self.trade_engine.open_trade(signal, idx, confidence)
        created = len(self.ctx.trade_history) > before
        self.ctx.last_decision_state = "PENDING" if created else str(signal.state or "WAIT")
        self.ctx.last_decision_next_group = signal.next_group if created else None

        # Persist an OPEN immediately.
        if created:
            save_live_state(self.ctx)

    def hybrid_replay_once(self) -> None:
        # HYBRID LIVE:
        # First run only:
        # - rounds < LIVE_START_ROUND: warm-up windows only
        # - rounds >= LIVE_START_ROUND: replay trade once to build initial history
        # After that, state is kept in st.session_state and new rounds are processed live only.
        if getattr(self.ctx, "hybrid_initialized", False):
            return

        # Crash-safe resume: startup already rebuilt derived window state to
        # persisted last_length. Never replay rounds 1..last_length again.
        saved_frontier = int(getattr(self.ctx, "last_length", 0) or 0)
        start_idx = max(1, saved_frontier + 1)

        for idx in range(start_idx, len(self.groups) + 1):
            actual_group = self.groups[idx - 1]
            # IMPORTANT: this replay must be bit-for-bit equivalent to TRUE LIVE.
            # Do NOT advance ctx.last_length before processing the current round.
            # Live commits the frontier only after settle -> window -> signal -> protection -> trade.
            if idx < LIVE_START_ROUND:
                # Warm-up is state-mutating too. It therefore needs the same
                # durable transaction protection as live rounds: a crash after
                # update_one_round() must never replay that window update.
                same_warmup = int(getattr(self.ctx, "round_txn_round", -1)) == idx
                warm_phase = str(getattr(self.ctx, "round_txn_phase", "") or "") if same_warmup else ""
                if same_warmup and warm_phase == "WARMUP_COMPLETE":
                    self.ctx.last_length = idx
                    continue
                if not same_warmup:
                    self.ctx.round_txn_round = idx
                    self.ctx.round_txn_phase = "WARMUP_STARTED"
                    self.ctx.round_txn_opened = False
                    self.ctx.round_txn_settled = False
                    self.ctx.round_txn_signal = {}
                    save_live_state(self.ctx)
                    warm_phase = "WARMUP_STARTED"

                if warm_phase == "WARMUP_STARTED":
                    self.window_engine.update_one_round(actual_group, idx)
                    self.ctx.round_txn_phase = "WARMUP_UPDATED"
                    save_live_state(self.ctx)
                    warm_phase = "WARMUP_UPDATED"

                if warm_phase == "WARMUP_UPDATED":
                    self.ctx.last_length = idx
                    self.ctx.last_decision_round = idx
                    self.ctx.last_decision_state = "WARMUP"
                    self.ctx.last_decision_next_group = None
                    append_round_audit(self.ctx, idx, self.numbers[idx - 1], actual_group, None)
                    self.ctx.round_txn_phase = "WARMUP_COMPLETE"
                    save_live_state(self.ctx)
                continue

            # Durable per-round transaction with crash-safe phase resume.
            # LIVE GAP RULE: when several rows arrive in one snapshot, only the
            # latest row is a valid NEW-ENTRY frontier. Intermediate rows may
            # settle an already-open exact-target trade and update windows, but
            # MUST NOT create retrospective OPENs. This preserves live timing
            # when the Sheet/app was delayed or temporarily offline.
            is_live_frontier = (idx == current_length)
            same_txn = int(getattr(self.ctx, "round_txn_round", -1)) == idx
            phase = str(getattr(self.ctx, "round_txn_phase", "") or "") if same_txn else ""
            if same_txn and phase == "COMPLETE":
                self.ctx.last_length = idx
                continue
            if not same_txn:
                self.ctx.round_txn_round = idx
                self.ctx.round_txn_phase = "STARTED"
                self.ctx.round_txn_opened = False
                self.ctx.round_txn_settled = False
                self.ctx.round_txn_signal = {}
                save_live_state(self.ctx)
                phase = "STARTED"
            if phase == "STARTED":
                settled_this_round = self.trade_engine.settle_trade(actual_group, idx)
                self.ctx.round_txn_settled = bool(settled_this_round or getattr(self.ctx, "pending_trade", None) is None)
                self.ctx.round_txn_phase = "SETTLED"
                save_live_state(self.ctx)
                phase = "SETTLED"
            if phase == "SETTLED":
                self.window_engine.update_one_round(actual_group, idx)
                self.ctx.round_txn_phase = "WINDOW_UPDATED"
                save_live_state(self.ctx)
                phase = "WINDOW_UPDATED"

            # Intermediate catch-up rows are state/warm-up only. Do not run
            # build_signal() here because it can relock/cool windows and would
            # turn an old round into a retrospective trading decision.
            if phase == "WINDOW_UPDATED" and not is_live_frontier:
                self.ctx.last_decision_round = idx
                self.ctx.last_decision_state = "CATCH_UP"
                self.ctx.last_decision_next_group = None
                self.ctx.round_txn_opened = False
                self.ctx.round_txn_phase = "COMPLETE"
                self.ctx.round_txn_signal = {}
                self.ctx.last_length = idx
                append_round_audit(self.ctx, idx, self.numbers[idx - 1], actual_group, None)
                self.ctx.data_length = idx
                self.ctx.data_signature = make_numbers_signature(self.numbers, idx)
                save_live_state(self.ctx)
                continue

            if phase == "WINDOW_UPDATED":
                signal = self.signal_engine.build_signal(idx)
                signal = self.signal_engine.apply_sample_aware_coherence(signal)
                confidence = self.signal_engine.get_confidence_score(signal)
                self.ctx.last_decision_confidence = confidence
                setattr(signal, "decision_confidence", confidence)
                self.ctx.round_txn_signal = signal_to_txn_dict(signal, confidence)
                self.ctx.round_txn_phase = "SIGNAL_READY"
                save_live_state(self.ctx)
                phase = "SIGNAL_READY"
            else:
                snap = dict(getattr(self.ctx, "round_txn_signal", {}) or {})
                if snap:
                    signal = signal_from_txn_dict(snap)
                    confidence = float(snap.get("decision_confidence", 0.0) or 0.0)
                else:
                    signal = self.signal_engine.build_signal(idx)
                    signal = self.signal_engine.apply_sample_aware_coherence(signal)
                    confidence = self.signal_engine.get_confidence_score(signal)
                self.ctx.last_decision_confidence = confidence
                setattr(signal, "decision_confidence", confidence)
            if phase in ("SIGNAL_READY", "DECISION_READY"):
                # V3.4.24: DECISION_READY is durable. Resume it without rerunning
                # adaptive_ready_wait(), which can mutate protection counters.
                pending_round = int(getattr(self.ctx, "pending_round", 0) or 0)
                pending_exists_for_round = (
                    getattr(self.ctx, "pending_trade", None) is not None
                    and pending_round == idx
                )
                if pending_exists_for_round:
                    self.ctx.last_decision_round = idx
                    self.ctx.last_decision_state = "PENDING"
                    self.ctx.last_decision_next_group = getattr(self.ctx, "pending_trade", None)
                    self.ctx.open_reason = "OPEN_RESUMED"
                elif phase == "SIGNAL_READY":
                    self._apply_decision(signal, idx, confidence)
                else:
                    decision_state = str((getattr(self.ctx, "round_txn_signal", {}) or {}).get("decision_state", signal.state or "WAIT"))
                    if decision_state != "WAIT":
                        before = len(self.ctx.trade_history)
                        self.trade_engine.open_trade(signal, idx, confidence)
                        created = len(self.ctx.trade_history) > before
                        self.ctx.last_decision_round = idx
                        self.ctx.last_decision_state = "PENDING" if created else decision_state
                        self.ctx.last_decision_next_group = signal.next_group if created else None
                        if created:
                            save_live_state(self.ctx)
                    else:
                        self.ctx.last_decision_round = idx
                        self.ctx.last_decision_state = "WAIT"
                        self.ctx.last_decision_next_group = None
                self.ctx.round_txn_opened = bool(getattr(self.ctx, "last_open_round", -1) == idx)
                self.ctx.round_txn_phase = "OPENED" if self.ctx.round_txn_opened else "COMPLETE"
                save_live_state(self.ctx)
            self.ctx.round_txn_phase = "COMPLETE"
            self.ctx.round_txn_signal = {}
            self.ctx.last_length = idx
            append_round_audit(self.ctx, idx, self.numbers[idx - 1], actual_group, signal)
            save_live_state(self.ctx)
        self.ctx.last_length = len(self.groups)
        self.ctx.hybrid_initialized = True
        self.ctx.live_day_id = current_live_day_id()
        self.ctx.data_signature = make_numbers_signature(self.numbers, self.ctx.last_length)
        self.ctx.dataset_anchor_signature = make_numbers_signature(self.numbers, min(DATASET_RESET_ANCHOR_LEN, self.ctx.last_length))
        self.ctx.data_length = self.ctx.last_length
        rebuild_real_stats_from_history(self.ctx)
        save_live_state(self.ctx)

    def process_new_rounds(self) -> None:
        # Process only rows added after the first hybrid replay.
        current_length = len(self.groups)

        if current_length <= self.ctx.last_length:
            return

        for idx in range(self.ctx.last_length + 1, current_length + 1):
            # Transactional round processing:
            # last_length is committed ONLY after every state mutation for this
            # round has completed and the state has been persisted. This prevents
            # a crash/restart between steps from silently skipping a round.
            actual_group = self.groups[idx - 1]

            # V3.4.14: durable round transaction marker.
            # If a prior run crashed after OPEN/SETTLE but before frontier commit,
            # the persisted marker prevents repeating that phase.
            same_txn = int(getattr(self.ctx, "round_txn_round", -1)) == idx
            phase = str(getattr(self.ctx, "round_txn_phase", "") or "") if same_txn else ""
            if same_txn and phase == "COMPLETE":
                self.ctx.last_length = idx
                continue

            if not same_txn:
                self.ctx.round_txn_round = idx
                self.ctx.round_txn_phase = "STARTED"
                self.ctx.round_txn_opened = False
                self.ctx.round_txn_settled = False
                self.ctx.round_txn_signal = {}
                save_live_state(self.ctx)
                phase = "STARTED"

            # Resume from the last durable phase. Each phase is persisted
            # immediately after its state mutation so a crash cannot replay
            # the same irreversible step (especially window updates).
            if phase == "STARTED":
                settled_this_round = self.trade_engine.settle_trade(actual_group, idx)
                self.ctx.round_txn_settled = bool(settled_this_round or getattr(self.ctx, "pending_trade", None) is None)
                self.ctx.round_txn_phase = "SETTLED"
                save_live_state(self.ctx)
                phase = "SETTLED"

            if phase == "SETTLED":
                self.window_engine.update_one_round(actual_group, idx)
                self.ctx.round_txn_phase = "WINDOW_UPDATED"
                save_live_state(self.ctx)
                phase = "WINDOW_UPDATED"

            if phase == "WINDOW_UPDATED":
                signal = self.signal_engine.build_signal(idx)
                signal = self.signal_engine.apply_sample_aware_coherence(signal)
                confidence = self.signal_engine.get_confidence_score(signal)
                self.ctx.last_decision_confidence = confidence
                setattr(signal, "decision_confidence", confidence)
                self.ctx.round_txn_signal = signal_to_txn_dict(signal, confidence)
                self.ctx.round_txn_phase = "SIGNAL_READY"
                save_live_state(self.ctx)
                phase = "SIGNAL_READY"
            else:
                # Resume the exact persisted SIGNAL_READY snapshot.
                # build_signal() can relock/cool windows and update signal history,
                # so recomputing it after a crash is unsafe.
                snap = dict(getattr(self.ctx, "round_txn_signal", {}) or {})
                if snap:
                    signal = signal_from_txn_dict(snap)
                    confidence = float(snap.get("decision_confidence", 0.0) or 0.0)
                else:
                    signal = self.signal_engine.build_signal(idx)
                    signal = self.signal_engine.apply_sample_aware_coherence(signal)
                    confidence = self.signal_engine.get_confidence_score(signal)
                self.ctx.last_decision_confidence = confidence
                setattr(signal, "decision_confidence", confidence)

            if phase in ("SIGNAL_READY", "DECISION_READY"):
                # V3.4.24: DECISION_READY is durable. Resume it without rerunning
                # adaptive_ready_wait(), which can mutate protection counters.
                pending_round = int(getattr(self.ctx, "pending_round", 0) or 0)
                pending_exists_for_round = (
                    getattr(self.ctx, "pending_trade", None) is not None
                    and pending_round == idx
                )
                if pending_exists_for_round:
                    self.ctx.last_decision_round = idx
                    self.ctx.last_decision_state = "PENDING"
                    self.ctx.last_decision_next_group = getattr(self.ctx, "pending_trade", None)
                    self.ctx.open_reason = "OPEN_RESUMED"
                elif phase == "SIGNAL_READY":
                    self._apply_decision(signal, idx, confidence)
                else:
                    decision_state = str((getattr(self.ctx, "round_txn_signal", {}) or {}).get("decision_state", signal.state or "WAIT"))
                    if decision_state != "WAIT":
                        before = len(self.ctx.trade_history)
                        self.trade_engine.open_trade(signal, idx, confidence)
                        created = len(self.ctx.trade_history) > before
                        self.ctx.last_decision_round = idx
                        self.ctx.last_decision_state = "PENDING" if created else decision_state
                        self.ctx.last_decision_next_group = signal.next_group if created else None
                        if created:
                            save_live_state(self.ctx)
                    else:
                        self.ctx.last_decision_round = idx
                        self.ctx.last_decision_state = "WAIT"
                        self.ctx.last_decision_next_group = None
                self.ctx.round_txn_opened = bool(getattr(self.ctx, "last_open_round", -1) == idx)
                self.ctx.round_txn_phase = "OPENED" if self.ctx.round_txn_opened else "COMPLETE"
                save_live_state(self.ctx)

            # Audit must show the committed frontier for THIS round.
            self.ctx.round_txn_phase = "COMPLETE"
            self.ctx.round_txn_signal = {}
            self.ctx.last_length = idx
            append_round_audit(self.ctx, idx, self.numbers[idx - 1], actual_group, signal)
            self.ctx.live_day_id = str(getattr(self.ctx, "live_day_date", "") or "")
            self.ctx.data_length = idx
            self.ctx.data_signature = make_numbers_signature(self.numbers, idx)
            if not getattr(self.ctx, "dataset_anchor_signature", "") and idx >= 32:
                self.ctx.dataset_anchor_signature = make_numbers_signature(self.numbers, DATASET_RESET_ANCHOR_LEN)
            save_live_state(self.ctx)

    def render_live_source_debug(self) -> None:
        # Operator-visible diagnostic: proves exactly which physical column is
        # feeding the engine and whether the persistent ledger matches it.
        integrity = ledger_integrity_report(self.ctx)
        audit_integrity = round_audit_integrity_report(self.ctx)
        st.caption(
            f"LIVE SOURCE | Google Sheet A:E DAY_SEQ format | "
            f"day_seq={getattr(self.ctx, "live_day_seq", 0)} | numbers={len(self.numbers)} | sheet_round={self.round_id} | "
            f"state_last_length={self.ctx.last_length} | "
            f"trades={len(self.ctx.trade_history)} | "
            f"settled={sum(1 for x in self.ctx.trade_history if getattr(x, 'hit', None) is not None)} | "
            f"profit={sum(float(x.profit) for x in self.ctx.trade_history if getattr(x, 'hit', None) is not None):+.1f} | "
            f"ledger={'OK' if integrity['ok'] else 'ERROR:' + ','.join(integrity['errors'])} | audit={'OK' if audit_integrity['ok'] else 'ERROR:' + ','.join(audit_integrity['errors'])}"
        )

    def build_display_signal(self) -> tuple[SignalRecord, float, str]:
        # If a trade is pending, do not call build_signal(), because build_signal()
        # can relock and mutate state during a pure UI refresh.
        if self.ctx.pending_trade is not None:
            locked_obj = None
            if self.ctx.locked_window is not None:
                locked_obj = self.window_engine.state.get(self.ctx.locked_window)

            signal = SignalRecord()
            signal.state = "READY"
            signal.next_group = self.ctx.pending_trade
            signal.regime = "WAIT_RESULT"
            signal.locked_window = self.ctx.locked_window
            signal.lock_reason = self.ctx.lock_reason
            signal.consensus = 0.0
            signal.required_consensus = CONSENSUS_READY
            signal.stability = self.window_engine.get_stability()
            signal.top_profit20 = locked_obj.profit20 if locked_obj is not None else 0.0

            confidence_score = float(getattr(self.ctx, "pending_confidence", 0.0))
            confidence_level = self.signal_engine.get_confidence_level(confidence_score)

            self.ctx.protection_reason = "WAITING_RESULT"
            self.ctx.open_reason = "HAS_PENDING"
            return signal, confidence_score, confidence_level

        # V3.4.8: display is read-only and reflects the ACTUAL last decision.
        signal = self.signal_engine.build_signal_snapshot(self.ctx.last_length)
        confidence_score = self.signal_engine.get_confidence_score(signal)
        confidence_level = self.signal_engine.get_confidence_level(confidence_score)

        if getattr(self.ctx, "last_decision_round", -1) == self.ctx.last_length:
            actual_state = str(getattr(self.ctx, "last_decision_state", "WAIT"))
            signal.state = "READY" if actual_state == "PENDING" else actual_state
            signal.next_group = (
                getattr(self.ctx, "last_decision_next_group", None)
                if actual_state == "PENDING" else None
            )
        elif self.ctx.open_reason in ("TRADE_GAP", "SIGNAL_WAIT", "DUPLICATE_OPEN"):
            signal.state = "WAIT"

        return signal, confidence_score, confidence_level

    def run(self) -> None:
        self.hybrid_replay_once()
        self.process_new_rounds()

        signal, confidence_score, confidence_level = self.build_display_signal()

        self.dashboard.render_header()
        self.dashboard.render_signal(signal, confidence_score)
        self.dashboard.render_market(signal)
        self.dashboard.render_profit()
        self.dashboard.render_risk()
        self.dashboard.render_last_result()
        self.dashboard.render_current_trade()
        self.dashboard.render_profit_config()
        self.dashboard.render_top_windows()
        self.dashboard.render_window_debug()
        self.dashboard.render_real_stats_summary()
        self.render_live_source_debug()
        self.dashboard.render_trade_history()
        self.dashboard.render_equity()

        st.caption(
            f"""
V3.5 DAY_SEQ LIVE TRANSACTION + ROUND AUDIT / AUDITED

DAY boundary: highest Sheet DAY_SEQ. No daily CLEAR is required.

After that: only process new Google Sheet rows.
V58 rule: UI refresh is read-only; only new rounds can change trade state.
Open/settle decisions happen only when a new round appears, not every rerun.
Trade state is saved to Google Sheet if configured, otherwise local JSON fallback.
Main panel shows READY/WAIT only. PENDING is shown only in Trade History and Current Trade.

Current Sheet Round : {self.round_id}

Engine Last Round : {self.ctx.last_length}

Live Start : {LIVE_START_ROUND}

Confidence : {confidence_level}

Trade State : {self.ctx.trade_state}

Pending Trade : {self.ctx.pending_trade} / Open Round : {self.ctx.pending_round}

Locked Window : {self.ctx.locked_window}

Regime : {signal.regime}
"""
        )


# ============================================================
# MAIN
# ============================================================

manager = EngineManager()

try:
    manager.run()
except Exception as e:
    st.error(f"Engine Error: {e}")
    import traceback
    st.code(traceback.format_exc())


# ============================================================
# AUTO REFRESH - BROWSER SIDE ONLY
# ============================================================
# Do NOT use:
#     time.sleep(5)
#     st.rerun()
# on Streamlit Cloud. It keeps the server script thread alive and can crash
# the app when mobile/browser sessions reconnect repeatedly.
#
# This JS refresh runs in the browser, releases the Python script after render,
# and is much more stable for Streamlit Community Cloud.

with st.sidebar:
    st.divider()
    auto_refresh_enabled = st.checkbox("Auto refresh", value=True)
    refresh_seconds = st.number_input(
        "Refresh seconds",
        min_value=5,
        max_value=60,
        value=10,
        step=5,
    )

if auto_refresh_enabled:
    components.html(
        f"""
        <script>
        setTimeout(function() {{
            window.parent.location.reload();
        }}, {int(refresh_seconds) * 1000});
        </script>
        """,
        height=0,
    )
