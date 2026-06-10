# ============================================================
# app_v42.py
# PART 1/10
# Config + Session + Dataclass
# ============================================================

import time
from collections import deque, Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import streamlit as st


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V44 Clean Rebuild Full",
    layout="wide"
)


# ============================================================
# CONFIG
# ============================================================

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = list(range(6, 23))

TOPN_TREND = 3
TOPN_SIDEWAY = 5
TOPN_CHAOS = 8

SIGNAL_HISTORY_LEN = 50
LEADER_HISTORY_LEN = 50
STATE_HISTORY_LEN = 200

PROFIT10_STOP = -3
WR20_STOP = 0.35
DRAWDOWN_STOP = -10
FLIPRATE_STOP = 0.60

COOLDOWN_ROUNDS = 3


# ============================================================
# SESSION INIT
# ============================================================

DEFAULT_LIST = [
    "trade_history",
    "equity_curve",
    "equity_history"
]

for key in DEFAULT_LIST:

    if key not in st.session_state:

        st.session_state[key] = []


DEFAULT_DEQUE = {

    "signal_history": SIGNAL_HISTORY_LEN,

    "signal_flip_history": SIGNAL_HISTORY_LEN,

    "leader_history": LEADER_HISTORY_LEN,

    "state_history": STATE_HISTORY_LEN

}

for key, size in DEFAULT_DEQUE.items():

    if key not in st.session_state:

        st.session_state[key] = deque(
            maxlen=size
        )


DEFAULT_SCALAR = {

    "trade_state": "IDLE",

    "pending_trade": None,

    
    "pending_round": 0,

    "pending_round": 0,

    

    

    

    

    

    
    "last_length": 0,

    "cooldown_counter": 0

}

for key, value in DEFAULT_SCALAR.items():

    if key not in st.session_state:

        st.session_state[key] = value


# ============================================================
# WINDOW REWARD
# ============================================================

if "window_reward" not in st.session_state:

    st.session_state.window_reward = {

        w: 0

        for w in WINDOWS

    }


# ============================================================
# WINDOW BLACKLIST
# ============================================================

if "blacklist_window" not in st.session_state:

    st.session_state.blacklist_window = set()


# ============================================================
# RECOVERY COUNTER
# ============================================================

if "recover_counter" not in st.session_state:

    st.session_state.recover_counter = {

        w: 0

        for w in WINDOWS

    }


# ============================================================
# TRADE RECORD
# ============================================================

@dataclass
class TradeRecord:

    predict: int

    actual: int

    hit: int

    profit: float


# ============================================================
# SIGNAL RECORD
# ============================================================

@dataclass
class SignalRecord:

    state: str = "WAIT"

    next_group: int | None = None

    regime: str = "CHAOS"

    top_n: int = 5

    health20: float = 0

    health50: float = 0

    consensus: float = 0

    stability: float = 0

    momentum: float = 0

    trend_score: float = 0

    zigzag_score: float = 0

    leader_change_rate: float = 0

    market_score: float = 0

    quality: str = "CHAOS"

    threshold: float = 0.8


# ============================================================
# WINDOW RECORD
# ============================================================

@dataclass
class WindowRecord:

    results: list = field(default_factory=list)

    profit20: float = 0

    profit50: float = 0

    loss_streak: int = 0

    score: float = 0

    next_group: int | None = None

    reward: float = 0

    blacklisted: bool = False


# ============================================================
# WINDOW STATE
# ============================================================

window_state = {

    w: WindowRecord()

    for w in WINDOWS

}


# ============================================================
# END PART 1
# ============================================================
# ============================================================
# app_v42.py
# PART 2/10
# DataLoader Layer
# ============================================================

# ============================================================
# GOOGLE SHEET CONFIG
# ============================================================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"


# ============================================================
# LOAD NUMBERS
# ============================================================

@st.cache_data(ttl=30)
def load_numbers():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv"
        f"&cache={time.time()}"
    )

    try:

        df = pd.read_csv(url)

    except Exception as e:

        st.error(

            f"Load sheet error : {e}"

        )

        st.stop()

    # ---------------------
    # normalize columns
    # ---------------------

    df.columns = [

        str(x).lower().strip()

        for x in df.columns

    ]

    if "number" not in df.columns:

        st.error(

            "Sheet must contain column 'number'"

        )

        st.stop()

    nums = (

        pd.to_numeric(

            df["number"],

            errors="coerce"

        )

        .dropna()

        .astype(int)

        .tolist()

    )

    nums = [

        x

        for x in nums

        if 1 <= x <= 12

    ]

    return nums


# ============================================================
# GROUP ENGINE
# ============================================================

def group_of(n):

    if n <= 3:

        return 1

    elif n <= 6:

        return 2

    elif n <= 9:

        return 3

    else:

        return 4


# ============================================================
# BUILD GROUPS
# ============================================================

