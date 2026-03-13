import streamlit as st
import pandas as pd
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("🚀 V1000 Edge Hunter Engine")

results = []

for lookback in range(2,7):

    for gap in range(0,11):

        for window in range(3,21):

            trades = 0
            wins = 0

            for i in range(lookback + gap + window, len(numbers)-1):

                pattern = numbers[i-gap-lookback:i-gap]

                history = []

                for j in range(i-gap-window, i-gap):

                    if j-lookback < 0:
                        continue

                    if numbers[j-lookback:j] == pattern:
                        history.append(numbers[j])

                if len(history) < 5:
                    continue

                pred = pd.Series(history).value_counts().idxmax()

                trades += 1

                if numbers[i+1] == pred:
                    wins += 1

            if trades < 30:
                continue

            winrate = wins / trades
            ev = winrate * 9 - (1-winrate)

            results.append({
                "lookback": lookback,
                "gap": gap,
                "window": window,
                "trades": trades,
                "wins": wins,
                "winrate": winrate,
                "EV": ev
            })


df_res = pd.DataFrame(results)

df_res = df_res.sort_values("EV", ascending=False)

st.subheader("Top Edge Configurations")

st.dataframe(df_res.head(20))

st.bar_chart(df_res.head(20).set_index(["lookback","gap","window"])["EV"])
