import streamlit as st
import pandas as pd

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

df = pd.read_csv(DATA_URL)
numbers = df["number"].dropna().astype(int).tolist()

st.title("🚀 V1100 Walk-Forward Reality Engine")

train_data = numbers[:2000]
test_data  = numbers[2000:4000]

results = []

# SEARCH BEST CONFIG ON TRAIN
for lookback in range(2,5):
    for gap in range(0,6):
        for window in range(3,15):

            trades = 0
            wins = 0

            for i in range(lookback + gap + window, len(train_data)-1):

                pattern = train_data[i-gap-lookback:i-gap]

                history = []

                for j in range(i-gap-window, i-gap):

                    if j-lookback < 0:
                        continue

                    if train_data[j-lookback:j] == pattern:
                        history.append(train_data[j])

                if len(history) < 5:
                    continue

                pred = pd.Series(history).value_counts().idxmax()

                trades += 1

                if train_data[i+1] == pred:
                    wins += 1

            if trades < 20:
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

df_train = pd.DataFrame(results)

if df_train.empty:
    st.error("No strategy found in training set")
    st.stop()

df_train = df_train.sort_values("EV", ascending=False)

best = df_train.iloc[0]

st.subheader("Best strategy from TRAIN")

st.write(best)

# TEST PHASE

lookback = int(best.lookback)
gap = int(best.gap)
window = int(best.window)

trades = 0
wins = 0

for i in range(lookback + gap + window, len(test_data)-1):

    pattern = test_data[i-gap-lookback:i-gap]

    history = []

    for j in range(i-gap-window, i-gap):

        if j-lookback < 0:
            continue

        if test_data[j-lookback:j] == pattern:
            history.append(test_data[j])

    if len(history) < 5:
        continue

    pred = pd.Series(history).value_counts().idxmax()

    trades += 1

    if test_data[i+1] == pred:
        wins += 1

if trades == 0:
    st.error("No trades in test set")
else:

    winrate = wins / trades
    ev = winrate * 9 - (1-winrate)

    st.subheader("Test result (Out-of-sample)")

    st.write({
        "trades": trades,
        "wins": wins,
        "winrate": winrate,
        "EV": ev
    })