def build_groups(

        numbers

):

    return [

        group_of(x)

        for x in numbers

    ]


# ============================================================
# RESET WINDOW STATE
# ============================================================

def reset_window_state():

    global window_state

    window_state = {

        w: WindowRecord()

        for w in WINDOWS

    }


# ============================================================
# SAFE LAST VALUE
# ============================================================

def safe_last(

        arr,

        default=None

):

    if len(arr) == 0:

        return default

    return arr[-1]


# ============================================================
# GET ROUND ID
# ============================================================

def get_round_id(

        numbers

):

    return len(

        numbers

    )


# ============================================================
# NEW ROUND DETECT
# ============================================================

def is_new_round(

        numbers

):

    round_id = get_round_id(

        numbers

    )

    if (

        round_id

        >

        st.session_state.last_round_id

    ):

        st.session_state.last_round_id = (

            round_id

        )

        return True

    return False


# ============================================================
# LOAD DATA PIPELINE
# ============================================================

def load_data():

    numbers = load_numbers()

    if len(numbers) < 30:

        st.warning(

            "Waiting data..."

        )

        st.stop()

    groups = build_groups(

        numbers

    )

    actual_group = safe_last(

        groups

    )

    round_id = get_round_id(

        numbers

    )

    return (

        numbers,

        groups,

        actual_group,

        round_id

    )


# ============================================================
# END PART 2
# ============================================================
# ============================================================
# app_v42.py
# PART 3/10
# CoreEngine
# ============================================================

class CoreEngine:

    def __init__(self):

        pass

    # ========================================================
    # UPDATE WINDOW
    # ========================================================

    def update_window(

            self,

            groups,

            idx

    ):

        for w in WINDOWS:

            if idx - w < 0:

                continue

            pred = groups[idx - w]

            hit = int(

                pred == groups[idx]

            )

            stt = window_state[w]

            stt.results.append(

                hit

            )

            # --------------------------------
            # profit20
            # --------------------------------

            tail20 = stt.results[-20:]

            stt.profit20 = sum(

                WIN_GROUP if x else LOSS_GROUP

                for x in tail20

            )

            # --------------------------------
            # profit50
            # --------------------------------

            tail50 = stt.results[-50:]

            stt.profit50 = sum(

                WIN_GROUP if x else LOSS_GROUP

                for x in tail50

            )

            # --------------------------------
            # loss streak
            # --------------------------------

            loss_streak = 0

            for x in reversed(

                    stt.results

            ):

                if x == 0:

                    loss_streak += 1

                else:

                    break

            stt.loss_streak = loss_streak

            # --------------------------------
            # score
            # --------------------------------

            stt.score = (

                    stt.profit20

                    +

                    0.30 * stt.profit50

                    -

                    loss_streak

                    +

                    st.session_state.window_reward[w]

            )

            # blacklist penalty

            if w in st.session_state.blacklist_window:

                stt.score -= 2

            stt.next_group = pred

    # ========================================================
    # BUILD STATE
    # ========================================================

    def build_state(

            self,

            groups

    ):

        reset_window_state()

        # keep leader history across reruns

        for idx in range(

                22,

                len(groups)

        ):

            self.update_window(

                groups,

                idx

            )

            rows = sorted(

                window_state.items(),

                key=lambda x: x[1].score,

                reverse=True

            )

            if len(rows) > 0:

                st.session_state.leader_history.append(

                    rows[0][0]

                )

    # ========================================================
    # TOP WINDOWS
    # ========================================================

    def get_top_windows(

            self,

            top_n

    ):

        rows = sorted(

            window_state.items(),

            key=lambda x: x[1].score,

            reverse=True

        )

        return rows[:top_n]

    # ========================================================
    # HEALTH ENGINE
    # ========================================================

    def get_health(

            self

    ):

        positive20 = sum(

            1

            for w in WINDOWS

            if window_state[w].profit20 > 0

        )

        positive50 = sum(

            1

            for w in WINDOWS

            if window_state[w].profit50 > 0

        )

        total = len(

            WINDOWS

        )

        health20 = positive20 / total

        health50 = positive50 / total

        return (

            round(

                health20,

                3

            ),

            round(

                health50,

                3

            )

        )

    # ========================================================
    # CONSENSUS
    # ========================================================

    def get_consensus(

            self,

            top_rows

    ):

        preds = [

            row[1].next_group

            for row in top_rows

            if row[1].next_group is not None

        ]

        if len(preds) == 0:

            return None, 0

        group, count = Counter(

            preds

        ).most_common(1)[0]

        consensus = count / len(preds)

        return (

            group,

            round(

                consensus,

                3

            )

        )

    # ========================================================
    # LEADER CHANGE RATE
    # ========================================================

    def get_leader_change_rate(

            self

    ):

        history = (

            st.session_state.leader_history

        )

        if len(history) < 2:

            return 0

        changes = 0

        for i in range(

                1,

                len(history)

        ):

            if history[i] != history[i - 1]:

                changes += 1

        return round(

            changes

            /

            (

                len(history)

                - 1

            ),

            3

        )

    # ========================================================
    # STABILITY
    # ========================================================

    def get_stability(

            self

    ):

        return round(

            max(

                0,

                1

                -

                self.get_leader_change_rate()

            ),

            3

        )


