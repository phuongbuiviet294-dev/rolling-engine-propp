import time
import numpy as np
import pandas as pd
import streamlit as st
from collections import Counter
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=2000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

START_LIVE = 168
WINDOW_MIN = 6
WINDOW_MAX = 20
TOP_WINDOWS = 3

VOTE_REQUIRED = 2
GAP = 1

WIN = 2.5
LOSS = -1

# ================= LOAD =================
@st.cache_data(ttl=5)
def load():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower().strip() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load()

# ================= MAP =================
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group(n) for n in numbers]

# ================= RUN =================
def get_run_info(seq):
    if len(seq) < 2:
        return seq[-1], 1

    last = seq[-1]
    run = 1
    for i in range(len(seq)-2, -1, -1):
        if seq[i] == last:
            run += 1
        else:
            break
    return last, run

def run_predict(last, run):
    # pattern đơn giản (tránh overfit)
    if run >= 3:
        return last  # theo trend
    elif run == 2:
        return last  # nhẹ
    else:
        return None  # run yếu

# ================= WINDOW =================
def eval_window(seq, w):
    wins = 0
    trades = 0
    for i in range(w, len(seq)):
        pred = seq[i-w]
        if seq[i] == pred:
            wins += 1
        trades += 1
    if trades == 0:
        return 0
    return wins / trades

def pick_windows(seq):
    scores = []
    for w in range(WINDOW_MIN, WINDOW_MAX+1):
        wr = eval_window(seq, w)
        scores.append((w, wr))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in scores[:TOP_WINDOWS]]

# ================= LOCK =================
train = groups[:START_LIVE]
locked_windows = pick_windows(train)

# ================= LIVE =================
profit = 0
hits = []
last_trade = -999

history = []

for i in range(START_LIVE, len(groups)):

    # ===== WINDOW VOTE =====
    preds = [groups[i-w] for w in locked_windows if i-w >= 0]
    if not preds:
        continue

    vote, strength = Counter(preds).most_common(1)[0]

    # ===== RUN =====
    last, run = get_run_info(groups[:i])
    run_pred = run_predict(last, run)

    # ===== DECISION =====
    signal = strength >= VOTE_REQUIRED
    same = (run_pred == vote)

    action = "WAIT"

    if signal and same and (i - last_trade >= GAP):
        action = "BET"
    elif signal and (i - last_trade >= GAP):
        action = "BET_SMALL"

    # ===== TRADE =====
    hit = None

    if action in ["BET", "BET_SMALL"]:
        last_trade = i

        if groups[i] == vote:
            profit += WIN
            hits.append(1)
            hit = 1
        else:
            profit += LOSS
            hits.append(0)
            hit = 0

    history.append({
        "round": i,
        "group": groups[i],
        "pred": vote,
        "run_pred": run_pred,
        "run_len": run,
        "strength": strength,
        "action": action,
        "hit": hit,
        "profit": profit
    })

# ================= NEXT =================
next_i = len(groups)

preds = [groups[next_i-w] for w in locked_windows if next_i-w >= 0]

if preds:
    vote, strength = Counter(preds).most_common(1)[0]
else:
    vote, strength = None, 0

last, run = get_run_info(groups)
run_pred = run_predict(last, run)

signal = strength >= VOTE_REQUIRED
same = (run_pred == vote)

if signal and same:
    next_action = "BET"
elif signal:
    next_action = "BET_SMALL"
else:
    next_action = "WAIT"

# ================= UI =================
st.title("⚡ HYBRID LIVE (RUN + WINDOW)")

st.write("Locked windows:", locked_windows)
st.write("Current group:", groups[-1])
st.write("Run length:", run)
st.write("Run predict:", run_pred)
st.write("Window vote:", vote)
st.write("Vote strength:", strength)

st.markdown(f"""
<div style="background:yellow;padding:20px;font-size:28px;font-weight:bold;text-align:center">
NEXT → {next_action} | GROUP {vote}
</div>
""", unsafe_allow_html=True)

# ================= STATS =================
st.subheader("Stats")

st.metric("Profit", profit)
st.metric("Trades", len(hits))
st.metric("Winrate", round(np.mean(hits)*100,2) if hits else 0)

# ================= CHART =================
df = pd.DataFrame(history)

if not df.empty:
    st.line_chart(df["profit"])

st.subheader("History")
st.dataframe(df.tail(50), use_container_width=True)
