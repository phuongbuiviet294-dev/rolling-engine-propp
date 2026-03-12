import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime

# ==========================================================
# CONFIG
# ==========================================================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

WINDOWS = [9, 15]

LOOKBACK_RANGE = range(18, 41)
GAP_RANGE = range(2, 7)

TRAIN_SIZE = 2000
LIVE_SIZE = 400

STOPLOSS_STREAK = 5
PAUSE_AFTER_SL = 3

PF_RELOCK = 0.9
EXPECT_RELOCK = 0

# ==========================================================
# STREAMLIT CONFIG
# ==========================================================

st.set_page_config(layout="wide")
st.title("🚀 PRO WALK FORWARD TRADING ENGINE")

# ==========================================================
# GROUP LOGIC
# ==========================================================

def get_group(n):

    if 1 <= n <= 3:
        return 1
    if 4 <= n <= 6:
        return 2
    if 7 <= n <= 9:
        return 3
    if 10 <= n <= 12:
        return 4

    return None


# ==========================================================
# LOAD DATA
# ==========================================================

@st.cache_data(ttl=AUTO_REFRESH)
def load_data():

    df = pd.read_csv(DATA_URL)

    df.columns = [c.strip().lower() for c in df.columns]

    numbers = df["number"].dropna().astype(int).tolist()

    return numbers


numbers = load_data()

# ==========================================================
# REGIME DETECTION
# ==========================================================

def detect_regime(data, window=50):

    if len(data) < window + 5:
        return "UNKNOWN"

    seq = []

    for i in range(window, len(data)):

        if get_group(data[i]) == get_group(data[i-window]):
            seq.append(1)
        else:
            seq.append(0)

    score = np.mean(seq)

    if score > 0.55:
        return "TREND"

    if score < 0.45:
        return "RANDOM"

    return "MEAN"


# ==========================================================
# CORE ENGINE
# ==========================================================

def run_engine(data, LOOKBACK, GAP, WINDOW):

    total_profit = 0

    engine = []

    next_signal = None

    last_trade_round = -999

    loss_streak = 0

    pause = 0

    for i, n in enumerate(data):

        g = get_group(n)

        predicted = None

        hit = None

        state = "SCAN"

        # =========================
        # PAUSE
        # =========================

        if pause > 0:

            state = "PAUSE"

            pause -= 1

        else:

            # =========================
            # EXECUTE
            # =========================

            if next_signal is not None:

                predicted = next_signal

                hit = 1 if predicted == g else 0

                total_profit += WIN_PROFIT if hit else -LOSE_LOSS

                state = "TRADE"

                last_trade_round = i

                next_signal = None

                if hit == 0:

                    loss_streak += 1

                    if loss_streak >= STOPLOSS_STREAK:

                        state = "STOPLOSS"

                        pause = PAUSE_AFTER_SL

                        loss_streak = 0

                else:

                    loss_streak = 0

            # =========================
            # SEARCH SIGNAL
            # =========================

            if len(engine) >= 40 and i - last_trade_round > GAP:

                recent = []

                start = max(WINDOW, len(engine) - LOOKBACK)

                for j in range(start, len(engine)):

                    if j >= WINDOW:

                        recent.append(
                            1
                            if engine[j]["group"]
                            == engine[j - WINDOW]["group"]
                            else 0
                        )

                if len(recent) >= 20:

                    wr = np.mean(recent)

                    ev = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

                    if wr > 0.30 and ev > 0:

                        g1 = engine[-WINDOW]["group"]

                        if engine[-1]["group"] != g1:

                            next_signal = g1

                            state = "SIGNAL"

        engine.append(
            {
                "round": i,
                "number": n,
                "group": g,
                "predicted": predicted,
                "hit": hit,
                "state": state,
                "profit": total_profit,
            }
        )

    return total_profit, engine, next_signal


# ==========================================================
# GRID SEARCH
# ==========================================================

def optimize(train_data):

    best_profit = -999

    best_cfg = (26, 4, 9)

    for LB in LOOKBACK_RANGE:

        for GP in GAP_RANGE:

            for W in WINDOWS:

                p, _, _ = run_engine(train_data, LB, GP, W)

                if p > best_profit:

                    best_profit = p

                    best_cfg = (LB, GP, W)

    return best_cfg, best_profit


# ==========================================================
# WALK FORWARD
# ==========================================================

pointer = TRAIN_SIZE

results = []

configs = []

while pointer + LIVE_SIZE < len(numbers):

    train = numbers[pointer - TRAIN_SIZE : pointer]

    best_cfg, best_profit = optimize(train)

    LB, GP, W = best_cfg

    live = numbers[pointer : pointer + LIVE_SIZE]

    profit, engine, _ = run_engine(live, LB, GP, W)

    results.append(profit)

    configs.append(best_cfg)

    pointer += LIVE_SIZE


# ==========================================================
# LIVE ENGINE (LAST WINDOW)
# ==========================================================

train = numbers[-TRAIN_SIZE:]

LB, GP, W = optimize(train)[0]

live_data = numbers[-LIVE_SIZE:]

profit, engine, next_signal = run_engine(live_data, LB, GP, W)

# ==========================================================
# METRICS
# ==========================================================

hits = [x["hit"] for x in engine if x["hit"] is not None]

wr = np.mean(hits) if hits else 0

profits = [x["profit"] for x in engine]

peak = max(profits) if profits else 0

drawdown = peak - profits[-1] if profits else 0

wins = [WIN_PROFIT for x in hits if x == 1]

losses = [LOSE_LOSS for x in hits if x == 0]

pf = sum(wins) / sum(losses) if losses else 0

expectancy = wr * WIN_PROFIT - (1 - wr) * LOSE_LOSS

regime = detect_regime(live_data)

# ==========================================================
# DASHBOARD
# ==========================================================

c1, c2, c3 = st.columns(3)

c1.metric("Live Profit", round(profit, 2))

c2.metric("Winrate %", round(wr * 100, 2))

c3.metric("Profit Factor", round(pf, 2))

c4, c5, c6 = st.columns(3)

c4.metric("Drawdown", round(drawdown, 2))

c5.metric("Expectancy", round(expectancy, 3))

c6.metric("Regime", regime)

st.caption(
    f"CONFIG → Lookback {LB} | Gap {GP} | Window {W}"
)

# ==========================================================
# SIGNAL PANEL
# ==========================================================

if next_signal:

    st.markdown(
        f"""
        <div style='padding:20px;background:#c62828;color:white;
        border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>
        🚨 LIVE SIGNAL 🚨<br>
        NEXT GROUP: {next_signal}
        </div>
        """,
        unsafe_allow_html=True,
    )

else:

    st.info("Scanning live...")

# ==========================================================
# EQUITY CURVE
# ==========================================================

st.subheader("Equity Curve")

equity = pd.DataFrame({"profit": profits})

st.line_chart(equity)

# ==========================================================
# HISTORY
# ==========================================================

st.subheader("Live History")

hist = pd.DataFrame(engine)

st.dataframe(hist.iloc[::-1], use_container_width=True)

# ==========================================================
# WALK FORWARD SUMMARY
# ==========================================================

st.subheader("Walk Forward Summary")

wf = pd.DataFrame(
    {
        "cycle": range(len(results)),
        "profit": results,
        "config": configs,
    }
)

st.dataframe(wf)