# ============================================================
# CORE INSTANCE
# ============================================================

core = CoreEngine()


# ============================================================
# END PART 3
# ============================================================
# ============================================================
# app_v42.py
# PART 4/10
# Market Analysis Engine
# ============================================================

class MarketEngine:

    # ========================================================
    # MOMENTUM
    # ========================================================

    def get_momentum(

            self,

            top_rows

    ):

        if len(top_rows) == 0:

            return 0

        value = np.mean(

            [

                row[1].profit20

                -

                row[1].profit50

                for row in top_rows

            ]

        )

        return round(

            float(value),

            3

        )

    # ========================================================
    # ZIGZAG SCORE
    # ========================================================

    def get_zigzag_score(

            self

    ):

        history = st.session_state.signal_history

        if len(history) < 6:

            return 0

        zigzag = 0

        for i in range(

                2,

                len(history)

        ):

            if (

                    history[i]

                    ==

                    history[i - 2]

                    and

                    history[i]

                    !=

                    history[i - 1]

            ):

                zigzag += 1

        score = zigzag / (

                len(history)

                - 2

        )

        return round(

            score,

            3

        )

    # ========================================================
    # TREND SCORE
    # ========================================================

    def get_trend_score(

            self,

            top_rows

    ):

        if len(top_rows) == 0:

            return 0

        p10 = np.mean(

            [

                sum(

                    WIN_GROUP if x else LOSS_GROUP

                    for x in row[1].results[-10:]

                )

                for row in top_rows

            ]

        )

        p20 = np.mean(

            [

                row[1].profit20

                for row in top_rows

            ]

        )

        p50 = np.mean(

            [

                row[1].profit50

                for row in top_rows

            ]

        )

        score = 0

        if p10 > p20:

            score += 0.5

        if p20 > p50:

            score += 0.5

        return round(

            score,

            3

        )

    # ========================================================
    # SIDEWAY SCORE
    # ========================================================

    def get_sideway_score(

            self,

            consensus,

            momentum

    ):

        score = 0

        if consensus < 0.80:

            score += 0.5

        if abs(momentum) < 1:

            score += 0.5

        return round(

            score,

            3

        )

    # ========================================================
    # REGIME
    # ========================================================

    def get_regime(

            self,

            consensus,

            stability,

            momentum,

            zigzag_score,

            leader_change_rate

    ):

        # --------------------
        # CHAOS
        # --------------------

        if zigzag_score > 0.85:

            return "CHAOS"

        if leader_change_rate > 0.75:

            return "CHAOS"

        if consensus < 0.60:

            return "CHAOS"

        if stability < 0.50:

            return "CHAOS"

        # --------------------
        # TREND
        # --------------------

        if momentum > 2:

            return "TREND"

        # --------------------
        # SIDEWAY
        # --------------------

        return "SIDEWAY"

    # ========================================================
    # ADAPTIVE TOPN
    # ========================================================

    def get_top_n(

            self,

            regime

    ):

        if regime == "TREND":

            return TOPN_TREND

        elif regime == "SIDEWAY":

            return TOPN_SIDEWAY

        return TOPN_CHAOS

    # ========================================================
    # MARKET SCORE
    # ========================================================

    def get_market_score(

            self,

            health20,

            health50,

            consensus,

            stability,

            trend_score

    ):

        score = (

                0.30 * health20

                +

                0.20 * health50

                +

                0.25 * consensus

                +

                0.15 * stability

                +

                0.10 * trend_score

        )

        return round(

            score,

            3

        )

    # ========================================================
    # QUALITY
    # ========================================================

    def get_market_quality(

            self,

            market_score

    ):

        if market_score >= 0.90:

            return "EXCELLENT"

        elif market_score >= 0.80:

            return "GOOD"

        elif market_score >= 0.70:

            return "NORMAL"

        elif market_score >= 0.60:

            return "BAD"

        return "CHAOS"

    # ========================================================
    # DYNAMIC THRESHOLD
    # ========================================================

    def get_threshold(
            self,
            regime
    ):
        if regime == "TREND":
            return 0.60
        elif regime == "SIDEWAY":
            return 0.50
        return 0.35


# ============================================================
# MARKET INSTANCE
# ============================================================

market = MarketEngine()


# ============================================================
# END PART 4
# ============================================================
# ============================================================
# app_v42.py
# PART 5/10
# Signal Engine
# ============================================================

