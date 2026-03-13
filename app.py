import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=0.5
LOSS=-3

st.set_page_config(layout="wide")

# ---------------- GROUP ----------------

def group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# ---------------- LOAD ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()

groups=[group(n) for n in numbers]

st.title("Advanced Dataset Analyzer")


# ---------------- DISTRIBUTION ----------------

st.subheader("Group Distribution")

dist=pd.Series(groups).value_counts().sort_index()

st.write(dist)

st.bar_chart(dist)


# ---------------- TRANSITION MATRIX ----------------

st.subheader("Transition Probability")

matrix=np.zeros((4,4))

for i in range(1,len(groups)):

    matrix[groups[i-1]-1][groups[i]-1]+=1

matrix=matrix/matrix.sum(axis=1,keepdims=True)

st.write(pd.DataFrame(matrix,
columns=["to1","to2","to3","to4"],
index=["from1","from2","from3","from4"]))


# ---------------- STREAK ANALYSIS ----------------

st.subheader("Streak Distribution")

streaks=[]

current=1

for i in range(1,len(groups)):

    if groups[i]==groups[i-1]:

        current+=1

    else:

        streaks.append(current)

        current=1

streaks.append(current)

streak_df=pd.Series(streaks)

st.write(streak_df.describe())

st.bar_chart(streak_df.value_counts().sort_index())


# ---------------- PATTERN SCAN ----------------

st.subheader("Pattern Scan")

patterns={}

for i in range(2,len(groups)):

    key=f"{groups[i-2]}{groups[i-1]}"

    nextg=groups[i]

    if key not in patterns:

        patterns[key]=[]

    patterns[key].append(nextg)

pattern_result={}

for k,v in patterns.items():

    counts=Counter(v)

    total=len(v)

    best=max(counts.values())/total

    pattern_result[k]=best

pattern_df=pd.DataFrame.from_dict(pattern_result,orient="index",columns=["max_prob"])

st.write(pattern_df.sort_values("max_prob",ascending=False).head(20))


# ---------------- WINDOW SCAN ----------------

st.subheader("Window Scan")

results=[]

for w in range(2,50):

    profit=0
    trades=0

    for i in range(w,len(groups)):

        g1=groups[i-w]

        if groups[i-1]!=g1:

            trades+=1

            if groups[i]==g1:

                profit+=WIN

            else:

                profit+=LOSS

    results.append((w,profit,trades))


window_df=pd.DataFrame(results,columns=["window","profit","trades"])

st.write(window_df.sort_values("profit",ascending=False).head(10))


# ---------------- STREAK STRATEGY ----------------

st.subheader("Strategy: Streak >=4")

profit=0

hits=0

trades=0

equity=[]

for i in range(4,len(groups)):

    last4=groups[i-4:i]

    if len(set(last4))==1:

        trades+=1

        if groups[i]!=last4[0]:

            profit+=WIN
            hits+=1

        else:

            profit+=LOSS

    equity.append(profit)

wr=hits/trades if trades else 0

st.write("Trades:",trades)

st.write("Winrate:",wr)

st.write("Profit:",profit)

st.line_chart(pd.DataFrame({"equity":equity}))


# ---------------- DAILY OPPORTUNITY ----------------

st.subheader("Daily Opportunities")

rounds_per_day=288

prob_streak4=(1/4)**3

expected=rounds_per_day*prob_streak4

st.write("Expected trades/day:",expected)


# ---------------- LONGEST STREAK ----------------

st.subheader("Longest Streak")

st.write(max(streaks))
