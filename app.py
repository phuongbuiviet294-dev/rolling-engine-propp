import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

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

# -------- streak detection --------

def detect_streak(groups):

    if len(groups)<3:
        return None

    if groups[-1]==groups[-2]==groups[-3]:

        return f"Break streak → bet NOT {groups[-1]}"

    return None


# -------- imbalance detection --------

def detect_imbalance(groups):

    if len(groups)<40:
        return None

    window=groups[-40:]

    count=Counter(window)

    for g in range(1,5):

        count.setdefault(g,0)

    expected=10

    diff={g:expected-count[g] for g in count}

    best=max(diff,key=diff.get)

    if diff[best]>=4:

        return f"Mean reversion → bet {best}"

    return None


# -------- cluster detection --------

def detect_cluster(groups):

    if len(groups)<6:
        return None

    seq=groups[-6:]

    if seq[0]==seq[2]==seq[4] and seq[1]==seq[3]==seq[5]:

        return f"Cluster oscillation → bet {seq[-2]} or {seq[-1]}"

    return None


# -------- decision --------

signal=None

for fn in [detect_streak,detect_imbalance,detect_cluster]:

    signal=fn(groups)

    if signal:
        break

# -------- UI --------

st.title("⚡ V15 Edge Engine")

st.metric("Rounds",len(groups))

if signal:

    st.success(signal)

else:

    st.info("No edge detected → SKIP")

# -------- distribution chart --------

dist=Counter(groups)

df=pd.DataFrame({
    "group":list(dist.keys()),
    "count":list(dist.values())
})

st.subheader("Distribution")

st.bar_chart(df.set_index("group"))

# -------- recent rounds --------

st.subheader("Last 30 groups")

st.write(groups[-30:])
