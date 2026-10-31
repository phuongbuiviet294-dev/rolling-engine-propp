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

# V4.4: calculation is stateless. Every refresh replays R1..current from the
# fresh immutable Google snapshot, exactly like the Excel/backtest path.
STATELESS_REPLAY_LIVE = True
BUILD_TAG = "V71.18.2 | LIVE101 | NO CACHE | 101+CONF>=0.55 WAIT2 | DYNAMIC LOCK 2.5/10 | C79"

# V70 causal switch: evaluated only after the just-settled REAL/CANDIDATE trade is LOSS.
# Uses only window statistics available at the current round after update_one_round().
V70_SWITCH_ENABLED = False
V70_SWITCH_RANK20_MIN = 3
V70_SWITCH_WR_GAP_MIN = 0.075

# V70.6 CUTOVER SAFE
# V70 is disabled until the live DAY_SEQ reaches this value.
# Set with Streamlit/container environment, e.g. V70_CUTOVER_DAY_SEQ=39.
# Keep 0 to run baseline only. For a clean deployment, set this to the NEXT
# DaySeq and deploy before its Round 1 appears.
try:
    V70_CUTOVER_DAY_SEQ = int(os.environ.get("V70_CUTOVER_DAY_SEQ", "0") or 0)
except Exception:
    V70_CUTOVER_DAY_SEQ = 0

# V71.2 PROFIT-DAY GATE
# Historical audit rule:
#   At the first LIVE decision (R180), count windows whose causal Profit20 > 4.
#   Trade the day only when at least 1 such window exists.
#
# CUTOVER SAFE:
# - Days before V71_HEALTH_GATE_CUTOVER_DAY_SEQ replay exactly as V71 baseline.
# - Default 45 preserves all history through current DaySeq 44 and is intended for a clean
#   next-day deployment starting at DaySeq 45.
# - Override with env V71_HEALTH_GATE_CUTOVER_DAY_SEQ if your next DaySeq differs.
# LIVE-SAFE: fixed deployment boundary. Do not let stale environment variables
# retroactively change Day45+ history.
V71_HEALTH_GATE_CUTOVER_DAY_SEQ = 45

V71_HEALTH_GATE_MIN_WINDOWS = 1
V71_HEALTH_GATE_PROFIT20_GT = 4.0

# V71.3 dynamic window-score cutover.
# Preserve D1-D48 exactly; apply only from DaySeq 49 onward.
# LIVE-SAFE: fixed deployment boundary for the dynamic window score.
V71_WINDOW_REGIME_CUTOVER_DAY_SEQ = 49

V71_WINDOW_REGIME_RECENT10_LT = -5.0
V71_WINDOW_REGIME_P20_WEIGHT = 1.40

V70_BASELINE_DAILY_PROFIT_LOCK = 30.5
V70_LIVE_DAILY_PROFIT_LOCK = 10.0

KEEP_WIN_ROUNDS = 4
DATASET_RESET_ANCHOR_LEN = 32
LIVE_TIMEZONE = "Asia/Phnom_Penh"
STATE_VERSION = "V71_18_2_LIVE101_D49_V1"
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
# V71.4 physical-frontier journal
FRONTIER_JOURNAL_CUTOVER_DAY_SEQ = 49
ENTRY_DEFENSIVE_CUTOVER_DAY_SEQ = 49
STRATEGY_FRONTIER_MODE = "continuous"
DYNAMIC_LOCK_ENABLED = True
DYNAMIC_LOCK_WEAK_TARGET = 2.5
DYNAMIC_LOCK_NORMAL_TARGET = 10.0

def get_dynamic_daily_profit_lock(prior_history):
    """
    Causal day-level lock:
    - If the immediately previous resolved day was negative: target +2.5 today.
    - Otherwise: keep normal +10 target.
    Only prior-day resolved profit is used.
    """
    if not DYNAMIC_LOCK_ENABLED:
        return float(DYNAMIC_LOCK_NORMAL_TARGET)
    hist = list(prior_history or [])
    if hist and float(hist[-1].get("profit", 0.0) or 0.0) < 0.0:
        return float(DYNAMIC_LOCK_WEAK_TARGET)
    return float(DYNAMIC_LOCK_NORMAL_TARGET)

HISTORICAL_MISSING_FRONTIER_POLICY = "logical_recovery"
FRONTIER_JOURNAL_VERSION = "V71_6_FRONTIER_JOURNAL_V2"
FRONTIER_JOURNAL_FILE = os.environ.get(
    "V71_FRONTIER_JOURNAL_FILE", STATE_FILE + ".frontiers.json"
)

# V71.9 verified raw-history profit cache.
# Cache is optimization-only: a miss/corruption always falls back to exact replay.
HISTORY_CACHE_VERSION = "DISABLED_V71_18_1_NO_CACHE"
HISTORY_CACHE_FILE = os.environ.get(
    "V71_HISTORY_CACHE_FILE", STATE_FILE + ".history_cache.json"
)

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
LIVE101_ENABLED = True
LIVE101_CONFIDENCE_MIN = 0.55
LIVE101_WAIT_ROUNDS = 2
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
DAILY_PROFIT_LOCK = 10.0

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

    # V4.1: immutable snapshot captured at the REAL OPEN moment.
    # Never recompute these fields during replay/restart.
    open_confidence: float = 0.0
    open_regime: str = ""
    open_consensus: float = 0.0
    open_required_consensus: float = 0.0
    open_stability: float = 0.0
    open_shadow_profit20: float = 0.0
    open_shadow_wr20: float = 0.0
    # Adaptive physical-bet layer snapshots. Keys are P windows 4..26.
    # Captured at OPEN; never recomputed from future rounds.
    open_shadow_profit_by_n: dict = field(default_factory=dict)
    open_shadow_wr_by_n: dict = field(default_factory=dict)
    open_real_window_profit: float = 0.0
    open_real_window_wr: float = 0.0
    open_real_window_trade_count: int = 0
    open_real_window_loss_streak: int = 0
    open_protection_reason: str = ""
    open_lock_reason: str = ""
    open_day_seq: int = 0
    open_day_date: str = ""
    open_batch_id: str = ""
    open_is_frontier: bool = False


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
    shadow_live_profit_by_n: dict = field(default_factory=dict)
    shadow_live_wr_by_n: dict = field(default_factory=dict)
    real_window_profit: float = 0.0
    real_window_wr: float = 0.0
    real_window_trade_count: int = 0
    real_window_loss_streak: int = 0

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
    # Cross-deploy/display archive. Strategy NEVER reads this field.
    trade_archive: list[TradeRecord] = field(default_factory=list)
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
    window_score_mode: str = "BASE"
    # None = legacy logical-every-round replay; list = observed physical frontiers.
    live_frontiers: Optional[list[int]] = None
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
    # One-shot offline ledger reconstruction from the current data stream.
    # Recovery mode is NEVER used by normal live processing.
    recovery_replay_all_rounds: bool = False
    data_correction_sequential_replay: bool = False
    fast_recovery_mode: bool = False
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
    if not hasattr(ctx, "window_score_mode"):
        ctx.window_score_mode = "BASE"
    if not hasattr(ctx, "live_frontiers"):
        ctx.live_frontiers = None
    if not hasattr(ctx, "round_log") or ctx.round_log is None:
        ctx.round_log = []
    ctx.round_log = list(ctx.round_log)[-300:]
    if not hasattr(ctx, "state_revision"):
        ctx.state_revision = 0
    if not hasattr(ctx, "recovery_replay_all_rounds"):
        ctx.recovery_replay_all_rounds = False
    if not hasattr(ctx, "data_correction_sequential_replay"):
        ctx.data_correction_sequential_replay = False
    if not hasattr(ctx, "fast_recovery_mode"):
        ctx.fast_recovery_mode = False
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
    if not hasattr(ctx, "current_batch_id"):
        ctx.current_batch_id = ""
    if not hasattr(ctx, "current_is_frontier"):
        ctx.current_is_frontier = False

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

DATA_SHEET_NAME = "data"
HISTORY_SHEET_NAME = "history"
MAX_ROUNDS_PER_DAY = 288

# V6 operator/runtime safety. Current-day raw Numbers are still replayed fresh
# on every refresh. Only completed-history replay may be reused when its raw
# fingerprint is byte-for-byte identical.
VERIFIED_HISTORY_REPLAY_MEMO = True
LIVE_STALE_SECONDS = int(os.environ.get("LIVE_STALE_SECONDS", "720") or 720)
VERIFIED_REPLAY_VERSION = "V6_HISTORY_RAW_HASH_1"


def _sheet_csv_url(sheet_name: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
        f"?sheet={sheet_name}&tqx=out:csv&cache={time.time()}"
    )


def _load_live_sheet_df() -> pd.DataFrame:
    """Read ONLY the current-day `data` tab.

    Contract: data contains header + at most 288 round rows. Historical rows
    must never be mixed into the live Number stream.
    """
    if INPUT_CSV_PATH:
        try:
            return pd.read_csv(INPUT_CSV_PATH)
        except Exception as e:
            st.error(f"Load local CSV error: {e}")
            st.stop()
    try:
        df = pd.read_csv(_sheet_csv_url(DATA_SHEET_NAME))
    except Exception as e:
        st.error(f"Load Sheet tab '{DATA_SHEET_NAME}' error: {e}")
        st.stop()
    if len(df) > MAX_ROUNDS_PER_DAY + 5:
        st.error(
            f"LIVE DATA ERROR: tab '{DATA_SHEET_NAME}' has {len(df)} rows. "
            f"Expected at most {MAX_ROUNDS_PER_DAY + 5}. Do not put history in data."
        )
        st.stop()
    return df


def _load_history_sheet_df() -> pd.DataFrame:
    """Read historical days separately; never used as live Number input."""
    if INPUT_CSV_PATH:
        return pd.DataFrame()
    try:
        return pd.read_csv(_sheet_csv_url(HISTORY_SHEET_NAME))
    except Exception as e:
        st.warning(f"History tab '{HISTORY_SHEET_NAME}' unavailable: {e}")
        return pd.DataFrame()



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
        if rr != pos:
            st.error(
                f"LIVE DATA ERROR DaySeq {current_seq}: expected round {pos}, found {raw_r!r}. "
                "Engine stopped; row order must be contiguous."
            )
            st.stop()
        if n is None:
            # A blank tail is normal. A blank/invalid row followed by any valid
            # Number in the same DAY_SEQ is a data gap and must fail-stop rather
            # than silently treating the earlier row as the live frontier.
            later_valid = False
            for j in idxs[pos:]:
                if _parse_number_value(c_number.iloc[j]) is not None:
                    later_valid = True
                    break
            if later_valid:
                st.error(
                    f"LIVE DATA GAP DaySeq {current_seq}: round {pos} is blank/invalid "
                    "but a later round has a Number. Engine stopped."
                )
                st.stop()
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


def _extract_day_seq_snapshot_from_df(df: pd.DataFrame, target_seq: int) -> tuple[str, list[int]]:
    """Extract one DAY_SEQ from an already-fetched immutable Sheet snapshot.

    Used at a day boundary so an app that was offline near midnight can finish
    every still-unprocessed round of DAY_SEQ N before switching to N+1.
    This function NEVER performs another Google read.
    """
    if df.shape[1] < 4 or int(target_seq or 0) <= 0:
        return "", []
    seqs = [_normalize_day_seq(x) for x in df.iloc[:, 2].tolist()]
    idxs = [i for i, x in enumerate(seqs) if x == int(target_seq)]
    if not idxs:
        return "", []
    nums: list[int] = []
    dates: list[str] = []
    for pos, i in enumerate(idxs, start=1):
        raw_r = df.iloc[i, 0]
        try:
            rr = int(float(str(raw_r).replace(",", ".")))
        except Exception:
            rr = -1
        if rr != pos:
            st.error(f"DAY BOUNDARY ERROR DaySeq {target_seq}: expected round {pos}, found {raw_r!r}.")
            st.stop()
        n = _parse_number_value(df.iloc[i, 1])
        if n is None:
            later_valid = any(_parse_number_value(df.iloc[j, 1]) is not None for j in idxs[pos:])
            if later_valid:
                st.error(f"DAY BOUNDARY GAP DaySeq {target_seq}: round {pos} blank/invalid but later Number exists.")
                st.stop()
            break
        nums.append(n)
        d = _parse_date_value(df.iloc[i, 3])
        dates.append(d.isoformat() if d is not None else "")
    nonempty = {d for d in dates if d}
    if len(nonempty) > 1:
        st.error(f"DAY_SEQ {target_seq} has multiple dates: {sorted(nonempty)}")
        st.stop()
    return next(iter(nonempty), ""), nums


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


def load_daily_profit_history_from_sheet() -> list[dict]:
    """Read completed daily P/L from `history`, never from live `data`."""
    try:
        live_df = _load_live_sheet_df()
        if live_df.shape[1] < 3:
            return []
        live_seqs = [_normalize_day_seq(x) for x in live_df.iloc[:, 2].tolist()]
        current_seq = max([x for x in live_seqs if x is not None], default=0)
        history_df = _load_history_sheet_df()
        if history_df.empty or history_df.shape[1] < 5:
            return []
        return _get_daily_history_from_df_v35(history_df, current_seq)
    except Exception:
        return []



def _merge_sheet_daily_history_into_ctx(ctx: EngineContext) -> EngineContext:
    """V4.3.2: persistent ledger/state history is authoritative.

    Google `history` is intentionally NOT merged into decision state on a live
    refresh.  This prevents a delayed/formula-stale history tab from changing
    multi-day protection.  Historical Sheet data may still be displayed or
    audited explicitly, but never overwrites ctx.daily_profit_history here.
    """
    ensure_ctx_fields(ctx)
    clean = []
    for item in list(getattr(ctx, "daily_profit_history", []) or []):
        if not isinstance(item, dict):
            continue
        try:
            seq = int(item.get("day_seq"))
            clean.append({
                "day_seq": seq,
                "day_id": str(item.get("day_id", seq)),
                "profit": round(float(item.get("profit", 0.0)), 2),
                **({"source": item.get("source")} if item.get("source") else {}),
            })
        except Exception:
            continue
    by_seq = {int(x["day_seq"]): x for x in clean}
    ctx.daily_profit_history = [by_seq[k] for k in sorted(by_seq)][-10:]
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


def v70_active_for_day(day_seq: int) -> bool:
    """V71: V70 switch is intentionally disabled.

    Kept only as a compatibility helper so the surrounding engine code does not
    need a larger refactor.  Always returns False.
    """
    return False



def _validate_postcutover_completed_day(
    *,
    seq: int,
    numbers: list[int],
    frontier_journal: Optional[dict],
) -> dict:
    """Validate that a post-cutover historical day is safe to replay.

    Distinguishes three cases:
    1) historical raw data itself is incomplete -> FAIL CLOSED;
    2) physical journal is inconsistent with raw history -> FAIL CLOSED;
    3) raw day is complete enough but app was never physically observed at/after
       LIVE_START_ROUND -> legitimate physical-live profit 0, with explicit diagnostic.
    """
    seq = int(seq or 0)
    nums = list(numbers or [])

    if seq < int(FRONTIER_JOURNAL_CUTOVER_DAY_SEQ):
        return {
            "status": "LEGACY_PRE_CUTOVER",
            "raw_len": len(nums),
            "max_seen": len(nums),
            "frontiers": None,
        }

    if len(nums) < int(LIVE_START_ROUND):
        raise ValueError(
            f"HISTORICAL DAY INCOMPLETE: DaySeq {seq} has only {len(nums)} raw rounds, "
            f"below LIVE_START_ROUND={LIVE_START_ROUND}. "
            "LIVE is paused instead of silently recording profit 0."
        )

    journal = _normalize_frontier_journal(frontier_journal or {})
    key = str(seq)
    if key not in journal.get("days", {}):
        if HISTORICAL_MISSING_FRONTIER_POLICY == "logical_recovery":
            return {
                "status": "LOGICAL_RECOVERY_NO_JOURNAL",
                "raw_len": len(nums),
                "max_seen": 0,
                "frontiers": None,
            }
        raise ValueError(
            f"FRONTIER JOURNAL NOT READY: missing DaySeq {seq}. "
            "LIVE is fail-closed to prevent retrospective OPENs."
        )

    day = dict(journal["days"].get(key, {}) or {})
    frontiers = sorted(set(
        int(x)
        for x in list(day.get("frontiers", []) or [])
        if int(x) >= int(LIVE_START_ROUND)
    ))
    max_seen = int(day.get("max_seen", 0) or 0)

    if max_seen > len(nums):
        raise ValueError(
            f"HISTORY/JOURNAL REGRESSION DaySeq {seq}: journal max_seen={max_seen} "
            f"but history has only {len(nums)} contiguous rounds. "
            "History copy is not ready; LIVE is paused."
        )

    if frontiers and max(frontiers) > len(nums):
        raise ValueError(
            f"HISTORY/JOURNAL FRONTIER MISMATCH DaySeq {seq}: "
            f"last frontier={max(frontiers)} but history length={len(nums)}. "
            "LIVE is paused."
        )

    if max_seen >= int(LIVE_START_ROUND) and not frontiers:
        raise ValueError(
            f"FRONTIER JOURNAL INCONSISTENT DaySeq {seq}: max_seen={max_seen} "
            f"but no frontier >= R{LIVE_START_ROUND}. LIVE is paused."
        )

    if max_seen < int(LIVE_START_ROUND):
        if HISTORICAL_MISSING_FRONTIER_POLICY == "logical_recovery":
            return {
                "status": "LOGICAL_RECOVERY_NO_LIVE_FRONTIER",
                "raw_len": len(nums),
                "max_seen": max_seen,
                "frontiers": None,
            }
        return {
            "status": "NO_PHYSICAL_LIVE_AFTER_R180",
            "raw_len": len(nums),
            "max_seen": max_seen,
            "frontiers": [],
        }

    return {
        "status": "PHYSICAL_LIVE_OK",
        "raw_len": len(nums),
        "max_seen": max_seen,
        "frontiers": frontiers,
    }


def _historical_day_diagnostic_message(seq: int, check: dict) -> str:
    status = str(check.get("status", "") or "")
    if status == "NO_PHYSICAL_LIVE_AFTER_R180":
        return (
            f"D{int(seq)} physical-live profit is 0 by design: "
            f"history has {int(check.get('raw_len', 0))} raw rounds, "
            f"but the app was only physically observed through R"
            f"{int(check.get('max_seen', 0))}, before LIVE_START R{LIVE_START_ROUND}."
        )
    if status == "LOGICAL_RECOVERY_NO_LIVE_FRONTIER":
        return (
            f"D{int(seq)} RECOVERED_LOGICAL: history has "
            f"{int(check.get('raw_len', 0))} raw rounds but physical journal only reached "
            f"R{int(check.get('max_seen', 0))}. Profit is rebuilt from raw Numbers, "
            "not claimed as observed physical-live profit."
        )
    if status == "LOGICAL_RECOVERY_NO_JOURNAL":
        return (
            f"D{int(seq)} RECOVERED_LOGICAL: no physical frontier journal exists. "
            f"Profit is rebuilt from {int(check.get('raw_len', 0))} raw Numbers, "
            "not claimed as observed physical-live profit."
        )
    return ""


