import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from math import gcd
from collections import defaultdict

st.set_page_config(page_title="V9000 RNG Exploit Scanner",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# -----------------------
# LOAD DATA
# -----------------------

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower().strip() for c in df.columns]
    nums=df["number"].dropna().astype(int)
    return nums

numbers=load().values
n=len(numbers)

st.title("🧠 V9000 RNG Exploit Scanner")

st.write("Total outputs:",n)

# -----------------------
# LCG MODULUS TEST
# -----------------------

st.header("LCG Modulus Detection")

mods=[]

for i in range(n-4):

    x0=numbers[i]
    x1=numbers[i+1]
    x2=numbers[i+2]
    x3=numbers[i+3]

    t1=(x2-x1)*(x0-x1)
    t2=(x1-x0)*(x3-x2)

    val=abs(t1-t2)

    if val>0:
        mods.append(val)

if len(mods)>0:
    
    m=mods[0]
    
    for v in mods[1:50]:
        m=gcd(m,v)

    st.write("Estimated modulus candidate:",m)

    if m>1e6:
        st.warning("Possible LCG modulus found")
    else:
        st.success("No clear LCG modulus")

# -----------------------
# TRANSITION MATRIX
# -----------------------

st.header("Markov Transition Bias")

matrix=defaultdict(lambda:defaultdict(int))

for i in range(n-1):
    
    a=numbers[i]
    b=numbers[i+1]
    
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

if max_prob>0.2:
    st.warning("Transition bias detected")
else:
    st.success("No transition bias")

# -----------------------
# PREDICTOR TEST
# -----------------------

st.header("Predictor Simulation")

wins=0
bets=0

for i in range(n-1000,n-1):

    current=numbers[i]

    probs=df[df["from"]==current]

    if len(probs)==0:
        continue

    guess=probs.sort_values("prob",ascending=False).iloc[0]["to"]

    actual=numbers[i+1]

    bets+=1

    if guess==actual:
        wins+=1

if bets>0:

    winrate=wins/bets

    st.metric("Predictor winrate",round(winrate,4))

    random_rate=1/12

    st.write("Random baseline:",random_rate)

    if winrate>random_rate+0.02:
        st.error("Predictable RNG detected")
    else:
        st.success("Predictor performs like random")

# -----------------------
# EXPLOIT SCORE
# -----------------------

st.header("Exploitability Score")

score=0

if max_prob>0.2:
    score+=40

if winrate>0.1:
    score+=40

if 'm' in locals() and m>1e6:
    score+=20

st.metric("Exploit score",score)

if score<30:
    st.success("RNG likely secure")

elif score<60:
    st.warning("Weak RNG signals")

else:
    st.error("RNG may be exploitable")
