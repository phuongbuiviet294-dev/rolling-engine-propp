# ============================================================
# app_v40.py
# PART 1/10
# ============================================================
import time
from collections import deque, Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="V40 Stable Engine",
    layout="wide"
)

# ============================================================
# CONFIG
# ============================================================

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = range(6, 23)

TOPN_TREND = 3
TOPN_SIDEWAY = 5
TOPN_CHAOS = 8

LEADER_HISTORY_LEN = 20
SIGNAL_HISTORY_LEN = 50

PROFIT10_STOP = -3
WR20_STOP = 0.35
FLIPRATE_STOP = 0.60
DRAWDOWN_STOP = -10

COOLDOWN_ROUNDS = 3

# ============================================================
# SESSION INIT
# ============================================================

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

if "equity_curve" not in st.session_state:
    st.session_state.equity_curve = []

if "pending_trade" not in st.session_state:
    st.session_state.pending_trade = None

if "trade_state" not in st.session_state:
    st.session_state.trade_state = "IDLE"

if "cooldown_counter" not in st.session_state:
    st.session_state.cooldown_counter = 0

if "signal_history" not in st.session_state:
    st.session_state.signal_history = deque(
        maxlen=SIGNAL_HISTORY_LEN
    )

if "leader_history" not in st.session_state:
    st.session_state.leader_history = deque(
        maxlen=LEADER_HISTORY_LEN
    )

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
# WINDOW STATE
# ============================================================

window_state = {

    w: {

        "results": [],

        "profit20": 0,

        "profit50": 0,

        "loss_streak": 0,

        "score": 0,

        "next_group": None,

        "reward": 0,

        "blacklisted": False

    }

    for w in WINDOWS

}


# ============================================================
# RESET WINDOW STATE
# ============================================================

def reset_window_state():

    global window_state

    window_state = {

        w: {

            "results": [],

            "profit20": 0,

            "profit50": 0,

            "loss_streak": 0,

            "score": 0,

            "next_group": None,

            "reward": 0,

            "blacklisted": False

        }

        for w in WINDOWS

    }


# ============================================================
# TRADE OBJECT
# ============================================================

@dataclass
class TradeRecord:

    predict: int

    actual: int

    hit: int

    profit: float


# ============================================================
# DEFAULT SIGNAL
# ============================================================

DEFAULT_SIGNAL = {

    "state": "WAIT",

    "next_group": None,

    "top_n": 5,

    "health20": 0,

    "health50": 0,

    "consensus": 0,

    "stability": 0,

    "momentum": 0,

    "leader_change_rate": 0,

    "zigzag_score": 0,

    "trend_score": 0,

    "regime": "CHAOS",

    "market_score": 0,

    "confidence": 0

}

# ============================================================
# END PART 1
# ============================================================


# ============================================================
# app_v40.py
# PART 2/10
# ============================================================

# ============================================================
# GOOGLE SHEET
# ============================================================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"


@st.cache_data(ttl=30)
def load_numbers():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&cache={time.time()}"
    )

    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(str(e))
        st.stop()

    df.columns = [

        str(x).lower().strip()

        for x in df.columns

    ]

    if "number" not in df.columns:

        st.error("Sheet must contain column number")

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
# UPDATE WINDOW
# ============================================================

def update_window_state(groups, idx):

    for w in WINDOWS:

        if idx - w < 0:

            continue

        pred = groups[idx - w]

        hit = int(

            pred == groups[idx]

        )

        stt = window_state[w]

        stt["results"].append(hit)

        tail20 = stt["results"][-20:]

        tail50 = stt["results"][-50:]

        stt["profit20"] = sum(

            WIN_GROUP if x else LOSS_GROUP

            for x in tail20

        )

        stt["profit50"] = sum(

            WIN_GROUP if x else LOSS_GROUP

            for x in tail50

        )

        # -------------------
        # loss streak
        # -------------------

        loss_streak = 0

        for x in reversed(stt["results"]):

            if x == 0:

                loss_streak += 1

            else:

                break

        stt["loss_streak"] = loss_streak

        # -------------------
        # blacklist
        # -------------------

        if loss_streak >= 3:

            stt["blacklisted"] = True

            stt["score"] = -9999

        else:

            stt["blacklisted"] = False

            stt["score"] = (

                stt["profit20"]

                +

                0.3 * stt["profit50"]

                -

                loss_streak

            )

        stt["next_group"] = pred


# ============================================================
# BUILD STATE
# ============================================================

