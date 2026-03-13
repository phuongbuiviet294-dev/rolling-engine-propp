import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE = 2000
WINDOW_RANGE = range(6,19)
MAX_STREAK = 10

WIN = 2.5
LOSS = 1

TOP_K = 5
MIN_TRADES = 30


def get_group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]
    return df["number"].dropna().astype(int).tolist()


numbers = load()
groups = [get_group(n) for n in numbers]

st.title("🚀 V420 Ensemble Edge Engine")

# =====================
# TRAIN PHASE
# =====================

train = groups[:TRAIN_SIZE]

patterns = []

for window in WINDOW_RANGE:

    hits = []

    for i in range(window,len(train)):
        hit = 1 if train[i]==train[i-window] else 0
        hits.append(hit)

    streak=0

    for i in range(len(hits)-1):

        if hits[i]==0:
            streak+=1
        else:
            streak=0

        if streak>0 and streak<=MAX_STREAK:

            next_hit=hits[i+1]

            patterns.append({
                "window":window,
                "streak":streak,
                "hit":next_hit
            })

df=pd.DataFrame(patterns)

summary=[]

for (window,streak),g in df.groupby(["window","streak"]):

    trades=len(g)

    if trades<MIN_TRADES:
        continue

    winrate=g["hit"].mean()

    ev=winrate*WIN-(1-winrate)*LOSS

    summary.append({
        "window":window,
        "streak":streak,
        "trades":trades,
        "winrate":winrate,
        "EV":ev
    })

summary_df=pd.DataFrame(summary)

summary_df=summary_df.sort_values("EV",ascending=False)

top_patterns=summary_df.head(TOP_K)

st.subheader("Top Patterns (Train)")
st.dataframe(top_patterns)

# =====================
# FORWARD TEST
# =====================

equity=0
curve=[]

streaks={w:0 for w in WINDOW_RANGE}

trades=0
wins=0
losses=0

for i in range(TRAIN_SIZE,len(groups)):

    trade=False

    for window in WINDOW_RANGE:

        if groups[i]!=groups[i-window]:
            streaks[window]+=1
        else:
            streaks[window]=0

        for _,row in top_patterns.iterrows():

            if window==row.window and streaks[window]>=row.streak:
                trade=True

    if trade:

        trades+=1

        if groups[i]==groups[i-int(row.window)]:
            equity+=WIN
            wins+=1
        else:
            equity-=LOSS
            losses+=1

        for w in streaks:
            streaks[w]=0

    curve.append(equity)


winrate=wins/trades if trades>0 else 0
pf=(wins*WIN)/(losses*LOSS) if losses>0 else 0

st.metric("Forward Profit",round(equity,2))
st.metric("Trades",trades)
st.metric("Winrate",round(winrate*100,2))
st.metric("Profit Factor",round(pf,2))

st.line_chart(curve)
