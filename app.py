import streamlit as st
import pandas as pd
import requests
import io
from collections import Counter, defaultdict

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=200
WINDOW_RANGE=range(8,18)

LOOKBACK=26

WIN=2.5
LOSS=1

CONF_THRESHOLD=0.34

# ================= PAGE =================

st.set_page_config(layout="wide")

# ================= GROUP =================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

# ================= LOAD DATA =================

@st.cache_data(ttl=5)
def load_data():

    try:

        r=requests.get(DATA_URL)

        df=pd.read_csv(io.StringIO(r.text))

        nums=df["number"].dropna().astype(int).tolist()

        return nums

    except Exception as e:

        st.error("DATA LOAD ERROR")

        return []

numbers=load_data()

if len(numbers)==0:

    st.stop()

groups=[group(n) for n in numbers]

# ================= PREDICT =================

def predict(data,window):

    seq=data[-window:]

    c=Counter(seq)

    return max(c,key=c.get)

# ================= WINDOW TRAIN =================

def train_window(data):

    best_window=None
    best_profit=-999

    for w in WINDOW_RANGE:

        profit=0

        for i in range(w,len(data)-1):

            pred=predict(data[:i],w)

            actual=data[i]

            if pred==actual:

                profit+=WIN

            else:

                profit-=LOSS

        if profit>best_profit:

            best_profit=profit
            best_window=w

    return best_window

window=train_window(groups[:TRAIN_SIZE])

# ================= LIVE ENGINE =================

hits=[]
equity=[]
profit=0

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

    confidence=0.55*pattern_prob+0.30*markov_prob+0.15*momentum

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
        "hit":hit,
        "confidence":round(confidence,3),
        "trade":trade,
        "profit":profit

    })

wr=wins/trades if trades else 0

peak=max(equity) if equity else 0
dd=max(peak-x for x in equity) if equity else 0

hist_df=pd.DataFrame(history)

# ================= NEXT SIGNAL =================

next_pred=predict(groups,window)

confidence=0.55*pattern_prob+0.30*markov_prob+0.15*momentum

# ================= UI =================

st.title("⚡ V68.1 Adaptive Live Engine")

col1,col2,col3=st.columns(3)

col1.metric("Best Window",window)
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))

col4,col5=st.columns(2)

col4.metric("Profit",round(profit,2))
col5.metric("Drawdown",round(dd,2))

st.subheader("Edge Metrics")

st.write("Pattern Prob:",round(pattern_prob,3))
st.write("Markov Prob:",round(markov_prob,3))
st.write("Momentum:",round(momentum,3))
st.write("Confidence:",round(confidence,3))

st.subheader("Next Group Signal")

if confidence>=CONF_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"SKIP → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Recent History")

st.dataframe(hist_df.tail(30),use_container_width=True)
