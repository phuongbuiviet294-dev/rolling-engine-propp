import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import math

# ================= CONFIG =================

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN = 2.5
LOSS = 1

WINDOW_POOL = range(8,18)
TOP_WINDOWS = 3

LOOKBACK = 30
LOCK_ROUND = 3662

AUTO_REFRESH = 5

st.set_page_config(layout="wide")

# ================= GROUP =================

def get_group(n):

    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

# ================= LOAD DATA =================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df = pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    nums = df["number"].dropna().astype(int)

    return nums.tolist()

numbers = load()

groups = [get_group(n) for n in numbers if get_group(n)]

st.write("Total rounds:", len(groups))

# ================= ENTROPY =================

def entropy(seq):

    c = Counter(seq)
    total = len(seq)

    e = 0

    for v in c.values():

        p = v / total
        e -= p * math.log(p)

    return e

# ================= WINDOW SCORE =================

def window_score(data, w):

    profit = 0
    peak = 0
    dd = 0

    for i in range(w, len(data)-1):

        seq = data[i-w:i]

        pred = Counter(seq).most_common(1)[0][0]

        if pred == data[i]:

            profit += WIN

        else:

            profit -= LOSS

        peak = max(peak, profit)

        dd = max(dd, peak - profit)

    return profit - dd

# ================= TRAIN WINDOWS =================

scores = {w: window_score(groups[:LOCK_ROUND], w) for w in WINDOW_POOL}

top_windows = sorted(scores, key=scores.get, reverse=True)[:TOP_WINDOWS]

# ================= ENGINE =================

profit = 0
equity = []

trades = 0
wins = 0

hits = []
confidence_hist = []

trade_log = []

# ================= MAIN LOOP =================

for i in range(LOCK_ROUND, len(groups)-1):

    preds = {}
    strengths = {}

    for w in top_windows:

        seq = groups[i-w:i]

        pred = Counter(seq).most_common(1)[0][0]

        preds[w] = pred

        pattern = np.mean(hits[-40:]) if len(hits)>=40 else 0

        momentum = np.mean(hits[-LOOKBACK:]) if len(hits)>=LOOKBACK else 0

        markov = 0

        if len(hits) > 5:

            last = hits[-1]

            trans = [hits[j+1] for j in range(len(hits)-1) if hits[j]==last]

            if trans:
                markov = np.mean(trans)

        stability = momentum

        strength = (

            0.35 * pattern +
            0.25 * markov +
            0.25 * momentum +
            0.15 * stability

        )

        strengths[w] = strength

    # ================= ENSEMBLE =================

    vote = {}

    for w in strengths:

        g = preds[w]

        vote[g] = vote.get(g,0) + strengths[w]

    pred = max(vote, key=vote.get)

    confidence = vote[pred]

    confidence_hist.append(confidence)

    # ================= DYNAMIC THRESHOLD =================

    if len(confidence_hist) > 200:

        base = np.median(confidence_hist[-200:])

    else:

        base = 0.30

    threshold = base + 0.03

    # ================= REGIME DETECT =================

    momentum = np.mean(hits[-LOOKBACK:]) if len(hits)>=LOOKBACK else 0

    ent = entropy(groups[i-30:i]) if i>30 else 0

    regime_ok = (momentum > 0.40) and (ent < 1.36)

    # ================= TRADE DECISION =================

    trade = False

    if confidence >= threshold and regime_ok:

        trade = True

    actual = groups[i]

    hit = 1 if pred == actual else 0

    if trade:

        trades += 1

        if hit:

            wins += 1
            profit += WIN
            hits.append(1)

        else:

            profit -= LOSS
            hits.append(0)

    equity.append(profit)

    trade_log.append({

        "round": i,
        "pred": pred,
        "actual": actual,
        "hit": hit if trade else None,
        "confidence": round(confidence,3),
        "profit": profit

    })

# ================= METRICS =================

wr = wins / trades if trades else 0

# ================= NEXT SIGNAL =================

i = len(groups)-1

vote = {}

for w in top_windows:

    seq = groups[i-w:i]

    p = Counter(seq).most_common(1)[0][0]

    vote[p] = vote.get(p,0)+1

next_pred = max(vote, key=vote.get)

# ================= UI =================

st.title("⚡ V80.1 Stable Quant Engine")

c1,c2,c3 = st.columns(3)

c1.metric("Active Window", top_windows[0])
c2.metric("Trades", trades)
c3.metric("Winrate %", round(wr*100,2))

st.write("Top Windows:", top_windows)

st.metric("Live Profit", round(profit,2))

st.subheader("Next Signal")

if confidence >= threshold:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"WAIT → Group {next_pred}")

st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))

st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_log).iloc[::-1].head(50))
