import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int)

st.title("V800 RNG Bias Detector")

# Number distribution
st.subheader("Number Distribution")

counts = numbers.value_counts().sort_index()

st.dataframe(counts)

expected = len(numbers)/len(counts)

chi = ((counts - expected)**2 / expected).sum()

st.write("Chi-square score:", chi)

# Autocorrelation
st.subheader("Autocorrelation")

series = pd.Series(numbers)

lags = []

for i in range(1,10):

    lags.append(series.autocorr(i))

df_auto = pd.DataFrame({
    "lag":range(1,10),
    "correlation":lags
})

st.dataframe(df_auto)

st.line_chart(df_auto.set_index("lag"))