class SignalEngine:

    # ========================================================
    # CONFIDENCE SCORE
    # ========================================================

    def get_confidence_score(

            self,

            signal

    ):

        score = (

                0.25 * signal.consensus

                +

                0.20 * signal.health20

                +

                0.20 * signal.health50

                +

                0.20 * signal.stability

                +

                0.15 * signal.trend_score

        )

        return round(

            score,

            3

        )

    # ========================================================
    # CONFIDENCE LEVEL
    # ========================================================

    def get_confidence_level(

            self,

            score

    ):

        if score >= 0.90:

            return "VERY HIGH"

        elif score >= 0.80:

            return "HIGH"

        elif score >= 0.70:

            return "NORMAL"

        elif score >= 0.60:

            return "LOW"

        return "DANGER"

    # ========================================================
    # BUILD SIGNAL
    # ========================================================

    def build_signal(

            self

    ):

        signal = SignalRecord()

        # -----------------------
        # temporary topn
        # -----------------------

        top_rows = core.get_top_windows(

            5

        )

        next_group, consensus = (

            core.get_consensus(

                top_rows

            )

        )

        health20, health50 = (

            core.get_health()

        )

        stability = (

            core.get_stability()

        )

        momentum = (

            market.get_momentum(

                top_rows

            )

        )

        leader_change_rate = (

            core.get_leader_change_rate()

        )

        zigzag_score = (

            market.get_zigzag_score()

        )

        trend_score = (

            market.get_trend_score(

                top_rows

            )

        )

        sideway_score = (

            market.get_sideway_score(

                consensus,

                momentum

            )

        )

        regime = (

            market.get_regime(

                consensus,

                stability,

                momentum,

                zigzag_score,

                leader_change_rate

            )

        )

        # -----------------------
        # adaptive top n
        # -----------------------

        top_n = market.get_top_n(

            regime

        )

        top_rows = core.get_top_windows(

            top_n

        )

        next_group, consensus = (

            core.get_consensus(

                top_rows

            )

        )

        market_score = (

            market.get_market_score(

                health20,

                health50,

                consensus,

                stability,

                trend_score

            )

        )

        quality = (

            market.get_market_quality(

                market_score

            )

        )

        threshold = (

            market.get_threshold(

                regime

            )

        )

        state = "READY"

        # -----------------------
        # market filters
        # -----------------------

        if market_score < threshold:

            state = "WAIT"

        if zigzag_score > 0.85:

            state = "WAIT"

        if leader_change_rate > 0.75:

            state = "WAIT"

        # -----------------------
        # fill signal
        # -----------------------

        signal.state = state

        signal.next_group = next_group

        signal.regime = regime

        signal.top_n = top_n

        signal.health20 = health20

        signal.health50 = health50

        signal.consensus = consensus

        signal.stability = stability

        signal.momentum = momentum

        signal.trend_score = trend_score

        signal.zigzag_score = zigzag_score

        signal.leader_change_rate = (

            leader_change_rate

        )

        signal.market_score = market_score

        signal.quality = quality

        signal.threshold = threshold

        # emergency override
        confidence_score = self.get_confidence_score(signal)
        if signal.market_score > 0.35 and confidence_score > 0.35:
            signal.state = "READY"

        return signal

    # ========================================================
    # UPDATE SIGNAL HISTORY
    # ========================================================

    def update_signal_history(

            self,

            signal,

            round_id

    ):

        if (

                signal.next_group is None

        ):

            return

        if (

                round_id

                <=

                st.session_state.signal_round_id

        ):

            return

        if round_id <= st.session_state.last_signal_round:
            return

        st.session_state.last_signal_round = round_id

        st.session_state.signal_history.append(

            signal.next_group

        )

        st.session_state.signal_flip_history.append(

            signal.next_group

        )


# ============================================================
# SIGNAL INSTANCE
# ============================================================

signal_engine = SignalEngine()


# ============================================================
# END PART 5
# ============================================================
# ============================================================
# app_v42.py
# PART 6/10
# Trade Engine
# ============================================================

