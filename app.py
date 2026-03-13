import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import chisquare

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

def get_group(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    else:
        return 4


df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

groups = [get_group(n) for n in numbers]

st.title("🔬 V800 RNG Bias Detector")


# =========================
# NUMBER DISTRIBUTION
# =========================

st.subheader("Number Distribution")

num_counts = pd.Series(numbers).value_counts().sort_index()

expected = [len(numbers)/len(num_counts)] * len(num_counts)

chi_stat, p_val = chisquare(num_counts, expected)

st.dataframe(num_counts)

st.write("Chi-square statistic:", chi_stat)
st.write("p-value:", p_val)

if p_val < 0.05:
    st.error("Distribution NOT random (bias detected)")
else:
    st.success("Distribution looks random")


# =========================
# GROUP DISTRIBUTION
# =========================

st.subheader("Group Distribution")

group_counts = pd.Series(groups).value_counts().sort_index()

expected_g = [len(groups)/4] * 4

chi_stat_g, p_val_g = chisquare(group_counts, expected_g)

st.dataframe(group_counts)

st.write("Chi-square statistic:", chi_stat_g)
st.write("p-value:", p_val_g)


# =========================
# AUTOCORRELATION
# =========================

st.subheader("Autocorrelation Test")

lags = 10

autocorr = []

series = pd.Series(numbers)

for lag in range(1, lags+1):

    corr = series.autocorr(lag)

    autocorr.append(corr)

df_auto = pd.DataFrame({
    "lag": range(1,lags+1),
    "correlation": autocorr
})

st.dataframe(df_auto)

st.line_chart(df_auto.set_index("lag")["correlation"])
