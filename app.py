# ============================================================
# APP V50 AUTO OPTIMIZE
# Clean live engine with parameter backtest optimizer
# ============================================================

from __future__ import annotations

import itertools
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V50 Auto Optimize Fast",
    layout="wide"
)


# ============================================================
# BASE CONFIG
# ============================================================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = list(range(6, 23))
MIN_DATA_LEN = 30
LIVE_START_ROUND = 180

HIT_HISTORY_LEN = 50
GROUP_HISTORY_LEN = 80

PROFIT10_STOP = -3.0
WR20_STOP = 0.35
DRAWDOWN_STOP = -10.0
FLIPRATE_STOP = 0.75


# ============================================================
# AUTO OPTIMIZER SEARCH SPACE
# ============================================================

TOPN_OPTIONS = [3, 5]
CONSENSUS_OPTIONS = [0.50, 0.60]
LOW_WR_CONSENSUS_OPTIONS = [0.70, 0.80]
MAX_WINDOW_LOSS_STREAK_OPTIONS = [3, 5]
COOLDOWN_OPTIONS = [2, 3]
GAP_OPTIONS = [0, 1]
STABILITY_OPTIONS = [0.50]


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(frozen=True)
class EngineConfig:
    topn: int = 5
    consensus_ready: float = 0.50
    low_wr_consensus_ready: float = 0.80
    max_window_loss_streak_for_top: int = 5
    cooldown_rounds: int = 3
    trade_gap_rounds: int = 1
    stability_ready: float = 0.50


@dataclass
class TradeRecord:
    open_round: int
    predict: int
    settle_round: Optional[int] = None
    actual: Optional[int] = None
    hit: Optional[int] = None
    profit: float = 0.0
    status: str = "PENDING"


@dataclass
class SignalRecord:
    state: str = "WAIT"
    next_group: Optional[int] = None
    regime: str = "NORMAL"
    consensus: float = 0.0
    required_consensus: float = 0.0
    health20: float = 0.0
    health50: float = 0.0
    stability: float = 0.0
    momentum: float = 0.0
    top_profit20: float = 0.0


@dataclass
class WindowRecord:
    hit_history: deque = field(default_factory=lambda: deque(maxlen=HIT_HISTORY_LEN))
    group_history: deque = field(default_factory=lambda: deque(maxlen=GROUP_HISTORY_LEN))
    profit20: float = 0.0
    profit50: float = 0.0
    loss_streak: int = 0
    score: float = 0.0
    next_group: Optional[int] = None


@dataclass
class BacktestResult:
    config: EngineConfig
    total_profit: float
    trade_count: int
    winrate: float
    max_drawdown: float
    score: float


@dataclass
class EngineContext:
    trade_history: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    signal_history: deque = field(default_factory=lambda: deque(maxlen=50))
    signal_flip_history: deque = field(default_factory=lambda: deque(maxlen=50))
    leader_history: deque = field(default_factory=lambda: deque(maxlen=50))

    pending_trade: Optional[int] = None
    pending_round: int = 0
    pending_index: Optional[int] = None
    trade_state: str = "IDLE"

    last_length: int = 0
    last_open_round: int = -1
    last_settle_round: int = -1
    last_window_round: int = -1
    last_signal_round: int = -1

    cooldown_counter: int = 0
    cooldown_loss_streak_marker: int = -1

    protection_reason: str = ""
    open_reason: str = ""


# ============================================================
# DATA LOADER
# ============================================================

@st.cache_data(ttl=30)
def load_numbers() -> list[int]:
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

    df.columns = [str(x).lower().strip() for x in df.columns]

    if "number" not in df.columns:
        st.error("Sheet must contain column 'number'")
        st.stop()

    nums = (
        pd.to_numeric(df["number"], errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )

    return [x for x in nums if 1 <= x <= 12]


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


def load_data() -> tuple[list[int], list[int], int, int]:
    numbers = load_numbers()

    if len(numbers) < MIN_DATA_LEN:
        st.warning("Waiting data...")
        st.stop()

    groups = build_groups(numbers)
    return numbers, groups, groups[-1], len(numbers)


# ============================================================
# CORE MATH HELPERS
# ============================================================

def calc_profit(hits: list[int]) -> float:
    return round(sum(WIN_GROUP if x else LOSS_GROUP for x in hits), 2)


def calc_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0

    peak = 0.0
    dd = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)
        dd = min(dd, equity - peak)

    return round(dd, 2)


