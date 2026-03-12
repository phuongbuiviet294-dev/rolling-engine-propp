import streamlit as st
import pandas as pd
import numpy as np

# =============================
# CONFIG
# =============================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW = 9
LOOKBACK = 26
GAP = 4

WIN = 2.5
LOSS = 1

st.set_page_config(layout="wide")

st.title("🚀 FULL BACKTEST ENGINE")

# =============================
# GROUP
# =============================

def group(n):

    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

# =============================
# LOAD DATA
# =============================

@st.cache_data
def load_data():

    df = pd.read_csv(DATA_URL)

    df.columns = [c.strip().lower() for c in df.columns]

    numbers = df["number"].dropna().astype(int).tolist()

    return numbers

numbers = load_data()

st.write("Total rounds:", len(numbers))

# =============================
# ENGINE
# =============================

profit = 0
profits = []

engine = []

next_signal = None
last_trade_round = -999

for i, n in enumerate(numbers):

    g = group(n)

    predicted = None
    hit = None
    state = "SCAN"

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal

        hit = 1 if predicted == g else 0

        if hit == 1:
            profit += WIN
        else:
            profit -= LOSS

        state = "TRADE"

        last_trade_round = i

        next_signal = None

    # ===== SIGNAL GENERATION =====

    if i - last_trade_round > GAP and i > LOOKBACK:

        recent = []

        start = max(WINDOW, i - LOOKBACK)

        for j in range(start, i):

            if j >= WINDOW:

                recent.append(
                    1 if group(numbers[j]) == group(numbers[j - WINDOW]) else 0
                )

        if len(recent) > 10:

            wr = np.mean(recent)

            ev = wr * WIN - (1 - wr) * LOSS

            if ev > 0:

                g1 = group(numbers[i - WINDOW])

                if group(numbers[i - 1]) != g1:

                    next_signal = g1
                    state = "SIGNAL"

    profits.append(profit)

    engine.append({

        "round": i + 1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "state": state,
        "profit": profit

    })

# =============================
# METRICS
# =============================

hits = [x["hit"] for x in engine if x["hit"] is not None]

wr = np.mean(hits) if hits else 0

wins = hits.count(1) * WIN
losses = hits.count(0) * LOSS

pf = wins / losses if losses else 0

peak = max(profits)
final_profit = profits[-1]

drawdown = peak - final_profit

# =============================
# DASHBOARD
# =============================

c1, c2, c3 = st.columns(3)

c1.metric("Profit", round(final_profit,2))
c2.metric("Winrate %", round(wr * 100,2))
c3.metric("Profit Factor", round(pf,2))

c4, c5 = st.columns(2)

c4.metric("Drawdown", round(drawdown,2))
c5.metric("Trades", len(hits))

# =============================
# EQUITY CURVE
# =============================

st.subheader("Equity Curve")

equity = pd.DataFrame({"profit": profits})

st.line_chart(equity)

# =============================
# SEGMENT TEST (EDGE STABILITY)
# =============================

st.subheader("Segment Analysis")

segments = 4

size = len(numbers) // segments

segment_results = []

for s in range(segments):

    start = s * size
    end = (s + 1) * size

    seg = profits[start:end]

    segment_results.append({

        "segment": f"{start}-{end}",
        "profit": seg[-1] - seg[0]

    })

st.dataframe(pd.DataFrame(segment_results))

# =============================
# HISTORY
# =============================

st.subheader("Trade History")

hist = pd.DataFrame(engine)

st.dataframe(hist.iloc[::-1], use_container_width=True)