def _raw_history_seed_from_df(history_df: pd.DataFrame, current_seq: int, frontier_journal: Optional[dict] = None) -> list[dict]:
    """Rebuild prior-day profit directly from raw Numbers on every refresh.

    NO-CACHE invariant:
    - never read cached historical profit
    - never write cached historical profit
    - replay Day1..Day(N-1) causally from raw Numbers every refresh
    - current day remains stateless R1->CURRENT
    """
    current_seq = int(current_seq or 0)
    if current_seq <= 1:
        try:
            st.caption("HISTORY CACHE: DISABLED | full raw replay every refresh")
        except Exception:
            pass
        return []

    raw_list = _validated_numbers_by_day(history_df, current_seq)
    raw_by_seq = {
        int(seq): (str(day_id or seq), list(nums))
        for seq, day_id, nums in raw_list
    }

    required = list(range(1, current_seq))
    missing = [seq for seq in required if seq not in raw_by_seq]
    if missing:
        raise ValueError(
            "RAW HISTORY REPLAY NOT READY: missing completed raw DaySeq="
            f"{missing}. LIVE is fail-closed."
        )

    resolved: list[dict] = []
    replayed_days = 0
    recovered_logical_days: list[int] = []
    # V117.5 betting-layer prior P/L is rebuilt inside this SAME raw replay.
    # No second historical replay and no cache/session dependency.
    _v1175_prev_bet_profit = 0.0
    _adaptive_prev_bet_profit = 0.0

    for seq in required:
        day_id, nums = raw_by_seq[seq]

        _frontiers = None
        _postcutover_check = None
        if int(seq) >= FRONTIER_JOURNAL_CUTOVER_DAY_SEQ:
            _postcutover_check = _validate_postcutover_completed_day(
                seq=int(seq),
                numbers=list(nums),
                frontier_journal=frontier_journal or {},
            )
            _checked_frontiers = _postcutover_check.get("frontiers", [])
            _frontiers = None if _checked_frontiers is None else list(_checked_frontiers or [])

            _diag_msg = _historical_day_diagnostic_message(int(seq), _postcutover_check)
            _diag_status = str(_postcutover_check.get("status", "") or "")
            if _diag_status.startswith("LOGICAL_RECOVERY_"):
                recovered_logical_days.append(int(seq))
            elif _diag_msg:
                try:
                    st.warning(_diag_msg)
                except Exception:
                    pass

        _recovery_status = (
            str(_postcutover_check.get("status", "") or "")
            if _postcutover_check is not None else ""
        )
        _recovered_logical = _recovery_status.startswith("LOGICAL_RECOVERY_")

        _day_profit_lock = get_dynamic_daily_profit_lock(resolved[-10:])

        profit, _ledger, _diag = _replay_one_day_stateless_audit(
            nums,
            resolved[-10:],
            seq,
            day_id,
            v70_enabled=False,
            daily_profit_lock=_day_profit_lock,
            allowed_frontiers=_frontiers,
        )
        profit = round(float(profit), 2)

        _logical_profit = None
        if int(seq) >= int(FRONTIER_JOURNAL_CUTOVER_DAY_SEQ):
            _logical_profit, _logical_ledger = _replay_one_day_stateless(
                nums,
                resolved[-10:],
                seq,
                day_id,
                v70_enabled=False,
                daily_profit_lock=_day_profit_lock,
                allowed_frontiers=None,
            )
            _logical_profit = round(float(_logical_profit), 2)

            if STRATEGY_FRONTIER_MODE == "continuous":
                _physical_profit = profit
                profit = _logical_profit
            else:
                _physical_profit = profit
        else:
            _physical_profit = None

        replayed_days += 1
        source = "RECOVERED_LOGICAL" if _recovered_logical else "RAW_REPLAY_NO_CACHE"

        # V117.5 SHADOW P/L piggybacks on the already-computed engine ledger.
        # In continuous strategy mode, use the logical ledger because that is
        # the same ledger/path used by the audited V117.5 candidate.
        _v1175_bet_ledger = _ledger
        if (
            int(seq) >= int(FRONTIER_JOURNAL_CUTOVER_DAY_SEQ)
            and STRATEGY_FRONTIER_MODE == "continuous"
            and _logical_profit is not None
        ):
            _v1175_bet_ledger = _logical_ledger
        _v1175_bet_profit_value = _v1175_bet_profit(
            _v1175_bet_ledger,
            _v1175_prev_bet_profit,
        )
        _adaptive_choices = _adaptive_select_choices(resolved) if ADAPTIVE_SAFE_ENABLED else _adaptive_defaults()
        _adaptive_rows = _adaptive_apply_bet_filter(_v1175_bet_ledger, _adaptive_prev_bet_profit, _adaptive_choices)
        _adaptive_profit_value = round(sum(float(_r.get("bet_profit",0.0) or 0.0) for _r in _adaptive_rows),2)
        _adaptive_cf = _adaptive_counterfactual(_v1175_bet_ledger, _adaptive_prev_bet_profit)

        resolved.append({
            "day_seq": int(seq),
            "day_id": str(day_id or seq),
            "profit": profit,
            "daily_profit_lock": float(_day_profit_lock),
            "physical_profit": _physical_profit,
            "logical_profit": _logical_profit,
            "source": (
                "CONTINUOUS_STRATEGY_NO_CACHE"
                if int(seq) >= int(FRONTIER_JOURNAL_CUTOVER_DAY_SEQ)
                and STRATEGY_FRONTIER_MODE == "continuous"
                else source
            ),
            "diag": dict(_diag or {}),
            "bet_profit_v1175": round(float(_v1175_bet_profit_value), 2),
            "adaptive_bet_profit": round(float(_adaptive_profit_value), 2),
            "adaptive_choices": dict(_adaptive_choices),
            "adaptive_cf": dict(_adaptive_cf),
        })
        _v1175_prev_bet_profit = float(_v1175_bet_profit_value)
        _adaptive_prev_bet_profit = float(_adaptive_profit_value)

    try:
        if recovered_logical_days:
            _first = min(recovered_logical_days)
            _last = max(recovered_logical_days)
            _span = (
                f"D{_first}-D{_last}"
                if recovered_logical_days == list(range(_first, _last + 1))
                else ",".join(f"D{x}" for x in recovered_logical_days)
            )
            st.info(
                "ENGINE FRONTIER JOURNAL (AUDIT ONLY): missing/incomplete for "
                f"{_span}. Continuous strategy rebuilt from raw Numbers; "
                "continuous engine strategy is rebuilt from raw Numbers; adaptive actual BET/SKIP is unaffected."
            )
        st.caption(
            f"HISTORY CACHE: DISABLED | raw replayed={replayed_days} "
            f"| required={len(required)} | every refresh"
        )
    except Exception:
        pass

    return resolved[-10:]

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


