import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 2000
RETRAIN_INTERVAL = 200

WINDOW_RANGE = range(6,19)

LOOKBACK = 26
GAP = 4

WIN = 2.5
LOSS = 1

st.set_page_config(layout="wide")

# ================= GROUP =================

def get_group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

# ================= LOAD =================

@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers = load()
groups = [get_group(n) for n in numbers]

# ================= OPTIMIZER =================

def find_best_window(data):

    best_profit=-999
    best_window=None

    for W in WINDOW_RANGE:

        profit=0
        next_signal=None
        last_trade=-999

        for i in range(len(data)):

            g=data[i]

            if next_signal is not None:

                hit = 1 if next_signal==g else 0
                profit += WIN if hit else -LOSS

                next_signal=None
                last_trade=i

            if i-last_trade>GAP and i>LOOKBACK:

                rec=[]

                for j in range(max(W,i-LOOKBACK),i):

                    if j>=W:
                        rec.append(
                            1 if data[j]==data[j-W] else 0
                        )

                if len(rec)>15:

                    wr=np.mean(rec)
                    ev=wr*WIN-(1-wr)*LOSS

                    if ev>0:

                        g1=data[i-W]

                        if data[i-1]!=g1:

                            next_signal=g1

        if profit>best_profit:
            best_profit=profit
            best_window=W

    return best_window,best_profit

# ================= TRAIN =================

train_groups = groups[:TRAIN_SIZE]

best_window,train_profit = find_best_window(train_groups)

# ================= LIVE =================

profit=0
equity=[]
hits=[]

next_signal=None
last_trade=-999

history=[]

current_window=best_window
last_retrain=TRAIN_SIZE

for i in range(TRAIN_SIZE,len(groups)):

    g=groups[i]

    predicted=None
    hit=None
    state="SCAN"

    # ===== EXECUTE =====

    if next_signal is not None:

        predicted=next_signal

        hit = 1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        hits.append(hit)

        next_signal=None
        last_trade=i
        state="TRADE"

    # ===== RETRAIN =====

    if i-last_retrain>=RETRAIN_INTERVAL:

        train_slice = groups[:i]

        current_window,_ = find_best_window(train_slice)

        last_retrain=i

    # ===== SIGNAL =====

    if i-last_trade>GAP and i>LOOKBACK:

        rec=[]

        for j in range(max(current_window,i-LOOKBACK),i):

            if j>=current_window:

                rec.append(
                    1 if groups[j]==groups[j-current_window] else 0
                )

        if len(rec)>15:

            wr=np.mean(rec)
            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=groups[i-current_window]

                if groups[i-1]!=g1:

                    next_signal=g1
                    state="SIGNAL"

    equity.append(profit)

    history.append({

        "round":i+1,
        "number":numbers[i],
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":current_window,
        "state":state,
        "profit":profit

    })

# ================= METRICS =================

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

# ================= UI =================

st.title("🚀 V100 SELF ADAPTIVE ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))
c4.metric("Active Window",current_window)

st.caption(f"Train size = {TRAIN_SIZE} | Retrain every {RETRAIN_INTERVAL} rounds")

# ================= EQUITY =================

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

# ================= NEXT GROUP =================

st.subheader("Next Group")

if next_signal:

    st.markdown(f"""
    <div style='padding:20px;background:#c62828;color:white;
    border-radius:10px;text-align:center;font-size:28px'>
    NEXT GROUP → {next_signal}
    </div>
    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")

# ================= HISTORY =================

st.subheader("History")

hist_df=pd.DataFrame(history)

st.dataframe(hist_df.iloc[::-1],use_container_width=True)
