import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import math

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=2000
RETRAIN=200

WIN=2.5
LOSS=1

WINDOW_RANGE=range(6,19)

LOOKBACK=26
CLUSTER=10

# ---------------- group ----------------

def get_group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4

# ---------------- entropy ----------------

def entropy(seq):

    c=Counter(seq)
    total=len(seq)

    e=0
    for v in c.values():
        p=v/total
        e-=p*math.log(p)

    return e

# ---------------- load ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[get_group(n) for n in numbers]

# ---------------- train window ----------------

def train_window(data):

    best=None
    best_profit=-999

    for w in WINDOW_RANGE:

        p=0

        for i in range(w,len(data)):

            pred=data[i-w]
            actual=data[i]

            p += WIN if pred==actual else -LOSS

        if p>best_profit:
            best_profit=p
            best=w

    return best

# ---------------- training ----------------

window=train_window(groups[:TRAIN_SIZE])

profit=0
hits=[]
equity=[]
history=[]

pending_signal=None

last_retrain=TRAIN_SIZE

# ---------------- engine ----------------

for i in range(TRAIN_SIZE,len(groups)):

    g=groups[i]

    predicted=None
    hit=None

    # ----- execute trade -----

    if pending_signal is not None:

        predicted=pending_signal
        hit=1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        hits.append(hit)

        pending_signal=None

    # ----- pattern detection -----

    if i>=window+3:

        h1 = 1 if groups[i-1]==groups[i-1-window] else 0
        h2 = 1 if groups[i-2]==groups[i-2-window] else 0
        h3 = 1 if groups[i-3]==groups[i-3-window] else 0

        pattern=False

        if h1==1 and h2==1:
            pattern=True

        if h1==0 and h2==0 and h3==0:
            pattern=True

        if pattern:

            # hit rate

            rec=[]

            for j in range(max(window,i-LOOKBACK),i):

                if j>=window:
                    rec.append(1 if groups[j]==groups[j-window] else 0)

            hit_rate=np.mean(rec) if rec else 0

            # cluster

            cluster_hits=hits[-CLUSTER:].count(1)
            cluster_rate=cluster_hits/CLUSTER

            # entropy

            seq=groups[i-20:i]
            ent=entropy(seq) if len(seq)>5 else 0

            entropy_score=1-ent/1.4

            # score

            score=(
                0.5*hit_rate+
                0.3*cluster_rate+
                0.2*entropy_score
            )

            if score>=0.52:

                pending_signal=groups[i-window]

    # ----- retrain -----

    if i-last_retrain>=RETRAIN:

        window=train_window(groups[:i])
        last_retrain=i

    equity.append(profit)

    history.append({
        "round":i+1,
        "number":numbers[i],
        "group":g,
        "pred":predicted,
        "hit":hit,
        "window":window,
        "profit":profit
    })

# ---------------- stats ----------------

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0

# ---------------- UI ----------------

st.title("🚀 V105 PROFESSIONAL BACKTEST ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))
c4.metric("Active Window",window)

st.caption("Train=2000 | Retrain every 200 rounds")

st.subheader("Equity Curve")
st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Next Signal")

if pending_signal:
    st.success(f"TRADE NEXT → Group {pending_signal}")
else:
    st.info("WAIT SIGNAL")

st.subheader("History")

hist_df=pd.DataFrame(history)
st.dataframe(hist_df.iloc[::-1],use_container_width=True)
