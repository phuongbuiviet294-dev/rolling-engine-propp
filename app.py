import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=2000
RETRAIN_INTERVAL=200

WINDOW_RANGE=range(6,19)

WIN=2.5
LOSS=1

st.set_page_config(layout="wide")

# ================= GROUP =================

def get_group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ================= LOAD =================

@st.cache_data(ttl=5)
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[get_group(n) for n in numbers]

# ================= TRAIN WINDOW =================

def train_window(data):

    best_w=None
    best_profit=-999

    for w in WINDOW_RANGE:

        profit=0

        for i in range(w,len(data)):

            pred=data[i-w]
            actual=data[i]

            if pred==actual:
                profit+=WIN
            else:
                profit-=LOSS

        if profit>best_profit:
            best_profit=profit
            best_w=w

    return best_w

# ================= TRAIN =================

train_groups=groups[:TRAIN_SIZE]
window=train_window(train_groups)

# ================= ENGINE =================

profit=0
hits=[]
equity=[]
history=[]

state="SCAN"
signal=None

last_retrain=TRAIN_SIZE

for i in range(TRAIN_SIZE,len(groups)):

    g=groups[i]

    predicted=None
    hit=None

    # ===== EXECUTE TRADE =====

    if state=="TRADE":

        predicted=signal

        hit = 1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        hits.append(hit)

        state="SCAN"
        signal=None

    # ===== PATTERN DETECTION =====

    if state=="SCAN" and i>=window+3:

        h1 = 1 if groups[i-1]==groups[i-1-window] else 0
        h2 = 1 if groups[i-2]==groups[i-2-window] else 0
        h3 = 1 if groups[i-3]==groups[i-3-window] else 0

        # 1-1 continuation
        if h1==1 and h2==1:

            signal=groups[i-window]
            state="TRADE"

        # 0-0-0 rebound
        elif h1==0 and h2==0 and h3==0:

            signal=groups[i-window]
            state="TRADE"

    # ===== RETRAIN WINDOW =====

    if i-last_retrain>=RETRAIN_INTERVAL:

        window=train_window(groups[:i])
        last_retrain=i

    equity.append(profit)

    history.append({

        "round":i+1,
        "number":numbers[i],
        "group":g,
        "signal":signal,
        "hit":hit,
        "state":state,
        "window":window,
        "profit":profit

    })

# ================= METRICS =================

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

# ================= UI =================

st.title("⚡ V101.1 CORE SIGNAL ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))
c4.metric("Active Window",window)

st.caption(f"Train=2000 | Retrain every {RETRAIN_INTERVAL} rounds")

# ================= EQUITY =================

st.subheader("Equity Curve")
st.line_chart(pd.DataFrame({"equity":equity}))

# ================= NEXT SIGNAL =================

st.subheader("Next Signal")

if signal:
    st.success(f"TRADE → Group {signal}")
else:
    st.info("WAITING SIGNAL")

# ================= HISTORY =================

st.subheader("History")

hist_df=pd.DataFrame(history)

st.dataframe(hist_df.iloc[::-1],use_container_width=True)