def build_state(groups):

    reset_window_state()

    st.session_state.leader_history.clear()

    for idx in range(22, len(groups)):

        update_window_state(

            groups,

            idx

        )

        rows = sorted(

            window_state.items(),

            key=lambda x: x[1]["score"],

            reverse=True

        )

        if rows:

            st.session_state.leader_history.append(

                rows[0][0]

            )


# ============================================================
# TOP WINDOWS
# ============================================================

def get_top_windows(top_n=5):

    rows = sorted(

        window_state.items(),

        key=lambda x: x[1]["score"],

        reverse=True

    )

    return rows[:top_n]


# ============================================================
# HEALTH ENGINE
# ============================================================

def get_health():

    positive20 = sum(

        1

        for w in WINDOWS

        if window_state[w]["profit20"] > 0

    )

    positive50 = sum(

        1

        for w in WINDOWS

        if window_state[w]["profit50"] > 0

    )

    total = len(WINDOWS)

    health20 = positive20 / total

    health50 = positive50 / total

    return health20, health50


# ============================================================
# CONSENSUS ENGINE
# ============================================================

def get_consensus(top_rows):

    preds = [

        row[1]["next_group"]

        for row in top_rows

        if row[1]["next_group"] is not None

    ]

    if len(preds) == 0:

        return None, 0

    group, count = Counter(

        preds

    ).most_common(1)[0]

    consensus = count / len(preds)

    return group, consensus


# ============================================================
# LEADER CHANGE ENGINE
# ============================================================

def get_leader_change_rate():

    history = st.session_state.leader_history

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

        changes / (len(history) - 1),

        3

    )


# ============================================================
# STABILITY ENGINE
# ============================================================

def get_stability():

    return round(

        max(

            0,

            1 - get_leader_change_rate()

        ),

        3

    )


# ============================================================
# END PART 2
# ============================================================

# ============================================================
# app_v40.py
# PART 3/10
# Core Analysis Engine
# ============================================================

# ============================================================
# MOMENTUM ENGINE
# ============================================================

def get_momentum(top_rows):

    if len(top_rows) == 0:
        return 0

    value = np.mean(

        [

            row[1]["profit20"]

            -

            row[1]["profit50"]

            for row in top_rows

        ]

    )

    return round(float(value), 3)


# ============================================================
# ZIGZAG ENGINE
# ============================================================

def get_zigzag_score():

    history = st.session_state.signal_history

    if len(history) < 6:

        return 0

    zigzag_count = 0

    for i in range(2, len(history)):

        if (

            history[i]

            ==

            history[i - 2]

            and

            history[i]

            !=

            history[i - 1]

        ):

            zigzag_count += 1

    score = zigzag_count / (len(history) - 2)

    return round(score, 3)


# ============================================================
# TREND ENGINE
# ============================================================

def get_trend_score(top_rows):

    if len(top_rows) == 0:

        return 0

    p10 = np.mean(

        [

            sum(

                WIN_GROUP if x else LOSS_GROUP

                for x in row[1]["results"][-10:]

            )

            for row in top_rows

        ]

    )

    p20 = np.mean(

        [

            row[1]["profit20"]

            for row in top_rows

        ]

    )

    p50 = np.mean(

        [

            row[1]["profit50"]

            for row in top_rows

        ]

    )

    score = 0

    if p10 > p20:

        score += 0.5

    if p20 > p50:

        score += 0.5

    return round(score, 3)


# ============================================================
# SIDEWAY ENGINE
# ============================================================

def get_sideway_score(

        consensus,

        momentum

):

    score = 0

    if consensus < 0.80:

        score += 0.5

    if abs(momentum) < 1:

        score += 0.5

    return round(score, 3)


# ============================================================
# REGIME ENGINE
# ============================================================

def get_regime(

        consensus,

        stability,

        momentum,

        zigzag_score,

        leader_change_rate

):

    # CHAOS

    if zigzag_score > 0.60:

        return "CHAOS"

    if leader_change_rate > 0.50:

        return "CHAOS"

    if consensus < 0.60:

        return "CHAOS"

    if stability < 0.50:

        return "CHAOS"

    # TREND

    if momentum > 2:

        return "TREND"

    # SIDEWAY

    return "SIDEWAY"


# ============================================================
# ADAPTIVE TOPN
# ============================================================

def get_adaptive_topn(

        regime

):

    if regime == "TREND":

        return TOPN_TREND

    elif regime == "SIDEWAY":

        return TOPN_SIDEWAY

    else:

        return TOPN_CHAOS