class TradeEngine:

    # ========================================================
    # EQUITY CURVE
    # ========================================================

    def update_equity_curve(self):

        equity = 0

        curve = []

        for x in st.session_state.trade_history:

            equity += x["profit"]

            curve.append(

                round(

                    equity,

                    2

                )

            )

        st.session_state.equity_curve = curve

        st.session_state.equity_history = curve.copy()

    # ========================================================
    # OPEN TRADE
    # ========================================================

    def open_trade(

            self,

            signal,

            round_id

    ):

        if signal.state != "READY":

            return

        if signal.next_group is None:

            return

        if st.session_state.pending_trade is not None:
            return

        st.session_state.pending_trade = signal.next_group
        st.session_state.pending_round = len(load_numbers())
        st.session_state.pending_number = st.session_state.last_number

        st.session_state.trade_state = (

            "PENDING"

        )

    # ========================================================
    # SETTLE TRADE
    # ========================================================

    def settle_trade(

            self,

            actual_group,

            current_number

    ):

        # no pending trade

        if (

                st.session_state.pending_trade

                is None

        ):

            return

        current_round = len(load_numbers())
        if current_round <= st.session_state.pending_round:
            return

        predict = (

            st.session_state.pending_trade

        )

        hit = int(

            predict

            ==

            actual_group

        )

        profit = (

            WIN_GROUP

            if hit

            else LOSS_GROUP

        )

        record = {

            "predict":

                predict,

            "actual":

                actual_group,

            "hit":

                hit,

            "profit":

                profit

        }

        st.session_state.trade_history.append(

            record

        )

        self.update_equity_curve()

        st.session_state.pending_trade = None
        st.session_state.pending_number = None
        st.session_state.pending_round = 0
        st.session_state.trade_state = "IDLE" 

    # ========================================================
    # TOTAL PROFIT
    # ========================================================

    def get_total_profit(

            self

    ):

        return round(

            sum(

                x["profit"]

                for x in st.session_state.trade_history

            ),

            2

        )

    # ========================================================
    # PROFIT10
    # ========================================================

    def get_profit10(

            self

    ):

        trades = (

            st.session_state.trade_history[-10:]

        )

        return round(

            sum(

                x["profit"]

                for x in trades

            ),

            2

        )

    # ========================================================
    # PROFIT20
    # ========================================================

    def get_profit20(

            self

    ):

        trades = (

            st.session_state.trade_history[-20:]

        )

        return round(

            sum(

                x["profit"]

                for x in trades

            ),

            2

        )

    # ========================================================
    # PROFIT50
    # ========================================================

    def get_profit50(

            self

    ):

        trades = (

            st.session_state.trade_history[-50:]

        )

        return round(

            sum(

                x["profit"]

                for x in trades

            ),

            2

        )

    # ========================================================
    # WINRATE
    # ========================================================

    def get_winrate(

            self,

            n=20

    ):

        trades = (

            st.session_state.trade_history[-n:]

        )

        if len(

                trades

        ) == 0:

            return 0

        wr = (

                sum(

                    x["hit"]

                    for x in trades

                )

                /

                len(trades)

        )

        return round(

            wr,

            3

        )

    # ========================================================
    # LOSS STREAK
    # ========================================================

    def get_loss_streak(

            self

    ):

        streak = 0

        trades = (

            st.session_state.trade_history

        )

        for x in reversed(

                trades

        ):

            if x["hit"] == 0:

                streak += 1

            else:

                break

        return streak

    # ========================================================
    # DRAWDOWN
    # ========================================================

    def get_drawdown(

            self

    ):

        equity = 0

        peak = 0

        dd = 0

        for x in st.session_state.trade_history:

            equity += x["profit"]

            peak = max(

                peak,

                equity

            )

            dd = min(

                dd,

                equity - peak

            )

        return round(

            dd,

            2

        )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def snapshot(

            self

    ):

        return {

            "trade_state":

                st.session_state.trade_state,

            "profit10":

                self.get_profit10(),

            "profit20":

                self.get_profit20(),

            "profit50":

                self.get_profit50(),

            "total_profit":

                self.get_total_profit(),

            "wr20":

                self.get_winrate(

                    20

                ),

            "drawdown":

                self.get_drawdown(),

            "pending_trade":

                st.session_state.pending_trade

        }


# ============================================================
# TRADE INSTANCE
# ============================================================

trade_engine = TradeEngine()


# ============================================================
# STATE MACHINE
# ============================================================

"""
IDLE
 ↓
OPEN
 ↓
PENDING
 ↓
new round
 ↓
SETTLE
 ↓
IDLE
"""


# ============================================================
# END PART 6
# ============================================================
# ============================================================
# app_v42.py
# PART 7/10
# Protection Engine
# ============================================================

