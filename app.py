# ============================================================
# APP V50 SINGLE CLEAN
# Refactor from uploaded app_v50_fix_v7 source
# ============================================================

from __future__ import annotations

import time
import json
import os
import math
import hashlib
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Optional, Any

import pandas as pd
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V58.2 Robust Walk-Forward Live",
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
STATE_FILE = os.environ.get("V50_STATE_FILE", "v50_live_state.json")
STATE_WORKSHEET_DEFAULT = "state"

# V50 profit protection tuning
LIVE_LOSS_COOLDOWN_ROUNDS = 5
LOCK_MIN_PROFIT20 = 0.0
LOCK_MAX_LOSS_STREAK = 1
LIVE_RELOCK_PROFIT_STOP = 0.0
LIVE_RELOCK_LOSS_STREAK = 1

# Shadow live scoring per window from LIVE_START_ROUND.
# Window selection will prefer live performance, not only historical profit.
LEADER_MIN_LIVE_WR20 = 0.34
LEADER_MIN_LIVE_PROFIT20 = 0.0
CANDIDATE_MIN_LIVE_PROFIT20 = 0.0
CANDIDATE_MIN_LIVE_WR20 = 0.34
CANDIDATE_MAX_LIVE_LOSS_STREAK = 1

# Real trade-aware relock.
# After a window has real trades, relock uses REAL performance first.
REAL_MIN_TRADE_COUNT_FOR_LOCK = 3
REAL_MIN_PROFIT_FOR_LOCK = 0.0
REAL_MAX_LOSS_STREAK_FOR_LOCK = 0
REAL_MIN_WR_FOR_LOCK = 0.35

# V4 fallback/anti-deadlock.
# If no real-positive window exists, use short-term candidate score
# so the engine can continue testing instead of WAIT forever.
FALLBACK_MIN_PROFIT20 = 0.0
FALLBACK_MIN_WR20 = 0.34
FALLBACK_MAX_LOSS_STREAK = 1
TRADE_GAP_ROUNDS = 1
LOW_WR_CONSENSUS_READY = 0.667
LOW_WR_LEVEL = 0.50
MAX_WINDOW_LOSS_STREAK_FOR_TOP = 5

# V52 anti-zigzag: after a window loses / turns negative, do not select it again soon.
WINDOW_COOLDOWN_ROUNDS = 6
BLACKLIST_REAL_NEGATIVE = True

PROFIT10_STOP = -3.0
WR20_STOP = 0.30
DRAWDOWN_STOP = -6.0
FLIPRATE_STOP = 0.65

CONSENSUS_READY = 0.667
STABILITY_READY = 0.50

# V53 defensive gates
MIN_CONFIDENCE_READY = 0.43
SAFE_DRAWDOWN_FROM_PEAK = -3.0
SAFE_MODE_ROUNDS = 3

# V56 True Live Deterministic: avoid trade starvation.
REAL_SHADOW_BLEND_MIN_TRADES = 10
REAL_SHADOW_BLEND_FULL_TRADES = 30
MIN_SHADOW_PROFIT20_FOR_TEST = 1.0
MIN_SHADOW_WR20_FOR_TEST = 0.34
MAX_REAL_NEGATIVE_SOFT = -2.0
WINDOW_SELECTION_MODE = "robust"
UCB_EXPLORATION_C = 0.0

# V58.3 robust selection: fixed, sample-aware, no per-dataset tuning.
ROBUST_MIN_SHADOW_SAMPLES = 8
ROBUST_MIN_SHADOW_SAMPLES_FOR_LOCK = 12
ROBUST_MAX_LOCK_DRAWDOWN_SCORE = -0.50
ROBUST_RELOCK_LOSS_STREAK = 2
ROBUST_REAL_MIN_TRADES = 5
ROBUST_READY_FLOOR = -0.25
ROBUST_Z = 0.84  # one-sided ~80% Wilson lower bound

# V54 long-run controls
RISK_PAUSE_ROUNDS = 4
BLACKLIST_DURATION_ROUNDS = 8
MIN_TRADES_FOR_PROTECTION = 8

# Optional local CSV replay input. If set, load_numbers() reads this file instead of Google Sheet.
INPUT_CSV_PATH = os.environ.get("V54_INPUT_CSV", "").strip()
# ============================================================
# V58.1 CLEAN / NO-OVERFIT PROFILE
# ============================================================
# This profile intentionally does NOT add per-dataset score thresholds,
# exceptional-window recovery, or outcome-dependent parameter changes.
# Parameters remain fixed while the Sheet data advances.
STATE_VERSION = "V58_1_LIVE_DETERMINISTIC_2LOSS"


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
    state_version: str = "V58_4_ROBUST_ANTI_OVERFIT"
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
    data_signature: str = ""



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

    last_length: int = 0
    last_open_round: int = -1
    last_settle_round: int = -1
    last_window_round: int = -1
    last_signal_round: int = -1

    cooldown_counter: int = 0
    cooldown_loss_streak_marker: int = -1
    safe_mode_counter: int = 0
    protection_reason: str = ""
    open_reason: str = ""
    locked_window: Optional[int] = None
    lock_reason: str = ""
    state_version: str = "V58_4_ROBUST_ANTI_OVERFIT"

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
    data_signature: str = ""
    dataset_anchor_signature: str = ""
    processed_numbers: list[int] = field(default_factory=list)
    correction_pause: bool = False
    correction_round: int = 0
    correction_old_value: Optional[int] = None
    correction_new_value: Optional[int] = None




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

    previous_version = getattr(ctx, "state_version", "")
    ctx.state_version = STATE_VERSION

    if not hasattr(ctx, "pending_confidence"):
        ctx.pending_confidence = 0.0
    if not hasattr(ctx, "pending_target_round"):
        ctx.pending_target_round = 0
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

    if previous_version and previous_version != STATE_VERSION:
        ctx.algorithm_migration_pending = True
    if not hasattr(ctx, "algorithm_migration_pending"):
        ctx.algorithm_migration_pending = False

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

