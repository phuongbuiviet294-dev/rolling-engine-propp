# ============================================================
# APP V50 SINGLE CLEAN
# Refactor from uploaded app_v50_fix_v7 source
# ============================================================

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional, Any

import pandas as pd
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V50 Single Clean Live",
    layout="wide"
)


# ============================================================
# CONFIG
# ============================================================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = list(range(6, 23))
TOPN = 5

SIGNAL_HISTORY_LEN = 50
LEADER_HISTORY_LEN = 50
HIT_HISTORY_LEN = 50
GROUP_HISTORY_LEN = 80

COOLDOWN_ROUNDS = 3
MIN_DATA_LEN = 30
LIVE_START_ROUND = 180

# V50 profit protection tuning
LIVE_LOSS_COOLDOWN_ROUNDS = 5
TRADE_GAP_ROUNDS = 1
LOW_WR_CONSENSUS_READY = 0.80
LOW_WR_LEVEL = 0.50

PROFIT10_STOP = -3.0
WR20_STOP = 0.35
DRAWDOWN_STOP = -10.0
FLIPRATE_STOP = 0.60

CONSENSUS_READY = 0.50
STABILITY_READY = 0.50


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class TradeRecord:
    round_id: int
    predict: int
    actual: Optional[int] = None
    hit: Optional[int] = None
    profit: float = 0.0
    status: str = "PENDING"
    settle_round: Optional[int] = None


@dataclass
class SignalRecord:
    state: str = "WAIT"
    next_group: Optional[int] = None
    regime: str = "NORMAL"
    top_n: int = TOPN
    health20: float = 0.0
    health50: float = 0.0
    consensus: float = 0.0
    stability: float = 0.0
    momentum: float = 0.0
    required_consensus: float = CONSENSUS_READY
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
class EngineContext:
    trade_history: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    signal_history: deque = field(default_factory=lambda: deque(maxlen=SIGNAL_HISTORY_LEN))
    signal_flip_history: deque = field(default_factory=lambda: deque(maxlen=SIGNAL_HISTORY_LEN))
    leader_history: deque = field(default_factory=lambda: deque(maxlen=LEADER_HISTORY_LEN))

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