# ============================================================
# MARKET SCORE
# ============================================================

def get_market_score(

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

    return round(score, 3)


# ============================================================
# MARKET QUALITY
# ============================================================

def get_market_quality(

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


# ============================================================
# DYNAMIC THRESHOLD
# ============================================================

def get_dynamic_threshold(

        regime

):

    if regime == "TREND":

        return 0.70

    elif regime == "SIDEWAY":

        return 0.80

    else:

        return 0.90


# ============================================================
# CORE SIGNAL ENGINE
# ============================================================

def get_next_signal():

    top_rows = get_top_windows(5)

    next_group, consensus = get_consensus(

        top_rows

    )

    health20, health50 = get_health()

    stability = get_stability()

    momentum = get_momentum(

        top_rows

    )

    leader_change_rate = get_leader_change_rate()

    zigzag_score = get_zigzag_score()

    trend_score = get_trend_score(

        top_rows

    )

    sideway_score = get_sideway_score(

        consensus,

        momentum

    )

    regime = get_regime(

        consensus,

        stability,

        momentum,

        zigzag_score,

        leader_change_rate

    )

    # adaptive top n

    top_n = get_adaptive_topn(

        regime

    )

    top_rows = get_top_windows(

        top_n

    )

    next_group, consensus = get_consensus(

        top_rows

    )

    market_score = get_market_score(

        health20,

        health50,

        consensus,

        stability,

        trend_score

    )

    quality = get_market_quality(

        market_score

    )

    threshold = get_dynamic_threshold(

        regime

    )

    state = "READY"

    if market_score < threshold:

        state = "WAIT"

    if zigzag_score > 0.60:

        state = "WAIT"

    if leader_change_rate > 0.50:

        state = "WAIT"

    signal = {

        "state": state,

        "next_group": next_group,

        "top_n": top_n,

        "health20": health20,

        "health50": health50,

        "consensus": consensus,

        "stability": stability,

        "momentum": momentum,

        "leader_change_rate": leader_change_rate,

        "zigzag_score": zigzag_score,

        "trend_score": trend_score,

        "sideway_score": sideway_score,

        "regime": regime,

        "market_score": market_score,

        "quality": quality,

        "threshold": threshold

    }

    return signal


# ============================================================
# END PART 3
# ============================================================

# ============================================================
# app_v40.py
# PART 4/10
# Trading Layer
# ============================================================

# ============================================================
# TRADE HISTORY
# ============================================================

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

if "equity_curve" not in st.session_state:
    st.session_state.equity_curve = []

if "pending_trade" not in st.session_state:
    st.session_state.pending_trade = None

if "trade_state" not in st.session_state:
    st.session_state.trade_state = "IDLE"


# ============================================================
# TOTAL PROFIT
# ============================================================

def get_total_profit():

    return round(

        sum(

            x["profit"]

            for x in st.session_state.trade_history

        ),

        2

    )


# ============================================================
# PROFIT 10
# ============================================================

def get_profit10():

    trades = st.session_state.trade_history[-10:]

    return round(

        sum(

            x["profit"]

            for x in trades

        ),

        2

    )


# ============================================================
# PROFIT 20
# ============================================================

def get_profit20():

    trades = st.session_state.trade_history[-20:]

    return round(

        sum(

            x["profit"]

            for x in trades

        ),

        2

    )


# ============================================================
# PROFIT 50
# ============================================================

def get_profit50():

    trades = st.session_state.trade_history[-50:]

    return round(

        sum(

            x["profit"]

            for x in trades

        ),

        2

    )


# ============================================================
# WINRATE ENGINE
# ============================================================

def get_winrate(n=20):

    trades = st.session_state.trade_history[-n:]

    if len(trades) == 0:

        return 0

    wr = (

        sum(

            x["hit"]

            for x in trades

        )

        /

        len(trades)

    )

    return round(wr, 3)


# ============================================================
# DRAWDOWN ENGINE
# ============================================================

def get_drawdown():

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

    return round(dd, 2)


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def get_confidence_score(

        signal

):

    score = (

        0.25 * signal["consensus"]

        +

        0.20 * signal["health20"]

        +

        0.20 * signal["health50"]

        +

        0.20 * signal["stability"]

        +

        0.15 * signal["trend_score"]

    )

    return round(score, 3)


# ============================================================
# CONFIDENCE LEVEL
# ============================================================

def get_confidence_level(

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


# ============================================================
# EQUITY CURVE
# ============================================================

def update_equity_curve():

    equity = 0

    curve = []

    for x in st.session_state.trade_history:

        equity += x["profit"]

        curve.append(

            equity

        )

    st.session_state.equity_curve = curve


# ============================================================
# TRADE STATE MACHINE
# ============================================================

def trade_state_machine(

        signal,

        actual_group

):

    # -----------------
    # open trade
    # -----------------

    if (

            st.session_state.pending_trade

            is None

    ):

        if signal["state"] == "READY":

            st.session_state.pending_trade = (

                signal["next_group"]

            )

            st.session_state.trade_state = (

                "PENDING"

            )

        return

    # -----------------
    # settle
    # -----------------

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

        else

        LOSS_GROUP

    )

    record = {

        "predict": predict,

        "actual": actual_group,

        "hit": hit,

        "profit": profit

    }

    st.session_state.trade_history.append(

        record

    )

    update_equity_curve()

    st.session_state.pending_trade = None

    st.session_state.trade_state = "IDLE"


# ============================================================
# TRADE SNAPSHOT
# ============================================================

def get_trade_snapshot(

        signal

):

    confidence_score = (

        get_confidence_score(

            signal

        )

    )

    snapshot = {

        "trade_state":

            st.session_state.trade_state,

        "profit10":

            get_profit10(),

        "profit20":

            get_profit20(),

        "profit50":

            get_profit50(),

        "total_profit":

            get_total_profit(),

        "wr20":

            get_winrate(20),

        "drawdown":

            get_drawdown(),

        "confidence_score":

            confidence_score,

        "confidence_level":

            get_confidence_level(

                confidence_score

            )

    }

    return snapshot


# ============================================================
# END PART 4
# ============================================================

# ============================================================
# app_v40.py
# PART 5/10
# Risk Management Layer
# ============================================================

# ============================================================
# SIGNAL FLIP HISTORY
# ============================================================

if "signal_flip_history" not in st.session_state:

    st.session_state.signal_flip_history = deque(
        maxlen=50
    )

# ============================================================
# FLIP RATE ENGINE
# ============================================================

def get_flip_rate():

    history = st.session_state.signal_flip_history

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

        flip / (len(history) - 1),

        3

    )


# ============================================================
# COOLDOWN COUNTER
# ============================================================

if "cooldown_counter" not in st.session_state:

    st.session_state.cooldown_counter = 0


# ============================================================
# LOSS STREAK ENGINE
# ============================================================

def get_trade_loss_streak():

    streak = 0

    trades = st.session_state.trade_history

    for x in reversed(trades):

        if x["hit"] == 0:

            streak += 1

        else:

            break

    return streak


# ============================================================
# PROFIT PROTECTION
# ============================================================

def profit_protection_engine():

    p10 = get_profit10()

    wr20 = get_winrate(20)

    dd = get_drawdown()

    flip_rate = get_flip_rate()

    if p10 <= PROFIT10_STOP:

        return True

    if wr20 <= WR20_STOP:

        return True

    if dd <= DRAWDOWN_STOP:

        return True

    if flip_rate >= FLIPRATE_STOP:

        return True

    return False


# ============================================================
# COOLDOWN ENGINE
# ============================================================

def cooldown_engine():

    if get_trade_loss_streak() >= 3:

        st.session_state.cooldown_counter = COOLDOWN_ROUNDS

    if st.session_state.cooldown_counter > 0:

        st.session_state.cooldown_counter -= 1

        return True

    return False


# ============================================================
# RECOVERY ENGINE
# ============================================================

def recovery_engine(

        signal,

        confidence_score

):

    if signal["health20"] < 0.80:

        return False

    if confidence_score < 0.80:

        return False

    if get_flip_rate() > 0.30:

        return False

    if get_winrate(20) < 0.55:

        return False

    return True


# ============================================================
# READY WAIT ENGINE
# ============================================================

def final_ready_wait(

        signal

):

    confidence_score = get_confidence_score(

        signal

    )

    # -------------------
    # Protection
    # -------------------

    if profit_protection_engine():

        return "WAIT"

    # -------------------
    # Cooldown
    # -------------------

    if cooldown_engine():

        return "WAIT"

    # -------------------
    # Flip Rate
    # -------------------

    if get_flip_rate() > 0.60:

        return "WAIT"

    # -------------------
    # Confidence
    # -------------------

    if confidence_score < 0.70:

        return "WAIT"

    # -------------------
    # Market
    # -------------------

    if signal["state"] != "READY":

        return "WAIT"

    return "READY"


# ============================================================
# ADAPTIVE LOCK ENGINE
# ============================================================

def adaptive_lock_engine(

        signal

):

    state = final_ready_wait(

        signal

    )

    confidence_score = get_confidence_score(

        signal

    )

    if state == "WAIT":

        if recovery_engine(

                signal,

                confidence_score

        ):

            state = "READY"

    return state


# ============================================================
# TRADE SIGNAL SNAPSHOT
# ============================================================

def get_trade_signal(

        signal

):

    confidence_score = get_confidence_score(

        signal

    )

    trade_signal = {

        "state":

            adaptive_lock_engine(

                signal

            ),

        "trade_state":

            st.session_state.trade_state,

        "confidence_score":

            confidence_score,

        "confidence_level":

            get_confidence_level(

                confidence_score

            ),

        "profit10":

            get_profit10(),

        "profit20":

            get_profit20(),

        "profit50":

            get_profit50(),

        "total_profit":

            get_total_profit(),

        "wr20":

            get_winrate(

                20

            ),

        "drawdown":

            get_drawdown(),

        "flip_rate":

            get_flip_rate(),

        "cooldown":

            st.session_state.cooldown_counter

    }

    return trade_signal


# ============================================================
# END PART 5
# ============================================================

# ============================================================
# app_v40.py
# PART 6/10
# Dashboard Layer
# ============================================================

# ============================================================
# TITLE
# ============================================================

st.title(

    "V40 STABLE ENGINE"

)


# ============================================================
# READY PANEL
# ============================================================

def render_ready_panel(

        trade_signal,

        signal

):

    if trade_signal["state"] == "READY":

        st.markdown(

            f"""

            <div style="

            background:#008800;

            padding:20px;

            border-radius:15px;

            text-align:center;

            color:white;

            font-size:30px;

            font-weight:bold;

            ">

            READY

            <br>

            NEXT GROUP =

            {signal["next_group"]}

            </div>

            """,

            unsafe_allow_html=True

        )

    else:

        st.markdown(

            """

            <div style="

            background:#444444;

            padding:20px;

            border-radius:15px;

            text-align:center;

            color:white;

            font-size:30px;

            font-weight:bold;

            ">

            WAIT

            </div>

            """,

            unsafe_allow_html=True

        )


# ============================================================
# HEADER PANEL
# ============================================================

def render_header(

        signal,

        trade_signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "STATE",

        trade_signal["state"]

    )

    c2.metric(

        "NEXT GROUP",

        signal["next_group"]

    )

    c3.metric(

        "REGIME",

        signal["regime"]

    )

    c4.metric(

        "CONFIDENCE",

        trade_signal["confidence_level"]

    )


# ============================================================
# HEALTH PANEL
# ============================================================

def render_health(

        signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "Health20",

        round(

            signal["health20"],

            2

        )

    )

    c2.metric(

        "Health50",

        round(

            signal["health50"],

            2

        )

    )

    c3.metric(

        "Consensus",

        round(

            signal["consensus"],

            2

        )

    )

    c4.metric(

        "Stability",

        round(

            signal["stability"],

            2

        )

    )


# ============================================================
# MARKET PANEL
# ============================================================

def render_market(

        signal,

        trade_signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "Momentum",

        round(

            signal["momentum"],

            2

        )

    )

    c2.metric(

        "TrendScore",

        round(

            signal["trend_score"],

            2

        )

    )

    c3.metric(

        "Zigzag",

        round(

            signal["zigzag_score"],

            2

        )

    )

    c4.metric(

        "FlipRate",

        round(

            trade_signal["flip_rate"],

            2

        )

    )


# ============================================================
# PROFIT PANEL
# ============================================================

def render_profit(

        trade_signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "Profit10",

        trade_signal["profit10"]

    )

    c2.metric(

        "Profit20",

        trade_signal["profit20"]

    )

    c3.metric(

        "Profit50",

        trade_signal["profit50"]

    )

    c4.metric(

        "Total Profit",

        trade_signal["total_profit"]

    )


# ============================================================
# RISK PANEL
# ============================================================

def render_risk(

        trade_signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "WR20",

        trade_signal["wr20"]

    )

    c2.metric(

        "Drawdown",

        trade_signal["drawdown"]

    )

    c3.metric(

        "Cooldown",

        trade_signal["cooldown"]

    )

    c4.metric(

        "Trade State",

        trade_signal["trade_state"]

    )


# ============================================================
# CONTROL PANEL
# ============================================================

def render_control(

        signal

):

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(

        "TopN",

        signal["top_n"]

    )

    c2.metric(

        "Quality",

        signal["quality"]

    )

    c3.metric(

        "MarketScore",

        round(

            signal["market_score"],

            2

        )

    )

    c4.metric(

        "Threshold",

        signal["threshold"]

    )


# ============================================================
# END PART 6
# ============================================================

# ============================================================
# app_v40.py
# PART 7/10
# Dashboard Tables + Charts
# ============================================================

# ============================================================
# TOP WINDOWS TABLE
# ============================================================

def render_top_windows(

        signal

):

    st.subheader(

        "Top Windows"

    )

    top_rows = get_top_windows(

        signal["top_n"]

    )

    rows = []

    for w, s in top_rows:

        rows.append(

            {

                "window":

                    w,

                "profit20":

                    round(

                        s["profit20"],

                        2

                    ),

                "profit50":

                    round(

                        s["profit50"],

                        2

                    ),

                "loss_streak":

                    s["loss_streak"],

                "score":

                    round(

                        s["score"],

                        2

                    ),

                "next_group":

                    s["next_group"]

            }

        )

    df = pd.DataFrame(

        rows

    )

    st.dataframe(

        df,

        use_container_width=True

    )


# ============================================================
# WINDOW HEALTH TABLE
# ============================================================

def render_window_health():

    st.subheader(

        "Window Health"

    )

    rows = []

    for w in WINDOWS:

        rows.append(

            {

                "window":

                    w,

                "profit20":

                    round(

                        window_state[w]["profit20"],

                        2

                    ),

                "profit50":

                    round(

                        window_state[w]["profit50"],

                        2

                    ),

                "loss_streak":

                    window_state[w]["loss_streak"],

                "score":

                    round(

                        window_state[w]["score"],

                        2

                    )

            }

        )

    df = pd.DataFrame(

        rows

    )

    st.dataframe(

        df,

        use_container_width=True

    )


# ============================================================
# TRADE HISTORY TABLE
# ============================================================

def render_trade_history():

    st.subheader(

        "Trade History"

    )

    trades = st.session_state.trade_history

    if len(trades) == 0:

        st.info(

            "No trade history"

        )

        return

    df = pd.DataFrame(

        trades

    )

    st.dataframe(

        df.iloc[::-1],

        use_container_width=True

    )


# ============================================================
# EQUITY CURVE
# ============================================================

def render_equity_curve():

    st.subheader(

        "Equity Curve"

    )

    curve = st.session_state.equity_curve

    if len(curve) == 0:

        return

    curve_df = pd.DataFrame(

        {

            "equity":

                curve

        }

    )

    st.line_chart(

        curve_df

    )


# ============================================================
# SCORE SUMMARY
# ============================================================

def render_score_summary(

        signal

):

    st.subheader(

        "Score Summary"

    )

    summary_df = pd.DataFrame(

        {

            "metric": [

                "Health20",

                "Health50",

                "Consensus",

                "Stability",

                "TrendScore",

                "MarketScore"

            ],

            "value": [

                signal["health20"],

                signal["health50"],

                signal["consensus"],

                signal["stability"],

                signal["trend_score"],

                signal["market_score"]

            ]

        }

    )

    st.bar_chart(

        summary_df.set_index(

            "metric"

        )

    )


# ============================================================
# LAST NUMBERS
# ============================================================

def render_last_numbers(

        numbers,

        groups

):

    st.subheader(

        "Last Numbers"

    )

    df = pd.DataFrame(

        {

            "number":

                numbers[-30:],

            "group":

                groups[-30:]

        }

    )

    st.dataframe(

        df.iloc[::-1],

        use_container_width=True

    )


# ============================================================
# FOOTER
# ============================================================

def render_footer():

    st.caption(

        "V40 Stable Engine"

    )


# ============================================================
# END PART 7
# ============================================================

# ============================================================
# app_v40.py
# PART 8/10
# Main Pipeline
# ============================================================

# ============================================================
# LOAD DATA
# ============================================================

numbers = load_numbers()

if len(numbers) < 30:

    st.error(

        "Not enough data"

    )

    st.stop()


# ============================================================
# GROUPS
# ============================================================

groups = [

    group_of(x)

    for x in numbers

]


# ============================================================
# BUILD STATE
# ============================================================

build_state(

    groups

)


# ============================================================
# CORE SIGNAL
# ============================================================

signal = get_next_signal()



if "signal_round_id" not in st.session_state:
    st.session_state.signal_round_id = 0

# ============================================================
# SIGNAL HISTORY
# ============================================================

if signal["next_group"] is not None and round_id > st.session_state.signal_round_id:

    st.session_state.signal_round_id = round_id

    st.session_state.signal_history.append(signal["next_group"])

    st.session_state.signal_flip_history.append(signal["next_group"])


# ============================================================
# ACTUAL GROUP
# ============================================================

actual_group = groups[-1]


# ============================================================
# TRADE STATE MACHINE
# ============================================================


round_id = len(numbers)

if "last_round_id" not in st.session_state:
    st.session_state.last_round_id = 0

if round_id > st.session_state.last_round_id:
    st.session_state.last_round_id = round_id
    trade_state_machine(
        signal,
        actual_group
    )



# ============================================================
# TRADE SIGNAL
# ============================================================

trade_signal = get_trade_signal(

    signal

)


# ============================================================
# READY PANEL
# ============================================================

render_ready_panel(

    trade_signal,

    signal

)


# ============================================================
# HEADER
# ============================================================

render_header(

    signal,

    trade_signal

)


# ============================================================
# HEALTH PANEL
# ============================================================

render_health(

    signal

)


# ============================================================
# MARKET PANEL
# ============================================================

render_market(

    signal,

    trade_signal

)


# ============================================================
# PROFIT PANEL
# ============================================================

render_profit(

    trade_signal

)


# ============================================================
# RISK PANEL
# ============================================================

render_risk(

    trade_signal

)


# ============================================================
# CONTROL PANEL
# ============================================================

render_control(

    signal

)


# ============================================================
# TOP WINDOWS
# ============================================================

render_top_windows(

    signal

)


# ============================================================
# WINDOW HEALTH
# ============================================================

render_window_health()


# ============================================================
# TRADE HISTORY
# ============================================================

render_trade_history()


# ============================================================
# EQUITY CURVE
# ============================================================

render_equity_curve()


# ============================================================
# SCORE SUMMARY
# ============================================================

render_score_summary(

    signal

)


# ============================================================
# LAST NUMBERS
# ============================================================

render_last_numbers(

    numbers,

    groups

)


# ============================================================
# FOOTER
# ============================================================

render_footer()


# ============================================================
# END PART 8
# ============================================================

# ============================================================
# app_v40.py
# PART 9/10
# Persistence + Self Learning Layer
# ============================================================

# ============================================================
# ROUND ID
# ============================================================

if "last_round_id" not in st.session_state:

    st.session_state.last_round_id = 0


def get_round_id(

        numbers

):

    return len(

        numbers

    )


# ============================================================
# DUPLICATE ROUND PROTECTION
# ============================================================

def is_new_round(

        numbers

):

    round_id = get_round_id(

        numbers

    )

    if round_id > st.session_state.last_round_id:

        st.session_state.last_round_id = round_id

        return True

    return False


# ============================================================
# WINDOW REWARD
# ============================================================

if "window_reward" not in st.session_state:

    st.session_state.window_reward = {

        w: 0

        for w in WINDOWS

    }


# ============================================================
# SELF LEARNING ENGINE
# ============================================================

def update_window_reward(

        hit

):

    top_rows = get_top_windows(3)

    delta = 0.20 if hit else -0.30

    for w, _ in top_rows:

        old = (

            st.session_state.window_reward[w]

        )

        new_reward = (

                0.80 * old

                +

                0.20 * delta

        )

        st.session_state.window_reward[w] = (

            round(

                new_reward,

                3

            )

        )


# ============================================================
# BLACKLIST
# ============================================================

if "blacklist_window" not in st.session_state:

    st.session_state.blacklist_window = set()


if "recover_counter" not in st.session_state:

    st.session_state.recover_counter = {

        w: 0

        for w in WINDOWS

    }


# ============================================================
# BLACKLIST ENGINE
# ============================================================

def update_blacklist():

    for w in WINDOWS:

        if (

                window_state[w]["loss_streak"]

                >=

                3

        ):

            st.session_state.blacklist_window.add(

                w

            )


# ============================================================
# RECOVERY ENGINE
# ============================================================

def recovery_window():

    for w in WINDOWS:

        if w not in st.session_state.blacklist_window:

            continue

        if (

                window_state[w]["profit20"]

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


# ============================================================
# APPLY REWARD
# ============================================================

def apply_reward_score():

    for w in WINDOWS:

        reward = (

            st.session_state.window_reward[w]

        )

        penalty = 0

        if w in st.session_state.blacklist_window:

            penalty = -2

        window_state[w]["score"] += (

                reward

                +

                penalty

        )


# ============================================================
# EQUITY HISTORY
# ============================================================

if "equity_history" not in st.session_state:

    st.session_state.equity_history = []


def update_equity_history():

    st.session_state.equity_history = (

        st.session_state.equity_curve.copy()

    )


# ============================================================
# PERSISTENCE SNAPSHOT
# ============================================================

def persistence_snapshot():

    snapshot = {

        "trade_count":

            len(

                st.session_state.trade_history

            ),

        "equity":

            get_total_profit(),

        "drawdown":

            get_drawdown(),

        "cooldown":

            st.session_state.cooldown_counter

    }

    return snapshot


# ============================================================
# BLACKLIST TABLE
# ============================================================

def render_blacklist():

    st.subheader(

        "Blacklist"

    )

    rows = []

    for w in WINDOWS:

        rows.append(

            {

                "window":

                    w,

                "blacklisted":

                    w in st.session_state.blacklist_window,

                "reward":

                    round(

                        st.session_state.window_reward[w],

                        3

                    ),

                "recover_counter":

                    st.session_state.recover_counter[w]

            }

        )

    df = pd.DataFrame(

        rows

    )

    st.dataframe(

        df,

        use_container_width=True

    )


# ============================================================
# STATE HISTORY
# ============================================================

if "state_history" not in st.session_state:

    st.session_state.state_history = deque(

        maxlen=200

    )


def update_state_history(

        trade_signal

):

    st.session_state.state_history.append(

        trade_signal["state"]

    )


# ============================================================
# END PART 9
# ============================================================

# ============================================================
# app_v40.py
# PART 10/10
# Final Wiring + Timeline + Footer
# ============================================================

# ============================================================
# APPLY SELF LEARNING
# ============================================================

update_blacklist()

recovery_window()

apply_reward_score()

update_equity_history()

update_state_history(

    trade_signal

)


# ============================================================
# BLACKLIST TABLE
# ============================================================

render_blacklist()


# ============================================================
# STATE TIMELINE
# ============================================================

st.subheader(

    "State Timeline"

)

if len(

        st.session_state.state_history

) > 0:

    state_df = pd.DataFrame(

        {

            "state":

                list(

                    st.session_state.state_history

                )

        }

    )

    state_df["value"] = state_df["state"].apply(

        lambda x:

        1

        if x == "READY"

        else 0

    )

    st.line_chart(

        state_df["value"]

    )


# ============================================================
# EQUITY TIMELINE
# ============================================================

st.subheader(

    "Equity Timeline"

)

if len(

        st.session_state.equity_history

) > 0:

    eq_df = pd.DataFrame(

        {

            "equity":

                st.session_state.equity_history

        }

    )

    st.line_chart(

        eq_df

    )


# ============================================================
# SNAPSHOT
# ============================================================

snapshot = persistence_snapshot()

c1, c2, c3, c4 = st.columns(4)

c1.metric(

    "Trades",

    snapshot["trade_count"]

)

c2.metric(

    "Equity",

    snapshot["equity"]

)

c3.metric(

    "Drawdown",

    snapshot["drawdown"]

)

c4.metric(

    "Cooldown",

    snapshot["cooldown"]

)


# ============================================================
# DEBUG
# ============================================================

with st.expander(

        "Debug"

):

    st.write(

        "Signal"

    )

    st.json(

        signal

    )

    st.write(

        "Trade Signal"

    )

    st.json(

        trade_signal

    )


# ============================================================
# AUTO REFRESH
# ============================================================

time.sleep(

    1

)


# ============================================================
# FOOTER
# ============================================================

st.markdown(

    """

    ---

    ### V40 Stable Engine

    Adaptive TopN

    Trend / Sideway / Chaos Detect

    Trade State Machine

    Profit Engine

    Drawdown Engine

    Protection Engine

    Cooldown Engine

    Self Learning

    Persistence

    Dashboard

    Version V40 Stable

    """

)


# ============================================================
# END OF FILE
# ============================================================
