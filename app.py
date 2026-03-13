import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="RNG V3000 Analyzer",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# ================= LOAD DATA =================

@st.cache_data
def load_data():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int)

    return numbers

numbers=load_data()

st.title("🎲 RNG V3000 Regime Detector")

st.write("Total rounds:",len(numbers))

# ================= GROUP =================

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4

groups=numbers.apply(group)

g=groups.tolist()

# ================= GLOBAL DISTRIBUTION =================

st.header("Global Distribution")

freq=groups.value_counts().sort_index()

df_freq=pd.DataFrame({
    "group":freq.index,
    "count":freq.values,
    "prob":freq.values/len(groups)
})

st.dataframe(df_freq)

fig=px.bar(df_freq,x="group",y="prob")

st.plotly_chart(fig,use_container_width=True)

# ================= BLOCK ANALYSIS =================

st.header("Regime Detection")

block_sizes=[100,200,300,500]

results=[]

for block in block_sizes:

    for i in range(0,len(g)-block,block):

        segment=g[i:i+block]

        counts=pd.Series(segment).value_counts()

        probs=counts/block

        max_prob=probs.max()

        bias_group=probs.idxmax()

        entropy=-np.sum(probs*np.log2(probs))

        results.append({

            "start":i,
            "block":block,
            "bias_group":bias_group,
            "max_prob":max_prob,
            "entropy":entropy
        })

df_regime=pd.DataFrame(results)

st.dataframe(df_regime.sort_values("max_prob",ascending=False).head(20))

# ================= REGIME CHART =================

st.header("Bias over time")

fig2=px.line(df_regime,x="start",y="max_prob",color="block")

st.plotly_chart(fig2,use_container_width=True)

# ================= TRADE SIGNAL =================

st.header("Trade Signal")

recent=df_regime[df_regime["start"]>len(g)-500]

best=recent.sort_values("max_prob",ascending=False).iloc[0]

edge=best["max_prob"]

st.write("Best recent bias:",best["bias_group"])
st.write("Edge probability:",round(edge,4))

if edge>0.286:

    st.success("TRADE SIGNAL")

    st.write("Bet group:",best["bias_group"])

else:

    st.warning("NO EDGE")

# ================= NEXT SIGNAL =================

WINDOW=9

next_group=g[-WINDOW]

st.header("Next Signal")

st.metric("Next group",next_group)
