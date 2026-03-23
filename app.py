import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=10000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

TRAIN_SCAN = 182
WINDOW_MIN = 6
WINDOW_MAX = 30
TOP_WINDOWS = 8

GAP = 1
WIN = 2.5
LOSS = -1

PROFIT_TARGET = 7
MIN_WINDOW_PROFIT = -10  # <-- chỉnh ở đây nếu muốn

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()


numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4


groups = [group(n) for n in numbers]

if len(groups) <= TRAIN_SCAN:
    st.error(f"Chưa đủ dữ liệu (> {TRAIN_SCAN})")
    st.stop()

# ---------------- WINDOW SCAN ----------------
def evaluate_window(seq, w):
    profit = trades = wins = 0
    for i in range(w, len(seq)):
        pred = seq[i - w]
        if seq[i - 1] != pred:
            trades += 1
            if seq[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    wr = wins / trades if trades > 0 else 0
    score = profit * wr * np.log(trades) if trades > 0 else -999999

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": wr,
        "score": score,
    }


def select_windows(train):
    rows = [evaluate_window(train, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    # lọc window xấu
    filtered = df[df["profit"] >= MIN_WINDOW_PROFIT]

    if len(filtered) >= TOP_WINDOWS:
        selected = filtered.head(TOP_WINDOWS)["window"].tolist()
    else:
        selected = filtered["window"].tolist()

    return selected, df, filtered


# ---------------- INIT STATE ----------------
if "init" not in st.session_state:
    train = groups[:TRAIN_SCAN]
    windows, scan_df, scan_filtered = select_windows(train)

    st.session_state.windows = windows
    st.session_state.scan_df = scan_df
    st.session_state.scan_filtered = scan_filtered

    st.session_state.history = []
    st.session_state.hits = []
    st.session_state.profit = 0
    st.session_state.last_trade = -999
    st.session_state.idx = TRAIN_SCAN - 1

    st.session_state.init = True

# ---------------- LOAD STATE ----------------
windows = st.session_state.windows
profit = st.session_state.profit
last_trade = st.session_state.last_trade
history = st.session_state.history
hits = st.session_state.hits
idx = st.session_state.idx

# ---------------- VOTE ĐỘNG ----------------
def get_vote_required(n):
    if n >= 8:
        return 5
    elif n >= 5:
        return 4
    elif n >= 4:
        return 3
    else:
        return n


vote_required = get_vote_required(len(windows))

# ---------------- PROCESS LIVE ----------------
for i in range(idx + 1, len(groups)):
    if i < TRAIN_SCAN:
        continue

    preds = [groups[i - w] for w in windows if i - w >= 0]
    if not preds:
        continue

    vote, conf = Counter(preds).most_common(1)[0]

    signal = conf >= vote_required
    distance = i - last_trade

    if profit >= PROFIT_TARGET:
        trade = False
        state = "STOP"
    else:
        trade = signal and distance >= GAP
        state = "TRADE" if trade else ("SIGNAL" if signal else "WAIT")

    bet = vote if trade else None
    hit = None

    if trade:
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
        "number": numbers[i],
        "group": groups[i],
        "vote": vote,
        "confidence": conf,
        "trade": trade,
        "bet": bet,
        "hit": hit,
        "state": state,
        "profit": profit,
    })

    idx = i

# save lại
st.session_state.profit = profit
st.session_state.last_trade = last_trade
st.session_state.history = history
st.session_state.hits = hits
st.session_state.idx = idx

hist = pd.DataFrame(history)

# ---------------- NEXT ----------------
i = len(groups)
preds = [groups[i - w] for w in windows if i - w >= 0]

vote, conf = Counter(preds).most_common(1)[0] if preds else (None, 0)

last_trade_rows = hist[hist["trade"] == True]
distance = i - last_trade_rows["round"].max() if len(last_trade_rows) else 999

signal = conf >= vote_required
can_bet = signal and distance >= GAP and profit < PROFIT_TARGET

# ---------------- UI ----------------
st.title("🎯 Engine - Lock 182 + Dynamic Vote")

st.write("Windows:", windows)
st.write("Vote Required:", vote_required)
st.write("Window Count:", len(windows))

col1, col2, col3 = st.columns(3)
col1.metric("Current", numbers[-1])
col2.metric("Group", groups[-1])
col3.metric("Next", vote)

st.write("Confidence:", conf)

if profit >= PROFIT_TARGET:
    st.error("STOP PROFIT")
elif can_bet:
    st.error(f"BET → {vote}")
else:
    st.info("WAIT")

# stats
st.subheader("Stats")
c1, c2, c3 = st.columns(3)
c1.metric("Profit", profit)
c2.metric("Trades", len(hits))
c3.metric("WR", round(np.mean(hits)*100,2) if hits else 0)

# chart
st.line_chart(hist["profit"] if not hist.empty else [])

# history
st.dataframe(hist.iloc[::-1], use_container_width=True)
