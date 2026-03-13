import streamlit as st
import pandas as pd
from collections import Counter,defaultdict

DATA_URL="YOUR_GOOGLE_SHEET"

TRAIN_SIZE=200
WINDOW_RANGE=range(8,18)

LOOKBACK=26

WIN=2.5
LOSS=1

CONF_THRESHOLD=0.34

# ---------------- GROUP ----------------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ---------------- LOAD ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

# ---------------- PREDICT ----------------

def predict(data,window):

    seq=data[-window:]

    c=Counter(seq)

    return max(c,key=c.get)

# ---------------- WINDOW TRAIN ----------------

def eval_window(data,window):

    profit=0

    for i in range(window,len(data)-1):

        pred=predict(data[:i],window)

        actual=data[i]

        if pred==actual:
            profit+=WIN
        else:
            profit-=LOSS

    return profit

best_window=None
best_profit=-999

for w in WINDOW_RANGE:

    p=eval_window(groups[:TRAIN_SIZE],w)

    if p>best_profit:

        best_profit=p
        best_window=w

window=best_window

# ---------------- LIVE ENGINE ----------------

hits=[]
profit=0
equity=[]

trades=0
wins=0

pattern_prob=0
markov_prob=0
momentum=0

history=[]

for i in range(TRAIN_SIZE,len(groups)-1):

    pred=predict(groups[:i],window)

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)

    # -------- pattern --------

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

    # -------- markov --------

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

    # -------- momentum --------

    if len(hits)>=LOOKBACK:

        momentum=sum(hits[-LOOKBACK:])/LOOKBACK

    confidence=0.55*pattern_prob+0.3*markov_prob+0.15*momentum

    trade=False

    if confidence>=CONF_THRESHOLD and pattern_prob>=0.30:

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
        "confidence":confidence,
        "trade":trade,
        "profit":profit
    })

wr=wins/trades if trades else 0

# ---------------- NEXT SIGNAL ----------------

next_pred=predict(groups,window)

confidence=0.55*pattern_prob+0.3*markov_prob+0.15*momentum

# ---------------- UI ----------------

st.title("⚡ V68 Adaptive Live Engine")

st.metric("Best Window",window)

col1,col2,col3=st.columns(3)

col1.metric("Trades",trades)
col2.metric("Winrate %",round(wr*100,2))
col3.metric("Profit",round(profit,2))

st.subheader("Edge Metrics")

st.write("Pattern",round(pattern_prob,3))
st.write("Markov",round(markov_prob,3))
st.write("Momentum",round(momentum,3))
st.write("Confidence",round(confidence,3))

st.subheader("Next Group")

if confidence>=CONF_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"SKIP → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("History")

st.dataframe(pd.DataFrame(history).tail(50))