class ProtectionEngine:

    # ========================================================
    # FLIP RATE
    # ========================================================

    def get_flip_rate(

            self

    ):

        history = (

            st.session_state.signal_flip_history

        )

        if len(history) < 2:

            return 0

        flip = 0

        for i in range(

                1,

                len(history)

        ):

            if history[i] != history[i - 1]:

                flip += 1

        return round(

            flip

            /

            (

                len(history)

                - 1

            ),

            3

        )

    # ========================================================
    # PROFIT PROTECTION
    # ========================================================

    def profit_protection(

            self

    ):

        trade_count = len(st.session_state.trade_history)
        if trade_count < 20:
            return False

        if (

                trade_engine.get_profit10()

                <=

                PROFIT10_STOP

        ):

            return True

        if (

                trade_engine.get_winrate(20)

                <=

                WR20_STOP

        ):

            return True

        if (

                trade_engine.get_drawdown()

                <=

                DRAWDOWN_STOP

        ):

            return True

        if (

                self.get_flip_rate()

                >=

                FLIPRATE_STOP

        ):

            return True

        return False

    # ========================================================
    # COOLDOWN ENGINE
    # ========================================================

    def cooldown_engine(

            self

    ):

        if (

                trade_engine.get_loss_streak()

                >=

                3

        ):

            st.session_state.cooldown_counter = (

                COOLDOWN_ROUNDS

            )

        if (

                st.session_state.cooldown_counter

                >

                0

        ):

            st.session_state.cooldown_counter -= 1

            return True

        return False

    # ========================================================
    # RECOVERY ENGINE
    # ========================================================

    def recovery_engine(

            self,

            signal,

            confidence_score

    ):

        if signal.health20 < 0.80:

            return False

        if confidence_score < 0.80:

            return False

        if self.get_flip_rate() > 0.30:

            return False

        if trade_engine.get_winrate(20) < 0.55:

            return False

        return True

    # ========================================================
    # WINDOW BLACKLIST
    # ========================================================

    def update_blacklist(

            self

    ):

        for w in WINDOWS:

            if (

                    window_state[w].loss_streak

                    >=

                    3

            ):

                st.session_state.blacklist_window.add(

                    w

                )

    # ========================================================
    # RECOVERY WINDOW
    # ========================================================

    def recovery_window(

            self

    ):

        for w in WINDOWS:

            if (

                    w

                    not in

                    st.session_state.blacklist_window

            ):

                continue

            if (

                    window_state[w].profit20

                    >

                    0

            ):

                st.session_state.recover_counter[w] += 1

            else:

                st.session_state.recover_counter[w] = 0

            if (

                    st.session_state.recover_counter[w]

                    >=

                    5

            ):

                st.session_state.blacklist_window.remove(

                    w

                )

                st.session_state.recover_counter[w] = 0

    # ========================================================
    # APPLY REWARD
    # ========================================================

    def update_reward(

            self,

            hit

    ):

        top_rows = core.get_top_windows(

            3

        )

        delta = 0.20 if hit else -0.30

        for w, _ in top_rows:

            old = (

                st.session_state.window_reward[w]

            )

            reward = (

                    0.80 * old

                    +

                    0.20 * delta

            )

            st.session_state.window_reward[w] = max(
                -2,
                min(
                    2,
                    round(reward,3)
                )
            )

    # ========================================================
    # ADAPTIVE READY WAIT
    # ========================================================

    def adaptive_ready_wait(

            self,

            signal,

            confidence_score

    ):

        # ----------------
        # protection
        # ----------------

        if self.profit_protection():

            return "WAIT"

        # ----------------
        # cooldown
        # ----------------

        if self.cooldown_engine():

            return "WAIT"

        # ----------------
        # flip rate
        # ----------------

        if self.get_flip_rate() > 0.60:

            return "WAIT"

        # ----------------
        # confidence
        # ----------------

        if confidence_score < 0.35:

            return "WAIT"

        # ----------------
        # market state
        # ----------------

        if signal.state != "READY":

            return "WAIT"

        # ----------------
        # recovery override
        # ----------------

        if self.recovery_engine(

                signal,

                confidence_score

        ):

            return "READY"

        return "READY"


# ============================================================
# PROTECTION INSTANCE
# ============================================================

protection_engine = ProtectionEngine()


# ============================================================
# END PART 7
# ============================================================
# ============================================================
# app_v42.py
# PART 8/10
# Persistence Engine
# ============================================================

