import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter, defaultdict
import math

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

st.set_page_config(layout="wide")

def group(n):
    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()

numbers=load()

groups=[group(n) for n in numbers]

st.title("🧠 V14 Pattern Detector")

# ---------- distribution ----------

dist=Counter(groups)

dist_df=pd.DataFrame({
    "group":dist.keys(),
    "count":dist.values()
})

dist_df["ratio"]=dist_df["count"]/len(groups)

st.subheader("Group Distribution")

st.dataframe(dist_df)

st.bar_chart(dist_df.set_index("group")["ratio"])


# ---------- Markov transition ----------

trans=defaultdict(lambda:defaultdict(int))

for i in range(len(groups)-1):

    g1=groups[i]
    g2=groups[i+1]

    trans[g1][g2]+=1

rows=[]

for g1 in trans:

    total=sum(trans[g1].values())

    for g2 in trans[g1]:

        rows.append({
            "from":g1,
            "to":g2,
            "prob":trans[g1][g2]/total
        })

trans_df=pd.DataFrame(rows)

st.subheader("Markov Transition")

st.dataframe(trans_df)


# ---------- pattern test ----------

patterns=Counter()

for i in range(len(groups)-3):

    key=(groups[i],groups[i+1],groups[i+2],groups[i+3])

    patterns[key]+=1

top_patterns=pd.DataFrame(patterns.most_common(20),
                         columns=["pattern","count"])

st.subheader("Top Patterns")

st.dataframe(top_patterns)


# ---------- entropy ----------

counts=np.array(list(dist.values()))

probs=counts/counts.sum()

entropy=-np.sum(probs*np.log2(probs))

st.subheader("Entropy")

st.metric("Entropy",round(entropy,3))

st.write("Max entropy for 4 states =",round(math.log2(4),3))


# ---------- randomness indicator ----------

if entropy>1.9:
    st.error("Dataset looks RANDOM")

elif entropy>1.7:
    st.warning("Dataset mostly random")

else:
    st.success("Dataset has structure")
