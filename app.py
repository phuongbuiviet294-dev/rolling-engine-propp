import streamlit as st
import pandas as pd
from collections import Counter

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5

WIN=2.5
LOSS=1

WINDOW_POOL=range(8,18)
TOP_WINDOWS=3

LOOKBACK=30

CONF_THRESHOLD=0.34

LOCK_ROUND=3662

st.set_page_config(layout="wide")

# ================= GROUP =================

def group(n):

    if 1<=n<=3:return 1
    if 4<=n<=6:return 2
    if 7<=n<=9:return 3
    if 10<=n<=12:return 4

# ================= LOAD =================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    nums=df["number"].dropna().astype(int)

    return nums.tolist()

numbers=load()

groups=[group(n) for n in numbers]

st.write("Total rounds:",len(groups))

# ================= WINDOW TRAIN =================

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

    return profit-dd*0.6

scores={w:window_score(groups[:LOCK_ROUND],w) for w in WINDOW_POOL}

top_windows=sorted(scores,key=scores.get,reverse=True)[:TOP_WINDOWS]

# ================= TRAIN HISTORY =================

hits=[]

for i in range(max(top_windows),LOCK_ROUND):

    w=top_windows[0]

    seq=groups[i-w:i]

    pred=Counter(seq).most_common(1)[0][0]

    hit=1 if pred==groups[i] else 0

    hits.append(hit)

# ================= LIVE ENGINE =================

profit=0
equity=[]

trades=0
wins=0

loss_streak=0
pause=0

trade_log=[]

for i in range(LOCK_ROUND,len(groups)-1):

    strengths={}
    preds={}

    for w in top_windows:

        seq=groups[i-w:i]

        pred=Counter(seq).most_common(1)[0][0]

        preds[w]=pred

        pattern=sum(hits[-40:])/40 if len(hits)>=40 else 0

        momentum=sum(hits[-LOOKBACK:])/LOOKBACK if len(hits)>=LOOKBACK else 0

        markov=0

        if len(hits)>5:

            last=hits[-1]

            trans=[hits[j+1] for j in range(len(hits)-1) if hits[j]==last]

            if trans:

                markov=sum(trans)/len(trans)

        stability=momentum

        cluster=0

        if hits[-2:]==[1,1]:

            cluster+=0.3

        if hits[-3:]==[1,0,1]:

            cluster+=0.25

        if hits[-5:].count(1)>=3:

            cluster+=0.25

        confidence=(

            0.35*pattern+
            0.25*markov+
            0.20*momentum+
            0.10*stability+
            0.10*cluster

        )

        strengths[w]=confidence

    best_window=max(strengths,key=strengths.get)

    confidence=strengths[best_window]

    pred=preds[best_window]

    actual=groups[i]

    hit=1 if pred==actual else 0

    # ===== regime =====

    momentum=sum(hits[-LOOKBACK:])/LOOKBACK if len(hits)>=LOOKBACK else 0

    regime="random"

    if momentum>=0.52:

        regime="trend"

    elif momentum>=0.40:

        regime="neutral"

    # ===== trade decision =====

    trade=False

    if pause>0:

        pause-=1

    else:

        if confidence>=CONF_THRESHOLD and regime!="random":

            trade=True

    if trade:

        trades+=1

        if hit:

            wins+=1
            profit+=WIN
            loss_streak=0

        else:

            profit-=LOSS
            loss_streak+=1

    if loss_streak>=3:

        pause=5
        loss_streak=0

    hits.append(hit)

    equity.append(profit)

    trade_log.append({

        "round":i,
        "window":best_window,
        "pred":pred,
        "actual":actual,
        "hit":hit,
        "confidence":round(confidence,3),
        "profit":profit

    })

wr=wins/trades if trades else 0

# ================= NEXT SIGNAL =================

next_pred=preds[best_window]

# ================= UI =================

st.title("⚡ V79 Quant Regime Engine")

c1,c2,c3=st.columns(3)

c1.metric("Active Window",best_window)
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))

st.metric("Live Profit",round(profit,2))

st.subheader("Next Signal")

if confidence>=CONF_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"WAIT → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_log).iloc[::-1].head(50))