@st.cache_data(ttl=8)
def load_numbers(refresh_bucket: int = 0) -> list[int]:
    if INPUT_CSV_PATH:
        try:
            df = pd.read_csv(INPUT_CSV_PATH)
        except Exception as e:
            st.error(f"Load local CSV error: {e}")
            st.stop()
    else:
        url = (
            f"https://docs.google.com/spreadsheets/d/"
            f"{SHEET_ID}/export?format=csv"
            f"&cache={time.time()}"
        )

        try:
            df = pd.read_csv(url)
        except Exception as e:
            st.error(f"Load sheet error: {e}")
            st.stop()

    df.columns = [
        str(x).lower().strip()
        for x in df.columns
    ]

    if "number" not in df.columns:
        st.error("Sheet must contain column 'number'")
        st.stop()

    nums = (
        pd.to_numeric(df["number"], errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )

    return [
        x
        for x in nums
        if 1 <= x <= 12
    ]



@st.cache_data(ttl=8)
def load_round_times(refresh_bucket: int = 0) -> list[str]:
    """Load the Sheet time column aligned with valid number rows.

    Supported column names: time, round_time, timestamp, datetime.
    Invalid/blank number rows are skipped exactly like load_numbers().
    """
    if INPUT_CSV_PATH:
        df = pd.read_csv(INPUT_CSV_PATH)
    else:
        url = (
            f"https://docs.google.com/spreadsheets/d/"
            f"{SHEET_ID}/export?format=csv"
            f"&cache={time.time()}"
        )
        df = pd.read_csv(url)

    df.columns = [str(x).lower().strip() for x in df.columns]
    time_col = next(
        (c for c in ("time", "round_time", "timestamp", "datetime", "date_time")
         if c in df.columns),
        None
    )
    if time_col is None:
        return []

    number_series = pd.to_numeric(df["number"], errors="coerce")
    out = []
    for i, raw_n in enumerate(number_series):
        if pd.isna(raw_n):
            continue
        n = int(raw_n)
        if not (1 <= n <= 12):
            continue
        raw_t = df.iloc[i][time_col]
        if pd.isna(raw_t):
            out.append("")
        else:
            text = str(raw_t).strip()
            # Normalize spreadsheet datetime values to a compact display.
            try:
                dt = pd.to_datetime(raw_t, errors="raise")
                if not isinstance(raw_t, str) or any(ch in text for ch in ("/", "-")):
                    text = dt.strftime("%H:%M")
                elif re.match(r"^\d{1,2}:\d{2}", text):
                    text = text[:5]
            except Exception:
                text = text[:19]
            out.append(text)
    return out


def get_round_time(round_id: int, round_times: list[str]) -> str:
    """Return exact Sheet time for a round, or blank if unavailable."""
    try:
        r = int(round_id)
    except Exception:
        return ""
    if r <= 0 or r > len(round_times):
        return ""
    return str(round_times[r - 1] or "")


def infer_next_round_time(round_id: int, round_times: list[str]) -> tuple[str, bool]:
    """Infer next slot only when the Sheet provides a regular time sequence."""
    exact = get_round_time(round_id, round_times)
    if exact:
        return exact, False
    if len(round_times) < 2:
        return "", False

    try:
        vals = []
        for t in round_times[-5:]:
            if not t:
                continue
            vals.append(pd.to_datetime(t))
        if len(vals) < 2:
            return "", False
        deltas = [(vals[i] - vals[i-1]).total_seconds() for i in range(1, len(vals))]
        delta = sorted(deltas)[len(deltas)//2]
        if delta <= 0 or delta > 3600:
            return "", False
        return (vals[-1] + pd.to_timedelta(delta, unit="s")).strftime("%H:%M"), True
    except Exception:
        return "", False


def group_of(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def build_groups(numbers: list[int]) -> list[int]:
    return [
        group_of(x)
        for x in numbers
    ]


def detect_processed_data_change(ctx: EngineContext, numbers: list[int]) -> Optional[tuple[int, int, int]]:
    """Return (round, old_value, new_value) if a processed value was edited."""
    old = list(getattr(ctx, "processed_numbers", []) or [])
    n = min(len(old), int(getattr(ctx, "last_length", 0) or 0), len(numbers))
    for i in range(n):
        old_v = int(old[i])
        new_v = int(numbers[i])
        if old_v != new_v:
            return i + 1, old_v, new_v
    return None


def make_dataset_anchor_signature(numbers: list[int]) -> str:
    n = min(max(int(LIVE_START_ROUND), 1), len(numbers))
    h = hashlib.sha256()
    for i, value in enumerate(numbers[:n], start=1):
        h.update(f"{i}:{int(value)}|".encode("utf-8"))
    return h.hexdigest()


def make_numbers_signature(numbers: list[int], limit: Optional[int] = None) -> str:
    """Stable signature of the current dataset prefix for daily Sheet resets."""
    import hashlib
    sample = numbers if limit is None else numbers[:max(0, int(limit))]
    payload = f"{len(sample)}|" + ",".join(str(int(x)) for x in sample)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_data() -> tuple[list[int], list[int], int, int]:
    numbers = load_numbers(refresh_bucket=int(time.time() // 5))

    if len(numbers) < MIN_DATA_LEN:
        st.warning("Waiting data...")
        st.stop()

    groups = build_groups(numbers)
    actual_group = groups[-1]
    round_id = len(numbers)

    return numbers, groups, actual_group, round_id


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

    def _wilson_lower(self, wins: int, n: int, z: float = ROBUST_Z) -> float:
        if n <= 0:
            return 0.0
        p = wins / float(n)
        z2 = z * z
        denom = 1.0 + z2 / n
        centre = p + z2 / (2.0 * n)
        margin = z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
        return max(0.0, min(1.0, (centre - margin) / denom))

    def _robust_ev(self, hits: list[int]) -> float:
        n = len(hits)
        if n <= 0:
            return -1.0
        wins = int(sum(hits))
        posterior = (wins + 2.0) / (n + 4.0)
        lower = self._wilson_lower(wins, n)
        p = 0.65 * lower + 0.35 * posterior
        return 3.5 * p - 1.0

    def _canonical_rank_score(self, window_id: int, stt: WindowRecord) -> float:
        # Single source of truth: multi-horizon shadow + conservative real blend.
        h20 = list(stt.live_hit_history)[-20:]
        h50 = list(stt.live_hit_history)[-50:]
        if not h20:
            h20 = list(stt.hit_history)[-20:]
            h50 = list(stt.hit_history)[-50:]
        if not h20:
            return -9.0

        ev20 = self._robust_ev(h20)
        ev50 = self._robust_ev(h50) if len(h50) >= ROBUST_MIN_SHADOW_SAMPLES else ev20
        consistency = min(ev20, ev50)
        average_ev = 0.60 * ev20 + 0.40 * ev50
        disagreement = abs(ev20 - ev50)

        score = (
            0.70 * consistency
            + 0.30 * average_ev
            - 0.15 * disagreement
            - 0.12 * min(int(stt.live_loss_streak), 3)
        )

        real = get_history_real_stats(self.ctx, window_id)
        trades = int(real.get("trade_count", 0))
        if trades >= ROBUST_REAL_MIN_TRADES:
            rw = int(real.get("win", 0))
            rlb = self._wilson_lower(rw, trades)
            rpost = (rw + 2.0) / (trades + 4.0)
            real_ev = 3.5 * (0.65 * rlb + 0.35 * rpost) - 1.0
            score = 0.65 * score + 0.35 * real_ev
            score -= 0.10 * min(int(real.get("loss_streak", 0)), 3)

        return round(score, 6)

    def get_top_windows(self, top_n: int = TOPN) -> list[tuple[int, WindowRecord]]:
        # Canonical active ranking. No UCB bonus, no secondary selector.
        for stt in self.state.values():
            self._ensure_live_fields(stt)

        ranked = []
        for w, stt in self.state.items():
            if stt.next_group is None:
                continue

            cooled_until = int(getattr(self.ctx, "cooled_windows", {}).get(w, 0))
            black_until = int(getattr(self.ctx, "blacklisted_windows", {}).get(w, 0))
            if self.ctx.last_length < cooled_until or self.ctx.last_length < black_until:
                continue

            real = get_history_real_stats(self.ctx, w)
            hard_bad = (
                int(real.get("trade_count", 0)) >= ROBUST_REAL_MIN_TRADES
                and float(real.get("profit", 0.0)) <= -2.0
                and int(real.get("loss_streak", 0)) >= 2
            )
            if hard_bad:
                continue

            ranked.append((self._canonical_rank_score(w, stt), w, stt))

        ranked.sort(key=lambda x: (-x[0], x[1]))
        return [(w, stt) for _, w, stt in ranked[:max(1, int(top_n))]]


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

    @staticmethod
    def _wilson_lower(wins: int, n: int, z: float = ROBUST_Z) -> float:
        if n <= 0:
            return 0.0
        p = wins / float(n)
        z2 = z * z
        denom = 1.0 + z2 / n
        centre = p + z2 / (2.0 * n)
        margin = z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
        return max(0.0, min(1.0, (centre - margin) / denom))

    def _robust_ev(self, hits: list[int]) -> float:
        n = len(hits)
        if n <= 0:
            return -1.0
        wins = int(sum(hits))
        p_post = (wins + 2.0) / (n + 4.0)
        p_lb = self._wilson_lower(wins, n)
        p_robust = 0.65 * p_lb + 0.35 * p_post
        return 3.5 * p_robust - 1.0

    def robust_shadow_score(self, obj: WindowRecord) -> float:
        # Fixed walk-forward score. A 20-round spike cannot dominate a poor
        # 50-round result; consistency is explicitly rewarded.
        h20 = list(obj.live_hit_history)[-20:]
        h50 = list(obj.live_hit_history)[-50:]
        if not h20:
            return -1.0

        ev20 = self._robust_ev(h20)
        ev50 = self._robust_ev(h50) if len(h50) >= ROBUST_MIN_SHADOW_SAMPLES else ev20
        consistency = min(ev20, ev50)
        avg_ev = 0.60 * ev20 + 0.40 * ev50
        disagreement = abs(ev20 - ev50)
        loss_penalty = 0.12 * min(int(obj.live_loss_streak), 3)
        return round(0.70 * consistency + 0.30 * avg_ev - 0.15 * disagreement - loss_penalty, 3)

    def shadow_candidate_score(self, obj: WindowRecord) -> float:
        return self.robust_shadow_score(obj)

    def hybrid_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        stat = self.get_real_stats(window_id)
        trades = int(stat.get("trade_count", 0))
        shadow = self.robust_shadow_score(obj)
        if trades < ROBUST_REAL_MIN_TRADES:
            return shadow

        wins = int(stat.get("win", 0))
        p_post = (wins + 2.0) / (trades + 4.0)
        p_lb = self._wilson_lower(wins, trades)
        real_ev = 3.5 * (0.65 * p_lb + 0.35 * p_post) - 1.0
        return round(0.60 * shadow + 0.40 * real_ev - 0.10 * min(int(stat.get("loss_streak", 0)), 3), 3)

    def real_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        return self.hybrid_candidate_score(window_id, obj)

    def candidate_score(self, obj: WindowRecord) -> float:
        return self.robust_shadow_score(obj)

    def ucb_candidate_score(self, window_id: int, obj: WindowRecord) -> float:
        # Compatibility method only; exploration bonus is intentionally disabled.
        return self.hybrid_candidate_score(window_id, obj)

    def selection_score(self, window_id: int, obj: WindowRecord) -> float:
        return self.hybrid_candidate_score(window_id, obj)

    def choose_relock_candidate(
        self,
        top_rows: list[tuple[int, WindowRecord]]
    ) -> tuple[Optional[int], Optional[WindowRecord], str]:
        # The exact same ranking used by Top-N is used for locking.
        ranked = self.window_engine.get_top_windows(len(WINDOWS))
        for w, obj in ranked:
            if obj.next_group is None:
                continue
            if self.is_window_cooled(w) or self.is_window_blacklisted(w):
                continue

            real = self.get_real_stats(w)
            if (
                int(real.get("trade_count", 0)) >= ROBUST_REAL_MIN_TRADES
                and float(real.get("profit", 0.0)) < 0.0
                and int(real.get("loss_streak", 0)) >= 2
            ):
                continue

            return w, obj, "CANONICAL_ROBUST_RANK"

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

        if locked_obj is None:
            relock_needed = True
            lock_reason = "NO_LOCK"
        elif locked_obj.next_group is None:
            relock_needed = True
            lock_reason = "LOCK_NO_NEXT"
        else:
            real_stat = self.get_real_stats(locked_window)
            shadow_samples = len(locked_obj.live_hit_history)
            robust_score = self.window_engine._canonical_rank_score(locked_window, locked_obj)
            if int(locked_obj.live_loss_streak) >= ROBUST_RELOCK_LOSS_STREAK:
                relock_needed = True
                lock_reason = "LOCK_TWO_CONSECUTIVE_SHADOW_LOSSES"
            elif shadow_samples >= ROBUST_MIN_SHADOW_SAMPLES_FOR_LOCK and robust_score < ROBUST_MAX_LOCK_DRAWDOWN_SCORE:
                relock_needed = True
                lock_reason = "LOCK_ROBUST_SCORE_BAD"
            elif (
                real_stat["trade_count"] >= ROBUST_REAL_MIN_TRADES
                and real_stat["profit"] < 0
                and real_stat["loss_streak"] >= 2
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
        if round_id >= LIVE_START_ROUND and locked_obj is not None and next_group is not None:
            robust_score = self.window_engine._canonical_rank_score(locked_window, locked_obj)
            real_ok = (
                real_locked_stat["trade_count"] >= ROBUST_REAL_MIN_TRADES
                and real_locked_stat["profit"] > 0
                and real_locked_stat["loss_streak"] <= 1
            )
            strong_confirmation = consensus >= required_consensus and leader_wr20 >= 0.35
            if (
                stability >= STABILITY_READY
                and leader_loss_streak < ROBUST_RELOCK_LOSS_STREAK
                and robust_score >= ROBUST_READY_FLOOR
                and (real_ok or strong_confirmation)
            ):
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

    def reconcile_pending_from_sheet(
        self,
        groups: list[int],
        current_length: int
    ) -> bool:
        """Settle a persisted pending trade at its exact target round.

        This is a state-recovery mechanism, not a trading rule:
        - pending opened at round N targets round N+1
        - if round N+1 is already present in the Sheet, settle it immediately
        - guards/lock/confidence are never consulted for settlement
        """
        # EXACT_TARGET_ROUND_INVARIANT:
        # A pending trade opened at N can only settle against Sheet round N+1.
        # Never settle it against the latest available round when several rows
        # arrived at once; this prevents false WIN/LOSS results after downtime.
        pending = self.ctx.pending_trade
        if pending is None:
            return False

        try:
            open_round = int(self.ctx.pending_round)
        except Exception:
            open_round = 0

        target_round = open_round + 1
        if open_round <= 0 or target_round > current_length:
            return False

        actual_group = int(groups[target_round - 1])
        self.settle_trade(actual_group, target_round)
        return True

    def settle_trade(self, actual_group: int, current_round: int) -> None:
        if self.ctx.pending_trade is None:
            return
        if current_round <= self.ctx.pending_round:
            return
        if current_round == self.ctx.last_settle_round:
            return

        predict = self.ctx.pending_trade
        hit = int(predict == actual_group)
        profit = WIN_GROUP if hit else LOSS_GROUP

        if self.ctx.pending_index is not None and 0 <= self.ctx.pending_index < len(self.ctx.trade_history):
            record = self.ctx.trade_history[self.ctx.pending_index]
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

        self.ctx.pending_trade = None
        self.ctx.pending_confidence = 0.0
        self.ctx.pending_round = 0
        self.ctx.pending_index = None
        self.ctx.pending_locked_window = None
        self.ctx.pending_confidence = 0.0
        self.ctx.pending_target_round = 0
        self.ctx.trade_state = "IDLE"
        self.ctx.last_settle_round = current_round

        # Keep real stats/equity aligned with trade_history as source of truth.
        rebuild_real_stats_from_history(self.ctx)

        # Two-loss protection only: a single LOSS is recorded but does not
        # trigger cooldown/blacklist. Protection activates after exactly two
        # consecutive losses for the same locked window.
        if hit == 0 and record.locked_window is not None:
            try:
                w = int(record.locked_window)
            except Exception:
                w = record.locked_window
            ensure_ctx_fields(self.ctx)
            stat = get_history_real_stats(self.ctx, w)

            if int(stat.get("loss_streak", 0)) >= 2:
                self.ctx.cooled_windows[w] = int(current_round + WINDOW_COOLDOWN_ROUNDS)
                if not hasattr(self.ctx, "blacklisted_windows") or self.ctx.blacklisted_windows is None:
                    self.ctx.blacklisted_windows = {}
                self.ctx.blacklisted_windows[w] = int(current_round + BLACKLIST_DURATION_ROUNDS)

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

        # Chặn sớm khi loss streak >= 3.
        # Chỉ kích hoạt 1 lần cho mỗi mức streak để không bị WAIT mãi.
        if (
            loss_streak >= 3
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
        self.round_times: list[str] = []

    def set_round_times(self, round_times: list[str]) -> None:
        self.round_times = list(round_times or [])

    def render_header(self) -> None:
        st.title("🚀 V58 Stable Walk-Forward Live")

    def render_signal(self, signal: SignalRecord, confidence_score: float) -> None:
        color = "#00aa00" if signal.state == "READY" else "#555555"

        current_round = self.ctx.last_length
        target_round = current_round + 1
        current_time = get_round_time(current_round, self.round_times) or "—"
        target_time, target_is_estimated = infer_next_round_time(target_round, self.round_times)
        target_time = target_time or "—"
        target_time_label = (
            f"{target_time} (estimated)" if target_is_estimated else target_time
        )

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
CURRENT TIME = {current_time} → TARGET TIME = {target_time_label}<br>
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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Profit", snap["total_profit"])
        c2.metric("Profit20", snap["profit20"])
        c3.metric("WR20", snap["wr20"])
        c4.metric("Drawdown", snap["drawdown"])

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
        open_time = get_round_time(self.ctx.pending_round, self.round_times) or "—"
        target_time, target_estimated = infer_next_round_time(
            target_round, self.round_times
        )
        target_time = target_time or "—"
        if target_estimated:
            target_time += " (estimated)"

        display_pending_window = self.ctx.pending_locked_window
        if display_pending_window is None and self.ctx.pending_index is not None:
            try:
                display_pending_window = self.ctx.trade_history[self.ctx.pending_index].locked_window
            except Exception:
                display_pending_window = self.ctx.locked_window

        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Open Round", f"{self.ctx.pending_round} | {open_time}")
        c2.metric("Target Round", f"{target_round} | {target_time}")
        c3.metric("Locked Window", display_pending_window)
        c4.metric("Bet Group", self.ctx.pending_trade)
        c5.metric("Open CONF", round(float(getattr(self.ctx, "pending_confidence", 0.0)), 3))
        c6.metric("Status", "WAIT RESULT")

        if getattr(self.ctx, "correction_pause", False):
            st.warning(
                f"DATA CORRECTION PAUSED | Round {self.ctx.correction_round} | "
                f"{self.ctx.correction_old_value} -> {self.ctx.correction_new_value}"
            )

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
                    "UCB_EXPLORATION_C": UCB_EXPLORATION_C,
                    "MIN_TRADES_FOR_PROTECTION": MIN_TRADES_FOR_PROTECTION,
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
                }
                for x in self.ctx.trade_history
            ]
        )

        st.dataframe(df.tail(50), use_container_width=True)

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
            return None

        return json.loads(raw)
    except Exception as e:
        st.warning(f"Load Google state error, fallback local: {e}")
        return None


def save_state_to_gsheet(data: dict) -> bool:
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
            ws = sh.add_worksheet(
                title=cfg["worksheet"],
                rows=10,
                cols=2,
            )

        payload = json.dumps(data, ensure_ascii=False)
        ws.update("A1", [[payload]])
        ws.update("B1", [[time.strftime("%Y-%m-%d %H:%M:%S")]])
        return True
    except Exception as e:
        st.warning(f"Save Google state error, fallback local: {e}")
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



def save_live_state(ctx: EngineContext) -> None:
    ensure_ctx_fields(ctx)

    data = {
        "trade_history": [
            trade_record_to_dict(x)
            for x in ctx.trade_history
        ],
        "equity_curve": list(ctx.equity_curve),
        "signal_history": list(ctx.signal_history),
        "signal_flip_history": list(ctx.signal_flip_history),
        "leader_history": list(ctx.leader_history),

        "pending_trade": ctx.pending_trade,
        "pending_round": ctx.pending_round,
        "pending_index": ctx.pending_index,
        "pending_locked_window": ctx.pending_locked_window,
        "pending_confidence": ctx.pending_confidence,
        "pending_confidence": getattr(ctx, "pending_confidence", 0.0),
        "pending_target_round": getattr(ctx, "pending_target_round", 0),
        "trade_state": ctx.trade_state,

        "last_length": ctx.last_length,
        "last_open_round": ctx.last_open_round,
        "last_settle_round": ctx.last_settle_round,
        "last_window_round": ctx.last_window_round,
        "last_signal_round": ctx.last_signal_round,

        "cooldown_counter": ctx.cooldown_counter,
        "cooldown_loss_streak_marker": ctx.cooldown_loss_streak_marker,
        "safe_mode_counter": ctx.safe_mode_counter,
        "peak_equity": getattr(ctx, "peak_equity", 0.0),
        "last_safe_trigger_peak": getattr(ctx, "last_safe_trigger_peak", 0.0),
        "risk_pause_counter": getattr(ctx, "risk_pause_counter", 0),
        "last_risk_trigger_trade_count": getattr(ctx, "last_risk_trigger_trade_count", -1),
        "last_decision_confidence": getattr(ctx, "last_decision_confidence", 0.0),
        "data_signature": getattr(ctx, "data_signature", ""),
        "dataset_anchor_signature": getattr(ctx, "dataset_anchor_signature", ""),
        "processed_numbers": list(getattr(ctx, "processed_numbers", [])),
        "correction_pause": bool(getattr(ctx, "correction_pause", False)),
        "correction_round": int(getattr(ctx, "correction_round", 0)),
        "correction_old_value": getattr(ctx, "correction_old_value", None),
        "correction_new_value": getattr(ctx, "correction_new_value", None),
        "algorithm_migration_pending": getattr(ctx, "algorithm_migration_pending", False),

        "protection_reason": ctx.protection_reason,
        "open_reason": ctx.open_reason,

        "locked_window": ctx.locked_window,
        "lock_reason": ctx.lock_reason,

        "locked_live_profit": ctx.locked_live_profit,
        "locked_live_loss_streak": ctx.locked_live_loss_streak,
        "locked_live_win": ctx.locked_live_win,
        "locked_live_loss": ctx.locked_live_loss,

        "window_real_stats": {
            str(k): v
            for k, v in ctx.window_real_stats.items()
        },
        "cooled_windows": {
            str(k): int(v)
            for k, v in ctx.cooled_windows.items()
        },
        "blacklisted_windows": {
            str(k): int(v)
            for k, v in getattr(ctx, "blacklisted_windows", {}).items()
        },
        "state_version": getattr(ctx, "state_version", "V56_TRUE_LIVE_DETERMINISTIC"),
        "hybrid_initialized": getattr(ctx, "hybrid_initialized", False),
    }

    # Try Google Sheet backend first. If unavailable, fallback to local JSON.
    if save_state_to_gsheet(data):
        return

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"Save local state error: {e}")


def load_live_state() -> EngineContext:
    data = load_state_from_gsheet()

    if data is None:
        if not os.path.exists(STATE_FILE):
            return EngineContext()

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return EngineContext()

    if not isinstance(data, dict) or not data:
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
    ctx.data_signature = str(data.get("data_signature", "") or "")
    ctx.dataset_anchor_signature = str(data.get("dataset_anchor_signature", "") or "")
    ctx.processed_numbers = [int(x) for x in data.get("processed_numbers", [])]
    ctx.correction_pause = bool(data.get("correction_pause", False))
    ctx.correction_round = int(data.get("correction_round", 0) or 0)
    ctx.correction_old_value = data.get("correction_old_value")
    ctx.correction_new_value = data.get("correction_new_value")
    ctx.state_version = str(data.get("state_version", "") or "")
    ctx.algorithm_migration_pending = bool(data.get("algorithm_migration_pending", False))

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

    return ensure_ctx_fields(ctx)


# ============================================================
# TRUE LIVE SESSION STATE
# ============================================================

def get_live_ctx() -> EngineContext:
    if "v50_true_live_ctx" not in st.session_state:
        st.session_state.v50_true_live_ctx = ensure_ctx_fields(load_live_state())
    else:
        st.session_state.v50_true_live_ctx = ensure_ctx_fields(st.session_state.v50_true_live_ctx)
    return st.session_state.v50_true_live_ctx



def get_live_window_state() -> dict[int, WindowRecord]:
    if "v50_true_live_window_state" not in st.session_state:
        st.session_state.v50_true_live_window_state = {
            w: WindowRecord()
            for w in WINDOWS
        }
    return st.session_state.v50_true_live_window_state


def data_correction_controls() -> None:
    ctx = get_live_ctx()
    if not getattr(ctx, "correction_pause", False):
        return

    with st.sidebar:
        st.error(
            f"DATA CORRECTION DETECTED at round {ctx.correction_round}: "
            f"{ctx.correction_old_value} -> {ctx.correction_new_value}. "
            "Trading is paused."
        )
        st.caption(
            "Correct the Google Sheet first. Then rebuild the current dataset "
            "deterministically before resuming live mode."
        )
        if st.button("Rebuild Corrected Dataset"):
            # The corrected Sheet is the new source of truth. Rebuild all
            # derived state and trade history from LIVE_START_ROUND.
            ctx.trade_history = []
            ctx.equity_curve = []
            ctx.signal_history.clear()
            ctx.signal_flip_history.clear()
            ctx.leader_history.clear()
            ctx.window_real_stats = {}
            ctx.cooled_windows = {}
            ctx.blacklisted_windows = {}
            ctx.pending_trade = None
            ctx.pending_round = 0
            ctx.pending_index = None
            ctx.pending_locked_window = None
            ctx.pending_target_round = 0
            ctx.pending_confidence = 0.0
            ctx.trade_state = "IDLE"
            ctx.last_open_round = -1
            ctx.last_settle_round = -1
            ctx.last_length = 0
            ctx.last_window_round = -1
            ctx.last_signal_round = -1
            ctx.locked_window = None
            ctx.lock_reason = "CORRECTED_DATA_REBUILD"
            ctx.peak_equity = 0.0
            ctx.last_safe_trigger_peak = 0.0
            ctx.safe_mode_counter = 0
            ctx.risk_pause_counter = 0
            ctx.last_risk_trigger_trade_count = -1
            ctx.data_signature = ""
            ctx.processed_numbers = []
            ctx.correction_pause = False
            ctx.correction_round = 0
            ctx.correction_old_value = None
            ctx.correction_new_value = None
            ctx.hybrid_initialized = False
            save_live_state(ctx)
            st.rerun()

def reset_live_state_button() -> None:
    with st.sidebar:
        st.subheader("Live Control")
        cfg = get_state_backend_config()
        if cfg["backend"] == "gsheet" and cfg["sheet_id"]:
            st.caption(f"State backend: Google Sheet / worksheet={cfg['worksheet']}")
        else:
            st.caption(f"State backend: local file {STATE_FILE}")
        if st.button("Reset Live State"):
            if "v50_true_live_ctx" in st.session_state:
                del st.session_state.v50_true_live_ctx
            if "v50_true_live_window_state" in st.session_state:
                del st.session_state.v50_true_live_window_state
            delete_state_from_gsheet()
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            st.rerun()


# ============================================================
# ENGINE MANAGER
# ============================================================

class EngineManager:
    def __init__(self) -> None:
        reset_live_state_button()

        self.ctx = ensure_ctx_fields(get_live_ctx())
        data_correction_controls()
        self.window_state = get_live_window_state()

        self.numbers, self.groups, self.actual_group, self.round_id = load_data()
        self.round_times = load_round_times(refresh_bucket=int(time.time() // 5))

        # ============================================================
        # DATA INTEGRITY / DAILY RESET
        # ============================================================
        saved_length = int(getattr(self.ctx, "last_length", 0) or 0)
        current_anchor = make_dataset_anchor_signature(self.numbers)
        saved_anchor = str(getattr(self.ctx, "dataset_anchor_signature", "") or "")
        if (
            getattr(self.ctx, "hybrid_initialized", False)
            and saved_anchor
            and current_anchor != saved_anchor
            and len(self.groups) >= saved_length
        ):
            self.ctx.correction_pause = True
            self.ctx.open_reason = "DATASET_ANCHOR_CHANGED_RESET_REQUIRED"
            self.ctx.protection_reason = "DATASET_ANCHOR_CHANGED_RESET_REQUIRED"

        # Ignore an invalid stale correction marker such as round=0, None -> None.
        # It can only be a corrupted/legacy state marker, not a real edited number.
        if (
            getattr(self.ctx, "correction_pause", False)
            and int(getattr(self.ctx, "correction_round", 0) or 0) <= 0
            and getattr(self.ctx, "correction_old_value", None) is None
            and getattr(self.ctx, "correction_new_value", None) is None
        ):
            self.ctx.correction_pause = False
            self.ctx.correction_round = 0
            self.ctx.correction_old_value = None
            self.ctx.correction_new_value = None
            self.ctx.open_reason = ""
            self.ctx.protection_reason = ""

        saved_processed = list(getattr(self.ctx, "processed_numbers", []) or [])

        # A shorter Sheet is the explicit daily reset signal.
        length_dropped = len(self.groups) < saved_length

        # A changed value inside an already processed prefix is NOT a new round.
        # Pause trading and require a deterministic rebuild.
        correction = None
        if saved_processed and saved_length > 0 and not length_dropped:
            correction = detect_processed_data_change(self.ctx, self.numbers)

        if correction is not None and getattr(self.ctx, "hybrid_initialized", False):
            r, old_v, new_v = correction
            self.ctx.correction_pause = True
            self.ctx.correction_round = r
            self.ctx.correction_old_value = old_v
            self.ctx.correction_new_value = new_v
            self.ctx.open_reason = "DATA_CORRECTION_DETECTED"
            self.ctx.protection_reason = "DATA_CORRECTION_DETECTED"
            self.dataset_reset_detected = False
            # Do not process any round until the user rebuilds.
            self.data_correction_detected = True
        else:
            self.data_correction_detected = False

        self.dataset_reset_detected = (
            getattr(self.ctx, "hybrid_initialized", False)
            and length_dropped
        )

        if self.dataset_reset_detected:
            # New day: discard only the previous day's runtime/trade state.
            self.ctx.pending_trade = None
            self.ctx.pending_round = 0
            self.ctx.pending_index = None
            self.ctx.pending_locked_window = None
            self.ctx.pending_target_round = 0
            self.ctx.pending_confidence = 0.0
            self.ctx.trade_state = "IDLE"
            self.ctx.last_open_round = -1
            self.ctx.last_settle_round = -1
            self.ctx.last_length = 0
            self.ctx.last_window_round = -1
            self.ctx.last_signal_round = -1
            self.ctx.locked_window = None
            self.ctx.lock_reason = "NEW_DAY_DATASET_RESET"
            self.ctx.trade_history = []
            self.ctx.equity_curve = []
            self.ctx.signal_history.clear()
            self.ctx.signal_flip_history.clear()
            self.ctx.leader_history.clear()
            self.ctx.window_real_stats = {}
            self.ctx.cooled_windows = {}
            self.ctx.blacklisted_windows = {}
            self.ctx.peak_equity = 0.0
            self.ctx.last_safe_trigger_peak = 0.0
            self.ctx.safe_mode_counter = 0
            self.ctx.risk_pause_counter = 0
            self.ctx.last_risk_trigger_trade_count = -1
            self.ctx.data_signature = ""
            self.ctx.processed_numbers = []
            self.ctx.correction_pause = False
            self.ctx.correction_round = 0
            self.ctx.correction_old_value = None
            self.ctx.correction_new_value = None
            self.ctx.hybrid_initialized = False
            save_live_state(self.ctx)


        if getattr(self.ctx, "algorithm_migration_pending", False) and getattr(self.ctx, "hybrid_initialized", False):
            # Preserve settled history and an exact pending target, but remove
            # stale lock/cooldown/blacklist decisions from the previous algorithm.
            self.ctx.locked_window = None
            self.ctx.lock_reason = "ALGORITHM_UPGRADE_RESELECT"
            self.ctx.cooled_windows = {}
            self.ctx.blacklisted_windows = {}
            self.ctx.locked_live_profit = 0.0
            self.ctx.locked_live_loss_streak = 0
            self.ctx.locked_live_win = 0
            self.ctx.locked_live_loss = 0
            self.ctx.algorithm_migration_pending = False
            save_live_state(self.ctx)

        self.window_engine = WindowEngine(self.ctx, self.window_state)
        self.trade_engine = TradeEngine(self.ctx)
        self.signal_engine = SignalEngine(self.ctx, self.window_engine)
        self.protection_engine = ProtectionEngine(self.ctx, self.trade_engine)

        self.dashboard = Dashboard(
            self.ctx,
            self.window_engine,
            self.signal_engine,
            self.trade_engine,
            self.protection_engine
        )
        self.dashboard.set_round_times(self.round_times)

        if getattr(self.ctx, "hybrid_initialized", False):
            self.rebuild_windows_to_last_length()

    def rebuild_windows_to_last_length(self) -> None:
        # Window state is derived from number history, so rebuild it safely on every app start.
        # Trade history is NOT replayed here.
        target = min(self.ctx.last_length, len(self.groups))
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

    def hybrid_replay_once(self) -> None:
        """Fresh-state bootstrap with NO historical trade fabrication.

        Reset semantics:
        - The Google Sheet numbers are the source of truth and are never deleted.
        - All currently present numbers are used to rebuild window/turn statistics.
        - Existing rows are historical at the moment of reset; they are NOT treated
          as newly-arriving live rounds and therefore cannot create Trade History
          or Profit.
        - The current last sheet round becomes the live anchor. The first real
          trade can only be created when a NEW row is appended after this reset.
        - LIVE_START_ROUND remains the minimum amount of history required before
          live decisions are allowed; it is not a command to manufacture old trades.
        """
        if getattr(self.ctx, "hybrid_initialized", False):
            if self.ctx.pending_trade is not None:
                self.trade_engine.reconcile_pending_from_sheet(
                    self.groups,
                    len(self.groups)
                )
            return

        total = len(self.groups)
        if total <= 0:
            return

        # Rebuild all derived window statistics from the complete current dataset.
        # This is deterministic and contains NO trade open/settle side effects.
        for idx in range(1, total + 1):
            self.ctx.last_length = idx
            self.window_engine.update_one_round(self.groups[idx - 1], idx)

        # We need at least LIVE_START_ROUND rounds before enabling live mode.
        # At the current anchor, calculate the signal/lock for the NEXT unseen
        # round, but deliberately do not open a historical trade.
        if total >= LIVE_START_ROUND:
            anchor_round = total
            signal = self.signal_engine.build_signal(anchor_round)
            confidence = self.signal_engine.get_confidence_score(signal)
            self.ctx.last_decision_confidence = confidence
            setattr(signal, "decision_confidence", confidence)

            signal.state = self.protection_engine.adaptive_ready_wait(
                signal,
                confidence
            )
            self.ctx.last_signal_round = anchor_round
            self.ctx.open_reason = "RESET_ANCHOR_READY_FOR_NEXT_NEW_ROUND"
            self.ctx.trade_state = "IDLE"

            # Persist the lock selected from history so UI does not show "—".
            if getattr(signal, "locked_window", None) is not None:
                self.ctx.locked_window = signal.locked_window
                self.ctx.lock_reason = getattr(
                    signal, "lock_reason", "RESET_ANCHOR_LOCK"
                )

        # Everything currently in the Sheet is already observed at reset.
        # Therefore the next live round is total + 1.
        self.ctx.last_length = total
        self.ctx.data_signature = make_numbers_signature(self.numbers, total)
        self.ctx.dataset_anchor_signature = make_dataset_anchor_signature(self.numbers)
        self.ctx.processed_numbers = list(self.numbers[:total])
        self.ctx.hybrid_initialized = True
        rebuild_real_stats_from_history(self.ctx)
        save_live_state(self.ctx)

    def process_new_rounds(self) -> None:
        # Process only rows added after the first hybrid replay.
        current_length = len(self.groups)
        if getattr(self.ctx, "correction_pause", False):
            self.ctx.open_reason = "DATA_CORRECTION_PAUSED"
            self.ctx.protection_reason = "DATA_CORRECTION_PAUSED"
            return


        # Settlement recovery MUST happen before any new signal decision.
        # This fixes persisted pending trades after app restarts / downtime.
        if current_length > 0 and self.ctx.pending_trade is not None:
            self.trade_engine.reconcile_pending_from_sheet(
                self.groups,
                current_length
            )

        if current_length <= self.ctx.last_length:
            return

        # SETTLEMENT_FIRST_PER_NEW_ROUND:
        # For each newly appended row, settle an existing pending trade before
        # building any new signal. Guards never participate in settlement.
        for idx in range(self.ctx.last_length + 1, current_length + 1):
            self.ctx.last_length = idx
            actual_group = self.groups[idx - 1]

            self.ctx.last_length = idx
            self.trade_engine.settle_trade(actual_group, idx)
            self.window_engine.update_one_round(actual_group, idx)

            signal = self.signal_engine.build_signal(idx)
            confidence = self.signal_engine.get_confidence_score(signal)
            self.ctx.last_decision_confidence = confidence
            setattr(signal, "decision_confidence", confidence)

            signal.state = self.protection_engine.adaptive_ready_wait(
                signal,
                confidence
            )

            self.trade_engine.open_trade(signal, idx, confidence)

            self.ctx.data_signature = make_numbers_signature(self.numbers, len(self.numbers))
            self.ctx.dataset_anchor_signature = make_dataset_anchor_signature(self.numbers)
            self.ctx.processed_numbers = list(self.numbers[:self.ctx.last_length])
            save_live_state(self.ctx)

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

        # V56: display must be read-only. Never call build_signal() here.
        signal = self.signal_engine.build_signal_snapshot(self.ctx.last_length)
        confidence_score = self.signal_engine.get_confidence_score(signal)
        confidence_level = self.signal_engine.get_confidence_level(confidence_score)

        if self.ctx.open_reason in ("TRADE_GAP", "SIGNAL_WAIT", "DUPLICATE_OPEN"):
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
        self.dashboard.render_trade_history()
        self.dashboard.render_equity()

        st.caption(
            f"""
V58 FINAL SINGLE-FILE ROBUST LIVE

First run: replay from round {LIVE_START_ROUND} to current once.

After that: only process new Google Sheet rows.
V56 rule: UI refresh is read-only; only new rounds can change trade state.
Open/settle decisions happen only when a new round appears, not every rerun.
Trade state is saved to Google Sheet if configured, otherwise local JSON fallback.
Main panel shows READY/WAIT only. PENDING is shown only in Trade History and Current Trade.

Current Sheet Round : {self.round_id}
Current Sheet Time  : {get_round_time(self.round_id, self.round_times) or "—"}

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
# MAIN - TRUE LIVE / READ-ONLY UI REFRESH
# ============================================================

if not hasattr(st, "fragment"):
    st.error(
        "This build requires a recent Streamlit version with st.fragment(). "
        "Upgrade Streamlit before running live mode."
    )
else:
    @st.fragment(run_every=5)
    def live_engine_loop():
        try:
            manager = EngineManager()
            manager.run()
        except Exception as e:
            st.error(f"Engine Error: {e}")
            import traceback
            st.code(traceback.format_exc())

    live_engine_loop()

