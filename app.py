import streamlit as st
import pandas as pd
from collections import Counter,defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW_RANGE=range(8,18)
SCAN_ROUNDS=200

LOOKBACK_STABILITY=26

PATTERN_MIN=2
PATTERN_MAX=4

CONF_THRESHOLD=0.55

WIN=2.5
LOSS=1

st.set_page_config(layout="wide")

# ---------------- GROUP ----------------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------------- LOAD ----------------

@st.cache_data(ttl=10)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

# ---------------- PREDICT ----------------

def predict_freq(data,window):

    if len(data)<window:
        return None

    c=Counter(data[-window:])

    return max(c,key=c.get)

# ---------------- WINDOW SCAN ----------------

def eval_window(data,window):

    profit=0
    peak=0
    dd=0

    for i in range(window,len(data)-1):

        pred=predict_freq(data[:i],window)

        actual=data[i]

        if pred==actual:
            profit+=WIN
        else:
            profit-=LOSS

        peak=max(peak,profit)
        dd=max(dd,peak-profit)

    score=profit-dd

    return profit,dd,score


def scan_windows(data):

    rows=[]

    for w in WINDOW_RANGE:

        p,dd,s=eval_window(data,w)

        rows.append([w,p,dd,s])

    df=pd.DataFrame(rows,columns=["window","profit","drawdown","score"])

    best=df.sort_values("score",ascending=False).iloc[0]

    return int(best.window),df

best_window,window_table=scan_windows(groups[:SCAN_ROUNDS])

window=best_window

# ---------------- ENGINE ----------------

hits=[]
equity=[]
profit=0

trades=0
wins=0

pattern_prob=0
markov_prob=0
hit_rate_26=0

best_pattern=None

history=[]

for i in range(SCAN_ROUNDS,len(groups)-1):

    pred=predict_freq(groups[:i],window)

    actual=groups[i]

    hit=None

    if pred!=None:

        hit=1 if pred==actual else 0
        hits.append(hit)

    # -------- pattern scan --------

    if len(hits)>50:

        counts=defaultdict(int)
        success=defaultdict(int)

        for L in range(PATTERN_MIN,PATTERN_MAX+1):

            for j in range(len(hits)-L-1):

                pat=tuple(hits[j:j+L])
                nxt=hits[j+L]

                counts[pat]+=1

                if nxt==1:
                    success[pat]+=1

        best_prob=0

        for pat in counts:

            prob=success[pat]/counts[pat]

            if prob>best_prob and counts[pat]>10:

                best_prob=prob
                best_pattern=pat

        pattern_prob=best_prob

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

    if len(hits)>=LOOKBACK_STABILITY:

        hit_rate_26=sum(hits[-LOOKBACK_STABILITY:])/LOOKBACK_STABILITY

    # -------- confidence --------

    confidence=0.5*pattern_prob+0.3*markov_prob+0.2*hit_rate_26

    trade=False

    if confidence>=CONF_THRESHOLD:

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
        "confidence":confidence,
        "profit":profit,
        "trade":trade

    })


wr=wins/trades if trades else 0

peak=max(equity) if equity else 0
dd=max(peak-x for x in equity) if equity else 0

hist_df=pd.DataFrame(history)

# ---------------- NEXT SIGNAL ----------------

next_pred=predict_freq(groups,window)

confidence=0.5*pattern_prob+0.3*markov_prob+0.2*hit_rate_26

# ---------------- UI ----------------

st.title("⚡ V67 Hybrid Edge Engine")

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
st.write("Momentum:",round(hit_rate_26,3))
st.write("Confidence:",round(confidence,3))

st.subheader("Next Group")

if confidence>=CONF_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"SKIP → Next Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Window Scan")

st.dataframe(window_table)

st.subheader("History")

st.dataframe(hist_df.tail(50))
