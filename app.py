import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(page_title="V4000 RNG Analyzer", layout="wide")

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# -----------------------
# Load Data
# -----------------------

@st.cache_data
def load_data():
    df = pd.read_csv(DATA_URL)
    df.columns = [c.strip().lower() for c in df.columns]
    numbers = df["number"].dropna().astype(int)
    return numbers

numbers = load_data()

st.title("🎲 V4000 Advanced RNG Analyzer")

st.write("Total rounds:", len(numbers))

# -----------------------
# Convert to groups
# -----------------------

def group(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    else:
        return 4

groups = numbers.apply(group)
g = groups.values

# -----------------------
# Global distribution
# -----------------------

st.header("Distribution")

freq = groups.value_counts().sort_index()
prob = freq / len(groups)

dist_df = pd.DataFrame({
    "group": freq.index,
    "count": freq.values,
    "prob": prob.values
})

st.dataframe(dist_df)

fig = px.bar(dist_df, x="group", y="prob")
st.plotly_chart(fig, use_container_width=True)

# -----------------------
# Lag correlation
# -----------------------

st.header("Lag Correlation")

lags = 10
corr = []

for lag in range(1, lags+1):
    c = np.corrcoef(g[:-lag], g[lag:])[0,1]
    corr.append(c)

corr_df = pd.DataFrame({
    "lag": range(1,lags+1),
    "correlation": corr
})

st.dataframe(corr_df)

fig2 = px.line(corr_df, x="lag", y="correlation")
st.plotly_chart(fig2, use_container_width=True)

# -----------------------
# Entropy over time
# -----------------------

st.header("Entropy Drift")

window = 200
entropy_vals = []
pos = []

for i in range(0, len(g)-window):
    seg = g[i:i+window]
    counts = np.bincount(seg)[1:]
    probs = counts / window
    ent = -np.sum(probs * np.log2(probs + 1e-9))
    entropy_vals.append(ent)
    pos.append(i)

entropy_df = pd.DataFrame({
    "round": pos,
    "entropy": entropy_vals
})

fig3 = px.line(entropy_df, x="round", y="entropy")
st.plotly_chart(fig3, use_container_width=True)

# -----------------------
# Transition matrix
# -----------------------

st.header("Markov Transition")

matrix = np.zeros((4,4))

for i in range(len(g)-1):
    a = g[i]-1
    b = g[i+1]-1
    matrix[a][b] += 1

matrix_df = pd.DataFrame(matrix,
                         index=["1","2","3","4"],
                         columns=["1","2","3","4"])

st.dataframe(matrix_df)

fig4 = px.imshow(matrix,
                 labels=dict(x="Next", y="Current", color="Count"))
st.plotly_chart(fig4, use_container_width=True)

# -----------------------
# Markov probability
# -----------------------

prob_matrix = matrix / matrix.sum(axis=1, keepdims=True)

prob_df = pd.DataFrame(prob_matrix,
                       index=["1","2","3","4"],
                       columns=["1","2","3","4"])

st.header("Transition Probability")

st.dataframe(prob_df)

# -----------------------
# Detect edge
# -----------------------

edge_group = None
edge_prob = 0

for i in range(4):
    m = prob_matrix[i].max()
    if m > edge_prob:
        edge_prob = m
        edge_group = np.argmax(prob_matrix[i]) + 1

st.header("Edge Detection")

st.write("Max transition probability:", round(edge_prob,4))
st.write("Edge group:", edge_group)

if edge_prob > 0.32:
    st.success("TRADE SIGNAL")
    st.write("Bet group:", edge_group)
else:
    st.warning("NO EDGE")

# -----------------------
# Next signal
# -----------------------

current = g[-1]

next_prob = prob_matrix[current-1]
next_group = np.argmax(next_prob)+1

st.header("Next Signal")

st.write("Current group:", current)
st.write("Best next group:", next_group)
