import streamlit as st
import pandas as pd
from collections import Counter,defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------- group ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------- load ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

ROUNDS=len(groups)

# ---------- window predictor ----------
def window_pred(g,window):

    if len(g)<window:
        return None

    c=Counter(g[-window:])

    return max(c,key=c.get)

# ---------- markov predictor ----------
def markov_pred(g):

    if len(g)<2:
        return None

    trans=defaultdict(list)

    for i in range(len(g)-1):

        trans[g[i]].append(g[i+1])

    last=g[-1]

    if last not in trans:
        return None

    c=Counter(trans[last])

    return max(c,key=c.get)

# ---------- pattern predictor ----------
def pattern_pred(g):

    if len(g)<4:
        return None

    pattern=tuple(g[-3:])

    matches=[]

    for i in range(len(g)-3):

        if tuple(g[i:i+3])==pattern:

            matches.append(g[i+3])

    if not matches:
        return None

    c=Counter(matches)

    return max(c,key=c.get)

# ---------- frequency predictor ----------
def freq_pred(g):

    if len(g)<50:
        return None

    c=Counter(g[-50:])

    return max(c,key=c.get)

# ---------- voting ----------
def vote(preds):

    preds=[p for p in preds if p]

    if len(preds)==0:
        return None,0

    c=Counter(preds)

    group=c.most_common(1)[0][0]

    votes=c.most_common(1)[0][1]

    return group,votes

# ---------- backtest ----------
profit=0
peak=0
dd=0

trades=0
wins=0

history=[]

for i in range(60,ROUNDS-1):

    g=groups[:i]

    p1=window_pred(g,12)
    p2=markov_pred(g)
    p3=pattern_pred(g)
    p4=freq_pred(g)

    preds=[p1,p2,p3,p4]

    pred,votes=vote(preds)

    trade=False

    if votes>=3:

        trade=True

    actual=groups[i]

    hit=1 if pred==actual else 0

    if trade:

        trades+=1

        if hit:

            profit+=2.5
            wins+=1

        else:

            profit-=1

    peak=max(peak,profit)

    dd=max(dd,peak-profit)

    history.append({

        "round":i,
        "pred":pred,
        "actual":actual,
        "votes":votes,
        "hit":hit,
        "trade":trade,
        "profit":profit
    })

wr=wins/trades if trades else 0

hist_df=pd.DataFrame(history)

# ---------- live ----------
live_preds=[
window_pred(groups,12),
markov_pred(groups),
pattern_pred(groups),
freq_pred(groups)
]

live_pred,votes=vote(live_preds)

# ---------- UI ----------
st.title("🤖 V52 Hybrid AI Engine")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",ROUNDS)
c2.metric("Trades",trades)
c3.metric("Winrate",round(wr*100,2))

c4,c5=st.columns(2)

c4.metric("Profit",profit)
c5.metric("Drawdown",dd)

st.subheader("Next Group")

if live_pred and votes>=3:

    st.success(f"TRADE → Group {live_pred} (votes {votes})")

else:

    st.info("SKIP")

st.subheader("Equity Curve")

st.line_chart(hist_df["profit"])

st.subheader("Trade History")

st.dataframe(hist_df.tail(100))
