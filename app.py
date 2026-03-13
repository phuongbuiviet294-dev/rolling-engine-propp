import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict
import plotly.express as px
from math import gcd

st.title("🧠 V20000 RNG Hacker Toolkit")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# -----------------------
# LOAD DATA
# -----------------------

@st.cache_data
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower().strip() for c in df.columns]

    return df["number"].dropna().astype(int).values

data=load()

n=len(data)

st.write("Total rounds:",n)

# -----------------------
# LCG TEST
# -----------------------

st.subheader("LCG Crack Test")

vals=[]

for i in range(n-3):

    x0=data[i]
    x1=data[i+1]
    x2=data[i+2]

    t=abs((x2-x1)-(x1-x0))

    if t>0:
        vals.append(t)

if len(vals)>10:

    g=vals[0]

    for v in vals[1:50]:

        g=gcd(g,v)

    st.write("Estimated modulus candidate:",g)

else:

    st.write("Not enough data")

# -----------------------
# TRANSITION MATRIX
# -----------------------

st.subheader("Transition Matrix")

matrix=defaultdict(lambda:defaultdict(int))

for i in range(n-1):

    a=data[i]
    b=data[i+1]

    matrix[a][b]+=1

rows=[]

for a in matrix:

    total=sum(matrix[a].values())

    for b in matrix[a]:

        rows.append({
            "from":a,
            "to":b,
            "prob":matrix[a][b]/total
        })

df=pd.DataFrame(rows)

fig=px.scatter(df,x="from",y="to",size="prob",color="prob")

st.plotly_chart(fig,use_container_width=True)

max_prob=df["prob"].max()

st.write("Max transition probability:",max_prob)

# -----------------------
# PATTERN PREDICTOR
# -----------------------

st.subheader("Pattern Predictor")

lookback=5

wins=0
bets=0
profit=0

for i in range(lookback,n-1):

    window=tuple(data[i-lookback:i])

    next_vals=[]

    for j in range(lookback,n-1):

        if tuple(data[j-lookback:j])==window:

            next_vals.append(data[j])

    if len(next_vals)>3:

        pred=max(set(next_vals),key=next_vals.count)

        bets+=1

        if data[i]==pred:

            wins+=1
            profit+=11

        else:

            profit-=1

st.write("Bets:",bets)
st.write("Wins:",wins)
st.write("Profit:",profit)

# -----------------------
# RANDOM BASELINE
# -----------------------

baseline=1/12

st.write("Random baseline:",baseline)

if bets>0:

    wr=wins/bets

    st.write("Predictor winrate:",wr)

# -----------------------
# MONTE CARLO STRATEGY SEARCH
# -----------------------

st.subheader("Monte Carlo Strategy Scan")

best_profit=0

for _ in range(200):

    look=np.random.randint(3,10)

    wins=0
    bets=0
    profit=0

    for i in range(look,n-1):

        if np.random.random()<0.1:

            guess=np.random.randint(1,13)

            bets+=1

            if data[i]==guess:

                profit+=11
                wins+=1

            else:

                profit-=1

    if profit>best_profit:

        best_profit=profit

st.write("Best random strategy profit:",best_profit)