def winrate(records: list[TradeRecord], n: Optional[int] = None) -> float:
    settled = [x for x in records if x.hit is not None]
    if n is not None:
        settled = settled[-n:]
    if not settled:
        return 0.0
    return round(sum(int(x.hit) for x in settled) / len(settled), 3)


def profit_n(records: list[TradeRecord], n: int) -> float:
    settled = [x for x in records if x.hit is not None][-n:]
    return round(sum(x.profit for x in settled), 2)


def loss_streak(records: list[TradeRecord]) -> int:
    streak = 0
    for x in reversed(records):
        if x.hit is None:
            continue
        if x.hit == 0:
            streak += 1
        else:
            break
    return streak


def flip_rate(signal_flip_history: deque) -> float:
    history = list(signal_flip_history)
    if len(history) < 2:
        return 0.0

    flips = sum(
        1 for i in range(1, len(history))
        if history[i] != history[i - 1]
    )

    return round(flips / (len(history) - 1), 3)


# ============================================================
# WINDOW ENGINE
# ============================================================

class WindowEngine:
    def __init__(self, ctx: EngineContext, config: EngineConfig):
        self.ctx = ctx
        self.config = config
        self.state = {w: WindowRecord() for w in WINDOWS}

    def update_one_round(self, actual_group: int, round_id: int) -> None:
        if round_id == self.ctx.last_window_round:
            return

        for w, stt in self.state.items():
            if stt.next_group is not None:
                hit = int(stt.next_group == actual_group)
                stt.hit_history.append(hit)

                stt.profit20 = calc_profit(list(stt.hit_history)[-20:])
                stt.profit50 = calc_profit(list(stt.hit_history)[-50:])

                if hit:
                    stt.loss_streak = 0
                else:
                    stt.loss_streak += 1

            stt.group_history.append(actual_group)

            # Cycle logic: next round prediction = group from w rounds ago.
            if len(stt.group_history) >= w:
                stt.next_group = list(stt.group_history)[-w]
            else:
                stt.next_group = None

            stt.score = round(
                stt.profit20 +
                0.30 * stt.profit50 -
                stt.loss_streak,
                3
            )

        top = self.get_top_windows(1)
        if top:
            self.ctx.leader_history.append(top[0][0])

        self.ctx.last_window_round = round_id

    def get_top_windows(self, top_n: Optional[int] = None) -> list[tuple[int, WindowRecord]]:
        top_n = self.config.topn if top_n is None else top_n

        valid_rows = [
            (w, stt)
            for w, stt in self.state.items()
            if int(stt.loss_streak) <= self.config.max_window_loss_streak_for_top
        ]

        rows_source = valid_rows if valid_rows else list(self.state.items())

        rows = sorted(
            rows_source,
            key=lambda x: x[1].score,
            reverse=True
        )

        return rows[:top_n]

    def get_consensus(self, top_rows: Optional[list[tuple[int, WindowRecord]]] = None) -> tuple[Optional[int], float]:
        top_rows = self.get_top_windows() if top_rows is None else top_rows

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
        positive20 = sum(1 for w in WINDOWS if self.state[w].profit20 > 0)
        positive50 = sum(1 for w in WINDOWS if self.state[w].profit50 > 0)
        return round(positive20 / total, 3), round(positive50 / total, 3)

    def get_stability(self) -> float:
        history = list(self.ctx.leader_history)
        if len(history) < 2:
            return 1.0

        changes = sum(
            1 for i in range(1, len(history))
            if history[i] != history[i - 1]
        )

        change_rate = changes / (len(history) - 1)
        return round(max(0.0, 1.0 - change_rate), 3)


# ============================================================
# SIGNAL ENGINE
# ============================================================

