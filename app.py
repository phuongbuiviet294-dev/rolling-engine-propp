import time
from collections import Counter, deque

import numpy as np
import pandas as pd
import streamlit as st

# =====================================================
# CONFIG
# =====================================================

st.set_page_config(
    page_title="V36 Engine",
    layout="wide"
)

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WINDOWS = range(6,23)

LEADER_HISTORY_LEN = 20

leader_history = deque(maxlen=LEADER_HISTORY_LEN)
group_history = deque(maxlen=20)

signal_history = deque(maxlen=20)
trade_history = []
pending_trade = None
blacklist_leader=set()

DEFAULT_SIGNAL = {
    "state":"WAIT",
    "next_group":None,
    "health20":0,
    "health50":0,
    "consensus":0,
    "stability":0,
    "momentum":0,
    "leader_change_rate":0,
    "zigzag_score":0,
    "trend_score":0,
    "sideway_score":0,
    "regime":"CHAOS",
    "market_score":0,
    "quality":"CHAOS",
    "threshold":1
}



# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data(ttl=60)
def load_numbers():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&cache={time.time()}"
    )

    df = pd.read_csv(url)

    df.columns = [str(x).lower().strip() for x in df.columns]

    if "number" not in df.columns:
        st.error("Sheet must contain column number")
        st.stop()

    nums = (
        pd.to_numeric(df["number"], errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )

    nums = [x for x in nums if 1 <= x <= 12]

    return nums


# =====================================================
# GROUP MAP
# =====================================================

def group_of(n):

    if n <= 3:
        return 1

    elif n <= 6:
        return 2

    elif n <= 9:
        return 3

    else:
        return 4


# =====================================================
# WINDOW STATE
# =====================================================

window_state = {

    w: {

        "results": [],

        "profit20": 0,

        "profit50": 0,

        "loss_streak": 0,

        "score": 0,

        "next_group": None

    }

    for w in WINDOWS

}


# =====================================================
# RESET
# =====================================================

def reset_window_state():

    global window_state

    window_state = {

        w: {

            "results": [],

            "profit20": 0,

            "profit50": 0,

            "loss_streak": 0,

            "score": 0,

            "next_group": None

        }

        for w in WINDOWS

    }


# =====================================================
# UPDATE WINDOW
# =====================================================

def update_window_state(groups, idx):

    for w in WINDOWS:

        if idx - w < 0:
            continue

        pred = groups[idx - w]

        hit = int(pred == groups[idx])

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

        # loss streak
        loss_streak = 0

        for x in reversed(stt["results"]):

            if x == 0:
                loss_streak += 1
            else:
                break

        stt["loss_streak"] = loss_streak

        # blacklist
        if loss_streak >= 3:

            stt["score"] = -9999

        else:

            stt["score"] = (

                stt["profit20"]

                + 0.3 * stt["profit50"]

                - loss_streak

            )

        stt["next_group"] = pred


# =====================================================
# BUILD STATE
# =====================================================

def build_state(groups):

    reset_window_state()

    leader_history.clear()

    for idx in range(22, len(groups)):

        update_window_state(groups, idx)

        rows = sorted(

            window_state.items(),

            key=lambda x: x[1]["score"],

            reverse=True

        )

        if rows:

            leader_history.append(

                rows[0][0]

            )
         # =====================================================
# TOP WINDOWS
# =====================================================

def get_top_windows(top_n=5):

    rows = sorted(

        window_state.items(),

        key=lambda x: x[1]["score"],

        reverse=True

    )

    return rows[:top_n]


# =====================================================
# HEALTH
# =====================================================

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


# =====================================================
# CONSENSUS
# =====================================================

def get_consensus(top_rows):

    preds = [

        row[1]["next_group"]

        for row in top_rows

        if row[1]["next_group"] is not None

    ]

    if len(preds) == 0:

        return None, 0

    group, count = Counter(preds).most_common(1)[0]

    consensus = count / len(preds)

    return group, consensus


# =====================================================
# STABILITY
# =====================================================

def get_stability():
    return max(0,1-get_leader_change_rate())


# =====================================================
# MOMENTUM
# =====================================================

def get_momentum(top_rows):

    if len(top_rows) == 0:

        return 0

    value = np.mean([

        row[1]["profit20"]

        - row[1]["profit50"]

        for row in top_rows

    ])

    return float(value)


# =====================================================
# LEADER CHANGE RATE
# =====================================================

def get_leader_change_rate():

    if len(leader_history) < 2:

        return 0

    changes = 0

    for i in range(1, len(leader_history)):

        if leader_history[i] != leader_history[i-1]:

            changes += 1

    rate = changes / (len(leader_history) - 1)

    return rate


# =====================================================
# BASIC SNAPSHOT
# =====================================================

def get_basic_snapshot():

    top_rows = get_top_windows(5)

    next_group, consensus = get_consensus(top_rows)

    health20, health50 = get_health()

    stability = get_stability()

    momentum = get_momentum(top_rows)

    leader_change_rate = get_leader_change_rate()

    return {

        "next_group": next_group,

        "health20": health20,

        "health50": health50,

        "consensus": consensus,

        "stability": stability,

        "momentum": momentum,

        "leader_change_rate": leader_change_rate

    }
 # =====================================================
# ZIGZAG SCORE
# =====================================================

def get_zigzag_score():

    if len(signal_history) < 6:
        return 0

    zigzag_count = 0

    for i in range(2, len(signal_history)):

        if (
            signal_history[i] == signal_history[i-2]
            and
            signal_history[i] != signal_history[i-1]
        ):
            zigzag_count += 1

    score = zigzag_count / (len(signal_history)-2)

    return score


# =====================================================
# TREND SCORE
# =====================================================

def get_trend_score(top_rows):

    if len(top_rows)==0:
        return 0

    p10 = np.mean([

        sum(
            WIN_GROUP if x else LOSS_GROUP
            for x in row[1]["results"][-10:]
        )

        for row in top_rows

    ])

    p20 = np.mean([

        row[1]["profit20"]

        for row in top_rows

    ])

    p50 = np.mean([

        row[1]["profit50"]

        for row in top_rows

    ])

    score = 0

    if p10 > p20:
        score += 0.5

    if p20 > p50:
        score += 0.5

    return score


# =====================================================
# SIDEWAY SCORE
# =====================================================

def get_sideway_score(consensus, momentum):

    score = 0

    if consensus < 0.8:
        score += 0.5

    if abs(momentum) < 1:
        score += 0.5

    return score


# =====================================================
# REGIME DETECT
# =====================================================

def get_regime(
        consensus,
        stability,
        momentum,
        zigzag_score,
        leader_change_rate):

    # chaos

    if zigzag_score > 0.6:
        return "CHAOS"

    if leader_change_rate > 0.5:
        return "CHAOS"

    if consensus < 0.6:
        return "CHAOS"

    if stability < 0.5:
        return "CHAOS"

    # trend

    if momentum > 2:
        return "TREND"

    # sideway

    return "SIDEWAY"


# =====================================================
# ANALYSIS SNAPSHOT
# =====================================================

def get_analysis_snapshot():

    top_rows = get_top_windows(5)

    next_group, consensus = get_consensus(top_rows)

    health20, health50 = get_health()

    stability = get_stability()

    momentum = get_momentum(top_rows)

    leader_change_rate = get_leader_change_rate()

    zigzag_score = get_zigzag_score()

    trend_score = get_trend_score(top_rows)

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

    return {

        "next_group": next_group,

        "health20": health20,

        "health50": health50,

        "consensus": consensus,

        "stability": stability,

        "momentum": momentum,

        "leader_change_rate": leader_change_rate,

        "zigzag_score": zigzag_score,

        "trend_score": trend_score,

        "sideway_score": sideway_score,

        "regime": regime

    }
 # =====================================================
# ADAPTIVE TOPN
# =====================================================

def get_adaptive_topn(regime):

    if regime == "TREND":
        return 3

    elif regime == "SIDEWAY":
        return 5

    else:
        return 8


# =====================================================
# MARKET SCORE
# =====================================================

def get_market_score(
        health20,
        health50,
        consensus,
        stability,
        trend_score):

    score = (

        0.30 * health20

        + 0.20 * health50

        + 0.25 * consensus

        + 0.15 * stability

        + 0.10 * trend_score

    )

    return round(score,3)


# =====================================================
# MARKET QUALITY
# =====================================================

def get_market_quality(score):

    if score >= 0.90:
        return "EXCELLENT"

    elif score >= 0.80:
        return "GOOD"

    elif score >= 0.70:
        return "NORMAL"

    elif score >= 0.60:
        return "BAD"

    return "CHAOS"


# =====================================================
# DYNAMIC THRESHOLD
# =====================================================

def get_dynamic_threshold(regime):

    if regime == "TREND":
        return 0.70

    elif regime == "SIDEWAY":
        return 0.80

    else:
        return 0.90


# =====================================================
# NEXT SIGNAL
# =====================================================

def get_next_signal():

    # pass 1
    top_rows = get_top_windows(5)

    next_group, consensus = get_consensus(top_rows)

    health20, health50 = get_health()

    stability = get_stability()

    momentum = get_momentum(top_rows)

    leader_change_rate = get_leader_change_rate()

    zigzag_score = get_zigzag_score()

    trend_score = get_trend_score(top_rows)

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

    # adaptive topn
    top_n = get_adaptive_topn(regime)

    top_rows = get_top_windows(top_n)

    next_group, consensus = get_consensus(top_rows)

    momentum = get_momentum(top_rows)

    trend_score = get_trend_score(top_rows)

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

    if zigzag_score > 0.6:
        state = "WAIT"

    if leader_change_rate > 0.5:
        state = "WAIT"

    return {

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
 # =====================================================
# MAIN
# =====================================================

numbers = load_numbers()

if len(numbers) < 30:
    st.error("Not enough data")
    st.stop()

groups = [group_of(x) for x in numbers]

group_history.clear()

for g in groups[-20:]:
    group_history.append(g)

build_state(groups)

signal = get_next_signal()
if signal["next_group"] is not None:
    signal_history.append(signal["next_group"])

# =====================================================
# TITLE
# =====================================================

st.title("V36 ENGINE")

# =====================================================
# READY PANEL
# =====================================================

if signal["state"] == "READY":

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
        READY<br>
        NEXT GROUP = {signal["next_group"]}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.markdown(
        """
        <div style="
        background:#333333;
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

# =====================================================
# ROW 1
# =====================================================

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "STATE",
    signal["state"]
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
    "QUALITY",
    signal["quality"]
)

# =====================================================
# ROW 2
# =====================================================

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Health20",
    round(signal["health20"],2)
)

c2.metric(
    "Health50",
    round(signal["health50"],2)
)

c3.metric(
    "Consensus",
    round(signal["consensus"],2)
)

c4.metric(
    "Stability",
    round(signal["stability"],2)
)

# =====================================================
# ROW 3
# =====================================================

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Momentum",
    round(signal["momentum"],2)
)

c2.metric(
    "TrendScore",
    round(signal["trend_score"],2)
)

c3.metric(
    "Zigzag",
    round(signal["zigzag_score"],2)
)

c4.metric(
    "MarketScore",
    round(signal["market_score"],2)
)

# =====================================================
# EXTRA
# =====================================================

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Leader Change",
    round(signal["leader_change_rate"],2)
)

c2.metric(
    "SidewayScore",
    round(signal["sideway_score"],2)
)

c3.metric(
    "TopN",
    signal["top_n"]
)

c4.metric(
    "Threshold",
    signal["threshold"]
)

# =====================================================
# TOP WINDOWS
# =====================================================

st.subheader("Top Windows")

top_rows = get_top_windows(signal["top_n"])

rows = []

for w, s in top_rows:

    rows.append({

        "window": w,

        "profit20": round(s["profit20"],2),

        "profit50": round(s["profit50"],2),

        "loss_streak": s["loss_streak"],

        "score": round(s["score"],2),

        "next_group": s["next_group"]

    })

top_df = pd.DataFrame(rows)

st.dataframe(
    top_df,
    use_container_width=True
)

# =====================================================
# WINDOW HEALTH TABLE
# =====================================================

st.subheader("Window Health")

rows = []

for w in WINDOWS:

    rows.append({

        "window": w,

        "profit20": round(
            window_state[w]["profit20"],
            2
        ),

        "profit50": round(
            window_state[w]["profit50"],
            2
        ),

        "loss_streak":
            window_state[w]["loss_streak"],

        "score":
            round(window_state[w]["score"],2)

    })

health_df = pd.DataFrame(rows)

st.dataframe(
    health_df,
    use_container_width=True
)

# =====================================================
# SCORE CURVE
# =====================================================

st.subheader("Score Summary")

summary_df = pd.DataFrame({

    "metric":[

        "Health20",
        "Health50",
        "Consensus",
        "Stability",
        "TrendScore",
        "MarketScore"

    ],

    "value":[

        signal["health20"],
        signal["health50"],
        signal["consensus"],
        signal["stability"],
        signal["trend_score"],
        signal["market_score"]

    ]

})

st.bar_chart(
    summary_df.set_index("metric")
)

# =====================================================
# LAST DATA
# =====================================================

st.subheader("Last Numbers")

last_df = pd.DataFrame({

    "number": numbers[-30:],

    "group": groups[-30:]

})

st.dataframe(
    last_df.iloc[::-1],
    use_container_width=True
)

# =====================================================
# FOOTER
# =====================================================

st.caption(
    "V36 Engine | Adaptive TopN | Regime Detect | Zigzag Filter | Market Quality"
)


def get_total_profit():
    return sum(x["profit"] for x in trade_history)

def get_profit10():
    return sum(x["profit"] for x in trade_history[-10:])

def get_profit20_trade():
    return sum(x["profit"] for x in trade_history[-20:])

def get_profit50_trade():
    return sum(x["profit"] for x in trade_history[-50:])

def get_profit_score():
    score=0
    if get_profit10()>0: score+=0.4
    if get_profit20_trade()>0: score+=0.3
    if get_profit50_trade()>0: score+=0.3
    return score


# =====================================================
# V38 FULL PIPELINE
# WindowState
# -> Adaptive TopN
# -> Consensus
# -> Health20/50
# -> Stability
# -> Leader Change
# -> Signal History
# -> Zigzag
# -> Trend Score
# -> Trade State Machine
# -> Trade History
# -> Profit Engine
# -> Confidence Engine
# -> Profit Protection
# -> READY / WAIT
# -> Dashboard
# =====================================================

trade_state = "IDLE"
confidence_score = 0.0
profit_protection = False

def trade_state_machine(signal, actual_group):
    global pending_trade, trade_history, trade_state

    if pending_trade is None:
        if signal["state"] == "READY":
            pending_trade = signal["next_group"]
            trade_state = "PENDING"
        return

    hit = int(pending_trade == actual_group)
    profit = WIN_GROUP if hit else LOSS_GROUP

    trade_history.append({
        "predict": pending_trade,
        "actual": actual_group,
        "hit": hit,
        "profit": profit
    })

    pending_trade = None
    trade_state = "IDLE"

def get_confidence_engine(signal):
    score = (
        0.25*signal["consensus"]
        +0.20*signal["health20"]
        +0.20*signal["health50"]
        +0.20*signal["stability"]
        +0.15*signal["trend_score"]
    )
    return round(score,3)

def get_profit_protection():
    p10 = get_profit10()
    p20 = get_profit20_trade()

    if p10 < -3 or p20 < -5:
        return True
    return False



# =====================================================
# V39 ADVANCED ENGINE
# =====================================================

signal_flip_history = deque(maxlen=50)
pause_counter = 0

def get_flip_rate():
    if len(signal_flip_history) < 2:
        return 0

    flip = 0
    for i in range(1, len(signal_flip_history)):
        if signal_flip_history[i] != signal_flip_history[i-1]:
            flip += 1

    return round(flip/(len(signal_flip_history)-1),3)


def get_winrate_trade(n=20):
    trades = trade_history[-n:]
    if len(trades) == 0:
        return 0
    return round(sum(x["hit"] for x in trades)/len(trades),3)


def get_drawdown():
    equity = 0
    peak = 0
    dd = 0

    for x in trade_history:
        equity += x["profit"]
        peak = max(peak, equity)
        dd = min(dd, equity-peak)

    return round(dd,2)


def get_confidence_level(score):

    if score >= 0.90:
        return "VERY HIGH"

    if score >= 0.80:
        return "HIGH"

    if score >= 0.70:
        return "NORMAL"

    if score >= 0.60:
        return "LOW"

    return "DANGER"


def profit_protection_engine():
    global pause_counter

    p10 = get_profit10()
    wr20 = get_winrate_trade(20)

    if p10 < -3 or wr20 < 0.35:
        pause_counter = 3

    if pause_counter > 0:
        pause_counter -= 1
        return True

    return False


def final_ready_wait(signal):

    confidence = get_confidence_engine(signal)

    if profit_protection_engine():
        return "WAIT"

    if get_flip_rate() > 0.6:
        return "WAIT"

    if confidence < 0.70:
        return "WAIT"

    return "READY"

