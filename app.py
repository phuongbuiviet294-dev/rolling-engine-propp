import streamlit as st
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("V900 State Space Clustering")

# parameters
lookback = 5
clusters = 6

# build state vectors
X = []
y = []

for i in range(lookback, len(numbers)-1):
    state = numbers[i-lookback:i]
    X.append(state)
    y.append(numbers[i+1])

X = np.array(X)
y = np.array(y)

# clustering
kmeans = KMeans(n_clusters=clusters, random_state=0)
labels = kmeans.fit_predict(X)

# analyze clusters
results = []

for c in range(clusters):

    idx = np.where(labels == c)[0]

    next_nums = y[idx]

    counts = pd.Series(next_nums).value_counts(normalize=True)

    max_prob = counts.max()

    results.append({
        "cluster": c,
        "samples": len(idx),
        "max_next_prob": max_prob
    })

df_res = pd.DataFrame(results)

st.subheader("Cluster Bias")

st.dataframe(df_res)

st.bar_chart(df_res.set_index("cluster")["max_next_prob"])