class SignalEngine:
    def __init__(self, ctx: EngineContext, window_engine: WindowEngine, config: EngineConfig):
        self.ctx = ctx
        self.window_engine = window_engine
        self.config = config

    def get_momentum(self, top_rows: list[tuple[int, WindowRecord]]) -> float:
        if not top_rows:
            return 0.0

        return round(
            sum(stt.profit20 - stt.profit50 for _, stt in top_rows) / len(top_rows),
            3
        )

    def get_confidence_score(self, signal: SignalRecord) -> float:
        return round(
            0.35 * signal.consensus +
            0.25 * signal.health20 +
            0.20 * signal.health50 +
            0.20 * signal.stability,
            3
        )

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

    def build_signal(self, round_id: int, trade_engine: "TradeEngine") -> SignalRecord:
        top_rows = self.window_engine.get_top_windows()
        next_group, consensus = self.window_engine.get_consensus(top_rows)
        health20, health50 = self.window_engine.get_health()
        stability = self.window_engine.get_stability()
        momentum = self.get_momentum(top_rows)
        top_profit20 = top_rows[0][1].profit20 if top_rows else 0.0

        wr20 = trade_engine.get_winrate(20)
        required_consensus = self.config.consensus_ready
        if wr20 > 0 and wr20 < 0.50:
            required_consensus = self.config.low_wr_consensus_ready

        if consensus < required_consensus:
            regime = "CHAOS"
        elif stability < self.config.stability_ready:
            regime = "CHAOS"
        elif momentum > 2:
            regime = "TREND"
        else:
            regime = "NORMAL"

        state = "WAIT"
        if (
            round_id >= LIVE_START_ROUND
            and next_group is not None
            and consensus >= required_consensus
            and stability >= self.config.stability_ready
            and top_profit20 >= 0
        ):
            state = "READY"

        signal = SignalRecord(
            state=state,
            next_group=next_group,
            regime=regime,
            consensus=consensus,
            required_consensus=required_consensus,
            health20=health20,
            health50=health50,
            stability=stability,
            momentum=momentum,
            top_profit20=top_profit20
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
    def __init__(self, ctx: EngineContext, config: EngineConfig):
        self.ctx = ctx
        self.config = config

    def update_equity(self, profit: float) -> None:
        equity = 0.0 if not self.ctx.equity_curve else self.ctx.equity_curve[-1]
        equity += profit
        self.ctx.equity_curve.append(round(equity, 2))

    def open_trade(self, signal: SignalRecord, round_id: int) -> None:
        self.ctx.open_reason = ""

        if round_id < LIVE_START_ROUND:
            self.ctx.open_reason = "BEFORE_LIVE_START"
            return

        if (
            self.ctx.last_settle_round > 0
            and round_id - self.ctx.last_settle_round <= self.config.trade_gap_rounds
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

        record = TradeRecord(
            open_round=round_id,
            predict=signal.next_group
        )

        self.ctx.trade_history.append(record)
        self.ctx.pending_index = len(self.ctx.trade_history) - 1
        self.ctx.pending_trade = signal.next_group
        self.ctx.pending_round = round_id
        self.ctx.trade_state = "PENDING"
        self.ctx.last_open_round = round_id
        self.ctx.open_reason = "OPENED"

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

        if (
            self.ctx.pending_index is not None
            and 0 <= self.ctx.pending_index < len(self.ctx.trade_history)
        ):
            record = self.ctx.trade_history[self.ctx.pending_index]
        else:
            record = TradeRecord(
                open_round=self.ctx.pending_round,
                predict=predict
            )
            self.ctx.trade_history.append(record)

        record.settle_round = current_round
        record.actual = actual_group
        record.hit = hit
        record.profit = profit
        record.status = "WIN" if hit else "LOSS"

        self.update_equity(profit)

        self.ctx.pending_trade = None
        self.ctx.pending_round = 0
        self.ctx.pending_index = None
        self.ctx.trade_state = "IDLE"
        self.ctx.last_settle_round = current_round

    def get_total_profit(self) -> float:
        return round(
            sum(x.profit for x in self.ctx.trade_history if x.hit is not None),
            2
        )

    def get_profit(self, n: int) -> float:
        return profit_n(self.ctx.trade_history, n)

    def get_winrate(self, n: int = 20) -> float:
        return winrate(self.ctx.trade_history, n)

    def get_loss_streak(self) -> int:
        return loss_streak(self.ctx.trade_history)

    def get_drawdown(self) -> float:
        return calc_drawdown(self.ctx.equity_curve)

    def snapshot(self) -> dict:
        settled = [x for x in self.ctx.trade_history if x.hit is not None]
        return {
            "trade_state": self.ctx.trade_state,
            "profit10": self.get_profit(10),
            "profit20": self.get_profit(20),
            "profit50": self.get_profit(50),
            "total_profit": self.get_total_profit(),
            "wr20": self.get_winrate(20),
            "drawdown": self.get_drawdown(),
            "pending_trade": self.ctx.pending_trade,
            "trade_count": len(settled),
        }


# ============================================================
# PROTECTION ENGINE
# ============================================================

class ProtectionEngine:
    def __init__(self, ctx: EngineContext, trade_engine: TradeEngine, config: EngineConfig):
        self.ctx = ctx
        self.trade_engine = trade_engine
        self.config = config

    def get_flip_rate(self) -> float:
        return flip_rate(self.ctx.signal_flip_history)

    def profit_protection(self) -> bool:
        self.ctx.protection_reason = ""

        settled = [x for x in self.ctx.trade_history if x.hit is not None]
        if len(settled) < 20:
            return False

        if self.trade_engine.get_profit(10) <= PROFIT10_STOP:
            self.ctx.protection_reason = "PROFIT10_STOP"
            return True

        if self.trade_engine.get_winrate(20) <= WR20_STOP:
            self.ctx.protection_reason = "WR20_STOP"
            return True

        if self.trade_engine.get_drawdown() <= DRAWDOWN_STOP:
            self.ctx.protection_reason = "DRAWDOWN_STOP"
            return True

        if self.get_flip_rate() >= FLIPRATE_STOP:
            self.ctx.protection_reason = "FLIPRATE_STOP"
            return True

        return False

    def cooldown_engine(self) -> bool:
        streak = self.trade_engine.get_loss_streak()

        if streak == 0:
            self.ctx.cooldown_loss_streak_marker = -1

        if (
            streak >= 3
            and self.ctx.cooldown_counter == 0
            and self.ctx.cooldown_loss_streak_marker != streak
        ):
            self.ctx.cooldown_counter = self.config.cooldown_rounds
            self.ctx.cooldown_loss_streak_marker = streak

        if self.ctx.cooldown_counter > 0:
            self.ctx.cooldown_counter -= 1
            return True

        return False

    def adaptive_ready_wait(self, signal: SignalRecord, confidence_score: float) -> str:
        self.ctx.protection_reason = ""

        if signal.state != "READY":
            self.ctx.protection_reason = "SIGNAL_NOT_READY"
            return "WAIT"

        if self.profit_protection():
            return "WAIT"

        if self.cooldown_engine():
            self.ctx.protection_reason = "COOLDOWN"
            return "WAIT"

        if confidence_score < 0.35:
            self.ctx.protection_reason = "LOW_CONFIDENCE"
            return "WAIT"

        self.ctx.protection_reason = "ALLOW"
        return "READY"


# ============================================================
# BACKTEST / AUTO OPTIMIZER
# ============================================================

def run_simulation(groups: list[int], config: EngineConfig) -> BacktestResult:
    ctx_sim = EngineContext()
    window_engine = WindowEngine(ctx_sim, config)
    trade_engine = TradeEngine(ctx_sim, config)
    signal_engine = SignalEngine(ctx_sim, window_engine, config)
    protection_engine = ProtectionEngine(ctx_sim, trade_engine, config)

    for idx, actual_group in enumerate(groups, start=1):
        trade_engine.settle_trade(actual_group, idx)
        window_engine.update_one_round(actual_group, idx)

        signal = signal_engine.build_signal(idx, trade_engine)
        confidence = signal_engine.get_confidence_score(signal)
        signal.state = protection_engine.adaptive_ready_wait(signal, confidence)

        trade_engine.open_trade(signal, idx)

    settled = [x for x in ctx_sim.trade_history if x.hit is not None]
    total_profit = trade_engine.get_total_profit()
    wr = winrate(ctx_sim.trade_history, None)
    dd = trade_engine.get_drawdown()

    # Score favors profit, then lower drawdown, then sufficient trade count.
    score = (
        total_profit
        + 0.20 * len(settled)
        + 2.00 * wr
        + 0.30 * dd
    )

    return BacktestResult(
        config=config,
        total_profit=total_profit,
        trade_count=len(settled),
        winrate=wr,
        max_drawdown=dd,
        score=round(score, 4)
    )


@st.cache_data(ttl=30)
def optimize_config(groups_tuple: tuple[int, ...]) -> tuple[EngineConfig, pd.DataFrame]:
    groups = list(groups_tuple)

    results = []

    for (
        topn,
        consensus_ready,
        low_wr_consensus,
        max_window_ls,
        cooldown,
        gap,
        stability_ready
    ) in itertools.product(
        TOPN_OPTIONS,
        CONSENSUS_OPTIONS,
        LOW_WR_CONSENSUS_OPTIONS,
        MAX_WINDOW_LOSS_STREAK_OPTIONS,
        COOLDOWN_OPTIONS,
        GAP_OPTIONS,
        STABILITY_OPTIONS,
    ):
        cfg = EngineConfig(
            topn=topn,
            consensus_ready=consensus_ready,
            low_wr_consensus_ready=low_wr_consensus,
            max_window_loss_streak_for_top=max_window_ls,
            cooldown_rounds=cooldown,
            trade_gap_rounds=gap,
            stability_ready=stability_ready,
        )

        res = run_simulation(groups, cfg)
        results.append(res)

    rows = [
        {
            "score": r.score,
            "profit": r.total_profit,
            "trade_count": r.trade_count,
            "winrate": r.winrate,
            "drawdown": r.max_drawdown,
            "topn": r.config.topn,
            "consensus_ready": r.config.consensus_ready,
            "low_wr_consensus": r.config.low_wr_consensus_ready,
            "max_window_ls": r.config.max_window_loss_streak_for_top,
            "cooldown": r.config.cooldown_rounds,
            "gap": r.config.trade_gap_rounds,
            "stability": r.config.stability_ready,
        }
        for r in results
    ]

    df = pd.DataFrame(rows).sort_values(
        ["score", "profit", "winrate"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    best_row = df.iloc[0]

    best_config = EngineConfig(
        topn=int(best_row["topn"]),
        consensus_ready=float(best_row["consensus_ready"]),
        low_wr_consensus_ready=float(best_row["low_wr_consensus"]),
        max_window_loss_streak_for_top=int(best_row["max_window_ls"]),
        cooldown_rounds=int(best_row["cooldown"]),
        trade_gap_rounds=int(best_row["gap"]),
        stability_ready=float(best_row["stability"]),
    )

    return best_config, df


# ============================================================
# DASHBOARD
# ============================================================

class Dashboard:
    def __init__(
        self,
        ctx: EngineContext,
        config: EngineConfig,
        window_engine: WindowEngine,
        signal_engine: SignalEngine,
        trade_engine: TradeEngine,
        protection_engine: ProtectionEngine,
        opt_df: pd.DataFrame
    ):
        self.ctx = ctx
        self.config = config
        self.window_engine = window_engine
        self.signal_engine = signal_engine
        self.trade_engine = trade_engine
        self.protection_engine = protection_engine
        self.opt_df = opt_df

    def render_header(self) -> None:
        st.title("🚀 V50 Auto Optimize Fast")

    def render_signal(self, signal: SignalRecord, confidence_score: float) -> None:
        color = "#00aa00" if signal.state == "READY" else "#555555"

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
{signal.state}<br>
NEXT GROUP = {signal.next_group}<br>
CONF = {confidence_score:.2f}
</div>
""",
            unsafe_allow_html=True
        )

    def render_market(self, signal: SignalRecord) -> None:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Regime", signal.regime)
        c2.metric("Consensus", round(signal.consensus, 3))
        c3.metric("Req Consensus", round(signal.required_consensus, 3))
        c4.metric("Stability", round(signal.stability, 3))
        c5.metric("Momentum", round(signal.momentum, 3))
        c6.metric("Top Profit20", round(signal.top_profit20, 2))

    def render_profit(self) -> None:
        snap = self.trade_engine.snapshot()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Profit", snap["total_profit"])
        c2.metric("Profit20", snap["profit20"])
        c3.metric("WR20", snap["wr20"])
        c4.metric("Drawdown", snap["drawdown"])

    def render_risk(self) -> None:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("FlipRate", self.protection_engine.get_flip_rate())
        c2.metric("LossStreak", self.trade_engine.get_loss_streak())
        c3.metric("Cooldown", self.ctx.cooldown_counter)
        c4.metric("Live From", LIVE_START_ROUND)
        c5.metric("Wait Reason", self.ctx.protection_reason)
        c6.metric("Open Reason", self.ctx.open_reason)

    def render_config(self) -> None:
        st.subheader("Auto Selected Config")
        st.caption("Fast optimizer: 64 configs, cached by current groups history.")

        c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
        c1.metric("TopN", self.config.topn)
        c2.metric("Consensus", self.config.consensus_ready)
        c3.metric("LowWR Consensus", self.config.low_wr_consensus_ready)
        c4.metric("Max W Loss", self.config.max_window_loss_streak_for_top)
        c5.metric("Cooldown", self.config.cooldown_rounds)
        c6.metric("Gap", self.config.trade_gap_rounds)
        c7.metric("Stability", self.config.stability_ready)

    def render_top_windows(self) -> None:
        rows = self.window_engine.get_top_windows()
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
                    "LossStreak": int(obj.loss_streak),
                    "Next": obj.next_group,
                    "HitLen": len(obj.hit_history),
                    "GroupLen": len(obj.group_history),
                    "Filtered": int(obj.loss_streak) > self.config.max_window_loss_streak_for_top,
                }
            )

        st.subheader("Top Windows")
        df = pd.DataFrame(data)
        if not df.empty:
            df = df[
                [
                    "Rank", "Window", "Score", "Profit20", "Profit50",
                    "WR20", "WR50", "LossStreak", "Next",
                    "HitLen", "GroupLen", "Filtered"
                ]
            ]
        st.dataframe(df, use_container_width=True, hide_index=True)

    def render_trade_history(self) -> None:
        st.subheader("Trade History")

        if not self.ctx.trade_history:
            st.info("No trades")
            return

        df = pd.DataFrame(
            [
                {
                    "open_round": x.open_round,
                    "settle_round": x.settle_round,
                    "predict": x.predict,
                    "actual": x.actual,
                    "hit": x.hit,
                    "profit": x.profit,
                    "status": x.status,
                }
                for x in self.ctx.trade_history
            ]
        )

        st.dataframe(df.tail(50), use_container_width=True, hide_index=True)

    def render_equity(self) -> None:
        st.subheader("Equity Curve")

        if not self.ctx.equity_curve:
            return

        df = pd.DataFrame({"equity": self.ctx.equity_curve})
        st.line_chart(df)

    def render_optimizer(self) -> None:
        with st.expander("Optimizer Results - Top 20"):
            st.dataframe(self.opt_df.head(20), use_container_width=True, hide_index=True)

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
                        "LossStreak": int(obj.loss_streak),
                        "Next": obj.next_group,
                        "UseInTop": int(obj.loss_streak) <= self.config.max_window_loss_streak_for_top,
                    }
                )

            df = pd.DataFrame(rows).sort_values(
                ["UseInTop", "Score"],
                ascending=[False, False]
            )

            st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# ENGINE MANAGER
# ============================================================

class EngineManager:
    def __init__(self) -> None:
        self.ctx = EngineContext()
        self.numbers, self.groups, self.actual_group, self.round_id = load_data()

        self.config, self.opt_df = optimize_config(tuple(self.groups))

        self.window_engine = WindowEngine(self.ctx, self.config)
        self.trade_engine = TradeEngine(self.ctx, self.config)
        self.signal_engine = SignalEngine(self.ctx, self.window_engine, self.config)
        self.protection_engine = ProtectionEngine(self.ctx, self.trade_engine, self.config)

        self.dashboard = Dashboard(
            self.ctx,
            self.config,
            self.window_engine,
            self.signal_engine,
            self.trade_engine,
            self.protection_engine,
            self.opt_df
        )

    def replay(self) -> SignalRecord:
        signal = SignalRecord()

        for idx, actual_group in enumerate(self.groups, start=1):
            self.trade_engine.settle_trade(actual_group, idx)
            self.window_engine.update_one_round(actual_group, idx)

            signal = self.signal_engine.build_signal(idx, self.trade_engine)
            confidence = self.signal_engine.get_confidence_score(signal)

            signal.state = self.protection_engine.adaptive_ready_wait(signal, confidence)

            self.trade_engine.open_trade(signal, idx)

        return signal

    def run(self) -> None:
        signal = self.replay()
        confidence_score = self.signal_engine.get_confidence_score(signal)
        confidence_level = self.signal_engine.get_confidence_level(confidence_score)

        self.dashboard.render_header()
        self.dashboard.render_signal(signal, confidence_score)
        self.dashboard.render_config()
        self.dashboard.render_market(signal)
        self.dashboard.render_profit()
        self.dashboard.render_risk()
        self.dashboard.render_top_windows()
        self.dashboard.render_trade_history()
        self.dashboard.render_equity()
        self.dashboard.render_optimizer()
        self.dashboard.render_window_debug()

        st.caption(
            f"""
V50 Auto Optimize Fast

Round : {self.round_id}

Live Start : {LIVE_START_ROUND}

Confidence : {confidence_level}

Trade State : {self.ctx.trade_state}

Pending Trade : {self.ctx.pending_trade} / Open Round : {self.ctx.pending_round}

Regime : {signal.regime}
"""
        )


# ============================================================
# MAIN
# ============================================================

try:
    manager = EngineManager()
    manager.run()
except Exception as e:
    st.error(f"Engine Error: {e}")
    import traceback
    st.code(traceback.format_exc())


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(1)
st.rerun()
