import streamlit as st
import pandas as pd
import requests
import io
from collections import Counter, defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_ROUNDS=2000
WINDOW_RANGE=range(8,19)

WIN=2.5
LOSS=1

SIGNAL_THRESHOLD=0.45
LOOKBACK=26

st.set_page_config(layout="wide")

# -------- group --------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# -------- predict --------

def predict(data,w):

    if len(data)<w:
        return None

    seq=data[-w:]

    c=Counter(seq)

    return max(c,key=c.get)


# -------- load --------

@st.cache_data(ttl=5)
def load():

    r=requests.get(DATA_URL)

    df=pd.read_csv(io.StringIO(r.text))

    nums=df["Number"].dropna().astype(int)

    return nums.tolist()


numbers=load()

groups=[group(n) for n in numbers]

st.write("Total rounds:",len(groups))

# -------- window training --------

def train_windows(data):

    scores={}

    for w in WINDOW_RANGE:

        profit=0
        peak=0
        dd=0

        for i in range(w,len(data)-1):

            pred=predict(data[:i],w)

            actual=data[i]

            if pred==actual:
                profit+=WIN
            else:
                profit-=LOSS

            peak=max(peak,profit)
            dd=max(dd,peak-profit)

        score=profit-dd*0.5

        scores[w]=score

    best=sorted(scores,key=scores.get,reverse=True)[:5]

    return best


best_windows=train_windows(groups[:TRAIN_ROUNDS])

# -------- live simulation --------

profit=0
equity=[]

hits=[]
trades=0
wins=0

trade_history=[]

for i in range(TRAIN_ROUNDS,len(groups)-1):

    strengths={}
    preds={}

    for w in best_windows:

        pred=predict(groups[:i],w)

        if pred is None:
            continue

        preds[w]=pred

        # pattern
        pattern=0
        if len(hits)>50:

            counts=defaultdict(int)
            winp=defaultdict(int)

            for j in range(len(hits)-3):

                p=tuple(hits[j:j+3])
                nxt=hits[j+3]

                counts[p]+=1

                if nxt==1:
                    winp[p]+=1

            for p in counts:

                prob=winp[p]/counts[p]

                pattern=max(pattern,prob)

        # markov
        markov=0
        if len(hits)>5:

            last=hits[-1]

            total=0
            win=0

            for j in range(len(hits)-1):

                if hits[j]==last:

                    total+=1

                    if hits[j+1]==1:
                        win+=1

            if total>0:
                markov=win/total

        # momentum
        momentum=0
        if len(hits)>=LOOKBACK:

            momentum=sum(hits[-LOOKBACK:])/LOOKBACK

        stability=momentum

        cluster=0

        if len(hits)>=2 and hits[-2:]==[1,1]:
            cluster+=0.3

        if len(hits)>=3 and hits[-3:]==[1,0,1]:
            cluster+=0.25

        if len(hits)>=5 and hits[-5:].count(1)>=3:
            cluster+=0.25

        strength=(
            0.30*pattern+
            0.20*markov+
            0.25*momentum+
            0.15*stability+
            0.10*cluster
        )

        strengths[w]=strength

    if not strengths:
        continue

    best_window=max(strengths,key=strengths.get)

    strength=strengths[best_window]

    pred=preds[best_window]

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)

    if strength>=SIGNAL_THRESHOLD:

        trades+=1

        if hit:

            wins+=1
            profit+=WIN

        else:

            profit-=LOSS

    equity.append(profit)

    trade_history.append({
        "round":i,
        "window":best_window,
        "pred":pred,
        "actual":actual,
        "hit":hit,
        "strength":round(strength,3),
        "profit":profit
    })


wr=wins/trades if trades else 0

# -------- next prediction --------

next_preds={}
next_strength={}

for w in best_windows:

    pred=predict(groups,w)

    if pred is None:
        continue

    next_preds[w]=pred
    next_strength[w]=0.5

best_window=max(next_strength,key=next_strength.get)

next_pred=next_preds[best_window]

# -------- UI --------

st.title("⚡ V76 Adaptive Engine")

col1,col2,col3=st.columns(3)

col1.metric("Best Window",best_window)
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))

st.metric("Live Profit",round(profit,2))

st.subheader("Next Signal")

if next_strength[best_window]>=SIGNAL_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"WAIT → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_history).iloc[::-1].head(50))
