import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 400

WINDOWS = range(8,18)
LOOKBACKS = range(18,41)
GAPS = range(2,7)

WIN = 2.5
LOSS = 1

# ================= GROUP =================

def group(n):

    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


# ================= LOAD DATA =================

@st.cache_data(ttl=5)
def load():

    df = pd.read_csv(DATA_URL)

    df.columns = [c.strip().lower() for c in df.columns]

    numbers = df["number"].dropna().astype(int).tolist()

    return numbers


numbers = load()

# ================= SIM ENGINE =================

def simulate(nums, LB, GAP, W):

    profit = 0
    hits = []

    next_signal = None
    last_trade = -999

    for i, n in enumerate(nums):

        g = group(n)

        if next_signal is not None:

            hit = 1 if next_signal == g else 0

            hits.append(hit)

            profit += WIN if hit else -LOSS

            next_signal = None
            last_trade = i

        if i - last_trade > GAP and i > LB:

            rec = []

            for j in range(max(W, i-LB), i):

                if j >= W:

                    rec.append(
                        1 if group(nums[j]) == group(nums[j-W]) else 0
                    )

            if len(rec) > 15:

                wr = np.mean(rec)

                ev = wr * WIN - (1-wr) * LOSS

                if ev > 0:

                    g1 = group(nums[i-W])

                    if group(nums[i-1]) != g1:

                        next_signal = g1

    return profit, hits


# ================= TRAIN BEST PARAM =================

def find_best(train):

    best = -999
    best_cfg = (26,4,9)

    for LB in LOOKBACKS:

        for GAP in GAPS:

            for W in WINDOWS:

                p,_ = simulate(train,LB,GAP,W)

                if p > best:

                    best = p
                    best_cfg = (LB,GAP,W)

    return best_cfg


# ================= WALK FORWARD =================

profit = 0
equity = []

segments = []

start = 0

while start + TRAIN_SIZE < len(numbers):

    train = numbers[:start + TRAIN_SIZE]

    LB,GAP,W = find_best(train)

    trade = numbers[start + TRAIN_SIZE:start + TRAIN_SIZE*2]

    p,_ = simulate(trade,LB,GAP,W)

    profit += p

    equity.append(profit)

    segments.append({

        "start":start,
        "LOOKBACK":LB,
        "GAP":GAP,
        "WINDOW":W,
        "profit":p

    })

    start += TRAIN_SIZE


# ================= METRICS =================

hits_total = []
profit_curve = []

next_signal = None
last_trade = -999
profit_live = 0

for i,n in enumerate(numbers):

    g = group(n)

    if next_signal is not None:

        hit = 1 if next_signal == g else 0

        hits_total.append(hit)

        profit_live += WIN if hit else -LOSS

        next_signal = None
        last_trade = i

    if i-last_trade > 4 and i > 30:

        g1 = group(numbers[i-9])

        if group(numbers[i-1]) != g1:

            next_signal = g1

    profit_curve.append(profit_live)

# ================= DASHBOARD =================

st.title("🚀 LIVE QUANT ENGINE")

wr = np.mean(hits_total) if hits_total else 0

wins = hits_total.count(1)*WIN
loss = hits_total.count(0)*LOSS

pf = wins/loss if loss else 0

peak = max(profit_curve)
dd = peak - profit_curve[-1]

c1,c2,c3 = st.columns(3)

c1.metric("Profit",round(profit_live,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))

c4,c5 = st.columns(2)

c4.metric("Drawdown",round(dd,2))
c5.metric("Trades",len(hits_total))

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":profit_curve}))

st.subheader("Walk Forward Segments")

st.dataframe(pd.DataFrame(segments))

# ================= NEXT GROUP =================

st.subheader("NEXT GROUP SIGNAL")

if next_signal:

    st.markdown(f"""

    <div style='padding:20px;
    background:#c62828;
    color:white;
    border-radius:10px;
    text-align:center;
    font-size:30px'>

    NEXT GROUP → {next_signal}

    </div>

    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")
