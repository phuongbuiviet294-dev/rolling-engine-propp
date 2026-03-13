import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from collections import defaultdict

st.set_page_config(page_title="V6000 AI Betting Lab",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# ----------------
# LOAD DATA
# ----------------

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower().strip() for c in df.columns]
    nums=df["number"].dropna().astype(int)
    return nums

numbers=load()
n=len(numbers)

st.title("🧠 V6000 AI Betting Lab")

st.write("Total rounds:",n)

# ----------------
# PARAMETERS
# ----------------

lookback=st.slider("Lookback window",3,15,5)

threshold=st.slider("Confidence threshold",0.08,0.30,0.15)

payout=11

# ----------------
# TRAIN MODEL
# ----------------

model=defaultdict(lambda:defaultdict(int))

for i in range(lookback,n-1):

    seq=tuple(numbers[i-lookback:i])
    nxt=numbers[i]

    model[seq][nxt]+=1

# convert to probability

model_prob={}

for seq,counts in model.items():

    total=sum(counts.values())

    probs={k:v/total for k,v in counts.items()}

    model_prob[seq]=probs

# ----------------
# PREDICTION
# ----------------

predictions=[]
confidences=[]
actuals=[]
bets=[]

for i in range(lookback,n-1):

    seq=tuple(numbers[i-lookback:i])
    actual=numbers[i]

    if seq in model_prob:

        probs=model_prob[seq]

        pred=max(probs,key=probs.get)

        conf=probs[pred]

    else:

        pred=np.random.choice(numbers.unique())
        conf=0

    predictions.append(pred)
    confidences.append(conf)
    actuals.append(actual)

    if conf>threshold:
        bets.append(pred)
    else:
        bets.append(None)

# ----------------
# SIMULATE BETTING
# ----------------

profit=0
equity=[0]
bet_count=0
wins=0

for bet,actual in zip(bets,actuals):

    if bet is None:
        equity.append(profit)
        continue

    bet_count+=1

    if bet==actual:

        profit+=payout
        wins+=1

    else:

        profit-=1

    equity.append(profit)

# ----------------
# RESULTS
# ----------------

st.header("AI Betting Result")

st.metric("Total bets",bet_count)

if bet_count>0:

    win_rate=wins/bet_count

    st.metric("Win rate",round(win_rate,3))

st.metric("Final profit",profit)

# ----------------
# EQUITY CURVE
# ----------------

eq_df=pd.DataFrame({

    "round":range(len(equity)),
    "profit":equity

})

fig=px.line(eq_df,x="round",y="profit")

st.plotly_chart(fig,use_container_width=True)

# ----------------
# CONFIDENCE DISTRIBUTION
# ----------------

conf_df=pd.DataFrame({

    "confidence":confidences

})

fig2=px.histogram(conf_df,x="confidence",nbins=30)

st.plotly_chart(fig2,use_container_width=True)

# ----------------
# RANDOM BENCHMARK
# ----------------

st.header("Random Betting Benchmark")

rand_profit=0
rand_eq=[0]

for actual in actuals:

    bet=np.random.choice(numbers.unique())

    if bet==actual:

        rand_profit+=payout

    else:

        rand_profit-=1

    rand_eq.append(rand_profit)

rand_df=pd.DataFrame({

    "round":range(len(rand_eq)),
    "profit":rand_eq

})

fig3=px.line(rand_df,x="round",y="profit")

st.plotly_chart(fig3,use_container_width=True)

st.metric("Random profit",rand_profit)
