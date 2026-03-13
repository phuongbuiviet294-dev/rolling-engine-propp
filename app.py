import streamlit as st
import pandas as pd
import requests
import io
import math
from collections import Counter,defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=200
WINDOW_RANGE=range(8,18)

LOOKBACK=26

WIN=2.5
LOSS=1

CONF_THRESHOLD=0.42

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

    r=requests.get(DATA_URL)

    df=pd.read_csv(io.StringIO(r.text))

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

# ---------- predict ----------

def predict(data,window):

    seq=data[-window:]

    c=Counter(seq)

    return max(c,key=c.get)

# ---------- window scan ----------

def scan_windows(data):

    rows=[]

    for w in WINDOW_RANGE:

        profit=0

        for i in range(w,len(data)-1):

            pred=predict(data[:i],w)

            actual=data[i]

            if pred==actual:
                profit+=WIN
            else:
                profit-=LOSS

        rows.append((w,profit))

    rows.sort(key=lambda x:x[1],reverse=True)

    return [r[0] for r in rows[:3]]

windows=scan_windows(groups[:TRAIN_SIZE])

# ---------- entropy ----------

def entropy(seq):

    c=Counter(seq)

    total=len(seq)

    H=0

    for v in c.values():

        p=v/total

        H-=p*math.log2(p)

    return H

# ---------- engine ----------

hits=[]
equity=[]
profit=0

trades=0
wins=0

pattern_prob=0
markov_prob=0
momentum=0
ent=0

history=[]

for i in range(TRAIN_SIZE,len(groups)-1):

    preds=[predict(groups[:i],w) for w in windows]

    pred=max(set(preds),key=preds.count)

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)

    # pattern

    if len(hits)>50:

        counts=defaultdict(int)
        success=defaultdict(int)

        for j in range(len(hits)-3):

            pat=tuple(hits[j:j+3])
            nxt=hits[j+3]

            counts[pat]+=1

            if nxt==1:
                success[pat]+=1

        best=0

        for pat in counts:

            prob=success[pat]/counts[pat]

            if prob>best:
                best=prob

        pattern_prob=best

    # markov

    if len(hits)>20:

        last=hits[-1]

        total=0
        succ=0

        for j in range(len(hits)-1):

            if hits[j]==last:

                total+=1

                if hits[j+1]==1:
                    succ+=1

        if total>0:
            markov_prob=succ/total

    # momentum

    if len(hits)>=LOOKBACK:

        momentum=sum(hits[-LOOKBACK:])/LOOKBACK

    # entropy

    if len(groups)>=50:

        ent=entropy(groups[-50:])

    entropy_filter=1 if ent<1.8 else 0

    confidence=(
        0.45*pattern_prob
        +0.30*markov_prob
        +0.15*momentum
        +0.10*entropy_filter
    )

    trade=False

    if (
        confidence>=CONF_THRESHOLD
        and pattern_prob>=0.33
        and momentum>=0.32
        and ent<1.8
    ):

        trade=True

        trades+=1

        if hit==1:

            profit+=WIN
            wins+=1

        else:

            profit-=LOSS

    equity.append(profit)

    history.append({
        "round":i,
        "pred":pred,
        "actual":actual,
        "confidence":round(confidence,3),
        "entropy":round(ent,3),
        "trade":trade,
        "profit":profit
    })

wr=wins/trades if trades else 0

# ---------- next signal ----------

preds=[predict(groups,w) for w in windows]

next_pred=max(set(preds),key=preds.count)

# ---------- UI ----------

st.title("⚡ V69 Institutional Edge Engine")

col1,col2,col3=st.columns(3)

col1.metric("Windows",windows)
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))

st.metric("Profit",round(profit,2))

st.subheader("Edge Metrics")

st.write("Pattern",round(pattern_prob,3))
st.write("Markov",round(markov_prob,3))
st.write("Momentum",round(momentum,3))
st.write("Entropy",round(ent,3))

st.subheader("Next Signal")

if confidence>=CONF_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"SKIP → Group {next_pred}")

st.subheader("Equity")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("History")

st.dataframe(pd.DataFrame(history).tail(50))
