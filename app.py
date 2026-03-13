import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="RNG Analyzer",layout="wide")

# ================= CONFIG =================

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# ================= LOAD DATA =================

@st.cache_data
def load_data():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int)

    return numbers

numbers=load_data()

st.title("🎲 RNG Dataset Analyzer")

st.write("Total rounds:",len(numbers))

# ================= GROUP =================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

groups=numbers.apply(group)

# ================= GROUP DISTRIBUTION =================

st.header("Group Distribution")

freq=groups.value_counts().sort_index()

df_freq=pd.DataFrame({
    "group":freq.index,
    "count":freq.values,
    "prob":freq.values/len(groups)
})

st.dataframe(df_freq)

fig=px.bar(df_freq,x="group",y="prob")

st.plotly_chart(fig,use_container_width=True)

# ================= ENTROPY =================

st.header("Entropy")

p=df_freq["prob"].values

entropy=-np.sum(p*np.log2(p))

st.metric("Entropy",round(entropy,4))

# ================= CHI SQUARE =================

st.header("Chi-square randomness test")

expected=len(groups)/4

chi=((freq-expected)**2/expected).sum()

st.metric("Chi-square",round(chi,4))

# ================= TRANSITION MATRIX =================

st.header("Transition Matrix")

matrix=np.zeros((4,4))

g=groups.tolist()

for i in range(1,len(g)):

    a=g[i-1]-1
    b=g[i]-1

    matrix[a][b]+=1

df_matrix=pd.DataFrame(matrix,
columns=["1","2","3","4"],
index=["1","2","3","4"])

st.dataframe(df_matrix)

fig2=px.imshow(matrix,
labels=dict(x="Next",y="Current",color="Count"))

st.plotly_chart(fig2,use_container_width=True)

# ================= REPEAT PROBABILITY =================

st.header("Repeat Probability")

repeat=0

for i in range(1,len(g)):

    if g[i]==g[i-1]:

        repeat+=1

repeat_prob=repeat/(len(g)-1)

st.metric("P(same group again)",round(repeat_prob,4))

# ================= NEXT SIGNAL =================

st.header("Next Signal")

WINDOW=9

next_group=g[-WINDOW]

st.metric("Next group signal",next_group)

# ================= RUN STATS =================

st.header("Run statistics")

runs=[]

current=1

for i in range(1,len(g)):

    if g[i]==g[i-1]:

        current+=1

    else:

        runs.append(current)

        current=1

runs.append(current)

st.metric("Average streak",round(np.mean(runs),2))

fig3=px.histogram(runs,nbins=10)

st.plotly_chart(fig3,use_container_width=True)

st.success("Analysis complete")