class PersistenceEngine:

    # ========================================================
    # UPDATE STATE HISTORY
    # ========================================================

    def update_state_history(

            self,

            state

    ):

        st.session_state.state_history.append(

            state

        )

    # ========================================================
    # UPDATE EQUITY HISTORY
    # ========================================================

    def update_equity_history(

            self

    ):

        st.session_state.equity_history = (

            st.session_state.equity_curve.copy()

        )

    # ========================================================
    # ROUND MANAGER
    # ========================================================

    def is_new_round(

            self,

            round_id

    ):

        if (

                round_id

                >

                st.session_state.last_round_id

        ):

            st.session_state.last_round_id = (

                round_id

            )

            return True

        return False

    # ========================================================
    # SIGNAL HISTORY
    # ========================================================

    def update_signal_history(

            self,

            signal,

            round_id

    ):

        if signal.next_group is None:

            return

        if (

                round_id

                <=

                st.session_state.signal_round_id

        ):

            return

        if round_id <= st.session_state.last_signal_round:
            return

        st.session_state.last_signal_round = round_id

        st.session_state.signal_history.append(

            signal.next_group

        )

        st.session_state.signal_flip_history.append(

            signal.next_group

        )

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def snapshot(

            self,

            signal,

            confidence_score

    ):

        return {

            "trade_count":

                len(

                    st.session_state.trade_history

                ),

            "trade_state":

                st.session_state.trade_state,

            "pending_trade":

                st.session_state.pending_trade,

            "equity":

                trade_engine.get_total_profit(),

            "profit10":

                trade_engine.get_profit10(),

            "profit20":

                trade_engine.get_profit20(),

            "profit50":

                trade_engine.get_profit50(),

            "wr20":

                trade_engine.get_winrate(

                    20

                ),

            "drawdown":

                trade_engine.get_drawdown(),

            "flip_rate":

                protection_engine.get_flip_rate(),

            "cooldown":

                st.session_state.cooldown_counter,

            "confidence":

                confidence_score,

            "signal_state":

                signal.state,

            "regime":

                signal.regime

        }

    # ========================================================
    # SAVE SNAPSHOT
    # ========================================================

    def save_snapshot(

            self,

            signal,

            confidence_score

    ):

        if "snapshot_history" not in st.session_state:

            st.session_state.snapshot_history = []

        st.session_state.snapshot_history.append(

            self.snapshot(

                signal,

                confidence_score

            )

        )

    # ========================================================
    # APPLY SELF LEARNING
    # ========================================================

    def apply_self_learning(

            self

    ):

        protection_engine.update_blacklist()

        protection_engine.recovery_window()

    # ========================================================
    # RESET SESSION
    # ========================================================

    def reset_runtime(

            self

    ):

        st.session_state.pending_trade = None

        st.session_state.pending_round = 0

        st.session_state.trade_state = "IDLE"

    # ========================================================
    # FULL UPDATE
    # ========================================================

    def update(

            self,

            signal,

            confidence_score,

            round_id

    ):

        self.update_state_history(

            signal.state

        )

        self.update_equity_history()

        self.update_signal_history(

            signal,

            round_id

        )

        self.save_snapshot(

            signal,

            confidence_score

        )

        self.apply_self_learning()


# ============================================================
# PERSISTENCE INSTANCE
# ============================================================

persistence_engine = PersistenceEngine()


# ============================================================
# END PART 8
# ============================================================
# ============================================================
# app_v42.py
# PART 9/10
# Dashboard
# ============================================================

class Dashboard:

    # ========================================================
    # HEADER
    # ========================================================

    def render_header(

            self

    ):

        st.title(

            "🚀 V44 Clean Rebuild Full"

        )

    # ========================================================
    # SIGNAL PANEL
    # ========================================================

    def render_signal(

            self,

            signal,

            confidence_score

    ):

        color = "#00aa00"

        if signal.state != "READY":

            color = "#555555"

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

    # ========================================================
    # MARKET PANEL
    # ========================================================

    def render_market(

            self,

            signal

    ):

        c1, c2, c3, c4 = st.columns(

            4

        )

        c1.metric(

            "Regime",

            signal.regime

        )

        c2.metric(

            "MarketScore",

            round(

                signal.market_score,

                3

            )

        )

        c3.metric(

            "Consensus",

            round(

                signal.consensus,

                3

            )

        )

        c4.metric(

            "Quality",

            signal.quality

        )

    # ========================================================
    # HEALTH PANEL
    # ========================================================

    def render_health(

            self,

            signal

    ):

        c1, c2, c3, c4 = st.columns(

            4

        )

        c1.metric(

            "Health20",

            signal.health20

        )

        c2.metric(

            "Health50",

            signal.health50

        )

        c3.metric(

            "Stability",

            signal.stability

        )

        c4.metric(

            "Momentum",

            signal.momentum

        )

    # ========================================================
    # PROFIT PANEL
    # ========================================================

    def render_profit(

            self

    ):

        snap = trade_engine.snapshot()

        c1, c2, c3, c4 = st.columns(

            4

        )

        c1.metric(

            "Total Profit",

            snap["total_profit"]

        )

        c2.metric(

            "Profit20",

            snap["profit20"]

        )

        c3.metric(

            "WR20",

            snap["wr20"]

        )

        c4.metric(

            "Drawdown",

            snap["drawdown"]

        )

    # ========================================================
    # RISK PANEL
    # ========================================================

    def render_risk(

            self

    ):

        c1, c2, c3 = st.columns(

            3

        )

        c1.metric(

            "FlipRate",

            protection_engine.get_flip_rate()

        )

        c2.metric(

            "LossStreak",

            trade_engine.get_loss_streak()

        )

        c3.metric(

            "Cooldown",

            st.session_state.cooldown_counter

        )

    # ========================================================
    # TOP WINDOWS
    # ========================================================

    def render_top_windows(

            self,

            signal

    ):

        rows = core.get_top_windows(

            signal.top_n

        )

        data = []

        for w, obj in rows:

            data.append(

                {

                    "Window": w,

                    "Score": round(

                        obj.score,

                        2

                    ),

                    "Profit20": round(

                        obj.profit20,

                        2

                    ),

                    "Profit50": round(

                        obj.profit50,

                        2

                    ),

                    "LossStreak": obj.loss_streak,

                    "Next": obj.next_group

                }

            )

        st.subheader(

            "Top Windows"

        )

        st.dataframe(

            pd.DataFrame(

                data

            ),

            use_container_width=True

        )

    # ========================================================
    # TRADE HISTORY
    # ========================================================

    def render_trade_history(

            self

    ):

        st.subheader(

            "Trade History"

        )

        if len(

                st.session_state.trade_history

        ) == 0:

            st.info(

                "No trades"

            )

            return

        df = pd.DataFrame(

            st.session_state.trade_history

        )

        st.dataframe(

            df.tail(

                50

            ),

            use_container_width=True

        )

    # ========================================================
    # EQUITY CURVE
    # ========================================================

    def render_equity(

            self

    ):

        st.subheader(

            "Equity Curve"

        )

        if len(

                st.session_state.equity_curve

        ) == 0:

            return

        df = pd.DataFrame(

            {

                "equity":

                    st.session_state.equity_curve

            }

        )

        st.line_chart(

            df

        )

    # ========================================================
    # BLACKLIST
    # ========================================================

    def render_blacklist(

            self

    ):

        st.subheader(

            "Blacklist"

        )

        st.write(

            list(

                st.session_state.blacklist_window

            )

        )

    # ========================================================
    # DEBUG
    # ========================================================

    def render_debug(

            self,

            signal,

            confidence_score

    ):

        with st.expander(

                "Debug"

        ):

            st.json(

                persistence_engine.snapshot(

                    signal,

                    confidence_score

                )

            )


