import streamlit as st
import pandas as pd
import requests
import io
from collections import Counter, defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=2000
WINDOW_RANGE=range(8,18)
LOOKBACK=26
RECALIBRATE=200

WIN=2.5
LOSS=1

SIGNAL_THRESHOLD=0.40

st.set_page_config(layout="wide")

# ---------- group mapping ----------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- safe predict ----------

def predict(data,window):

    if not data:
        return 1

    window=min(window,len(data))

    seq=data[-window:]

    c=Counter(seq)

    return max(c,key=c.get)


# ---------- load data ----------

@st.cache_data(ttl=5)
def load():

    r=requests.get(DATA_URL)

    df=pd.read_csv(io.StringIO(r.text))

    nums=df.iloc[:,0].dropna().astype(int)

    return nums.tolist()


numbers=load()

groups=[group(n) for n in numbers]


# ---------- window scan ----------

def scan_windows(data):

    best=None
    best_score=-9999

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

        if score>best_score:

            best_score=score
            best=w

    return best


# ---------- TRAIN ----------

best_window=scan_windows(groups[:TRAIN_SIZE])


# ---------- LIVE ENGINE ----------

hits=[]
equity=[]
profit=0

trades=0
wins=0

pattern_prob=0
markov_prob=0
momentum=0
stability=0

trade_history=[]


for i in range(TRAIN_SIZE,len(groups)-1):


    # recalibrate window

    if (i-TRAIN_SIZE)%RECALIBRATE==0 and i>TRAIN_SIZE:

        best_window=scan_windows(groups[i-400:i])


    pred=predict(groups[:i],best_window)

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)


    # ---------- pattern ----------

    if len(hits)>40:

        counts=defaultdict(int)
        succ=defaultdict(int)

        for j in range(len(hits)-3):

            pat=tuple(hits[j:j+3])

            nxt=hits[j+3]

            counts[pat]+=1

            if nxt==1:
                succ[pat]+=1

        best=0

        for pat in counts:

            prob=succ[pat]/counts[pat]

            best=max(best,prob)

        pattern_prob=best


    # ---------- markov ----------

    if len(hits)>10:

        last=hits[-1]

        total=0
        s=0

        for j in range(len(hits)-1):

            if hits[j]==last:

                total+=1

                if hits[j+1]==1:
                    s+=1

        if total>0:
            markov_prob=s/total


    # ---------- momentum ----------

    if len(hits)>=LOOKBACK:

        momentum=sum(hits[-LOOKBACK:])/LOOKBACK

        stability=momentum


    # ---------- signal detect ----------

    signal=False

    if len(hits)>=2 and hits[-2:]==[1,1]:
        signal=True

    if len(hits)>=3 and hits[-3:]==[1,0,1]:
        signal=True

    if len(hits)>=5 and hits[-5:].count(1)>=3:
        signal=True

    if momentum>0.35:
        signal=True


    # ---------- strength ----------

    strength=(
        0.35*pattern_prob+
        0.25*markov_prob+
        0.20*momentum+
        0.20*stability
    )


    trade=False


    if signal and strength>=SIGNAL_THRESHOLD:

        trade=True

        trades+=1

        if hit==1:

            wins+=1
            profit+=WIN

        else:

            profit-=LOSS


    equity.append(profit)


    trade_history.append({

        "round":i,
        "pred":pred,
        "actual":actual,
        "hit":hit,
        "strength":round(strength,3),
        "trade":trade,
        "profit":profit

    })


wr=wins/trades if trades else 0

next_pred=predict(groups,best_window)


# ---------- UI ----------

st.title("⚡ V72.2 Stable Signal Engine")


col1,col2,col3=st.columns(3)

col1.metric("Best Window",best_window)
col2.metric("Trades",trades)
col3.metric("Winrate %",round(wr*100,2))


st.metric("Live Profit",round(profit,2))


st.subheader("Edge Metrics")

st.write("Pattern",round(pattern_prob,3))
st.write("Markov",round(markov_prob,3))
st.write("Momentum",round(momentum,3))
st.write("Stability",round(stability,3))
st.write("Strength",round(strength,3))


st.subheader("Next Signal")

if strength>=SIGNAL_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"WAIT → Group {next_pred}")


st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))


st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_history).iloc[::-1].head(50))
