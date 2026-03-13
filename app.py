import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

BACKTEST_ROUNDS=2000

WINDOW_POOL=range(8,21)
TOP_WINDOWS=3

AUTO_REFRESH=5

st.set_page_config(layout="wide")

# ================= GROUP =================

def get_group(n):

    if 1<=n<=3:return 1
    if 4<=n<=6:return 2
    if 7<=n<=9:return 3
    if 10<=n<=12:return 4

# ================= LOAD DATA =================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    nums=df["number"].dropna().astype(int)

    return nums.tolist()

numbers=load()

groups=[get_group(n) for n in numbers if get_group(n)]

st.write("Total rounds:",len(groups))

# ================= WINDOW SCORE =================

def window_score(data,w):

    profit=0
    peak=0
    dd=0

    for i in range(w,len(data)-1):

        seq=data[i-w:i]

        pred=Counter(seq).most_common(1)[0][0]

        if pred==data[i]:

            profit+=WIN
        else:

            profit-=LOSS

        peak=max(peak,profit)

        dd=max(dd,peak-profit)

    return profit-dd

# ================= BACKTEST =================

train_data=groups[:BACKTEST_ROUNDS]

scores={w:window_score(train_data,w) for w in WINDOW_POOL}

top_windows=sorted(scores,key=scores.get,reverse=True)[:TOP_WINDOWS]

# ================= LIVE ENGINE =================

profit=0
equity=[]

trades=0
wins=0

trade_log=[]

for i in range(BACKTEST_ROUNDS,len(groups)-1):

    vote={}

    for w in top_windows:

        seq=groups[i-w:i]

        pred=Counter(seq).most_common(1)[0][0]

        vote[pred]=vote.get(pred,0)+1

    pred=max(vote,key=vote.get)

    actual=groups[i]

    hit=1 if pred==actual else 0

    trades+=1

    if hit:

        profit+=WIN
        wins+=1
    else:

        profit-=LOSS

    equity.append(profit)

    trade_log.append({

        "round":i,
        "pred":pred,
        "actual":actual,
        "hit":hit,
        "profit":profit

    })

wr=wins/trades if trades else 0

# ================= NEXT SIGNAL =================

i=len(groups)-1

vote={}

for w in top_windows:

    seq=groups[i-w:i]

    p=Counter(seq).most_common(1)[0][0]

    vote[p]=vote.get(p,0)+1

next_pred=max(vote,key=vote.get)

# ================= UI =================

st.title("⚡ V82 Walk-Forward Engine")

c1,c2,c3=st.columns(3)

c1.metric("Active Window",top_windows[0])
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))

st.write("Top Windows:",top_windows)

st.metric("Live Profit",round(profit,2))

st.subheader("Next Signal")

st.success(f"PREDICT → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_log).iloc[::-1].head(50))