def make_history_signature(days: list[tuple[int, str, list[int]]]) -> str:
    """Hash only raw causal history inputs: DaySeq/date/Numbers."""
    parts = []
    for seq, day_id, nums in list(days or []):
        parts.append(
            f"{int(seq)}|{str(day_id or '')}|{make_numbers_signature(list(nums or []))}"
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def make_engine_ledger_signature(ctx) -> str:
    """Compact deterministic hash of the current reconstructed engine ledger."""
    rows = []
    for t in list(getattr(ctx, "trade_history", []) or []):
        rows.append(
            "|".join([
                str(int(getattr(t, "round_id", 0) or 0)),
                str(int(getattr(t, "predict", 0) or 0)),
                str(getattr(t, "status", "") or ""),
                f"{float(getattr(t, 'profit', 0.0) or 0.0):.2f}",
                str(getattr(t, "locked_window", "") or ""),
                str(getattr(t, "open_lock_reason", "") or ""),
            ])
        )
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def _short_hash(value: str) -> str:
    s = str(value or "")
    return s[:10] if s else "NA"


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
        _hist = list(getattr(self.ctx, "daily_profit_history", []) or [])[-10:]
        _profits = [float(_x.get("profit", 0.0) or 0.0) for _x in _hist]

        _r3 = sum(_profits[-3:]) if _profits else 0.0
        _r5 = sum(_profits[-5:]) if _profits else 0.0
        _r10 = sum(_profits[-10:]) if _profits else 0.0

        _day_seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)
        _meta_enabled = _day_seq >= 49

        # V71.6 causal meta-selector:
        # HIGH when recent 5-day equity is weak, OR when the broader 10-day
        # regime remains positive but the last 3 days have stalled/turned weak.
        _use_high = bool(
            _meta_enabled
            and (
                _r5 < 0.0
                or (_r10 > 0.0 and _r3 <= 0.0)
            )
        )

        _hist_p20_w = 1.30 if _use_high else 0.80
        _hist_wr20_w = 4.00 if _use_high else 3.00
        self.ctx.window_score_mode = "HIGH" if _use_high else "BASE"

        return round(
            1.20 * obj.live_profit20
            + 8.00 * obj.live_wr20
            + _hist_p20_w * obj.profit20
            + _hist_wr20_w * wr20
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

        _snapshot_hits = list(locked_obj.live_hit_history) if locked_obj is not None else []
        _snapshot_p_by_n = {}
        _snapshot_wr_by_n = {}
        for _n in range(4, 27):
            _tail = _snapshot_hits[-_n:]
            _snapshot_p_by_n[str(_n)] = round(sum(WIN_GROUP if bool(_x) else LOSS_GROUP for _x in _tail), 3) if _tail else 0.0
            _snapshot_wr_by_n[str(_n)] = round(sum(1 for _x in _tail if bool(_x)) / len(_tail), 3) if _tail else 0.0

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
            shadow_live_profit_by_n=_snapshot_p_by_n,
            shadow_live_wr_by_n=_snapshot_wr_by_n,
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

        _frontiers = sorted(set(
            int(x) for x in (getattr(self.ctx, "live_frontiers", None) or [])
        ))
        _prev_frontiers = [x for x in _frontiers if x < int(round_id)]
        _frontier_gap = (
            int(round_id) - max(_prev_frontiers)
            if _prev_frontiers else 1
        )

        keep_win_lock = (
            int(getattr(self.ctx, "keep_win_lock_until", 0) or 0) >= int(round_id)
            and locked_obj is not None
            and locked_obj.next_group is not None
        )

        if locked_obj is None:
            relock_needed = True
            lock_reason = "NO_LOCK"
        elif keep_win_lock and _frontier_gap < 4:
            relock_needed = False
            lock_reason = "KEEP_AFTER_WIN_5R"
        elif (
            len(locked_obj.live_hit_history) > 0
            and int(locked_obj.live_loss_streak) >= (
                1 if _frontier_gap >= 4 else LIVE_RELOCK_LOSS_STREAK
            )
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
            if _frontier_gap >= 4:
                _gap_candidates = []
                for _w, _obj in self.window_engine.state.items():
                    if _obj.next_group is None or self.known_bad_window(_w):
                        continue

                    _h20 = list(_obj.hit_history)[-20:]
                    _wr20 = round(sum(_h20) / len(_h20), 3) if _h20 else 0.0

                    if (
                        _obj.profit20 <= FALLBACK_MIN_PROFIT20
                        and _obj.live_profit20 < MIN_SHADOW_PROFIT20_FOR_TEST
                    ):
                        continue
                    if (
                        _wr20 < FALLBACK_MIN_WR20
                        and _obj.live_wr20 < MIN_SHADOW_WR20_FOR_TEST
                    ):
                        continue
                    if int(_obj.loss_streak) > FALLBACK_MAX_LOSS_STREAK:
                        continue

                    _gap_candidates.append(
                        (
                            _obj.profit20,
                            _wr20,
                            self.selection_score(_w, _obj),
                            -int(_obj.loss_streak),
                            _w,
                            _obj,
                        )
                    )

                if _gap_candidates:
                    _gap_candidates.sort(reverse=True)
                    _, _, _, _, candidate_w, candidate_obj = _gap_candidates[0]
                    candidate_reason = "SEVERE_GAP4_P20_RELOCK"
                else:
                    candidate_w, candidate_obj, candidate_reason = self.choose_relock_candidate(top_rows)
            else:
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

        _live_hits = list(locked_obj.live_hit_history) if locked_obj is not None else []
        _p_by_n = {}
        _wr_by_n = {}
        for _n in range(4, 27):
            _tail = _live_hits[-_n:]
            _p_by_n[str(_n)] = round(sum(WIN_GROUP if bool(_x) else LOSS_GROUP for _x in _tail), 3) if _tail else 0.0
            _wr_by_n[str(_n)] = round(sum(1 for _x in _tail if bool(_x)) / len(_tail), 3) if _tail else 0.0

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
            shadow_live_profit_by_n=_p_by_n,
            shadow_live_wr_by_n=_wr_by_n,
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
        # V71.18.2 LIVE101 audited rule:
        # settled pattern 101 + candidate confidence >= 0.55 => suppress entries
        # on the 101 settlement frontier and the immediately following frontier.
        # Causal only: uses settled current-day Trade History and current signal.
        if LIVE101_ENABLED:
            _settled101 = [
                t for t in getattr(self.ctx, "trade_history", [])
                if str(getattr(t, "status", "")).upper() in {"WIN", "LOSS"}
            ]
            _bits101 = "".join(
                "1" if str(getattr(t, "status", "")).upper() == "WIN" else "0"
                for t in _settled101
            )
            if (
                _bits101.endswith("101")
                and float(confidence_score or 0.0) >= float(LIVE101_CONFIDENCE_MIN)
            ):
                _last101_settle = int(
                    getattr(_settled101[-1], "settle_round", 0) or 0
                )
                if int(round_id) <= _last101_settle + int(LIVE101_WAIT_ROUNDS) - 1:
                    self.ctx.open_reason = (
                        f"LIVE101_WAIT{int(LIVE101_WAIT_ROUNDS)}_"
                        f"CONF_GE_{float(LIVE101_CONFIDENCE_MIN):.2f}"
                    )
                    return
        self.ctx.open_reason = ""

        if round_id < LIVE_START_ROUND:
            self.ctx.open_reason = "BEFORE_LIVE_START"
            return

        # LIVE-SAFE HARD GUARD:
        # _apply_decision() normally blocks at stop/target through ProtectionEngine.
        # Re-check here as defense-in-depth for crash/resume or stale decision state.
        _daily_stop, _daily_reason = self.daily_stop_status()
        if _daily_stop:
            self.ctx.daily_stop_active = True
            self.ctx.daily_stop_reason = _daily_reason
            self.ctx.open_reason = _daily_reason
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
            settle_round=None,
            open_confidence=float(confidence_score or 0.0),
            open_regime=str(getattr(signal, "regime", "") or ""),
            open_consensus=float(getattr(signal, "consensus", 0.0) or 0.0),
            open_required_consensus=float(getattr(signal, "required_consensus", 0.0) or 0.0),
            open_stability=float(getattr(signal, "stability", 0.0) or 0.0),
            open_shadow_profit20=float(getattr(signal, "shadow_live_profit20", getattr(signal, "live_profit20", 0.0)) or 0.0),
            open_shadow_wr20=float(getattr(signal, "shadow_live_wr20", getattr(signal, "live_wr20", 0.0)) or 0.0),
            open_shadow_profit_by_n=dict(getattr(signal, "shadow_live_profit_by_n", {}) or {}),
            open_shadow_wr_by_n=dict(getattr(signal, "shadow_live_wr_by_n", {}) or {}),
            open_real_window_profit=float(getattr(signal, "real_window_profit", 0.0) or 0.0),
            open_real_window_wr=float(getattr(signal, "real_window_wr", 0.0) or 0.0),
            open_real_window_trade_count=int(getattr(signal, "real_window_trade_count", 0) or 0),
            open_real_window_loss_streak=int(getattr(signal, "real_window_loss_streak", 0) or 0),
            open_protection_reason=str(getattr(self.ctx, "protection_reason", "") or ""),
            open_lock_reason=str(getattr(signal, "lock_reason", getattr(self.ctx, "lock_reason", "")) or ""),
            open_day_seq=int(getattr(self.ctx, "live_day_seq", 0) or 0),
            open_day_date=str(getattr(self.ctx, "live_day_date", "") or ""),
            open_batch_id=str(getattr(self.ctx, "current_batch_id", "") or ""),
            open_is_frontier=bool(getattr(self.ctx, "current_is_frontier", False)),
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
            # ADAPTIVE SAFE V3 NO-CACHE: never synthesize a settled record without the
            # immutable OPEN snapshots required by adaptive P4..P26 decisions.
            self.ctx.open_reason = "PENDING_RECORD_MISSING_FAIL_CLOSED"
            raise RuntimeError(
                "PENDING RECORD MISSING: original TradeRecord snapshot is unavailable. "
                "LIVE stopped to preserve deterministic adaptive replay."
            )

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

        daily_profit_lock = float(getattr(self.ctx, "daily_profit_lock_override", DAILY_PROFIT_LOCK))
        if total_profit >= daily_profit_lock:
            return True, "DAILY_PROFIT_LOCK"

        return False, ""

    def snapshot(self) -> dict[str, Any]:
        # Display must be derived from the actual current ledger, not from a flag
        # that is updated only when a READY signal passes through ProtectionEngine.
        _stop_now, _stop_reason_now = self.daily_stop_status()
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
            "daily_stop_active": bool(_stop_now),
            "daily_stop_reason": str(_stop_reason_now or ""),
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
        st.title("🚀 ADAPTIVE SAFE LIVE V8 COMPACT")
        st.caption("OPERATOR UI | ADAPTIVE ACTUAL BET/SKIP | ENGINE CORE UNCHANGED | NO CACHE")
        st.caption("LEGEND: ENGINE = strategy calculation | FRONTIER = old engine journal audit only | ADAPTIVE = actual BET/SKIP layer")

    def render_adaptive_operator_action(self) -> None:
        """Single authoritative physical BET/SKIP instruction."""
        if not ADAPTIVE_SAFE_ENABLED:
            st.error("ADAPTIVE SAFE is disabled. No physical BET instruction is available.")
            return
        try:
            hist = list(getattr(self.ctx, "daily_profit_history", []) or [])
            choices = _adaptive_select_choices(hist)
            prev_bet = float(hist[-1].get("adaptive_bet_profit", 0.0) or 0.0) if hist else 0.0
            rows = _adaptive_apply_bet_filter(
                list(getattr(self.ctx, "trade_history", []) or []),
                prev_bet,
                choices,
            )
            today_pnl = round(
                sum(float(r.get("bet_profit", 0.0) or 0.0) for r in rows),
                2,
            )
            current_round = int(getattr(self.ctx, "last_length", 0) or 0)
            pending_round = int(getattr(self.ctx, "pending_round", -1) or -1)
            pending_group = getattr(self.ctx, "pending_trade", None)

            st.markdown("## 🎯 LIVE ACTION — BET / SKIP / WAIT")
            st.caption("AUTHORITATIVE LIVE PANEL • fresh raw Numbers → verified replay → adaptive BET/SKIP")
            st.caption(
                f"DAY={int(getattr(self.ctx,'live_day_seq',0) or 0)} | "
                f"ROUND={current_round} | PREV ADAPTIVE P/L={prev_bet:+.1f} | "
                f"TODAY ADAPTIVE P/L={today_pnl:+.1f} | "
                f"G1=P{choices.get('G1')} | G2=WR{choices.get('G2')} | "
                f"G3={choices.get('G3')} | G4={choices.get('G4')}"
            )
            _raw_age = float(getattr(self.ctx, "live_raw_observed_age_seconds", 0.0) or 0.0)
            _raw_stale = bool(getattr(self.ctx, "live_raw_is_stale", False))
            st.caption(
                "STATUS: "
                f"RAW OK ({_short_hash(getattr(self.ctx,'live_raw_signature',''))}) | "
                f"HIST OK ({_short_hash(getattr(self.ctx,'live_history_signature',''))}) | "
                f"ENGINE OK ({_short_hash(getattr(self.ctx,'live_engine_signature',''))}) | "
                f"ADAPT OK ({_short_hash(getattr(self.ctx,'live_adaptive_choice_signature',''))}) | "
                f"AGE {int(_raw_age)}s | "
                f"HIST {'REUSED' if bool(getattr(self.ctx,'live_history_replay_reused',False)) else 'FRESH'}"
            )

            if _raw_stale:
                st.error(
                    f"DATA STALE: raw Numbers have not changed for ~{int(_raw_age)}s "
                    f"(limit={LIVE_STALE_SECONDS}s). CURRENT ACTION: WAIT / DO NOT BET."
                )
                return

            if current_round >= 288:
                st.success(
                    f"✅ DAY COMPLETE — WAIT FOR NEXT DAY  |  "
                    f"R{current_round}/288  |  TODAY P/L {today_pnl:+.1f}"
                )
                return

            current = None
            # NO-CACHE invariant: current-day adaptive features must come from the
            # freshly replayed TradeRecord objects in this Streamlit run.
            if pending_group is not None and pending_round >= 0:
                _pending_record = None
                if (
                    self.ctx.pending_index is not None
                    and 0 <= int(self.ctx.pending_index) < len(self.ctx.trade_history)
                ):
                    _pending_record = self.ctx.trade_history[int(self.ctx.pending_index)]
                if _pending_record is None:
                    st.error("NO-CACHE INVARIANT ERROR: pending TradeRecord missing after raw replay.")
                    st.stop()
                _pmap = dict(getattr(_pending_record, "open_shadow_profit_by_n", {}) or {})
                _wrmap = dict(getattr(_pending_record, "open_shadow_wr_by_n", {}) or {})
                if not _pmap or not _wrmap:
                    st.error(
                        "NO-CACHE INVARIANT ERROR: adaptive P/WR maps were not rebuilt "
                        "from fresh raw Numbers in this run."
                    )
                    st.stop()
                for row in reversed(rows):
                    if (
                        int(row.get("open_round", -999) or -999) == pending_round
                        and int(row.get("group", 0) or 0) == int(pending_group)
                        and str(row.get("status", "") or "").upper() == "PENDING"
                    ):
                        current = row
                        break

            if current is None:
                st.info(
                    "⏸️ CURRENT ACTION: WAIT — no valid pending adaptive trade."
                )
                return

            action = str(current.get("bet_action", "SKIP") or "SKIP").upper()
            group = int(current.get("group", 0) or 0)
            reason = str(current.get("bet_skip_reason", "") or "")
            target_round = pending_round + 1
            option = current.get("adaptive_option", "")

            # V6 action-expiry + self-check gate.
            # A physical instruction is valid only immediately after its OPEN round
            # and only for the very next round.
            _self_checks = {
                "pending_matches_current_round": int(pending_round) == int(current_round),
                "target_in_day": 1 <= int(target_round) <= MAX_ROUNDS_PER_DAY,
                "raw_not_stale": not bool(getattr(self.ctx, "live_raw_is_stale", False)),
                "fresh_pmap": bool(_pmap),
                "fresh_wrmap": bool(_wrmap),
                "raw_hash_present": bool(str(getattr(self.ctx, "live_raw_signature", "") or "")),
                "engine_hash_present": bool(str(getattr(self.ctx, "live_engine_signature", "") or "")),
                "adaptive_hash_present": bool(str(getattr(self.ctx, "live_adaptive_choice_signature", "") or "")),
            }
            _failed = [k for k, ok in _self_checks.items() if not ok]
            if _failed:
                st.error(
                    "LIVE SELF-CHECK FAILED: "
                    + ", ".join(_failed)
                    + ". CURRENT ACTION: WAIT / DO NOT BET."
                )
                return

            st.caption(
                f"ACTION VALID FOR R{target_round} ONLY | "
                f"OPEN R{pending_round} | SELF-CHECK=PASS"
            )

            if action == "BET":
                st.success(
                    f"✅ CURRENT ACTION: BET G{group} → R{target_round}  |  "
                    f"option={option}  |  {reason}"
                )
            else:
                st.warning(
                    f"⛔ CURRENT ACTION: SKIP R{target_round}  |  "
                    f"ENGINE G{group}  |  option={option}  |  {reason}"
                )
        except Exception as exc:
            st.error(f"ADAPTIVE OPERATOR ACTION FAIL-CLOSED: {exc}")
            st.stop()

    def render_signal(self, signal: SignalRecord, confidence_score: float) -> None:
        color = "#00aa00" if signal.state == "READY" else "#555555"

        current_round = self.ctx.last_length
        day_complete = int(current_round or 0) >= 288
        target_round = None if day_complete else int(current_round or 0) + 1

        # UI-only time labels. These values never enter the trading engine.
        current_time, target_time = get_current_target_time_display_only(current_round)

        if day_complete:
            title = "ENGINE DAY COMPLETE — DIAGNOSTIC ONLY"
            action = "WAIT FOR NEXT DAY"
            target_round_text = "DAY COMPLETE"
            target_time = "--:--"
        else:
            title = "ENGINE SIGNAL — DIAGNOSTIC ONLY" if signal.state == "READY" else "ENGINE WAIT"
            action = (
                f"ENGINE GROUP = {signal.next_group}"
                if signal.next_group is not None
                else "ENGINE GROUP = NONE"
            )
            target_round_text = str(target_round)

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
CURRENT ROUND = {current_round} → TARGET = {target_round_text}<br>
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
        c1.metric("ENGINE Total P/L", snap["total_profit"])
        c2.metric("ENGINE P20", snap["profit20"])
        c3.metric("ENGINE WR20", snap["wr20"])
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
        c6.metric("ENGINE Profit", last.profit)

    def render_current_trade(self) -> None:
        st.subheader("Current Trade")

        if self.ctx.pending_trade is None:
            st.info("No pending ENGINE trade. Do not place a bet unless the ADAPTIVE OPERATOR ACTION panel says BET.")
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
        c4.metric("Engine Group", self.ctx.pending_trade)
        c5.metric("Open CONF", round(float(getattr(self.ctx, "pending_confidence", 0.0)), 3))
        c6.metric("Status", "WAIT RESULT")

        st.caption(
            f"This is the pending ENGINE trade opened after round {self.ctx.pending_round}. "
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

        # V4.4.8 PROFIT/LEDGER SINGLE SOURCE:
        # In stateless mode the reconstructed current-day trade_history is the
        # only authoritative ledger shown to the operator. Do not merge legacy
        # persistent archives into the live table, because that can make the UI
        # appear to contain trades/profit that did not come from this replay.
        archive_rows = (
            list(self.ctx.trade_history)
            if STATELESS_REPLAY_LIVE
            else merge_trade_archive(self.ctx)
        )
        # ADAPTIVE SAFE LIVE: physical BET/SKIP only; engine state remains unchanged.
        if ADAPTIVE_SAFE_ENABLED:
            try:
                _hist_a=list(getattr(self.ctx,"daily_profit_history",[]) or []); _choices_a=_adaptive_select_choices(_hist_a)
                _prev_a=float(_hist_a[-1].get("adaptive_bet_profit",0.0) or 0.0) if _hist_a else 0.0
                _rows_a=_adaptive_apply_bet_filter(list(self.ctx.trade_history),_prev_a,_choices_a)
                _pnl_a=round(sum(float(_r.get("bet_profit",0.0) or 0.0) for _r in _rows_a),2)
                st.subheader("Adaptive Bet Audit (ledger only)")
                st.caption(f"DAY={int(getattr(self.ctx,'live_day_seq',0) or 0)} | ROUND={int(getattr(self.ctx,'last_length',0) or 0)} | PREV BET P/L={_prev_a:+.1f} | TODAY BET P/L={_pnl_a:+.1f} | G1=P{_choices_a.get('G1')} | G2=WR{_choices_a.get('G2')} | G3={_choices_a.get('G3')} | G4={_choices_a.get('G4')} | ENGINE UNCHANGED")
                _la=_rows_a[-1] if _rows_a else None
                if _la is None: st.info("NO ADAPTIVE LEDGER ROW YET")
                else:
                    _m=f"R{int(_la.get('open_round',0))} | G{int(_la.get('group',0))} | {_la.get('bet_action')} | {_la.get('status')} | {_la.get('bet_skip_reason')}"
                    st.caption("LATEST LEDGER ROW (AUDIT ONLY): " + _m)
            except Exception as _e:
                st.error(f"ADAPTIVE SAFE LIVE FAIL-CLOSED: {_e}"); st.stop()

        # V117.5 FAST LIVE V2: always show operator status BEFORE any
        # early return from an empty trade ledger.
        if V1175_BET_FILTER_ENABLED:
            try:
                _seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)
                _round_now = int(getattr(self.ctx, "last_length", 0) or 0)
                _prior_hist = list(getattr(self.ctx, "daily_profit_history", []) or [])
                _prev_bet_profit = (
                    float(_prior_hist[-1].get("bet_profit_v1175", 0.0) or 0.0)
                    if _prior_hist else 0.0
                )

                _bet_rows = _v1175_apply_bet_filter(
                    list(self.ctx.trade_history),
                    _prev_bet_profit,
                )
                _settled_bet_profit = round(
                    sum(float(r.get("bet_profit", 0.0) or 0.0) for r in _bet_rows),
                    2,
                )

                st.subheader("V117.5 Baseline Shadow (diagnostic only)")
                st.caption(
                    f"DAY={_seq} | ROUND={_round_now} | "
                    f"PREV BET P/L={_prev_bet_profit:+.1f} | "
                    f"TODAY BET P/L={_settled_bet_profit:+.1f} | "
                    "ENGINE STATE UNCHANGED"
                )

                _latest = _bet_rows[-1] if _bet_rows else None
                if _latest is None:
                    _live_start = int(globals().get("LIVE_START_ROUND", 180) or 180)
                    if _round_now < _live_start:
                        st.info(
                            f"NO ENGINE SIGNAL YET | current round={_round_now} | "
                            f"live starts from R{_live_start}"
                        )
                    else:
                        st.info(
                            f"NO ENGINE TRADE YET AT R{_round_now} | "
                            "engine has not opened a qualifying trade"
                        )
                else:
                    _action = str(_latest.get("bet_action", "SKIP"))
                    _reason = str(_latest.get("bet_skip_reason", ""))
                    _grp = int(_latest.get("group", 0) or 0)
                    _rnd = int(_latest.get("open_round", 0) or 0)
                    _status = str(_latest.get("status", "") or "")
                    if _action == "BET":
                        st.success(
                            f"R{_rnd} | G{_grp} | BET | {_status} | {_reason}"
                        )
                    else:
                        st.warning(
                            f"R{_rnd} | G{_grp} | SKIP | {_status} | {_reason}"
                        )
            except Exception as _bet_err:
                st.warning(f"V117.5 FAST LIVE unavailable: {_bet_err}")

        if not archive_rows:
            st.info("Trade History: No engine trades yet")
            return

        df = pd.DataFrame(
            [
                {
                    "day_seq": int(getattr(x, "open_day_seq", 0) or 0),
                    "date": str(getattr(x, "open_day_date", "") or ""),
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
                for x in archive_rows
            ]
        )

        if STATELESS_REPLAY_LIVE:
            st.caption(
                f"STATELESS CURRENT-DAY LEDGER | total={len(archive_rows)} | "
                f"settled={integrity['settled_count']} | pending={integrity['pending_count']} | "
                f"profit={integrity['profit']:+.1f}"
            )
        else:
            st.caption(
                f"PERSISTENT TRADE ARCHIVE | total={len(archive_rows)} | "
                f"current-day={len(self.ctx.trade_history)} | survives code deploy/reset/new day"
            )
        st.dataframe(df, use_container_width=True, hide_index=True)

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
        st.subheader("ENGINE Equity Curve")
        ledger_profit = round(
            sum(float(x.profit or 0.0) for x in self.ctx.trade_history if x.hit is not None), 2
        )
        st.caption(
            f"ENGINE CURRENT-DAY P/L: {ledger_profit:+.1f} | "
            f"settled={sum(1 for x in self.ctx.trade_history if x.hit is not None)}"
        )

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

    # V4.3.0: if write credentials exist, durable state defaults to the
    # same workbook as the Number stream instead of silently using ephemeral
    # local disk on Streamlit Cloud.
    try:
        has_google_credentials = bool(dict(st.secrets.get("gcp_service_account", {})))
    except Exception:
        has_google_credentials = False

    backend = str(cfg.get(
        "backend", "gsheet" if has_google_credentials else "local"
    )).lower().strip()
    sheet_id = str(cfg.get(
        "sheet_id", SHEET_ID if backend == "gsheet" else ""
    )).strip()
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
        st.error(f"Google state auth error: {e}")
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
    """Serialize durable WAL/day-boundary state only.

    NO-CACHE invariant:
    adaptive P4..P26 / WR4..WR26 feature maps are NOT persisted and are never
    authoritative. They are rebuilt from fresh raw Numbers on every run.
    """
    return {
        "trade_history": [trade_record_to_dict(x) for x in ctx.trade_history],
        "trade_archive": [trade_record_to_dict(x) for x in merge_trade_archive(ctx)],
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
        "recovery_replay_all_rounds": bool(getattr(ctx, "recovery_replay_all_rounds", False)),
        "data_correction_sequential_replay": bool(getattr(ctx, "data_correction_sequential_replay", False)),
        "fast_recovery_mode": bool(getattr(ctx, "fast_recovery_mode", False)),
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
        "open_confidence": float(getattr(x, "open_confidence", 0.0) or 0.0),
        "open_regime": str(getattr(x, "open_regime", "") or ""),
        "open_consensus": float(getattr(x, "open_consensus", 0.0) or 0.0),
        "open_required_consensus": float(getattr(x, "open_required_consensus", 0.0) or 0.0),
        "open_stability": float(getattr(x, "open_stability", 0.0) or 0.0),
        "open_shadow_profit20": float(getattr(x, "open_shadow_profit20", 0.0) or 0.0),
        "open_shadow_wr20": float(getattr(x, "open_shadow_wr20", 0.0) or 0.0),
        "open_real_window_profit": float(getattr(x, "open_real_window_profit", 0.0) or 0.0),
        "open_real_window_wr": float(getattr(x, "open_real_window_wr", 0.0) or 0.0),
        "open_real_window_trade_count": int(getattr(x, "open_real_window_trade_count", 0) or 0),
        "open_real_window_loss_streak": int(getattr(x, "open_real_window_loss_streak", 0) or 0),
        "open_protection_reason": str(getattr(x, "open_protection_reason", "") or ""),
        "open_lock_reason": str(getattr(x, "open_lock_reason", "") or ""),
        "open_day_seq": int(getattr(x, "open_day_seq", 0) or 0),
        "open_day_date": str(getattr(x, "open_day_date", "") or ""),
        "open_batch_id": str(getattr(x, "open_batch_id", "") or ""),
        "open_is_frontier": bool(getattr(x, "open_is_frontier", False)),
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
        open_confidence=float(d.get("open_confidence", 0.0) or 0.0),
        open_regime=str(d.get("open_regime", "") or ""),
        open_consensus=float(d.get("open_consensus", 0.0) or 0.0),
        open_required_consensus=float(d.get("open_required_consensus", 0.0) or 0.0),
        open_stability=float(d.get("open_stability", 0.0) or 0.0),
        open_shadow_profit20=float(d.get("open_shadow_profit20", 0.0) or 0.0),
        open_shadow_wr20=float(d.get("open_shadow_wr20", 0.0) or 0.0),
        # NO-CACHE: P4..P26 / WR4..WR26 are intentionally NOT restored.
        # They must be rebuilt from fresh raw Numbers during the current replay.
        open_shadow_profit_by_n={},
        open_shadow_wr_by_n={},
        open_real_window_profit=float(d.get("open_real_window_profit", 0.0) or 0.0),
        open_real_window_wr=float(d.get("open_real_window_wr", 0.0) or 0.0),
        open_real_window_trade_count=int(d.get("open_real_window_trade_count", 0) or 0),
        open_real_window_loss_streak=int(d.get("open_real_window_loss_streak", 0) or 0),
        open_protection_reason=str(d.get("open_protection_reason", "") or ""),
        open_lock_reason=str(d.get("open_lock_reason", "") or ""),
        open_day_seq=int(d.get("open_day_seq", 0) or 0),
        open_day_date=str(d.get("open_day_date", "") or ""),
        open_batch_id=str(d.get("open_batch_id", "") or ""),
        open_is_frontier=bool(d.get("open_is_frontier", False)),
    )



def _trade_archive_key(rec: TradeRecord) -> tuple:
    return (
        int(getattr(rec, "open_day_seq", 0) or 0),
        str(getattr(rec, "open_day_date", "") or ""),
        int(getattr(rec, "round_id", 0) or 0),
    )


def merge_trade_archive(ctx: EngineContext) -> list[TradeRecord]:
    """Merge immutable-ish display archive with current live ledger.

    Current trade_history wins for the same day/open_round so a legitimate
    corrected-day replay can replace its prior reconstructed record. This
    archive is display/persistence only and is never used for decisions/profit.
    """
    merged = {}
    for rec in list(getattr(ctx, "trade_archive", []) or []):
        merged[_trade_archive_key(rec)] = rec
    for rec in list(getattr(ctx, "trade_history", []) or []):
        merged[_trade_archive_key(rec)] = rec
    rows = list(merged.values())
    rows.sort(key=lambda x: (
        int(getattr(x, "open_day_seq", 0) or 0),
        str(getattr(x, "open_day_date", "") or ""),
        int(getattr(x, "round_id", 0) or 0),
    ))
    ctx.trade_archive = rows
    return rows


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
        "batch_id": str(getattr(ctx, "current_batch_id", "") or ""),
        "is_live_frontier": bool(getattr(ctx, "current_is_frontier", False)),
        "open_confidence": round(float(getattr(open_rec, "open_confidence", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_regime": str(getattr(open_rec, "open_regime", "")) if open_this and open_rec is not None else "",
        "open_consensus": round(float(getattr(open_rec, "open_consensus", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_required_consensus": round(float(getattr(open_rec, "open_required_consensus", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_stability": round(float(getattr(open_rec, "open_stability", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_shadow_profit20": round(float(getattr(open_rec, "open_shadow_profit20", 0.0)), 2) if open_this and open_rec is not None else None,
        "open_shadow_wr20": round(float(getattr(open_rec, "open_shadow_wr20", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_real_window_profit": round(float(getattr(open_rec, "open_real_window_profit", 0.0)), 2) if open_this and open_rec is not None else None,
        "open_real_window_wr": round(float(getattr(open_rec, "open_real_window_wr", 0.0)), 4) if open_this and open_rec is not None else None,
        "open_real_window_trade_count": int(getattr(open_rec, "open_real_window_trade_count", 0)) if open_this and open_rec is not None else None,
        "open_real_window_loss_streak": int(getattr(open_rec, "open_real_window_loss_streak", 0)) if open_this and open_rec is not None else None,
        "open_protection_reason": str(getattr(open_rec, "open_protection_reason", "")) if open_this and open_rec is not None else "",
        "open_lock_reason": str(getattr(open_rec, "open_lock_reason", "")) if open_this and open_rec is not None else "",
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


def save_live_checkpoint(ctx: EngineContext) -> None:
    """Fast crash-safe checkpoint for intermediate phases.

    Writes only the durable local WAL. The completed round is committed to the
    configured backend by save_live_state(). On restart load_live_state()
    already compares WAL/state revisions, so an interrupted round can resume
    from the newest durable phase without doing multiple remote writes.
    """
    if bool(getattr(ctx, "fast_recovery_mode", False)) or bool(getattr(ctx, "stateless_internal_replay", False)):
        return
    ensure_ctx_fields(ctx)
    refresh_ledger_checkpoint(ctx)
    ctx.state_revision = int(getattr(ctx, "state_revision", 0) or 0) + 1
    data = serialize_live_state(ctx)
    try:
        wal_tmp = STATE_WAL_FILE + ".tmp"
        with open(wal_tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(wal_tmp, STATE_WAL_FILE)
    except Exception as e:
        st.error(f"Durable WAL checkpoint failed: {e}")
        st.stop()


def save_live_state(ctx: EngineContext) -> None:
    # V4.2.1 FAST RECOVERY: sequential reconstruction can execute hundreds of
    # transaction phases. Do not write remote/local state at every phase.
    # Normal TRUE-LIVE never sets this flag, so crash-safe persistence is unchanged.
    if bool(getattr(ctx, "fast_recovery_mode", False)) or bool(getattr(ctx, "stateless_internal_replay", False)):
        return
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
        # V4.3.4 LOCAL CRASH RECOVERY:
        # Intermediate transaction phases are checkpointed to STATE_WAL_FILE,
        # while STATE_FILE is committed only at a completed durable save.
        # Therefore local mode MUST compare both files and resume the highest
        # valid revision. Ignoring a newer WAL can repeat SETTLE/WINDOW/SIGNAL/OPEN
        # after a process crash and make LIVE differ from deterministic replay.
        local_data = None
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
            except Exception:
                local_data = None

        if _valid_state(local_data) and _valid_state(wal_data):
            local_rev = int(local_data.get("state_revision", 0) or 0)
            wal_rev = int(wal_data.get("state_revision", 0) or 0)
            data = wal_data if wal_rev > local_rev else local_data
        elif _valid_state(wal_data):
            data = wal_data
        elif _valid_state(local_data):
            data = local_data
        else:
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
    archive_payload = data.get("trade_archive")
    if isinstance(archive_payload, list):
        ctx.trade_archive = [trade_record_from_dict(x) for x in archive_payload]
    else:
        # First upgrade from V4.2.3: preserve every trade that still exists
        # in the old persistent state before any reset/new-day transition.
        ctx.trade_archive = list(ctx.trade_history)
    merge_trade_archive(ctx)
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
    ctx.recovery_replay_all_rounds = bool(data.get("recovery_replay_all_rounds", False))
    ctx.data_correction_sequential_replay = bool(data.get("data_correction_sequential_replay", False))
    ctx.fast_recovery_mode = bool(data.get("fast_recovery_mode", False))
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
    return loaded



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
            st.success(
                f"State backend: Google Sheet / worksheet={cfg['worksheet']} "
                f"(durable across deploy)"
            )
        else:
            st.warning(
                f"State backend: local file {STATE_FILE}. "
                "LIVE can recover across refresh/restart in this container, but "
                "cloud redeploy/container replacement may lose state."
            )
        if st.button("RESET & REPLAY TODAY", type="primary", use_container_width=True):
            # Reset ONLY active day; preserve previous-day archive.
            old_ctx = ensure_ctx_fields(get_live_ctx())
            current_seq = int(getattr(old_ctx, "live_day_seq", 0) or 0)
            current_date = str(getattr(old_ctx, "live_day_date", "") or "")
            prior_archive = merge_trade_archive(old_ctx)
            kept_archive = []
            for rec in prior_archive:
                rec_seq = int(getattr(rec, "open_day_seq", 0) or 0)
                rec_date = str(getattr(rec, "open_day_date", "") or "")
                is_today = (rec_seq == current_seq) and (not current_date or rec_date == current_date)
                if not is_today:
                    kept_archive.append(rec)

            blank_ctx = ensure_ctx_fields(EngineContext())
            blank_ctx.trade_archive = list(kept_archive)
            blank_ctx.daily_profit_history = list(getattr(old_ctx, "daily_profit_history", []) or [])[-10:]
            blank_ctx.live_day_id = str(getattr(old_ctx, "live_day_id", "") or current_live_day_id())
            blank_ctx.live_day_seq = current_seq
            blank_ctx.live_day_date = current_date
            blank_ctx.protection_reason = "RESET_REPLAY_TODAY_SEQUENTIAL"
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""
            blank_ctx.recovery_replay_all_rounds = True
            blank_ctx.data_correction_sequential_replay = True
            blank_ctx.fast_recovery_mode = True
            blank_ctx.state_revision = int(getattr(old_ctx, "state_revision", 0) or 0) + 1
            rebuild_payload = serialize_live_state(blank_ctx)

            try:
                wal_tmp = STATE_WAL_FILE + ".tmp"
                with open(wal_tmp, "w", encoding="utf-8") as f:
                    json.dump(rebuild_payload, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(wal_tmp, STATE_WAL_FILE)
            except Exception as e:
                st.error(f"RESET & REPLAY stopped: WAL write failed: {e}")
                st.stop()

            if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
                if not save_state_to_gsheet(rebuild_payload):
                    st.error("RESET & REPLAY stopped: Google State write failed.")
                    st.stop()
            else:
                try:
                    tmp = STATE_FILE + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(rebuild_payload, f, ensure_ascii=False, indent=2)
                        f.flush(); os.fsync(f.fileno())
                    os.replace(tmp, STATE_FILE)
                except Exception as e:
                    st.error(f"RESET & REPLAY stopped: state write failed: {e}")
                    st.stop()

            st.session_state["live_ctx"] = blank_ctx
            st.session_state["engine_ctx"] = blank_ctx
            st.success(
                f"Reset DaySeq {current_seq}. Previous days preserved. "
                "Replaying today's numbers sequentially..."
            )
            st.rerun()

        if st.button("REBUILD ENGINE STATE FROM CURRENT B (NO HISTORICAL TRADES)"):
            # V4.0 TRUE-FRONTIER recovery: rebuild deterministic window/engine state
            # from the currently loaded Number column, but NEVER invent historical
            # trades. Historical arrival/frontier timing is not recoverable from
            # Number alone, so the old ledger cannot be reconstructed truthfully.
            old_ctx = ensure_ctx_fields(get_live_ctx())
            blank_ctx = ensure_ctx_fields(EngineContext())
            blank_ctx.trade_archive = list(getattr(old_ctx, "trade_archive", []) or getattr(old_ctx, "trade_history", []) or [])
            blank_ctx.daily_profit_history = list(getattr(old_ctx, "daily_profit_history", []) or [])[-10:]
            blank_ctx.live_day_id = current_live_day_id()
            blank_ctx.protection_reason = "MANUAL_REBUILD_ENGINE_NO_HISTORICAL_TRADES"
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""
            blank_ctx.recovery_replay_all_rounds = True
            # IMPORTANT: the durable WAL participates in load precedence.
            # The old rebuild path only cleared Google State/STATE_FILE but left
            # the previous WAL intact, so restart could immediately prefer the
            # stale WAL and erase recovery_replay_all_rounds again.
            blank_ctx.state_revision = int(getattr(old_ctx, "state_revision", 0) or 0) + 1
            rebuild_payload = serialize_live_state(blank_ctx)

            try:
                wal_tmp = STATE_WAL_FILE + ".tmp"
                with open(wal_tmp, "w", encoding="utf-8") as f:
                    json.dump(rebuild_payload, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(wal_tmp, STATE_WAL_FILE)
            except Exception as e:
                st.error(f"REBUILD stopped: WAL write failed: {e}")
                st.stop()

            if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
                if not save_state_to_gsheet(rebuild_payload):
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
            blank_ctx.trade_archive = list(getattr(old_ctx_for_history, "trade_archive", []) or getattr(old_ctx_for_history, "trade_history", []) or [])
            blank_ctx.daily_profit_history = carry_history
            blank_ctx.live_day_id = current_live_day_id()
            blank_ctx.protection_reason = "MANUAL_RESET"
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""
            # Reset must advance the durable revision and replace the WAL too;
            # otherwise the old WAL can win during the next load and undo Reset.
            blank_ctx.state_revision = int(getattr(old_ctx_for_history, "state_revision", 0) or 0) + 1
            reset_payload = serialize_live_state(blank_ctx)

            try:
                wal_tmp = STATE_WAL_FILE + ".tmp"
                with open(wal_tmp, "w", encoding="utf-8") as f:
                    json.dump(reset_payload, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(wal_tmp, STATE_WAL_FILE)
            except Exception as e:
                st.error(f"MANUAL RESET stopped: WAL write failed: {e}")
                st.stop()

            cfg2 = get_state_backend_config()
            if cfg2["backend"] == "gsheet" and cfg2["sheet_id"]:
                if not save_state_to_gsheet(reset_payload):
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
# V71.4 PHYSICAL FRONTIER JOURNAL
# ============================================================

def _frontiers_to_bits(frontiers: list[int]) -> str:
    """Compact frontier list into a hex bitset anchored at LIVE_START_ROUND."""
    mask = 0
    for x in list(frontiers or []):
        try:
            r = int(x)
        except Exception:
            continue
        if r >= LIVE_START_ROUND:
            mask |= 1 << (r - LIVE_START_ROUND)
    return format(mask, "x") if mask else ""


def _bits_to_frontiers(bits: Any) -> list[int]:
    try:
        mask = int(str(bits or "0"), 16)
    except Exception:
        return []

    vals = []
    offset = 0
    while mask:
        if mask & 1:
            vals.append(LIVE_START_ROUND + offset)
        mask >>= 1
        offset += 1
    return vals


def _normalize_frontier_journal(data: Any) -> dict:
    if not isinstance(data, dict):
        data = {}
    raw_days = data.get("days", {})
    if not isinstance(raw_days, dict):
        raw_days = {}

    days = {}
    for k, v in raw_days.items():
        try:
            seq = int(k)
        except Exception:
            continue
        if not isinstance(v, dict):
            v = {}

        vals = []

        # Legacy V1 used explicit "frontiers". V2 storage uses compact "b".
        legacy_vals = v.get("frontiers", None)
        if legacy_vals is not None:
            for x in list(legacy_vals or []):
                try:
                    r = int(x)
                except Exception:
                    continue
                if r >= LIVE_START_ROUND:
                    vals.append(r)
        else:
            vals.extend(_bits_to_frontiers(
                v.get("frontier_bits", v.get("b", ""))
            ))

        vals = sorted(set(vals))

        try:
            max_seen = int(v.get("max_seen", v.get("m", 0)) or 0)
        except Exception:
            max_seen = 0

        day_date = str(v.get("day_date", v.get("d", "")) or "")

        days[str(seq)] = {
            "frontiers": vals,
            "max_seen": max(max_seen, max(vals) if vals else 0),
            "day_date": day_date,
        }

    return {"version": FRONTIER_JOURNAL_VERSION, "days": days}


def _frontier_journal_storage_payload(journal: dict) -> dict:
    """Compact durable representation. Runtime continues using explicit lists."""
    journal = _normalize_frontier_journal(journal)
    out_days = {}

    for k, v in journal["days"].items():
        out_days[str(k)] = {
            "b": _frontiers_to_bits(list(v.get("frontiers", []) or [])),
            "m": int(v.get("max_seen", 0) or 0),
            "d": str(v.get("day_date", "") or ""),
        }

    return {
        "version": FRONTIER_JOURNAL_VERSION,
        "days": out_days,
    }



def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _history_day_input_hash(
    *,
    seq: int,
    day_id: str,
    numbers: list[int],
    allowed_frontiers: Optional[list[int]],
    prior_history: list[dict],
) -> str:
    """Deterministic causal signature for one completed historical day."""
    prior10 = [
        [
            int(x.get("day_seq", 0) or 0),
            round(float(x.get("profit", 0.0) or 0.0), 2),
        ]
        for x in list(prior_history or [])[-10:]
    ]

    payload = {
        "cache_version": HISTORY_CACHE_VERSION,
        "strategy_version": STATE_VERSION,
        "day_seq": int(seq),
        "day_id": str(day_id or seq),
        "numbers": [int(x) for x in list(numbers or [])],
        "frontiers": (
            None if allowed_frontiers is None
            else sorted(set(int(x) for x in list(allowed_frontiers or [])))
        ),
        "live_start_round": int(LIVE_START_ROUND),
        "frontier_cutover": int(FRONTIER_JOURNAL_CUTOVER_DAY_SEQ),
        "missing_frontier_policy": str(HISTORICAL_MISSING_FRONTIER_POLICY),
        "strategy_frontier_mode": str(STRATEGY_FRONTIER_MODE),
        "prior10": prior10,
        "v70_enabled": False,
        "daily_profit_lock": float(get_dynamic_daily_profit_lock(prior_history)),
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_history_profit_cache(data: Any) -> dict:
    if not isinstance(data, dict):
        data = {}

    raw_records = data.get("records", {})
    if not isinstance(raw_records, dict):
        raw_records = {}

    records = {}
    for k, v in raw_records.items():
        try:
            seq = int(k)
        except Exception:
            continue

        if seq <= 0 or not isinstance(v, dict):
            continue

        ih = str(v.get("input_hash", "") or "")
        if len(ih) != 64 or not _is_finite_number(v.get("profit")):
            continue

        records[str(seq)] = {
            "input_hash": ih,
            "profit": round(float(v.get("profit")), 2),
            "physical_profit": (
                round(float(v.get("physical_profit")), 2)
                if _is_finite_number(v.get("physical_profit"))
                else None
            ),
            "logical_profit": (
                round(float(v.get("logical_profit")), 2)
                if _is_finite_number(v.get("logical_profit"))
                else None
            ),
            "day_id": str(v.get("day_id", "") or ""),
            "diag": dict(v.get("diag", {}) or {}),
        }

    return {
        "version": HISTORY_CACHE_VERSION,
        "records": records,
    }


def _history_cache_worksheet_name(cfg: dict) -> str:
    base = str(cfg.get("worksheet", "state") or "state")
    return (base + "_history_cache")[:100]


def load_history_profit_cache() -> dict:
    """Best-effort optimization cache. Never stop LIVE if cache is unavailable."""
    cfg = get_state_backend_config()

    if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        try:
            client = get_gsheet_client()
            if client is None:
                return _normalize_history_profit_cache({})

            sh = client.open_by_key(cfg["sheet_id"])
            try:
                ws = sh.worksheet(_history_cache_worksheet_name(cfg))
            except Exception:
                return _normalize_history_profit_cache({})

            raw = "".join(str(x or "") for x in ws.col_values(1))
            if not raw:
                return _normalize_history_profit_cache({})

            parsed = json.loads(raw)
            if str(parsed.get("version", "")) != HISTORY_CACHE_VERSION:
                return _normalize_history_profit_cache({})
            return _normalize_history_profit_cache(parsed)
        except Exception:
            return _normalize_history_profit_cache({})

    try:
        if not os.path.exists(HISTORY_CACHE_FILE):
            return _normalize_history_profit_cache({})
        with open(HISTORY_CACHE_FILE, "r", encoding="utf-8") as f:
            parsed = json.load(f)
        if str(parsed.get("version", "")) != HISTORY_CACHE_VERSION:
            return _normalize_history_profit_cache({})
        return _normalize_history_profit_cache(parsed)
    except Exception:
        return _normalize_history_profit_cache({})


def save_history_profit_cache(cache: dict) -> None:
    """Best-effort atomic/chunked save. Failure must never alter LIVE decisions."""
    data = _normalize_history_profit_cache(cache)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    cfg = get_state_backend_config()

    if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        try:
            client = get_gsheet_client()
            if client is None:
                return

            sh = client.open_by_key(cfg["sheet_id"])
            name = _history_cache_worksheet_name(cfg)
            try:
                ws = sh.worksheet(name)
            except Exception:
                ws = sh.add_worksheet(title=name, rows=10, cols=2)

            chunk_size = 40000
            chunks = [
                payload[i:i + chunk_size]
                for i in range(0, len(payload), chunk_size)
            ] or [""]

            old_count = max(1, len(ws.col_values(1)))
            need_rows = max(10, len(chunks) + 2, old_count + 1)
            try:
                ws.resize(rows=need_rows, cols=2)
            except Exception:
                pass

            write_rows = [[x] for x in chunks]
            if old_count > len(chunks):
                write_rows.extend([[""]] * (old_count - len(chunks)))

            ws.update(
                f"A1:A{len(write_rows)}",
                write_rows,
            )
            ws.update("B1", [[time.strftime("%Y-%m-%d %H:%M:%S")]])

            verify = "".join(
                str(x or "")
                for x in ws.col_values(1)[:len(chunks)]
            )
            if verify != payload:
                # Cache write verification failure is performance-only.
                return
            return
        except Exception:
            return

    try:
        tmp = HISTORY_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, HISTORY_CACHE_FILE)
    except Exception:
        return


def _frontier_journal_worksheet_name(cfg: dict) -> str:
    base = str(cfg.get("worksheet", "state") or "state")
    return (base + "_frontiers")[:100]


def load_frontier_journal() -> dict:
    cfg = get_state_backend_config()

    if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        client = get_gsheet_client()
        if client is None:
            st.error("FRONTIER JOURNAL LOAD FAILED: Google client unavailable.")
            st.stop()
        try:
            sh = client.open_by_key(cfg["sheet_id"])
            try:
                ws = sh.worksheet(_frontier_journal_worksheet_name(cfg))
            except Exception:
                return _normalize_frontier_journal({})
            chunks = [str(x or "") for x in ws.col_values(1)]
            raw = "".join(chunks)
            if not raw:
                return _normalize_frontier_journal({})
            return _normalize_frontier_journal(json.loads(raw))
        except Exception as exc:
            st.error(f"FRONTIER JOURNAL LOAD FAILED: {exc}")
            st.stop()

    try:
        if not os.path.exists(FRONTIER_JOURNAL_FILE):
            return _normalize_frontier_journal({})
        with open(FRONTIER_JOURNAL_FILE, "r", encoding="utf-8") as f:
            return _normalize_frontier_journal(json.load(f))
    except Exception as exc:
        st.error(f"FRONTIER JOURNAL LOAD FAILED: {exc}")
        st.stop()


def save_frontier_journal(journal: dict) -> None:
    data = _frontier_journal_storage_payload(journal)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    cfg = get_state_backend_config()

    if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
        client = get_gsheet_client()
        if client is None:
            st.error("FRONTIER JOURNAL SAVE FAILED: Google client unavailable.")
            st.stop()
        try:
            sh = client.open_by_key(cfg["sheet_id"])
            name = _frontier_journal_worksheet_name(cfg)
            try:
                ws = sh.worksheet(name)
            except Exception:
                ws = sh.add_worksheet(title=name, rows=10, cols=2)

            # Google Sheets cells cap text size. Split payload safely across rows.
            chunk_size = 40000
            chunks = [
                payload[i:i + chunk_size]
                for i in range(0, len(payload), chunk_size)
            ] or [""]

            old_count = max(1, len(ws.col_values(1)))
            need_rows = max(10, len(chunks) + 2, old_count + 1)
            try:
                ws.resize(rows=need_rows, cols=2)
            except Exception:
                pass

            write_rows = [[x] for x in chunks]
            if old_count > len(chunks):
                write_rows.extend([[""]] * (old_count - len(chunks)))

            ws.update(
                f"A1:A{len(write_rows)}",
                write_rows,
            )
            ws.update("B1", [[time.strftime("%Y-%m-%d %H:%M:%S")]])

            verify = "".join(
                str(x or "")
                for x in ws.col_values(1)[:len(chunks)]
            )
            if verify != payload:
                st.error("FRONTIER JOURNAL SAVE FAILED: verification mismatch.")
                st.stop()
            return
        except Exception as exc:
            st.error(f"FRONTIER JOURNAL SAVE FAILED: {exc}")
            st.stop()

    try:
        tmp = FRONTIER_JOURNAL_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, FRONTIER_JOURNAL_FILE)
    except Exception as exc:
        st.error(f"FRONTIER JOURNAL SAVE FAILED: {exc}")
        st.stop()


def record_live_frontier(
    journal: dict,
    day_seq: int,
    day_date: str,
    current_length: int,
) -> tuple[dict, list[int]]:
    """Record the snapshot length that was physically visible on this refresh."""
    journal = _normalize_frontier_journal(journal)
    seq = int(day_seq or 0)
    n = max(0, int(current_length or 0))

    if seq < FRONTIER_JOURNAL_CUTOVER_DAY_SEQ:
        return journal, []

    key = str(seq)
    day_existed = key in journal["days"]
    day = dict(journal["days"].get(key, {}) or {})
    vals = sorted(set(int(x) for x in list(day.get("frontiers", []) or [])))
    old_vals = list(vals)
    previous_max_seen = int(day.get("max_seen", 0) or 0)
    previous_date = str(day.get("day_date", "") or "")

    # Only a forward-moving snapshot can create a new physical frontier.
    # If the Sheet shrinks because a Number was deleted/edited, do NOT convert
    # that historical round into a new trade opportunity.
    if n >= LIVE_START_ROUND and n > previous_max_seen:
        vals = sorted(set(vals + [n]))

    day["frontiers"] = vals
    day["max_seen"] = max(previous_max_seen, n)
    day["day_date"] = str(day_date or day.get("day_date", "") or "")
    journal["days"][key] = day

    # Do NOT prune old days. Raw causal replay of post-cutover history needs
    # every physical frontier journal from the cutover onward.
    changed = (
        (not day_existed)
        or vals != old_vals
        or int(day["max_seen"]) != previous_max_seen
        or str(day["day_date"]) != previous_date
    )
    if changed:
        save_frontier_journal(journal)

    return journal, vals


def frontier_list_for_replay(
    journal: dict,
    day_seq: int,
    *,
    require_record: bool,
) -> Optional[list[int]]:
    seq = int(day_seq or 0)
    if seq < FRONTIER_JOURNAL_CUTOVER_DAY_SEQ:
        return None

    journal = _normalize_frontier_journal(journal)
    key = str(seq)
    if key not in journal["days"]:
        if require_record:
            raise ValueError(
                f"FRONTIER JOURNAL NOT READY: missing DaySeq {seq}. "
                "LIVE is fail-closed to prevent retrospective OPENs."
            )
        return []

    return sorted(set(
        int(x) for x in journal["days"][key].get("frontiers", [])
        if int(x) >= LIVE_START_ROUND
    ))


# ============================================================
# ENGINE MANAGER
# ============================================================

class EngineManager:
    def __init__(self) -> None:
        # V4.4.2 STATELESS: legacy reset/replay buttons are not part of calculation.
        # Keep them hidden to avoid suggesting persistent state controls strategy.
        if not STATELESS_REPLAY_LIVE:
            reset_live_state_button()

        # V4.3.2 TRUE SINGLE SNAPSHOT: fetch Google `data` exactly once at the
        # beginning of this Streamlit run. Persistent state loading must not
        # trigger any second Google data/history read.
        raw_df, sheet_day_seq, sheet_day_date, raw_numbers = _load_day_seq_sheet_snapshot()

        # Load durable frontier history now, but DO NOT record the current
        # snapshot until history validation/seed replay succeeds. A paused engine
        # must never create a future retrospective trade opportunity.
        self.frontier_journal = load_frontier_journal()
        self.current_live_frontiers = None

        if STATELESS_REPLAY_LIVE:
            # V4.4 STATELESS CALCULATION:
            # Never use yesterday's/incremental persistent engine state to calculate
            # today's trades.  The current immutable Sheet snapshot is the complete
            # input.  This makes Google LIVE equivalent to Excel replay.
            self.ctx = ensure_ctx_fields(EngineContext())
            self.ctx.live_day_seq = int(sheet_day_seq or 0)
            self.ctx.live_day_date = str(sheet_day_date or "")
            self.ctx.live_day_id = self.ctx.live_day_date
            self.ctx.live_frontiers = None
            # Prior completed daily P/L is read from the SAME immutable A:E snapshot.
            # It is used only as causal D-1/D-2/... input; current DAY_SEQ is excluded.
            # V4.4.2: derive prior-day profit from historical Numbers using the
            # exact same deterministic engine. Google daily_profit is audit-only.
            history_df = _load_history_sheet_df()
            self.history_df = history_df
            # V4.4.3 DAY-BOUNDARY FAIL-SAFE:
            # Do not start Day N until history contains every completed DaySeq
            # 1..N-1. This prevents a newly-created Day N row in `data` from
            # making the engine run without Day N-1 while the history copy is
            # still catching up. Stored daily_profit remains audit-only.
            hist_days = _validated_numbers_by_day(history_df, int(sheet_day_seq or 0))
            hist_seqs = [int(x[0]) for x in hist_days]
            expected_hist = list(range(1, int(sheet_day_seq or 0)))
            if hist_seqs != expected_hist:
                missing = [x for x in expected_hist if x not in set(hist_seqs)]
                extra = [x for x in hist_seqs if x not in set(expected_hist)]
                st.warning(
                    f"HISTORY NOT READY for DaySeq {int(sheet_day_seq or 0)}. "
                    f"Missing completed DaySeq={missing[:10]}"
                    + (f", unexpected={extra[:10]}" if extra else "")
                    + ". LIVE calculation is paused; no trade will be generated."
                )
                st.stop()
            # V70.6 CUTOVER SAFE:
            # V70.8: multi-day protection is rebuilt only from historical raw Numbers.
            # Stored daily_profit is never trusted. Each completed day is replayed
            # causally using baseline before cutover and V70 from cutover onward.
            _history_sig = make_history_signature(hist_days)
            self.history_signature = _history_sig
            _hist_memo_key = "_v6_verified_history_replay_memo"
            _hist_memo = st.session_state.get(_hist_memo_key)
            _hist_reused = False

            if (
                VERIFIED_HISTORY_REPLAY_MEMO
                and isinstance(_hist_memo, dict)
                and str(_hist_memo.get("version", "")) == VERIFIED_REPLAY_VERSION
                and str(_hist_memo.get("history_signature", "")) == _history_sig
                and int(_hist_memo.get("current_day_seq", 0) or 0) == int(sheet_day_seq or 0)
                and isinstance(_hist_memo.get("daily_profit_history"), list)
            ):
                # Safe derived memoization: source raw history fingerprint is identical.
                # Current-day Numbers are NOT reused and will still replay from R1.
                self.ctx.daily_profit_history = [
                    dict(x) for x in list(_hist_memo.get("daily_profit_history") or [])
                ]
                _hist_reused = True
            else:
                try:
                    self.ctx.daily_profit_history = _raw_history_seed_from_df(
                        history_df,
                        int(sheet_day_seq or 0),
                        frontier_journal=self.frontier_journal,
                    )
                except ValueError as exc:
                    st.warning(str(exc))
                    st.stop()
                if VERIFIED_HISTORY_REPLAY_MEMO:
                    st.session_state[_hist_memo_key] = {
                        "version": VERIFIED_REPLAY_VERSION,
                        "history_signature": _history_sig,
                        "current_day_seq": int(sheet_day_seq or 0),
                        "daily_profit_history": [
                            dict(x) for x in list(self.ctx.daily_profit_history or [])
                        ],
                    }

            self.history_replay_reused = bool(_hist_reused)

            # Only an engine-ready snapshot is trade-eligible.
            if int(sheet_day_seq or 0) >= FRONTIER_JOURNAL_CUTOVER_DAY_SEQ:
                self.frontier_journal, self.current_live_frontiers = record_live_frontier(
                    self.frontier_journal,
                    int(sheet_day_seq or 0),
                    str(sheet_day_date or ""),
                    len(raw_numbers or []),
                )
                self.ctx.live_frontiers = (
                    None
                    if STRATEGY_FRONTIER_MODE == "continuous"
                    else list(self.current_live_frontiers)
                )
            else:
                self.ctx.live_frontiers = None

            replayed_seed = list(self.ctx.daily_profit_history or [])
            _live_dynamic_target = get_dynamic_daily_profit_lock(replayed_seed)
            # IMPORTANT: ProtectionEngine.daily_stop_status() reads
            # daily_profit_lock_override, not daily_profit_lock.
            self.ctx.daily_profit_lock_override = float(_live_dynamic_target)
            self.ctx.daily_profit_lock = float(_live_dynamic_target)
            with st.expander("Audit / History", expanded=False):
                st.caption(
                    f"LIVE DAILY TARGET: +{float(_live_dynamic_target):.1f} "
                    + (
                        "| previous day negative => WIN-AND-STOP"
                        if float(_live_dynamic_target) <= 2.5
                        else "| normal target"
                    )
                )
                if replayed_seed:
                    st.info(
                        "RAW HISTORY REPLAY SEED: "
                        + ", ".join(
                            (
                                (
                                    f"D{int(x['day_seq'])}={float(x['profit']):+.1f}"
                                    + (
                                        f"[FRONTIER={float(x.get('physical_profit')):+.1f}]"
                                        if x.get("physical_profit", None) is not None
                                        else ""
                                    )
                                    + (
                                        f"[ADAPT={float(x.get('adaptive_bet_profit')):+.1f}]"
                                        if x.get("adaptive_bet_profit", None) is not None
                                        else ""
                                    )
                                )
                                + (
                                    "[REC]"
                                    if str(x.get("source", "")).startswith("RECOVERED_LOGICAL")
                                    else ""
                                )
                                + (
                                    (
                                        f"[T={int((x.get('diag') or {}).get('trade_count', 0) or 0)}"
                                        f",G={int((x.get('diag') or {}).get('gate_count', 0) or 0)}"
                                        f",GE={1 if bool((x.get('diag') or {}).get('gate_eligible', False)) else 0}"
                                        f",F={(x.get('diag') or {}).get('frontier_count', 'L')}"
                                        + (
                                            f",LOG={float(x.get('logical_profit')):+.1f}"
                                            if x.get('logical_profit', None) is not None
                                            else ""
                                        )
                                        + "]"
                                    )
                                    if abs(float(x.get('profit', 0.0) or 0.0)) < 1e-9
                                    else ""
                                )
                            )
                            for x in replayed_seed
                        )
                        + " | daily_profit column ignored"
                    )

                    _zero_days = [
                        x for x in replayed_seed
                        if abs(float(x.get("profit", 0.0) or 0.0)) < 1e-9
                    ]
                    for _z in _zero_days:
                        _d = dict(_z.get("diag", {}) or {})
                        st.warning(
                            f"ZERO PROFIT AUDIT D{int(_z.get('day_seq', 0) or 0)}: "
                            f"source={str(_z.get('source', '') or '')}, "
                            f"raw_len={int(_d.get('raw_len', 0) or 0)}, "
                            f"frontiers={_d.get('frontier_count', 'NA')}, "
                            f"trades={int(_d.get('trade_count', 0) or 0)}, "
                            f"gate_count={int(_d.get('gate_count', 0) or 0)}, "
                            f"gate_eligible={1 if bool(_d.get('gate_eligible', False)) else 0}, "
                            f"gate_round={int(_d.get('gate_round', 0) or 0)}, "
                            f"last_state={str(_d.get('last_decision_state', '') or '')}, "
                            f"reason={str(_d.get('protection_reason', '') or '')}"
                        )

                    _dual = [
                        x for x in replayed_seed
                        if x.get("logical_profit", None) is not None
                    ]
                    if _dual:
                        st.info(
                            "ENGINE STRATEGY vs FRONTIER JOURNAL vs ADAPTIVE BET (AUDIT ONLY): "
                            + ", ".join(
                                (
                                    f"D{int(x.get('day_seq', 0) or 0)} "
                                    f"ENGINE={float(x.get('profit', 0.0) or 0.0):+.1f} "
                                    f"| FRONTIER={float(x.get('physical_profit', 0.0) or 0.0):+.1f} "
                                    f"| ADAPT={float(x.get('adaptive_bet_profit', 0.0) or 0.0):+.1f}"
                                )
                                for x in _dual
                            )
                        )

            # Explicit day-level deployment gate.  With cutover=0 V70 is baseline-only.
            self.ctx.v70_switch_enabled = False
            self.ctx.daily_profit_lock_override = float(
                get_dynamic_daily_profit_lock(list(self.ctx.daily_profit_history or []))
            )

            # Suppress WAL/state writes during deterministic replay.  Calculation
            # state is disposable and rebuilt from R1 on every refresh.
            # V4.4.5 PURE STATELESS:
            # This context is disposable calculation state. Keep persistence disabled
            # for the ENTIRE Streamlit run, including the final hybrid_replay_once()
            # commit path. Earlier V4.4.x could clear fast_recovery_mode at the end
            # and accidentally write the reconstructed calculation state to WAL/state.
            self.ctx.fast_recovery_mode = True
            self.ctx.stateless_internal_replay = True
            self.ctx.hybrid_initialized = False
            self.ctx.recovery_replay_all_rounds = True
            self.ctx.data_correction_sequential_replay = True
            self.window_state = {w: WindowRecord() for w in WINDOWS}
        else:
            self.ctx = ensure_ctx_fields(get_live_ctx())
            self.ctx.v70_switch_enabled = False
            self.ctx.daily_profit_lock_override = float(
                get_dynamic_daily_profit_lock(list(self.ctx.daily_profit_history or []))
            )
            self.window_state = get_live_window_state()

        # V4.3.4 CRASH-SAFE LOCAL WAL:
        # If Google has already started DAY_SEQ N+1 while persisted state for N
        # is behind the final contiguous Number present for N, finish N first.
        # Otherwise reset_context_for_new_day() would freeze an incomplete daily
        # ledger/profit and could change next-day multi-day protection.
        state_seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)
        if (not STATELESS_REPLAY_LIVE) and state_seq > 0 and int(sheet_day_seq or 0) == state_seq + 1:
            prev_date, prev_numbers = _extract_day_seq_snapshot_from_df(raw_df, state_seq)
            state_frontier = int(getattr(self.ctx, "last_length", 0) or 0)
            if len(prev_numbers) < state_frontier:
                st.error(
                    f"DAY BOUNDARY REGRESSION DaySeq {state_seq}: state frontier={state_frontier}, "
                    f"Sheet contiguous rounds={len(prev_numbers)}. Engine stopped."
                )
                st.stop()
            if len(prev_numbers) > state_frontier:
                sheet_day_seq = state_seq
                sheet_day_date = prev_date or str(getattr(self.ctx, "live_day_date", "") or "")
                raw_numbers = prev_numbers
                st.warning(
                    f"DAY BOUNDARY CATCH-UP: finishing DaySeq {state_seq} "
                    f"rounds {state_frontier + 1}..{len(prev_numbers)} before switching to DaySeq {state_seq + 1}."
                )

        # V3.5: the Sheet is append-only. DAY_SEQ is the only day boundary.
        if sheet_day_seq <= 0:
            st.warning("Waiting for DAY_SEQ...")
            st.stop()
        # V4.4.3: a new DaySeq may appear before its first Number is committed.
        # Treat that as an incomplete Google write, never as a calculable day.
        if STATELESS_REPLAY_LIVE and len(raw_numbers) == 0:
            st.warning(f"DaySeq {sheet_day_seq} detected but round 1 Number is not ready. Waiting; no trade generated.")
            st.stop()
        # V4.4.4 SNAPSHOT MONOTONIC GUARD:
        # A stale Google response is safe for calculation (stateless replay), but it
        # must not make the UI appear to move backwards within the same Streamlit
        # browser session. This guard NEVER supplies Numbers to the strategy; it only
        # rejects a regressed snapshot. A later fresh refresh will retry normally.
        if STATELESS_REPLAY_LIVE:
            snap_key = "_v444_last_accepted_snapshot"
            previous = st.session_state.get(snap_key)
            current_seq = int(sheet_day_seq or 0)
            current_len = int(len(raw_numbers))
            if isinstance(previous, dict):
                prev_seq = int(previous.get("day_seq", 0) or 0)
                prev_len = int(previous.get("round_count", 0) or 0)
                if current_seq < prev_seq or (current_seq == prev_seq and current_len < prev_len):
                    st.warning(
                        f"STALE GOOGLE SNAPSHOT rejected: received DaySeq {current_seq} R{current_len}, "
                        f"but this session already accepted DaySeq {prev_seq} R{prev_len}. "
                        "Waiting for a fresh snapshot; no calculation/trade generated from stale data."
                    )
                    st.stop()
            st.session_state[snap_key] = {
                "day_seq": current_seq,
                "round_count": current_len,
            }
        if not STATELESS_REPLAY_LIVE:
            self.maybe_auto_reset_for_new_day(sheet_day_seq, sheet_day_date)

        # V4.2.2 SINGLE-SNAPSHOT: reuse the exact snapshot already fetched above.
        # Do not call load_data()/load_numbers() here because that would fetch the
        # same Google Sheet again and can also create a mixed-snapshot race.
        self.numbers = list(raw_numbers)
        if len(self.numbers) < MIN_DATA_LEN:
            st.warning("Waiting data...")
            st.stop()
        self.groups = build_groups(self.numbers)
        self.actual_group = self.groups[-1]
        self.round_id = len(self.numbers)

        # V6 current raw observation fingerprint.
        # This is NOT a decision cache. It only measures whether the fresh raw
        # snapshot has changed between UI refreshes.
        self.current_raw_signature = make_numbers_signature(self.numbers)
        _obs_key = "_v6_raw_observation"
        _obs_now = time.time()
        _obs_prev = st.session_state.get(_obs_key)
        if (
            not isinstance(_obs_prev, dict)
            or int(_obs_prev.get("day_seq", 0) or 0) != int(sheet_day_seq or 0)
            or str(_obs_prev.get("raw_signature", "")) != self.current_raw_signature
        ):
            _obs_changed_at = _obs_now
        else:
            _obs_changed_at = float(_obs_prev.get("changed_at", _obs_now) or _obs_now)
        self.raw_observed_age_seconds = max(0.0, _obs_now - _obs_changed_at)
        self.raw_is_stale = bool(
            int(self.round_id or 0) < MAX_ROUNDS_PER_DAY
            and self.raw_observed_age_seconds > float(LIVE_STALE_SECONDS)
        )
        st.session_state[_obs_key] = {
            "day_seq": int(sheet_day_seq or 0),
            "round_count": int(self.round_id or 0),
            "raw_signature": self.current_raw_signature,
            "changed_at": float(_obs_changed_at),
            "observed_at": float(_obs_now),
        }

        # Expose transient live-check metadata on disposable context.
        self.ctx.live_raw_signature = self.current_raw_signature
        self.ctx.live_history_signature = str(getattr(self, "history_signature", "") or "")
        self.ctx.live_raw_observed_age_seconds = float(self.raw_observed_age_seconds)
        self.ctx.live_raw_is_stale = bool(self.raw_is_stale)
        self.ctx.live_history_replay_reused = bool(getattr(self, "history_replay_reused", False))

        # V4.4.6: persisted-ledger repair belongs only to the legacy incremental
        # path. Stateless calculation starts from an empty disposable ledger.
        if not STATELESS_REPLAY_LIVE:
            refresh_ledger_checkpoint(self.ctx)
            ledger_count = int(getattr(self.ctx, "ledger_trade_count", 0) or 0)
            actual_count = len(getattr(self.ctx, "trade_history", []) or [])
            if ledger_count != actual_count:
                st.warning(
                    f"LEDGER CHECKPOINT REPAIRED: metadata={ledger_count}, actual={actual_count}."
                )
                save_live_state(self.ctx)

        self.window_engine = WindowEngine(self.ctx, self.window_state)
        self.trade_engine = TradeEngine(self.ctx)
        self.signal_engine = SignalEngine(self.ctx, self.window_engine)
        self.protection_engine = ProtectionEngine(self.ctx, self.trade_engine)
        self.dashboard = Dashboard(self.ctx, self.window_engine, self.signal_engine, self.trade_engine, self.protection_engine)

        # V4.4.6: stateless replay must never resume/rebuild from a persisted
        # frontier. hybrid_replay_once() will consume R1..current from scratch.
        if not STATELESS_REPLAY_LIVE:
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

        # V4.3.3 DAY-BOUNDARY CATCH-UP:
        # The just-completed day's profit must come from the immutable LIVE
        # ledger, not from the Google `history` tab. The history tab may be
        # copied/formula-refreshed several seconds or minutes after DAY_SEQ
        # advances. Depending on that external timing would make the next day's
        # multi-day protection nondeterministic.
        completed_seq = int(getattr(old_ctx, "live_day_seq", 0) or 0)
        completed_date = str(getattr(old_ctx, "live_day_date", "") or "")
        completed_profit = round(sum(
            float(x.profit or 0.0)
            for x in list(getattr(old_ctx, "trade_history", []) or [])
            if getattr(x, "hit", None) is not None
        ), 2)
        hist_by_seq = {}
        for item in list(getattr(old_ctx, "daily_profit_history", []) or []):
            if not isinstance(item, dict):
                continue
            try:
                seq = int(item.get("day_seq"))
            except Exception:
                continue
            hist_by_seq[seq] = dict(item)
        if completed_seq > 0:
            hist_by_seq[completed_seq] = {
                "day_seq": completed_seq,
                "day_id": completed_date or str(completed_seq),
                "profit": completed_profit,
                "source": "LIVE_LEDGER_BOUNDARY",
            }

        blank_ctx = ensure_ctx_fields(EngineContext())
        blank_ctx.trade_archive = list(getattr(old_ctx, "trade_archive", []) or getattr(old_ctx, "trade_history", []) or [])
        blank_ctx.daily_profit_history = [hist_by_seq[k] for k in sorted(hist_by_seq)][-10:]
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

    def _v70_apply_loss_switch(self, signal: SignalRecord, idx: int) -> SignalRecord:
        """Causal V70 override immediately before OPEN, with core-equivalent safety.

        The switch may change only the selected window/prediction. It must not
        bypass the READY gates that the core engine would apply if that candidate
        had been selected normally. All inputs are known at decision round ``idx``.
        """
        if not bool(getattr(self.ctx, "v70_switch_enabled", V70_SWITCH_ENABLED)):
            return signal
        if str(getattr(self.ctx, "last_result_status", "") or "") != "LOSS":
            return signal
        if str(getattr(signal, "state", "WAIT") or "WAIT") != "READY":
            return signal

        locked_w = getattr(self.ctx, "locked_window", None)
        if locked_w is None:
            return signal
        locked_obj = self.window_engine.state.get(locked_w)
        if locked_obj is None or locked_obj.next_group is None:
            return signal

        rows = []
        for w in WINDOWS:
            obj = self.window_engine.state.get(w)
            if obj is None or obj.next_group is None:
                continue

            # Use the ACTUAL decision round for cooldown/blacklist expiry.
            # ctx.last_length is still idx-1 until the transaction commits.
            if self.signal_engine.is_window_cooled(w, idx):
                continue
            if self.signal_engine.is_window_blacklisted(w, idx):
                continue
            stat = self.signal_engine.get_real_stats(w)
            if stat["trade_count"] >= 3 and stat["profit"] <= MAX_REAL_NEGATIVE_SOFT and stat["loss_streak"] >= 2:
                continue
            if int(getattr(obj, "loss_streak", 0) or 0) > LOCK_MAX_LOSS_STREAK:
                continue
            if len(getattr(obj, "live_hit_history", []) or []) > 0:
                if float(getattr(obj, "live_profit20", 0.0) or 0.0) < CANDIDATE_MIN_LIVE_PROFIT20:
                    continue
                if float(getattr(obj, "live_wr20", 0.0) or 0.0) < CANDIDATE_MIN_LIVE_WR20:
                    continue
                if int(getattr(obj, "live_loss_streak", 0) or 0) > CANDIDATE_MAX_LIVE_LOSS_STREAK:
                    continue

            hits20 = list(obj.hit_history)[-20:]
            wr20 = (sum(hits20) / len(hits20)) if hits20 else 0.0
            rows.append((float(obj.profit20), float(wr20), float(obj.score), -int(w), int(w), obj))

        if not rows:
            return signal
        rows.sort(reverse=True)
        ranked = [(w, obj, p20, wr20) for p20, wr20, _score, _negw, w, obj in rows]

        locked_rank = next((i + 1 for i, (w, *_rest) in enumerate(ranked) if w == int(locked_w)), None)
        if locked_rank is None or locked_rank < V70_SWITCH_RANK20_MIN:
            return signal

        best_w, best_obj, best_profit20, best_hist_wr20 = ranked[0]
        locked_hits20 = list(locked_obj.hit_history)[-20:]
        locked_wr20 = (sum(locked_hits20) / len(locked_hits20)) if locked_hits20 else 0.0
        wr_gap = float(best_hist_wr20) - float(locked_wr20)
        if int(best_w) == int(locked_w) or wr_gap + 1e-12 < V70_SWITCH_WR_GAP_MIN:
            return signal

        # Rebuild every window-dependent SignalRecord field from the NEW candidate.
        # V70.4 inherited several fields from the old lock, which made audit/debug
        # snapshots misleading and could let the new window bypass core READY rules.
        best_hits20 = list(best_obj.hit_history)[-20:]
        best_leader_wr20 = (
            float(best_obj.live_wr20)
            if len(best_obj.live_hit_history) > 0
            else (sum(best_hits20) / len(best_hits20) if best_hits20 else 0.0)
        )
        best_top_profit20 = (
            float(best_obj.live_profit20)
            if len(best_obj.live_hit_history) > 0
            else float(best_obj.profit20)
        )
        best_real = self.signal_engine.get_real_stats(best_w)

        candidate = dataclasses.replace(signal)
        candidate.locked_window = int(best_w)
        candidate.next_group = int(best_obj.next_group)
        candidate.leader_window = int(best_w)
        candidate.leader_wr20 = float(best_leader_wr20)
        candidate.leader_loss_streak = int(best_obj.loss_streak)
        candidate.top_profit20 = float(best_top_profit20)
        candidate.shadow_live_profit20 = float(best_obj.live_profit20)
        candidate.shadow_live_wr20 = float(best_obj.live_wr20)
        candidate.real_window_profit = float(best_real["profit"])
        candidate.real_window_wr = float(best_real["wr"])
        candidate.real_window_trade_count = int(best_real["trade_count"])
        candidate.real_window_loss_streak = int(best_real["loss_streak"])
        candidate.locked_live_profit = 0.0
        candidate.locked_live_loss_streak = 0

        if float(candidate.stability) < STABILITY_READY:
            candidate.regime = "CHAOS"
        elif float(best_obj.profit20) > 0 and float(best_leader_wr20) >= 0.35:
            candidate.regime = "TREND"
        else:
            candidate.regime = "NORMAL"

        # Exact core READY-equivalence for the new window. Global ledger-based
        # protection already passed once in adaptive_ready_wait(); do not run it
        # twice because that would decrement pause/cooldown counters twice.
        candidate.state = "WAIT"
        if idx >= LIVE_START_ROUND and candidate.next_group is not None:
            live_bad_profit = (
                len(best_obj.live_hit_history) > 0
                and float(best_obj.live_profit20) <= LEADER_MIN_LIVE_PROFIT20
            )
            live_bad_wr = (
                len(best_obj.live_hit_history) > 0
                and float(best_obj.live_wr20) < LEADER_MIN_LIVE_WR20
            )
            hist_bad_profit = float(best_obj.profit20) <= LOCK_MIN_PROFIT20
            leader_bad_wr = float(best_leader_wr20) < FALLBACK_MIN_WR20
            leader_bad_ls = int(best_obj.loss_streak) > LOCK_MAX_LOSS_STREAK
            stability_bad = float(candidate.stability) < STABILITY_READY
            if not any((live_bad_profit, live_bad_wr, hist_bad_profit, leader_bad_wr, leader_bad_ls, stability_bad)):
                real_ok = (
                    best_real["trade_count"] >= 1
                    and best_real["profit"] > 0
                    and best_real["wr"] >= REAL_MIN_WR_FOR_LOCK
                    and best_real["loss_streak"] <= REAL_MAX_LOSS_STREAK_FOR_LOCK
                )
                if real_ok or float(candidate.consensus) >= float(candidate.required_consensus) or float(best_leader_wr20) >= 0.50:
                    candidate.state = "READY"

        if candidate.state != "READY":
            return signal

        old_protection_reason = str(getattr(self.ctx, "protection_reason", "") or "")
        candidate = self.signal_engine.apply_sample_aware_coherence(candidate)
        if str(getattr(candidate, "state", "WAIT") or "WAIT") != "READY" or candidate.next_group is None:
            self.ctx.protection_reason = old_protection_reason
            return signal

        candidate_confidence = self.signal_engine.get_confidence_score(candidate)
        if float(candidate_confidence) < MIN_CONFIDENCE_READY:
            self.ctx.protection_reason = old_protection_reason
            return signal

        # Commit only after every candidate-specific safety gate has passed.
        self.ctx.locked_window = int(best_w)
        self.ctx.lock_reason = (
            f"V70_AFTER_LOSS_RANK{locked_rank}_WRGAP_{wr_gap:.3f}_"
            f"W{int(locked_w)}_TO_W{int(best_w)}"
        )
        self.ctx.locked_live_profit = 0.0
        self.ctx.locked_live_loss_streak = 0
        self.ctx.locked_live_win = 0
        self.ctx.locked_live_loss = 0

        candidate.lock_reason = self.ctx.lock_reason

        # build_signal() already appended the BASELINE next_group for this round.
        # Replace that last entry with the ACTUAL V70 prediction, otherwise future
        # FLIPRATE protection reads a history that was never actually traded.
        if int(getattr(self.ctx, "last_signal_round", -1)) == int(idx):
            if len(self.ctx.signal_history) > 0:
                self.ctx.signal_history[-1] = int(candidate.next_group)
            if len(self.ctx.signal_flip_history) > 0:
                self.ctx.signal_flip_history[-1] = int(candidate.next_group)

        snap = dict(getattr(self.ctx, "round_txn_signal", {}) or {})
        snap.update({
            "v70_switch": True,
            "v70_from_window": int(locked_w),
            "v70_to_window": int(best_w),
            "v70_locked_rank20": int(locked_rank),
            "v70_locked_wr20": float(locked_wr20),
            "v70_best_wr20": float(best_hist_wr20),
            "v70_wr_gap": float(wr_gap),
            "v70_next_group": int(candidate.next_group),
        })
        self.ctx.round_txn_signal = snap
        return candidate

    def _apply_decision(self, signal: SignalRecord, idx: int, confidence: float) -> None:
        # V70.1 CRASH-SAFE DECISION:
        # protection/readiness is evaluated first; if READY, the causal V70 switch
        # is applied BEFORE DECISION_READY is persisted.  The persisted transaction
        # snapshot therefore contains the exact next_group/window that OPEN must use
        # after any crash/restart.
        signal.state = self.protection_engine.adaptive_ready_wait(
            signal, confidence
        )

        # V71.5 EXTREME-LAG GUARD:
        # When the next physical snapshot arrives >=8 rounds later, the candidate
        # is stale enough that waiting is safer than forcing a fresh OPEN.
        _f = sorted(set(
            int(x) for x in (getattr(self.ctx, "live_frontiers", None) or [])
        ))
        _prev = [x for x in _f if x < int(idx)]
        _gap = int(idx) - max(_prev) if _prev else 1
        if _gap >= 8:
            self.ctx.protection_reason = "EXTREME_FRONTIER_GAP_WAIT"
            signal.state = "WAIT"

        if multi_day_low_confidence_filter(self.ctx, confidence):
            self.ctx.protection_reason = "MULTI_DAY_LOW_CONF_FILTER"
            signal.state = "WAIT"

        # V71.2 PROFIT-DAY GATE (causal + frozen for the whole day).
        # The gate is evaluated exactly once: at the first decision round >= R180.
        # It uses only window statistics available at that moment.
        _gate_cutover = int(V71_HEALTH_GATE_CUTOVER_DAY_SEQ or 0)
        _day_seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)
        _gate_enabled_today = (_gate_cutover > 0 and _day_seq >= _gate_cutover)

        if _gate_enabled_today:
            if not hasattr(self.ctx, "v71_health_gate_eligible"):
                _healthy_count = sum(
                    1
                    for _w, _obj in self.window_engine.state.items()
                    if float(getattr(_obj, "profit20", 0.0) or 0.0)
                    > float(V71_HEALTH_GATE_PROFIT20_GT)
                )
                self.ctx.v71_health_gate_count = int(_healthy_count)
                self.ctx.v71_health_gate_eligible = bool(
                    _healthy_count >= int(V71_HEALTH_GATE_MIN_WINDOWS)
                )
                self.ctx.v71_health_gate_round = int(idx)

            if not bool(getattr(self.ctx, "v71_health_gate_eligible", False)):
                self.ctx.protection_reason = (
                    f"V71_DAY_GATE_NO_TRADE_"
                    f"P20GT{V71_HEALTH_GATE_PROFIT20_GT:g}_"
                    f"COUNT{int(getattr(self.ctx, 'v71_health_gate_count', 0) or 0)}"
                )
                signal.state = "WAIT"

        # V71.7 CAUSAL ENTRY TIMING:
        # In a weak 10-day regime, do not immediately re-enter on the same
        # frontier that has just settled a WIN. Waiting one physical frontier
        # avoids over-trading a short-lived post-win continuation.
        _entry_prior = list(getattr(self.ctx, "daily_profit_history", []) or [])[-10:]
        _entry_recent10 = sum(
            float(_x.get("profit", 0.0) or 0.0)
            for _x in _entry_prior
        )
        _entry_day_seq = int(getattr(self.ctx, "live_day_seq", 0) or 0)

        _entry_frontiers = sorted(set(
            int(x) for x in (getattr(self.ctx, "live_frontiers", None) or [])
            if int(x) <= int(idx)
        ))

        if getattr(self.ctx, "live_frontiers", None) is None:
            # Legacy logical replay behaves like an every-round frontier stream.
            _entry_contiguous = True
        else:
            _entry_recent_frontiers = _entry_frontiers[-4:]
            _entry_recent_gaps = [
                _entry_recent_frontiers[i] - _entry_recent_frontiers[i - 1]
                for i in range(1, len(_entry_recent_frontiers))
            ]
            # Causal only: inspect already-observed frontiers <= current idx.
            # Require 3 consecutive gap=1 observations before enabling the
            # defensive post-WIN wait. This prevents the rule from firing in
            # intermittent/bursty refresh conditions.
            _entry_contiguous = (
                len(_entry_recent_gaps) >= 3
                and all(int(_g) == 1 for _g in _entry_recent_gaps[-3:])
            )

        if (
            _entry_day_seq >= int(ENTRY_DEFENSIVE_CUTOVER_DAY_SEQ)
            and _entry_recent10 < 0.0
            and _entry_contiguous
            and str(getattr(self.ctx, "last_result_status", "") or "") == "WIN"
            and int(getattr(self.ctx, "last_result_round", -1) or -1) == int(idx)
            and str(getattr(signal, "state", "WAIT") or "WAIT") == "READY"
        ):
            self.ctx.protection_reason = "ENTRY_DEFENSIVE_WAIT_AFTER_WIN"
            signal.state = "WAIT"

        # V71.16 CAUSAL DEFENSIVE ENTRY GUARDS
        # A) After two consecutive negative days, skip only the first entry frontier (R180).
        # B) In a weak/flat 10-day regime (< +5 total), do not immediately re-enter
        #    on the same round that just settled a WIN; wait one round.
        _v716_hist = list(getattr(self.ctx, "daily_profit_history", []) or [])

        _v716_two_neg_skip_r180 = (
            len(_v716_hist) >= 2
            and all(
                float(_x.get("profit", 0.0) or 0.0) < 0.0
                for _x in _v716_hist[-2:]
            )
            and int(idx) < 181
        )

        _v716_recent10 = sum(
            float(_x.get("profit", 0.0) or 0.0)
            for _x in _v716_hist[-10:]
        )

        _v716_postwin_weak_regime = (
            str(getattr(self.ctx, "last_result_status", "") or "") == "WIN"
            and int(getattr(self.ctx, "last_result_round", -1) or -1) == int(idx)
            and _v716_recent10 < 5.0
        )

        if (
            str(getattr(signal, "state", "WAIT") or "WAIT") == "READY"
            and (_v716_two_neg_skip_r180 or _v716_postwin_weak_regime)
        ):
            self.ctx.protection_reason = (
                "V716_SKIP_R180_AFTER_2_NEG"
                if _v716_two_neg_skip_r180
                else "V716_POSTWIN_WAIT_RECENT10_LT5"
            )
            signal.state = "WAIT"

        self.ctx.last_decision_round = idx
        self.ctx.last_decision_state = str(signal.state or "WAIT")
        self.ctx.last_decision_next_group = None

        # Only READY may change window/prediction. WAIT is durably WAIT.
        if str(signal.state or "WAIT") != "WAIT":
            signal = self._v70_apply_loss_switch(signal, idx)
            # Confidence must correspond to the FINAL window/prediction that will
            # actually be frozen into the trade record, not the pre-switch lock.
            confidence = self.signal_engine.get_confidence_score(signal)
            self.ctx.last_decision_confidence = float(confidence)
            setattr(signal, "decision_confidence", float(confidence))

        # Persist the FINAL signal, not the pre-switch signal. Preserve V70 diagnostics.
        prev_snap = dict(getattr(self.ctx, "round_txn_signal", {}) or {})
        v70_diag = {k: v for k, v in prev_snap.items() if str(k).startswith("v70_")}
        snap = signal_to_txn_dict(signal, confidence)
        snap.update(v70_diag)
        snap["decision_state"] = str(signal.state or "WAIT")
        snap["decision_confidence"] = float(confidence)
        snap["decision_next_group"] = signal.next_group
        snap["decision_locked_window"] = self.ctx.locked_window
        snap["decision_lock_reason"] = self.ctx.lock_reason
        self.ctx.round_txn_signal = snap
        self.ctx.round_txn_phase = "DECISION_READY"
        save_live_state(self.ctx)

        if str(signal.state or "WAIT") == "WAIT":
            return

        before = len(self.ctx.trade_history)
        self.trade_engine.open_trade(signal, idx, confidence)
        created = len(self.ctx.trade_history) > before
        self.ctx.last_decision_state = "PENDING" if created else str(signal.state or "WAIT")
        self.ctx.last_decision_next_group = signal.next_group if created else None

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
        recovery_mode = bool(getattr(self.ctx, "recovery_replay_all_rounds", False))
        saved_frontier = int(getattr(self.ctx, "last_length", 0) or 0)
        start_idx = 1 if recovery_mode else max(1, saved_frontier + 1)
        # The current snapshot length is the only valid live-entry frontier.
        # Intermediate rows in a delayed batch are catch-up only.
        current_length = len(self.numbers)
        _ctx_frontiers = getattr(self.ctx, "live_frontiers", None)
        _physical_frontier_set = (
            None if _ctx_frontiers is None
            else set(int(x) for x in _ctx_frontiers)
        )

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
            # V4.0 TRUE-FRONTIER invariant: only the current snapshot frontier may
            # create a NEW trade. Recovery may rebuild windows/state, but Number
            # history cannot prove historical arrival frontiers and therefore must
            # never create retrospective trades.
            # V4.2: normal live/recovery may OPEN only on the physical frontier.
            # Explicit DATA-CORRECTION replay is different: user has accepted a
            # deterministic sequential reconstruction of the active day because
            # its original ledger is missing/corrupt.
            # V4.2.7 DETERMINISTIC LIVE:
            # Every round is a logical decision frontier. This makes
            # [same ordered Numbers + same code + same prior-day seed]
            # produce the same trades/profit regardless of Sheet refresh batching.
            if _physical_frontier_set is None:
                # Legacy / pre-cutover replay keeps the old deterministic behavior.
                is_live_frontier = True
            else:
                # V71.4: OPEN only where this round was physically observed live.
                is_live_frontier = int(idx) in _physical_frontier_set

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
        # V4.3.2: never re-read Google during round processing; use the day/date
        # captured by the single snapshot at EngineManager initialization.
        self.ctx.live_day_id = str(getattr(self.ctx, "live_day_date", "") or "")
        self.ctx.data_signature = make_numbers_signature(self.numbers, self.ctx.last_length)
        self.ctx.dataset_anchor_signature = make_numbers_signature(self.numbers, min(DATASET_RESET_ANCHOR_LEN, self.ctx.last_length))
        self.ctx.data_length = self.ctx.last_length
        self.ctx.recovery_replay_all_rounds = False
        self.ctx.data_correction_sequential_replay = False
        if not bool(getattr(self.ctx, "stateless_internal_replay", False)):
            self.ctx.fast_recovery_mode = False
        rebuild_real_stats_from_history(self.ctx)
        save_live_state(self.ctx)

    def process_new_rounds(self) -> None:
        # Process only rows added after the first hybrid replay.
        current_length = len(self.groups)

        # V4.2.8 AUTO CORRECTION:
        # Same corrected Number history must converge to the same deterministic
        # state, whether the operator edits a value, deletes trailing rows, or
        # deletes then re-enters/adds Numbers.
        last_len = int(getattr(self.ctx, "last_length", 0) or 0)
        saved_sig = str(getattr(self.ctx, "data_signature", "") or "")
        correction_detected = False
        correction_reason = ""

        if last_len > 0:
            if current_length < last_len:
                correction_detected = True
                correction_reason = f"ROWS_DELETED:{last_len}->{current_length}"
            elif saved_sig:
                now_sig = make_numbers_signature(self.numbers, last_len)
                if now_sig != saved_sig:
                    correction_detected = True
                    correction_reason = "PROCESSED_NUMBER_EDITED"

        if correction_detected:
            old_ctx = self.ctx
            current_seq = int(getattr(old_ctx, "live_day_seq", 0) or 0)
            current_date = str(getattr(old_ctx, "live_day_date", "") or "")
            prior_archive = merge_trade_archive(old_ctx)
            kept_archive = []
            for rec in prior_archive:
                rec_seq = int(getattr(rec, "open_day_seq", 0) or 0)
                rec_date = str(getattr(rec, "open_day_date", "") or "")
                is_today = (rec_seq == current_seq) and (not current_date or rec_date == current_date)
                if not is_today:
                    kept_archive.append(rec)

            blank_ctx = ensure_ctx_fields(EngineContext())
            blank_ctx.trade_archive = list(kept_archive)
            blank_ctx.daily_profit_history = list(getattr(old_ctx, "daily_profit_history", []) or [])[-10:]
            blank_ctx.live_day_id = str(getattr(old_ctx, "live_day_id", "") or current_live_day_id())
            blank_ctx.live_day_seq = current_seq
            blank_ctx.live_day_date = current_date
            blank_ctx.protection_reason = "AUTO_CORRECTION_REPLAY:" + correction_reason
            blank_ctx.open_reason = blank_ctx.protection_reason
            blank_ctx.state_version = STATE_VERSION
            blank_ctx.hybrid_initialized = False
            blank_ctx.last_length = 0
            blank_ctx.data_length = 0
            blank_ctx.data_signature = ""
            blank_ctx.dataset_anchor_signature = ""
            blank_ctx.recovery_replay_all_rounds = True
            blank_ctx.data_correction_sequential_replay = True
            blank_ctx.fast_recovery_mode = True
            blank_ctx.state_revision = int(getattr(old_ctx, "state_revision", 0) or 0) + 1

            # Persist the blank current-day checkpoint before replay. Previous
            # days remain archived; today's old ledger is deliberately replaced.
            payload = serialize_live_state(blank_ctx)
            cfg = get_state_backend_config()
            try:
                wal_tmp = STATE_WAL_FILE + ".tmp"
                with open(wal_tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(wal_tmp, STATE_WAL_FILE)
            except Exception as e:
                st.error(f"AUTO CORRECTION stopped: WAL write failed: {e}")
                st.stop()

            if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
                if not save_state_to_gsheet(payload):
                    st.error("AUTO CORRECTION stopped: Google State write failed.")
                    st.stop()
            else:
                tmp = STATE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    f.flush(); os.fsync(f.fileno())
                os.replace(tmp, STATE_FILE)

            st.session_state["live_ctx"] = blank_ctx
            st.session_state["engine_ctx"] = blank_ctx
            # V4.3.2: no live Sheet cache exists. The rerun will perform a fresh
            # Google read automatically.
            st.warning(
                f"Detected corrected history ({correction_reason}). "
                f"Rebuilding DaySeq {current_seq} from corrected Numbers..."
            )
            st.rerun()

        if current_length <= self.ctx.last_length:
            return

        batch_start = int(self.ctx.last_length) + 1
        # Stable logical batch identity; physical polling batch is intentionally
        # excluded from strategy semantics.
        batch_id = None

        for idx in range(self.ctx.last_length + 1, current_length + 1):
            # V4.1 audit identity for the physical arrival snapshot.
            self.ctx.current_batch_id = f"{int(getattr(self.ctx, 'live_day_seq', 0) or 0)}:{idx}"
            self.ctx.current_is_frontier = True
            # Transactional round processing:
            # last_length is committed ONLY after every state mutation for this
            # round has completed and the state has been persisted. This prevents
            # a crash/restart between steps from silently skipping a round.
            actual_group = self.groups[idx - 1]

            # V4.2.9 CRITICAL LIVE-EQUIVALENCE FIX
            # Before LIVE_START_ROUND, TRUE LIVE must do EXACTLY the same thing
            # as full-history hybrid replay: update windows only. It must NOT
            # build signals, mutate protection counters, relock, or open trades.
            # Previously an app that was running from round 1 followed a different
            # state path from an app first opened after round 180.
            if idx < LIVE_START_ROUND:
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
                    save_live_checkpoint(self.ctx)
                    warm_phase = "WARMUP_STARTED"

                if warm_phase == "WARMUP_STARTED":
                    self.window_engine.update_one_round(actual_group, idx)
                    self.ctx.round_txn_phase = "WARMUP_UPDATED"
                    save_live_checkpoint(self.ctx)
                    warm_phase = "WARMUP_UPDATED"

                if warm_phase == "WARMUP_UPDATED":
                    self.ctx.last_length = idx
                    self.ctx.last_decision_round = idx
                    self.ctx.last_decision_state = "WARMUP"
                    self.ctx.last_decision_next_group = None
                    self.ctx.last_decision_confidence = 0.0
                    append_round_audit(
                        self.ctx, idx, self.numbers[idx - 1], actual_group, None
                    )
                    self.ctx.round_txn_phase = "WARMUP_COMPLETE"
                    self.ctx.live_day_id = str(getattr(self.ctx, "live_day_date", "") or "")
                    self.ctx.data_length = idx
                    self.ctx.data_signature = make_numbers_signature(self.numbers, idx)
                    if not getattr(self.ctx, "dataset_anchor_signature", "") and idx >= 32:
                        self.ctx.dataset_anchor_signature = make_numbers_signature(
                            self.numbers, DATASET_RESET_ANCHOR_LEN
                        )
                    save_live_checkpoint(self.ctx)
                continue

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
                save_live_checkpoint(self.ctx)
                phase = "STARTED"

            # Resume from the last durable phase. Each phase is persisted
            # immediately after its state mutation so a crash cannot replay
            # the same irreversible step (especially window updates).
            if phase == "STARTED":
                settled_this_round = self.trade_engine.settle_trade(actual_group, idx)
                self.ctx.round_txn_settled = bool(settled_this_round or getattr(self.ctx, "pending_trade", None) is None)
                self.ctx.round_txn_phase = "SETTLED"
                save_live_checkpoint(self.ctx)
                phase = "SETTLED"

            if phase == "SETTLED":
                self.window_engine.update_one_round(actual_group, idx)
                self.ctx.round_txn_phase = "WINDOW_UPDATED"
                save_live_checkpoint(self.ctx)
                phase = "WINDOW_UPDATED"

            # V4.0 TRUE-FRONTIER: if several Sheet rows are discovered in the
            # same refresh, only the newest row existed as a decision frontier.
            # Intermediate rows may SETTLE an already-open exact-target trade and
            # must update windows, but must never create a retrospective signal/open.
            # V4.2.7 DETERMINISTIC LIVE:
            # Do NOT let polling/cache batch size change trading decisions.
            # Rows discovered together are still processed sequentially, one by one,
            # with the same signal/open logic as historical replay.
            is_live_frontier = True
            if phase == "WINDOW_UPDATED" and not is_live_frontier:
                self.ctx.last_decision_round = idx
                self.ctx.last_decision_state = "CATCH_UP"
                self.ctx.last_decision_next_group = None
                self.ctx.last_decision_confidence = 0.0
                self.ctx.open_reason = "CATCH_UP_NO_RETRO_OPEN"
                self.ctx.round_txn_opened = False
                self.ctx.round_txn_phase = "COMPLETE"
                self.ctx.round_txn_signal = {}
                self.ctx.last_length = idx
                append_round_audit(self.ctx, idx, self.numbers[idx - 1], actual_group, None)
                self.ctx.live_day_id = str(getattr(self.ctx, "live_day_date", "") or "")
                self.ctx.data_length = idx
                self.ctx.data_signature = make_numbers_signature(self.numbers, idx)
                if not getattr(self.ctx, "dataset_anchor_signature", "") and idx >= 32:
                    self.ctx.dataset_anchor_signature = make_numbers_signature(self.numbers, DATASET_RESET_ANCHOR_LEN)
                save_live_checkpoint(self.ctx)
                continue

            if phase == "WINDOW_UPDATED":
                signal = self.signal_engine.build_signal(idx)
                signal = self.signal_engine.apply_sample_aware_coherence(signal)
                confidence = self.signal_engine.get_confidence_score(signal)
                self.ctx.last_decision_confidence = confidence
                setattr(signal, "decision_confidence", confidence)
                self.ctx.round_txn_signal = signal_to_txn_dict(signal, confidence)
                self.ctx.round_txn_phase = "SIGNAL_READY"
                save_live_checkpoint(self.ctx)
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
                            save_live_checkpoint(self.ctx)
                    else:
                        self.ctx.last_decision_round = idx
                        self.ctx.last_decision_state = "WAIT"
                        self.ctx.last_decision_next_group = None
                self.ctx.round_txn_opened = bool(getattr(self.ctx, "last_open_round", -1) == idx)
                self.ctx.round_txn_phase = "OPENED" if self.ctx.round_txn_opened else "COMPLETE"
                save_live_checkpoint(self.ctx)

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
            f"LIVE SOURCE | {'STATELESS R1->CURRENT' if STATELESS_REPLAY_LIVE else 'INCREMENTAL'} | Google Sheet A:E DAY_SEQ format | "
            f"day_seq={getattr(self.ctx, "live_day_seq", 0)} | numbers={len(self.numbers)} | sheet_round={self.round_id} | "
            f"v70={'ON' if bool(getattr(self.ctx, 'v70_switch_enabled', False)) else 'OFF'} | cutover={V70_CUTOVER_DAY_SEQ} | "
            f"physical_frontier_cutover={FRONTIER_JOURNAL_CUTOVER_DAY_SEQ} | "
            f"window_score={getattr(self.ctx, 'window_score_mode', 'BASE')} | "
            f"frontiers={len(getattr(self.ctx, 'live_frontiers', []) or []) if getattr(self.ctx, 'live_frontiers', None) is not None else 'LEGACY'} | "
            f"current_frontier={'YES' if getattr(self.ctx, 'live_frontiers', None) is not None and self.round_id in set(getattr(self.ctx, 'live_frontiers', []) or []) else 'LEGACY' if getattr(self.ctx, 'live_frontiers', None) is None else 'NO'} | "
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

        # PROFIT LEDGER LOCK: current-day settled trade_history is source of truth.
        # Never let stale equity from a previous deploy/reset alter displayed P/L.
        rebuild_real_stats_from_history(self.ctx)
        refresh_ledger_checkpoint(self.ctx)
        ledger_profit = round(
            sum(float(x.profit or 0.0) for x in self.ctx.trade_history if x.hit is not None), 2
        )
        equity_profit = round(float(self.ctx.equity_curve[-1]), 2) if self.ctx.equity_curve else 0.0
        if ledger_profit != equity_profit or round(float(getattr(self.ctx, "ledger_profit", 0.0)), 2) != ledger_profit:
            st.error(
                f"PROFIT INTEGRITY ERROR: ledger={ledger_profit:+.1f}, "
                f"checkpoint={float(getattr(self.ctx, 'ledger_profit', 0.0)):+.1f}, "
                f"equity={equity_profit:+.1f}. LIVE display stopped."
            )
            st.stop()

        signal, confidence_score, confidence_level = self.build_display_signal()

        # V6 deterministic current-run checksums. These are display/safety metadata
        # only and never feed the strategy.
        self.ctx.live_engine_signature = make_engine_ledger_signature(self.ctx)
        _choice_hist = list(getattr(self.ctx, "daily_profit_history", []) or [])
        _choice_now = _adaptive_select_choices(_choice_hist) if ADAPTIVE_SAFE_ENABLED else _adaptive_defaults()
        self.ctx.live_adaptive_choice_signature = hashlib.sha256(
            json.dumps(_choice_now, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        # V7 TOP-ACTION UI:
        # header + authoritative physical BET/SKIP/WAIT are injected into the
        # placeholder created before EngineManager, so they remain at the top
        # even when raw-history audit messages are rendered during initialization.
        with _live_top_slot.container():
            self.dashboard.render_header()
            self.dashboard.render_adaptive_operator_action()

        if int(getattr(self.ctx, "last_length", 0) or 0) < MAX_ROUNDS_PER_DAY:
            st.divider()
            st.caption("ENGINE / AUDIT DETAILS — diagnostic only")
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
        else:
            st.caption("Day complete. Engine diagnostic panels hidden until the next DaySeq.")

        st.caption(
            f"""
V4.4.2 STATELESS REPLAY LIVE / AUDITED

Calculation source: fresh Google Numbers. No st.cache_data.
Each refresh reads raw history/current Numbers fresh. Completed-history replay may be reused only when its raw hash is identical; current DAY_SEQ always replays R1 to current round.
Stored Google daily_profit and legacy persistent engine state do NOT control strategy calculation.
Invariant: same prior Numbers + same current Numbers + same code = same ledger/profit/signal.
ADAPTIVE OPERATOR ACTION is the only physical BET/SKIP instruction. ENGINE SIGNAL is diagnostic only.

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


def _validated_numbers_by_day(history_df: pd.DataFrame, current_seq: int) -> list[tuple[int, str, list[int]]]:
    """Build completed historical days from the history sheet.

    Only round/number/day_seq/date are trusted. daily_profit is deliberately ignored.
    A day must be contiguous from round 1; malformed days fail closed.
    """
    if history_df is None or history_df.empty or history_df.shape[1] < 3:
        return []
    cols = {str(c).strip().lower(): c for c in history_df.columns}
    rc = cols.get("round", history_df.columns[0])
    nc = cols.get("number", history_df.columns[1])
    sc = cols.get("day_seq", history_df.columns[2])
    dc = cols.get("date", history_df.columns[3] if history_df.shape[1] > 3 else history_df.columns[0])
    tmp = history_df[[rc, nc, sc, dc]].copy()
    tmp["_seq"] = pd.to_numeric(tmp[sc], errors="coerce")
    tmp["_round"] = pd.to_numeric(tmp[rc], errors="coerce")
    tmp = tmp[(tmp["_seq"] > 0) & (tmp["_seq"] < int(current_seq or 0))]
    out = []
    for seq, g in tmp.groupby("_seq", sort=True):
        g = g.sort_values("_round")
        nums=[]; expected=1; day_id=""
        for _, row in g.iterrows():
            rr = int(row["_round"]) if pd.notna(row["_round"]) else -1
            n = _parse_number_value(row[nc])
            if rr != expected or n is None:
                raise ValueError(f"Historical DaySeq {int(seq)} invalid at expected round {expected}: round={rr}, number={row[nc]}")
            nums.append(n); expected += 1
            if not day_id:
                d = _parse_date_value(row[dc])
                day_id = d.isoformat() if d else f"DAYSEQ_{int(seq)}"
        if nums:
            out.append((int(seq), day_id, nums))
    return out



def _replay_one_day_stateless_audit(
    numbers: list[int],
    prior_history: list[dict],
    day_seq: int,
    day_id: str,
    *,
    v70_enabled: bool = True,
    daily_profit_lock: float = DAILY_PROFIT_LOCK,
    allowed_frontiers: Optional[list[int]] = None,
) -> tuple[float, list[TradeRecord], dict]:
    m = EngineManager.__new__(EngineManager)
    m.ctx = ensure_ctx_fields(EngineContext())
    m.ctx.live_day_seq = int(day_seq)
    m.ctx.live_day_date = str(day_id or "")
    m.ctx.live_day_id = str(day_id or "")
    m.ctx.daily_profit_history = list(prior_history)[-10:]
    m.ctx.live_frontiers = (
        None if allowed_frontiers is None
        else sorted(set(int(x) for x in allowed_frontiers))
    )
    m.ctx.v70_switch_enabled = bool(v70_enabled)
    m.ctx.daily_profit_lock_override = float(daily_profit_lock)
    m.ctx.fast_recovery_mode = True
    m.ctx.stateless_internal_replay = True
    m.ctx.hybrid_initialized = False
    m.ctx.recovery_replay_all_rounds = True
    m.ctx.data_correction_sequential_replay = True
    m.window_state = {w: WindowRecord() for w in WINDOWS}
    m.numbers = list(numbers)
    m.groups = build_groups(m.numbers)
    m.actual_group = m.groups[-1] if m.groups else None
    m.round_id = len(m.numbers)
    m.window_engine = WindowEngine(m.ctx, m.window_state)
    m.trade_engine = TradeEngine(m.ctx)
    m.signal_engine = SignalEngine(m.ctx, m.window_engine)
    m.protection_engine = ProtectionEngine(m.ctx, m.trade_engine)
    m.hybrid_replay_once()
    rebuild_real_stats_from_history(m.ctx)

    ledger = list(m.ctx.trade_history)
    profit = round(sum(
        float(t.profit or 0.0)
        for t in ledger
        if str(t.status).upper() in {"WIN", "LOSS"}
    ), 2)

    settled = [
        t for t in ledger
        if str(t.status).upper() in {"WIN", "LOSS"}
    ]
    diag = {
        "raw_len": len(numbers),
        "frontier_count": (
            None if allowed_frontiers is None else len(set(allowed_frontiers))
        ),
        "trade_count": len(settled),
        "pending_count": sum(
            1 for t in ledger
            if str(t.status).upper() == "PENDING"
        ),
        "gate_count": int(getattr(m.ctx, "v71_health_gate_count", 0) or 0),
        "gate_eligible": bool(getattr(m.ctx, "v71_health_gate_eligible", False)),
        "gate_round": int(getattr(m.ctx, "v71_health_gate_round", 0) or 0),
        "last_decision_state": str(getattr(m.ctx, "last_decision_state", "") or ""),
        "protection_reason": str(getattr(m.ctx, "protection_reason", "") or ""),
        "window_score_mode": str(getattr(m.ctx, "window_score_mode", "") or ""),
        "profit": profit,
    }

    m.ctx.pending_trade = None
    m.ctx.pending_target_round = None
    m.ctx.pending_round = -1
    m.ctx.trade_state = "FLAT"
    return profit, ledger, diag


def _replay_one_day_stateless(
    numbers: list[int],
    prior_history: list[dict],
    day_seq: int,
    day_id: str,
    *,
    v70_enabled: bool = True,
    daily_profit_lock: float = DAILY_PROFIT_LOCK,
    allowed_frontiers: Optional[list[int]] = None,
) -> tuple[float, list[TradeRecord]]:
    """Replay one day from R1 using exactly EngineManager.hybrid_replay_once().

    ``v70_enabled=False`` + ``daily_profit_lock=30.5`` reproduces the V4.4.8
    baseline branch inside the same source.  V70 uses the live defaults.
    """
    m = EngineManager.__new__(EngineManager)
    m.ctx = ensure_ctx_fields(EngineContext())
    m.ctx.live_day_seq = int(day_seq)
    m.ctx.live_day_date = str(day_id or "")
    m.ctx.live_day_id = str(day_id or "")
    m.ctx.daily_profit_history = list(prior_history)[-10:]
    m.ctx.live_frontiers = (
        None if allowed_frontiers is None
        else sorted(set(int(x) for x in allowed_frontiers))
    )
    m.ctx.v70_switch_enabled = bool(v70_enabled)
    m.ctx.daily_profit_lock_override = float(daily_profit_lock)
    m.ctx.fast_recovery_mode = True
    m.ctx.stateless_internal_replay = True
    m.ctx.hybrid_initialized = False
    m.ctx.recovery_replay_all_rounds = True
    m.ctx.data_correction_sequential_replay = True
    m.window_state = {w: WindowRecord() for w in WINDOWS}
    m.numbers = list(numbers)
    m.groups = build_groups(m.numbers)
    m.actual_group = m.groups[-1] if m.groups else None
    m.round_id = len(m.numbers)
    m.window_engine = WindowEngine(m.ctx, m.window_state)
    m.trade_engine = TradeEngine(m.ctx)
    m.signal_engine = SignalEngine(m.ctx, m.window_engine)
    m.protection_engine = ProtectionEngine(m.ctx, m.trade_engine)
    m.hybrid_replay_once()
    rebuild_real_stats_from_history(m.ctx)

    # V4.4.7 DAY ISOLATION LOCK:
    # Profit belongs only to trades settled inside this DAY_SEQ. A trade opened
    # on the final available round remains PENDING in the returned audit ledger,
    # but its execution state is explicitly terminated with this disposable day
    # context. It can NEVER be settled by R1 of the next DAY_SEQ.
    ledger = list(m.ctx.trade_history)
    profit = round(sum(
        float(t.profit or 0.0)
        for t in ledger
        if str(t.status).upper() in {"WIN", "LOSS"}
    ), 2)
    m.ctx.pending_trade = None
    m.ctx.pending_target_round = None
    m.ctx.pending_round = -1
    m.ctx.trade_state = "FLAT"
    return profit, ledger



# ============================================================================
# ============================================================
# ADAPTIVE SAFE PHYSICAL BET LAYER
# ============================================================
ADAPTIVE_SAFE_ENABLED = True
ADAPTIVE_LOOKBACK_DAYS = 9
ADAPTIVE_MIN_OBS_DAYS = 2
ADAPTIVE_SWITCH_MARGIN = 3.0
ADAPTIVE_NEG_DAY_PENALTY = 0.50
ADAPTIVE_G3_GAP = 8.0

def _adaptive_defaults() -> dict:
    return {"G1": 20, "G2": 20, "G3": "BASE", "G4": "BASE"}

def _trade_pn(t: TradeRecord, n: int) -> float:
    d = dict(getattr(t, "open_shadow_profit_by_n", {}) or {})
    return float(d.get(str(int(n)), getattr(t, "open_shadow_profit20", 0.0) if int(n)==20 else 0.0) or 0.0)

def _trade_wrn(t: TradeRecord, n: int) -> float:
    d = dict(getattr(t, "open_shadow_wr_by_n", {}) or {})
    return float(d.get(str(int(n)), getattr(t, "open_shadow_wr20", 0.0) if int(n)==20 else 0.0) or 0.0)

def _adaptive_group_allowed(t: TradeRecord, group: int, option) -> tuple[bool, str]:
    p20 = _trade_pn(t, 20)
    stability = float(getattr(t, "open_stability", 0.0) or 0.0)
    confidence = float(getattr(t, "open_confidence", 0.0) or 0.0)
    lock_reason = str(getattr(t, "open_lock_reason", "") or "")
    if group == 1:
        n=int(option); pn=_trade_pn(t,n); th=11.0*n/20.0
        ok=(pn>=th and stability>=0.60) or (lock_reason==V1175_G1_RELOCK_REASON and pn<th and stability>=0.60)
        return ok, f"G1_P{n}_{'OK' if ok else 'FILTER'}"
    if group == 2:
        n=int(option); ok=_trade_wrn(t,n)>=0.40
        return ok, f"G2_WR{n}_{'OK' if ok else 'FILTER'}"
    if group == 3:
        if str(option)=="GAP8":
            ok=(p20-_trade_pn(t,12))<=ADAPTIVE_G3_GAP
            return ok, "G3_GAP8_OK" if ok else "G3_GAP8_FILTER"
        return True, "G3_BASE_OK"
    if group == 4:
        if confidence<0.53: return False, "G4_CONFIDENCE_FILTER"
        if str(option)=="BASE": return True, "G4_BASE_OK"
        n=int(option); ok=(p20-_trade_pn(t,n))<=max(0.0,float(20-n))
        return ok, f"G4_P{n}_{'OK' if ok else 'FILTER'}"
    return False, "UNKNOWN_GROUP"

def _adaptive_apply_bet_filter(ledger, prev_day_bet_profit: float, choices: dict) -> list[dict]:
    rows=[]; g3_seen=0; prev_negative=float(prev_day_bet_profit or 0.0)<0.0
    for t in sorted(list(ledger or []), key=lambda x:(int(getattr(x,"round_id",0) or 0),int(getattr(x,"settle_round",10**9) or 10**9))):
        g=int(getattr(t,"predict",0) or 0); opt=choices.get(f"G{g}",_adaptive_defaults().get(f"G{g}"))
        allowed,reason=_adaptive_group_allowed(t,g,opt)
        if g==3:
            g3_seen+=1
            if prev_negative and g3_seen<=V1175_G3_SKIP_AFTER_NEGATIVE_DAY:
                allowed=False; reason=f"G3_AFTER_NEG_DAY_SKIP_{g3_seen}"
        status=str(getattr(t,"status","") or "").upper(); settled=status in {"WIN","LOSS"}; ep=float(getattr(t,"profit",0.0) or 0.0)
        rows.append({"day_seq":int(getattr(t,"open_day_seq",0) or 0),"date":str(getattr(t,"open_day_date","") or ""),"open_round":int(getattr(t,"round_id",0) or 0),"settle_round":getattr(t,"settle_round",None),"group":g,"status":status,"engine_profit":round(ep,2),"bet_allowed":bool(allowed),"bet_action":"BET" if allowed else "SKIP","bet_skip_reason":reason,"bet_profit":round(ep if allowed and settled else 0.0,2),"adaptive_option":opt})
    return rows

def _adaptive_counterfactual(ledger, prev_day_bet_profit: float) -> dict:
    out={"G1":{},"G2":{},"G3":{},"G4":{}}
    optsets={"G1":list(range(4,27)),"G2":list(range(4,27)),"G3":["BASE","GAP8"],"G4":["BASE"]+list(range(4,27))}
    ordered=sorted(list(ledger or []),key=lambda x:int(getattr(x,"round_id",0) or 0))
    for key,opts in optsets.items():
        g=int(key[1])
        for opt in opts:
            pnl=0.0; g3=0
            for t in ordered:
                if int(getattr(t,"predict",0) or 0)!=g: continue
                allowed,_=_adaptive_group_allowed(t,g,opt)
                if g==3:
                    g3+=1
                    if float(prev_day_bet_profit or 0.0)<0.0 and g3<=V1175_G3_SKIP_AFTER_NEGATIVE_DAY: allowed=False
                if allowed and str(getattr(t,"status","") or "").upper() in {"WIN","LOSS"}: pnl+=float(getattr(t,"profit",0.0) or 0.0)
            out[key][str(opt)]=round(pnl,2)
    return out

def _adaptive_select_choices(prior_items: list[dict]) -> dict:
    defaults=_adaptive_defaults()
    if not prior_items: return defaults
    current=dict(prior_items[-1].get("adaptive_choices",defaults) or defaults); hist=list(prior_items[-ADAPTIVE_LOOKBACK_DAYS:]); selected=dict(current)
    sets={"G1":[str(x) for x in range(4,27)],"G2":[str(x) for x in range(4,27)],"G3":["BASE","GAP8"],"G4":["BASE"]+[str(x) for x in range(4,27)]}
    for gkey,opts in sets.items():
        scores={}; obs={}
        for opt in opts:
            vals=[]
            for item in hist:
                vals.append(float(dict(dict(item.get("adaptive_cf",{}) or {}).get(gkey,{}) or {}).get(str(opt),0.0) or 0.0))
            obs[opt]=sum(1 for v in vals if abs(v)>1e-9)
            comp=0.0
            if gkey in {"G1","G2"}: comp=0.02*abs(int(opt)-20)
            elif gkey=="G4" and opt!="BASE": comp=0.20+0.04*abs(int(opt)-20)
            scores[opt]=sum(vals)-ADAPTIVE_NEG_DAY_PENALTY*sum(1 for v in vals if v<0.0)-comp
        eligible=[o for o in opts if obs[o]>=ADAPTIVE_MIN_OBS_DAYS]
        if not eligible: continue
        best=max(eligible,key=lambda o:scores[o]); cur=str(current.get(gkey,defaults[gkey])); cur_score=scores.get(cur,float("-inf"))
        if best!=cur and scores[best]<cur_score+ADAPTIVE_SWITCH_MARGIN: best=cur
        selected[gkey]=best if gkey=="G3" or (gkey=="G4" and best=="BASE") else ("BASE" if gkey=="G4" and best=="BASE" else int(best))
    return selected

# V117.5 BET FILTER SHADOW LAYER
# ============================================================================
# IMPORTANT:
# - This layer NEVER changes EngineContext, window selection, KEEP/relock,
#   cooldown, blacklist, protection, C79, pending trade, or daily engine target.
# - It only decides whether an already-generated LIVE101 trade signal should be
#   physically BET or SKIP.
# - Previous-day BET profit is replayed causally from raw Numbers, not stored
#   session/cache state. Therefore browser refresh/restart is deterministic.
# - Frozen after D1-D54 anti-overfit audit. Do not retune thresholds in live.
V1175_BET_FILTER_ENABLED = True
V1175_G1_P20_MIN = 11.0
V1175_G1_STABILITY_MIN = 0.60
V1175_G2_WR20_MIN = 0.40
V1175_G4_CONFIDENCE_MIN = 0.53
V1175_PREV_DAY_NEGATIVE_THRESHOLD = 0.0
V1175_G3_SKIP_AFTER_NEGATIVE_DAY = 2
V1175_G1_RELOCK_REASON = "RELOCK_BY_SHORT_TERM_FALLBACK_REAL_2_LOSS_RELOCK"


def _v1175_trade_base_bet_decision(t: TradeRecord) -> tuple[bool, str]:
    """Frozen group filter. Pure function: reads TradeRecord only."""
    try:
        group = int(getattr(t, "predict", 0) or 0)
    except Exception:
        group = 0

    p20 = float(getattr(t, "open_shadow_profit20", 0.0) or 0.0)
    wr20 = float(getattr(t, "open_shadow_wr20", 0.0) or 0.0)
    stability = float(getattr(t, "open_stability", 0.0) or 0.0)
    confidence = float(getattr(t, "open_confidence", 0.0) or 0.0)
    lock_reason = str(getattr(t, "open_lock_reason", "") or "")

    if group == 1:
        normal_ok = (
            p20 >= V1175_G1_P20_MIN
            and stability >= V1175_G1_STABILITY_MIN
        )
        relock_ok = (
            lock_reason == V1175_G1_RELOCK_REASON
            and p20 < V1175_G1_P20_MIN
            and stability >= V1175_G1_STABILITY_MIN
        )
        if normal_ok:
            return True, "G1_P20_STABILITY_OK"
        if relock_ok:
            return True, "G1_RELOCK2LOSS_EXCEPTION"
        return False, "G1_FILTER"

    if group == 2:
        return (
            (True, "G2_WR20_OK")
            if wr20 >= V1175_G2_WR20_MIN
            else (False, "G2_WR20_FILTER")
        )

    if group == 3:
        return True, "G3_BASE_OK"

    if group == 4:
        return (
            (True, "G4_CONFIDENCE_OK")
            if confidence >= V1175_G4_CONFIDENCE_MIN
            else (False, "G4_CONFIDENCE_FILTER")
        )

    return False, "UNKNOWN_GROUP"


def _v1175_apply_bet_filter(
    ledger: list[TradeRecord],
    prev_day_bet_profit: float,
) -> list[dict]:
    """Return deterministic BET/SKIP rows without mutating the engine ledger.

    The G3 counter includes eligible G3 engine signals in opening-round order.
    This intentionally includes a current PENDING signal so the operator sees
    the BET/SKIP instruction before settlement.
    """
    rows = []
    g3_seen = 0
    prev_negative = (
        float(prev_day_bet_profit or 0.0)
        < V1175_PREV_DAY_NEGATIVE_THRESHOLD
    )

    ordered = sorted(
        list(ledger or []),
        key=lambda t: (
            int(getattr(t, "round_id", 0) or 0),
            int(getattr(t, "settle_round", 10**9) or 10**9),
        ),
    )

    for t in ordered:
        base_allowed, base_reason = _v1175_trade_base_bet_decision(t)
        allowed = bool(base_allowed)
        reason = str(base_reason)

        try:
            group = int(getattr(t, "predict", 0) or 0)
        except Exception:
            group = 0

        if base_allowed and group == 3:
            g3_seen += 1
            if (
                prev_negative
                and g3_seen <= V1175_G3_SKIP_AFTER_NEGATIVE_DAY
            ):
                allowed = False
                reason = f"G3_AFTER_NEG_DAY_SKIP_{g3_seen}"

        status = str(getattr(t, "status", "") or "").upper()
        settled = status in {"WIN", "LOSS"}
        engine_profit = float(getattr(t, "profit", 0.0) or 0.0)
        bet_profit = engine_profit if (allowed and settled) else 0.0

        rows.append(
            {
                "day_seq": int(getattr(t, "open_day_seq", 0) or 0),
                "date": str(getattr(t, "open_day_date", "") or ""),
                "open_round": int(getattr(t, "round_id", 0) or 0),
                "settle_round": getattr(t, "settle_round", None),
                "group": group,
                "status": status,
                "engine_profit": round(engine_profit, 2),
                "bet_allowed": bool(allowed),
                "bet_action": "BET" if allowed else "SKIP",
                "bet_skip_reason": reason,
                "bet_profit": round(bet_profit, 2),
                "prev_day_bet_profit": round(float(prev_day_bet_profit or 0.0), 2),
                "g3_signal_rank": int(g3_seen) if group == 3 and base_allowed else None,
                "open_p20": round(float(getattr(t, "open_shadow_profit20", 0.0) or 0.0), 3),
                "open_wr20": round(float(getattr(t, "open_shadow_wr20", 0.0) or 0.0), 3),
                "open_stability": round(float(getattr(t, "open_stability", 0.0) or 0.0), 3),
                "open_confidence": round(float(getattr(t, "open_confidence", 0.0) or 0.0), 3),
                "open_lock_reason": str(getattr(t, "open_lock_reason", "") or ""),
            }
        )
    return rows


def _v1175_bet_profit(
    ledger: list[TradeRecord],
    prev_day_bet_profit: float,
) -> float:
    rows = _v1175_apply_bet_filter(ledger, prev_day_bet_profit)
    return round(sum(float(r["bet_profit"]) for r in rows), 2)


def replay_prior_days_v1175_bet_filter(
    history_df: pd.DataFrame,
    current_seq: int,
) -> list[dict]:
    """Causal raw-history replay of prior-day V117.5 BET P/L.

    Engine target/history remain LIVE101's own engine P/L.  Only the G3
    post-negative-day guard uses the previous V117.5 BET P/L.
    """
    engine_seed = []
    bet_results = []
    prev_bet_profit = 0.0

    for seq, day_id, nums in _validated_numbers_by_day(history_df, current_seq):
        engine_target = get_dynamic_daily_profit_lock(engine_seed)
        engine_profit, ledger = _replay_one_day_stateless(
            nums,
            engine_seed,
            seq,
            day_id,
            v70_enabled=False,
            daily_profit_lock=engine_target,
        )
        bet_profit = _v1175_bet_profit(ledger, prev_bet_profit)

        engine_item = {
            "day_seq": int(seq),
            "day_id": day_id,
            "profit": float(engine_profit),
        }
        engine_seed.append(engine_item)
        engine_seed = engine_seed[-10:]

        bet_results.append(
            {
                "day_seq": int(seq),
                "day_id": day_id,
                "engine_profit": round(float(engine_profit), 2),
                "bet_profit": round(float(bet_profit), 2),
            }
        )
        prev_bet_profit = float(bet_profit)

    return bet_results


def current_day_v1175_bet_rows(
    history_df: pd.DataFrame,
    current_seq: int,
    current_ledger: list[TradeRecord],
) -> tuple[list[dict], float]:
    """Return current-day BET/SKIP rows and previous completed BET profit."""
    prior = replay_prior_days_v1175_bet_filter(history_df, current_seq)
    prev_bet_profit = float(prior[-1]["bet_profit"]) if prior else 0.0
    rows = _v1175_apply_bet_filter(current_ledger, prev_bet_profit)
    return rows, round(prev_bet_profit, 2)

def replay_prior_days_from_numbers(history_df: pd.DataFrame, current_seq: int) -> list[dict]:
    """Causal Day1..Day(N-1) replay. No stored daily_profit is trusted."""
    seed=[]
    results=[]
    for seq, day_id, nums in _validated_numbers_by_day(history_df, current_seq):
        _hist_target = get_dynamic_daily_profit_lock(seed)
        profit, _ = _replay_one_day_stateless(
            nums, seed, seq, day_id,
            v70_enabled=False, daily_profit_lock=_hist_target
        )
        item = {"day_seq": int(seq), "day_id": day_id, "profit": float(profit)}
        results.append(item)
        seed.append(item)
        seed = seed[-10:]
    return results

def _negative_day_streak(values: list[float]) -> int:
    best = cur = 0
    for v in values:
        if float(v) < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _equity_max_drawdown(values: list[float]) -> float:
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for v in values:
        eq += float(v)
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return round(mdd, 2)


def audit_history_baseline_vs_v70(history_df: pd.DataFrame, current_seq: int) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Exact raw-number DaySeq replay: V4.4.8 baseline vs V70 candidate.

    Both branches use independent causal prior-day seeds. No stored daily_profit
    is trusted and no future DaySeq result is visible to an earlier day.  The
    returned trade-detail table also makes timing changes explicit.
    """
    days = _validated_numbers_by_day(history_df, current_seq)
    baseline_seed: list[dict] = []
    v70_seed: list[dict] = []
    rows = []
    detail_rows = []

    def settled(ledger):
        return [t for t in ledger if str(t.status).upper() in {"WIN", "LOSS"}]

    def append_detail(version: str, seq: int, day_id: str, ledger):
        for t in ledger:
            if str(getattr(t, "status", "")).upper() not in {"WIN", "LOSS"}:
                continue
            detail_rows.append({
                "Version": version,
                "DaySeq": int(seq),
                "Date": day_id,
                "OpenRound": int(getattr(t, "round_id", 0) or 0),
                "SettleRound": int(getattr(t, "settle_round", 0) or 0),
                "Window": getattr(t, "locked_window", None),
                "Predict": getattr(t, "predict", None),
                "Actual": getattr(t, "actual", None),
                "Status": str(getattr(t, "status", "")),
                "Profit": float(getattr(t, "profit", 0.0) or 0.0),
                "LockReason": str(getattr(t, "open_lock_reason", "") or ""),
            })

    for seq, day_id, nums in days:
        base_profit, base_ledger = _replay_one_day_stateless(
            nums, baseline_seed, seq, day_id,
            v70_enabled=False, daily_profit_lock=30.5,
        )
        v70_profit, v70_ledger = _replay_one_day_stateless(
            nums, v70_seed, seq, day_id,
            v70_enabled=True, daily_profit_lock=10.0,
        )

        base_item = {"day_seq": int(seq), "day_id": day_id, "profit": float(base_profit)}
        v70_item = {"day_seq": int(seq), "day_id": day_id, "profit": float(v70_profit)}
        baseline_seed.append(base_item); baseline_seed = baseline_seed[-10:]
        v70_seed.append(v70_item); v70_seed = v70_seed[-10:]

        base_settled = settled(base_ledger)
        v70_settled = settled(v70_ledger)
        append_detail("BASELINE", seq, day_id, base_settled)
        append_detail("V70", seq, day_id, v70_settled)

        v70_switches = sum(
            1 for t in v70_settled
            if str(getattr(t, "open_lock_reason", "") or "").startswith("V70_AFTER_LOSS")
        )
        base_open = [int(getattr(t, "round_id", 0) or 0) for t in base_settled]
        v70_open = [int(getattr(t, "round_id", 0) or 0) for t in v70_settled]
        base_set = set(base_open); v70_set = set(v70_open)
        rows.append({
            "DaySeq": int(seq),
            "Date": day_id,
            "Rounds": len(nums),
            "BaselineProfit": float(base_profit),
            "V70Profit": float(v70_profit),
            "Delta": round(float(v70_profit) - float(base_profit), 2),
            "BaselineTrades": len(base_settled),
            "V70Trades": len(v70_settled),
            "V70Switches": int(v70_switches),
            "CommonOpenRounds": len(base_set & v70_set),
            "BaselineOnlyOpenRounds": len(base_set - v70_set),
            "V70OnlyOpenRounds": len(v70_set - base_set),
            "TimingSame": int(base_open == v70_open),
        })

    df = pd.DataFrame(rows)
    detail_df = pd.DataFrame(detail_rows)
    if df.empty:
        return df, {}, detail_df
    base = [float(x) for x in df["BaselineProfit"].tolist()]
    cand = [float(x) for x in df["V70Profit"].tolist()]
    metrics = {
        "days": len(df),
        "baseline_total": round(sum(base), 2),
        "v70_total": round(sum(cand), 2),
        "gain": round(sum(cand) - sum(base), 2),
        "baseline_negative_days": sum(x < 0 for x in base),
        "v70_negative_days": sum(x < 0 for x in cand),
        "baseline_negative_streak": _negative_day_streak(base),
        "v70_negative_streak": _negative_day_streak(cand),
        "baseline_max_drawdown": _equity_max_drawdown(base),
        "v70_max_drawdown": _equity_max_drawdown(cand),
        "v70_switches": int(df["V70Switches"].sum()),
        "timing_same_days": int(df["TimingSame"].sum()),
        "timing_changed_days": int((df["TimingSame"] == 0).sum()),
        "baseline_only_opens": int(df["BaselineOnlyOpenRounds"].sum()),
        "v70_only_opens": int(df["V70OnlyOpenRounds"].sum()),
    }
    return df, metrics, detail_df


def render_v70_historical_audit(manager: EngineManager) -> None:
    """Operator-triggered exact historical audit; never changes live calculation state."""
    with st.expander("V70 RAW LIVE AUDIT - historical DaySeq", expanded=False):
        st.caption(
            "Replays raw history DaySeq-by-DaySeq with the same EngineManager path. "
            "Baseline and V70 have independent causal prior-day seeds."
        )
        if st.button("Run V70 historical raw replay", key="run_v70_raw_history_audit"):
            with st.spinner("Running exact raw-number replay..."):
                hdf = getattr(manager, "history_df", None)
                df, metrics, detail_df = audit_history_baseline_vs_v70(
                    hdf, int(getattr(manager.ctx, "live_day_seq", 0) or 0)
                )
                st.session_state["v70_raw_audit_df"] = df
                st.session_state["v70_raw_audit_metrics"] = metrics
                st.session_state["v70_raw_audit_detail_df"] = detail_df

        metrics = st.session_state.get("v70_raw_audit_metrics")
        df = st.session_state.get("v70_raw_audit_df")
        detail_df = st.session_state.get("v70_raw_audit_detail_df")
        if isinstance(metrics, dict) and metrics:
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Baseline", f"{metrics['baseline_total']:+.1f}")
            c2.metric("V70", f"{metrics['v70_total']:+.1f}", f"{metrics['gain']:+.1f}")
            c3.metric("Negative days", f"{metrics['v70_negative_days']}", f"vs {metrics['baseline_negative_days']}")
            c4.metric("Neg streak", f"{metrics['v70_negative_streak']}", f"vs {metrics['baseline_negative_streak']}")
            c5.metric("Max DD", f"{metrics['v70_max_drawdown']:+.1f}", f"vs {metrics['baseline_max_drawdown']:+.1f}")
            st.json(metrics)
        if isinstance(df, pd.DataFrame) and not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download V70 raw audit CSV",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name="V70_RAW_LIVE_AUDIT.csv",
                mime="text/csv",
                key="download_v70_raw_audit",
            )
        if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
            st.download_button(
                "Download baseline vs V70 trade-detail CSV",
                data=detail_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="V70_RAW_LIVE_TRADE_DETAIL.csv",
                mime="text/csv",
                key="download_v70_raw_trade_detail",
            )


# V7: reserve the first visible position on the page for the live operator panel.
# EngineManager.__init__ may emit historical/audit messages, but this placeholder
# remains above them and is populated after the fresh replay finishes.
_live_top_slot = st.empty()

manager = EngineManager()

st.caption(
    "V8 COMPACT | VERIFIED HISTORY REPLAY | CURRENT DAY FRESH | LIVE SELF-CHECK"
)

try:
    manager.run()
    with st.expander("Advanced historical audit", expanded=False):
        render_v70_historical_audit(manager)
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
    st.caption("Refresh control — NO CACHE remains active on every refresh.")
    if st.button("🔄 Refresh now", use_container_width=True):
        st.rerun()

    auto_refresh_enabled = st.checkbox(
        "Auto refresh",
        value=False,
        help="OFF by default so the UI stays stable for inspection. When ON, the whole Streamlit page reloads."
    )
    refresh_seconds = st.number_input(
        "Refresh seconds",
        min_value=15,
        max_value=120,
        value=30,
        step=15,
        disabled=not auto_refresh_enabled,
    )

_current_round_for_refresh = int(getattr(manager.ctx, "last_length", 0) or 0)
if auto_refresh_enabled and _current_round_for_refresh < 288:
    st.sidebar.info(
        f"Auto refresh ON: every {int(refresh_seconds)}s. "
        "Turn it OFF while reviewing the dashboard."
    )
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
elif auto_refresh_enabled and _current_round_for_refresh >= 288:
    st.sidebar.success("Day complete at R288 — auto refresh paused.")
