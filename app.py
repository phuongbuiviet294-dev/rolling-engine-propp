import streamlit as st
import pandas as pd
from collections import Counter
import numpy as np

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

SCAN_ROUNDS = 200
LOCK_ROUNDS = 200

# ---------- GROUP ----------
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4


# ---------- LOAD ----------
@st.cache_data(ttl=5)
def load():
    df = pd.read_csv(DATA_URL)
    return df["number"].dropna().astype(int).tolist()

numbers = load()
groups = [group(n) for n in numbers]


# ---------- PREDICT ----------
def predict(g, window):

    if len(g) < window:
        return None, 0

    c = Counter(g[-window:])
    pred = max(c, key=c.get)

    confidence = c[pred] / window

    return pred, confidence


# ---------- WINDOW EVALUATION ----------
def evaluate_window(data, window):

    profit = 0
    peak = 0
    dd = 0

    for i in range(window, len(data)-1):

        pred,_ = predict(data[:i], window)

        actual = data[i]

        if pred == actual:
            profit += 2.5
        else:
            profit -= 1

        peak = max(peak, profit)
        dd = max(dd, peak-profit)

    score = profit - 0.5*dd

    return profit, dd, score


# ---------- FIND BEST WINDOW ----------
def find_best_window(data):

    results = []

    for w in range(8,18):

        p, d, s = evaluate_window(data, w)

        results.append((w,p,d,s))

    df = pd.DataFrame(results, columns=["window","profit","drawdown","score"])

    best = df.sort_values("score", ascending=False).iloc[0]

    return int(best.window), df


# ---------- MARKOV PROB ----------
def markov_prob(hits):

    count11 = 0
    count111 = 0

    for i in range(2, len(hits)):

        if hits[i-2] == 1 and hits[i-1] == 1:

            count11 += 1

            if hits[i] == 1:
                count111 += 1

    if count11 == 0:
        return 0

    return count111 / count11


# ---------- BACKTEST ----------

hits = []
history = []

profit = 0
peak = 0
dd = 0

trades = 0
wins = 0

best_window, scan_table = find_best_window(groups[:SCAN_ROUNDS])

lock_counter = 0

records = []

for i in range(SCAN_ROUNDS, len(groups)-1):

    if lock_counter >= LOCK_ROUNDS:

        best_window,_ = find_best_window(groups[i-SCAN_ROUNDS:i])

        lock_counter = 0


    pred, conf = predict(groups[:i], best_window)

    actual = groups[i]

    hit = 1 if pred == actual else 0

    hits.append(hit)

    prob = markov_prob(hits)

    signal = False

    if len(hits) >= 2:

        if hits[-1] == 1 and hits[-2] == 1:

            if prob > 0.5 and conf > 0.30:

                signal = True


    if signal:

        trades += 1

        if pred == actual:

            profit += 2.5
            wins += 1

        else:

            profit -= 1


    peak = max(peak, profit)

    dd = max(dd, peak-profit)

    history.append(profit)

    records.append({
        "round": i,
        "actual": actual,
        "prediction": pred,
        "confidence": conf,
        "hit": hit,
        "profit": profit,
        "signal": signal,
        "window": best_window
    })

    lock_counter += 1


wr = wins/trades if trades else 0

hist_df = pd.DataFrame(records)


# ---------- NEXT GROUP ----------
next_pred, next_conf = predict(groups, best_window)

prob = markov_prob(hits)

signal = False

if len(hits) >= 2:

    if hits[-1] == 1 and hits[-2] == 1:

        if prob > 0.5 and next_conf > 0.30:

            signal = True


# ---------- UI ----------

st.title("⚡ V60 Markov Momentum Engine")

c1,c2,c3 = st.columns(3)

c1.metric("Best Window", best_window)
c2.metric("Trades", trades)
c3.metric("Winrate", round(wr*100,2))


c4,c5 = st.columns(2)

c4.metric("Profit", profit)
c5.metric("Drawdown", dd)


# ---------- NEXT GROUP ----------

st.subheader("Next Group")

if signal:

    st.success(f"TRADE → Group {next_pred} (conf {round(next_conf,2)})")

else:

    st.info("SKIP")


# ---------- MARKOV ----------

st.subheader("Markov Probability")

st.write(f"P(hit_next | 1-1) = {round(prob,3)}")


# ---------- EQUITY ----------

st.subheader("Equity Curve")

st.line_chart(history)


# ---------- WINDOW SCAN ----------

st.subheader("Window Scan Result")

st.dataframe(scan_table)


# ---------- HISTORY ----------

st.subheader("Trade History")

st.dataframe(hist_df.tail(50))