def load_data() -> tuple[list[int], list[int], int, int]:
    numbers = load_numbers()

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

    def update_one_round(self, actual_group: int, round_id: int) -> None:
        if round_id == self.ctx.last_window_round:
            return

        for w, stt in self.state.items():
            # settle previous prediction for this window
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
                    stt.loss_streak += 1

            # update raw group history
            stt.group_history.append(actual_group)

            # generate next prediction for the next round
            # V50 live cycle logic:
            # at round t, prediction for round t+1 is group at (t+1-w),
            # which is the first element of the last w groups.
            # This avoids the majority-memory trap where the engine keeps
            # predicting the same group repeatedly.
            if len(stt.group_history) >= w:
                stt.next_group = list(stt.group_history)[-w]

            # score
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

    def get_top_windows(self, top_n: int = TOPN) -> list[tuple[int, WindowRecord]]:
        rows = sorted(
            self.state.items(),
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
        score = (
            0.35 * signal.consensus +
            0.25 * signal.health20 +
            0.20 * signal.health50 +
            0.20 * signal.stability
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

    def build_signal(self, round_id: int) -> SignalRecord:
        top_rows = self.window_engine.get_top_windows(TOPN)
        next_group, consensus = self.window_engine.get_consensus(top_rows)
        health20, health50 = self.window_engine.get_health()
        stability = self.window_engine.get_stability()
        momentum = self.get_momentum(top_rows)
        regime = self.get_regime(consensus, stability, momentum)

        # Dynamic READY rule.
        # If live WR is weak, require stronger consensus.
        wr20 = TradeEngine(self.ctx).get_winrate(20)
        required_consensus = CONSENSUS_READY
        if wr20 > 0 and wr20 < LOW_WR_LEVEL:
            required_consensus = LOW_WR_CONSENSUS_READY

        top_profit20 = top_rows[0][1].profit20 if top_rows else 0

        state = "WAIT"
        if round_id < LIVE_START_ROUND:
            state = "WAIT"
        elif top_profit20 < 0:
            state = "WAIT"
        elif (
            next_group is not None
            and consensus >= required_consensus
            and stability >= STABILITY_READY
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
    def __init__(self, ctx: EngineContext):
        self.ctx = ctx

    def update_equity(self, profit: float) -> None:
        equity = 0.0 if not self.ctx.equity_curve else self.ctx.equity_curve[-1]
        equity += profit
        self.ctx.equity_curve.append(round(equity, 2))

    def open_trade(self, signal: SignalRecord, round_id: int) -> None:
        self.ctx.open_reason = ""

        if round_id < LIVE_START_ROUND:
            self.ctx.open_reason = "BEFORE_LIVE_START"
            return

        # Avoid over-trading: after a settled trade, wait TRADE_GAP_ROUNDS
        # before opening a new one.
        if (
            self.ctx.last_settle_round > 0
            and round_id - self.ctx.last_settle_round <= TRADE_GAP_ROUNDS
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
            round_id=round_id,
            predict=signal.next_group,
            actual=None,
            hit=None,
            profit=0.0,
            status="PENDING",
            settle_round=None
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
                actual=actual_group,
                hit=hit,
                profit=profit,
                status="WIN" if hit else "LOSS",
                settle_round=current_round
            )
            self.ctx.trade_history.append(record)

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
        # V50 Live: protection should explain WHY WAIT.
        # It should not be a silent permanent stop.
        self.ctx.protection_reason = ""

        trade_count = len([x for x in self.ctx.trade_history if x.hit is not None])
        if trade_count < 20:
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
        st.title("🚀 V50 Single Clean Live")

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

    def render_top_windows(self) -> None:
        rows = self.window_engine.get_top_windows(TOPN)
        data = []

        for w, obj in rows:
            data.append(
                {
                    "Window": w,
                    "Score": round(obj.score, 2),
                    "Profit20": round(obj.profit20, 2),
                    "Profit50": round(obj.profit50, 2),
                    "LossStreak": obj.loss_streak,
                    "Next": obj.next_group,
                }
            )

        st.subheader("Top Windows")
        st.dataframe(pd.DataFrame(data), use_container_width=True)

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
# ENGINE MANAGER
# ============================================================

class EngineManager:
    def __init__(self) -> None:
        self.ctx = ctx
        self.window_engine = WindowEngine(ctx, window_state)
        self.signal_engine = SignalEngine(ctx, self.window_engine)
        self.trade_engine = TradeEngine(ctx)
        self.protection_engine = ProtectionEngine(ctx, self.trade_engine)
        self.dashboard = Dashboard(
            ctx,
            self.window_engine,
            self.signal_engine,
            self.trade_engine,
            self.protection_engine
        )

    def initialize_from_history(self, groups: list[int]) -> None:
        # Only initialize once after first load.
        if self.ctx.last_length != 0:
            return

        # Replay historical rounds using the same live pipeline:
        # settle previous pending -> update windows -> build signal -> open next trade.
        # Rounds before LIVE_START_ROUND are only used for learning/warm-up.
        for idx, actual_group in enumerate(groups, start=1):

            self.trade_engine.settle_trade(actual_group, idx)

            self.window_engine.update_one_round(actual_group, idx)

            signal = self.signal_engine.build_signal(idx)
            confidence_score = self.signal_engine.get_confidence_score(signal)

            signal.state = self.protection_engine.adaptive_ready_wait(
                signal,
                confidence_score
            )

            self.trade_engine.open_trade(signal, idx)

        self.ctx.last_length = len(groups)

    def run(self) -> None:
        numbers, groups, actual_group, round_id = load_data()

        self.initialize_from_history(groups)

        current_length = len(numbers)

        # New round: settle previous pending, then update windows with actual.
        if current_length > self.ctx.last_length:
            self.trade_engine.settle_trade(actual_group, current_length)
            self.window_engine.update_one_round(actual_group, current_length)
            self.ctx.last_length = current_length

        # Build signal after windows are current.
        signal = self.signal_engine.build_signal(current_length)
        confidence_score = self.signal_engine.get_confidence_score(signal)
        confidence_level = self.signal_engine.get_confidence_level(confidence_score)

        signal.state = self.protection_engine.adaptive_ready_wait(
            signal,
            confidence_score
        )

        self.trade_engine.open_trade(signal, current_length)

        # Dashboard
        self.dashboard.render_header()
        self.dashboard.render_signal(signal, confidence_score)
        self.dashboard.render_market(signal)
        self.dashboard.render_profit()
        self.dashboard.render_risk()
        self.dashboard.render_top_windows()
        self.dashboard.render_trade_history()
        self.dashboard.render_equity()
        self.dashboard.render_debug(signal, confidence_score)

        st.caption(
            f"""
V50 Single Clean

Round : {round_id}

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

manager = EngineManager()

try:
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