# ============================================================
# DASHBOARD INSTANCE
# ============================================================

dashboard = Dashboard()


# ============================================================
# END PART 9
# ============================================================
# ============================================================
# app_v42.py
# PART 10/10
# Engine Manager + Main Pipeline
# ============================================================

class EngineManager:

    def run(self):

        # ====================================================
        # LOAD DATA
        # ====================================================

        numbers, groups, actual_group, round_id = (

            load_data()

        )

        # ====================================================
        # CORE UPDATE
        # ====================================================

        core.build_state(

            groups

        )

        # ====================================================
        # BUILD SIGNAL
        # ====================================================

        signal = signal_engine.build_signal()

        confidence_score = (

            signal_engine.get_confidence_score(

                signal

            )

        )

        confidence_level = (

            signal_engine.get_confidence_level(

                confidence_score

            )

        )

        # ====================================================
        # PROTECTION LAYER
        # ====================================================

        signal.state = (

            protection_engine.adaptive_ready_wait(

                signal,

                confidence_score

            )

        )

        # ====================================================
        # NEW ROUND
        # ====================================================

        current_number = numbers[-1]

        if st.session_state.last_number is None:
            st.session_state.last_number = current_number

        current_length = len(numbers)

        if st.session_state.last_length == 0:
            st.session_state.last_length = current_length

        if current_length > st.session_state.last_length:

            trade_engine.settle_trade(
                actual_group,
                current_number
            )

            st.session_state.last_length = current_length

        st.session_state.last_number = current_number

        trade_engine.open_trade(
            signal,
            current_number
        )

        # ====================================================
        # PERSISTENCE
        # ====================================================

        persistence_engine.update(

            signal,

            confidence_score,

            round_id

        )

        # ====================================================
        # DASHBOARD
        # ====================================================

        dashboard.render_header()

        dashboard.render_signal(

            signal,

            confidence_score

        )

        dashboard.render_market(

            signal

        )

        dashboard.render_health(

            signal

        )

        dashboard.render_profit()

        dashboard.render_risk()

        dashboard.render_top_windows(

            signal

        )

        dashboard.render_trade_history()

        dashboard.render_equity()

        dashboard.render_blacklist()

        dashboard.render_debug(

            signal,

            confidence_score

        )

        # ====================================================
        # FOOTER
        # ====================================================

        st.caption(

            f"""
V44 Clean Rebuild Full

Round : {round_id}

Confidence : {confidence_level}

Trade State : {st.session_state.trade_state}

Pending Trade : {st.session_state.pending_trade}

Regime : {signal.regime}
"""
        )


# ============================================================
# MANAGER INSTANCE
# ============================================================

manager = EngineManager()


# ============================================================
# MAIN
# ============================================================

try:

    manager.run()

except Exception as e:

    st.error(

        f"Engine Error : {e}"

    )

    import traceback

    st.code(

        traceback.format_exc()

    )


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(

    1

)

st.rerun()


# ============================================================
# END OF FILE
# ============================================================


# ===============================
# V43_DEBUG_ENGINE
# ===============================
try:
    st.subheader("V43 State Debug")

    st.json({
        "trade_state": st.session_state.get("trade_state"),
        "pending_trade": st.session_state.get("pending_trade"),
        "pending_number": st.session_state.get("pending_number"),
        "last_number": st.session_state.get("last_number"),
        "trade_count": len(st.session_state.get("trade_history", []))
    })

except Exception:
    pass


# ======================
# V44 CLEAN REBUILD FULL
# ======================
