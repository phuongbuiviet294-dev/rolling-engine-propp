import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

# ---------- GROUP ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- LOAD DATA ----------
@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers


numbers=load()

groups=[group(n) for n in numbers]

st.title("RNG Forensics Scanner")

# ---------- BASIC INFO ----------

st.subheader("Dataset")

c1,c2=st.columns(2)

c1.metric("Total Rounds",len(groups))
c2.metric("Unique Groups",len(set(groups)))


# ---------- DISTRIBUTION ----------

counts=Counter(groups)

dist_data=pd.DataFrame({
    "group":[1,2,3,4],
    "count":[counts[1],counts[2],counts[3],counts[4]]
})

st.subheader("Group Distribution")

st.bar_chart(dist_data.set_index("group"))

# ---------- CHI-SQUARE ----------

expected=len(groups)/4

chi=sum((dist_data["count"]-expected)**2/expected)

st.subheader("Chi Square Test")

st.write("Chi-square statistic:",round(chi,4))

if chi<7.81:
    st.success("Distribution looks random")
else:
    st.warning("Possible bias detected")


# ---------- TRANSITION MATRIX ----------

matrix=np.zeros((4,4))

for i in range(len(groups)-1):

    a=groups[i]-1
    b=groups[i+1]-1

    matrix[a][b]+=1


transition=pd.DataFrame(matrix,
                        columns=["to1","to2","to3","to4"],
                        index=["from1","from2","from3","from4"])

st.subheader("Transition Matrix")

st.dataframe(transition)

st.subheader("Transition Probability")

prob=transition.div(transition.sum(axis=1),axis=0)

st.dataframe(prob.round(3))


# ---------- SERIAL CORRELATION ----------

g=np.array(groups)

corr=np.corrcoef(g[:-1],g[1:])[0,1]

st.subheader("Serial Correlation")

st.write("Lag1 correlation:",round(corr,5))


# ---------- ENTROPY ----------

pvals=np.array(list(counts.values()))/len(groups)

entropy=-(pvals*np.log2(pvals)).sum()

st.subheader("Entropy")

st.write("Entropy:",round(entropy,4))
st.write("Max entropy:",np.log2(4))


# ---------- RUN LENGTH ----------

runs=[]
current=1

for i in range(1,len(groups)):

    if groups[i]==groups[i-1]:
        current+=1
    else:
        runs.append(current)
        current=1

runs.append(current)

st.subheader("Run Statistics")

c3,c4=st.columns(2)

c3.metric("Max Run",max(runs))
c4.metric("Average Run",round(np.mean(runs),2))


# ---------- LAST DATA ----------

st.subheader("Last 20 Rounds")

recent=pd.DataFrame({
    "number":numbers[-20:],
    "group":groups[-20:]
})

st.dataframe(recent[::-1])
