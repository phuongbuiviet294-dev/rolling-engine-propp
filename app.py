import streamlit as st
import pandas as pd
from collections import Counter, defaultdict

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN=200
LOCK=200

# ---------- GROUP ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- LOAD ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    return df["number"].dropna().astype(int).tolist()

numbers=load()
groups=[group(n) for n in numbers]


# ---------- PREDICT ----------
def predict_freq(g,window):

    if len(g)<window:
        return None,0

    c=Counter(g[-window:])

    pred=max(c,key=c.get)

    conf=c[pred]/window

    return pred,conf


# ---------- PATTERN ENGINE ----------
def build_pattern_model(g):

    model=defaultdict(Counter)

    for i in range(len(g)-3):

        pattern=(g[i],g[i+1],g[i+2])

        nxt=g[i+3]

        model[pattern][nxt]+=1

    return model


def predict_pattern(g,model):

    if len(g)<3:
        return None,0

    pattern=(g[-3],g[-2],g[-1])

    if pattern not in model:
        return None,0

    c=model[pattern]

    total=sum(c.values())

    pred=max(c,key=c.get)

    prob=c[pred]/total

    return pred,prob


# ---------- MARKOV ----------
def markov_prob(hits):

    count11=0
    count111=0

    for i in range(2,len(hits)):

        if hits[i-2]==1 and hits[i-1]==1:

            count11+=1

            if hits[i]==1:

                count111+=1

    if count11==0:
        return 0

    return count111/count11


# ---------- WINDOW SCAN ----------
def eval_window(data,w):

    profit=0

    for i in range(w,len(data)-1):

        pred,_=predict_freq(data[:i],w)

        if pred==data[i]:

            profit+=2.5

        else:

            profit-=1

    return profit


def find_window(data):

    results=[]

    for w in range(8,18):

        p=eval_window(data,w)

        results.append((w,p))

    df=pd.DataFrame(results,columns=["window","profit"])

    best=df.sort_values("profit",ascending=False).iloc[0]

    return int(best.window),df


# ---------- BACKTEST ----------

hits=[]
history=[]
records=[]

profit=0
peak=0
dd=0

trades=0
wins=0

best_window,window_table=find_window(groups[:SCAN])

lock=0

pattern_model=build_pattern_model(groups[:SCAN])


for i in range(SCAN,len(groups)-1):

    if lock>=LOCK:

        best_window,_=find_window(groups[i-SCAN:i])

        pattern_model=build_pattern_model(groups[i-SCAN:i])

        lock=0


    pred_f,conf=predict_freq(groups[:i],best_window)

    pred_p,prob_p=predict_pattern(groups[:i],pattern_model)

    pred=pred_f

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)

    prob_m=markov_prob(hits)

    signal=False

    if prob_p>0.40 and prob_m>0.5 and conf>0.30:

        signal=True


    if signal:

        trades+=1

        if pred==actual:

            profit+=2.5
            wins+=1

        else:

            profit-=1


    peak=max(peak,profit)

    dd=max(dd,peak-profit)

    history.append(profit)

    records.append({
        "round":i,
        "actual":actual,
        "pred":pred,
        "pattern_prob":prob_p,
        "markov_prob":prob_m,
        "confidence":conf,
        "signal":signal,
        "profit":profit
    })

    lock+=1


wr=wins/trades if trades else 0

hist_df=pd.DataFrame(records)


# ---------- NEXT GROUP ----------
next_pred,conf=predict_freq(groups,best_window)

pattern_model=build_pattern_model(groups)

_,prob_p=predict_pattern(groups,pattern_model)

prob_m=markov_prob(hits)

signal=False

if prob_p>0.40 and prob_m>0.5 and conf>0.30:

    signal=True


# ---------- UI ----------
st.title("⚡ V61 Pattern + Markov Engine")


c1,c2,c3=st.columns(3)

c1.metric("Best Window",best_window)

c2.metric("Trades",trades)

c3.metric("Winrate",round(wr*100,2))


c4,c5=st.columns(2)

c4.metric("Profit",profit)

c5.metric("Drawdown",dd)


# ---------- NEXT ----------
st.subheader("Next Group")

if signal:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info("SKIP")


st.write(f"Pattern Prob = {round(prob_p,3)}")

st.write(f"Markov Prob = {round(prob_m,3)}")

st.write(f"Confidence = {round(conf,3)}")


# ---------- EQUITY ----------
st.subheader("Equity Curve")

st.line_chart(history)


# ---------- WINDOW ----------
st.subheader("Window Scan")

st.dataframe(window_table)


# ---------- HISTORY ----------
st.subheader("History")

st.dataframe(hist_df.tail(50))
