import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=1000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

TRAIN_SCAN = 204
WINDOW_MIN = 6
WINDOW_MAX = 20
TOP_WINDOWS = 5

VOTE_REQUIRED = 4
GAP = 0
WIN = 2.5
LOSS = -1

PROFIT_TARGET = 3

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

groups = [group(n) for n in numbers]

# ---------------- GUARD ----------------
if len(groups) <= TRAIN_SCAN:
    st.error(
        f"Chưa đủ dữ liệu để chạy trade. Cần nhiều hơn {TRAIN_SCAN} rounds, hiện có {len(groups)}."
    )
    st.stop()

# ---------------- WINDOW EVAL ----------------
def evaluate_window(seq_groups, w):
    profit = 0
    trades = 0
    wins = 0

    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]

        if seq_groups[i - 1] != pred:
            trades += 1
            if seq_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    winrate = wins / trades if trades > 0 else 0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
    }

def select_windows_from_train(train_groups):
    rows = []

    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        rows.append(evaluate_window(train_groups, w))

    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

    positive_df = df[df["profit"] > 0].copy()

    if len(positive_df) >= TOP_WINDOWS:
        selected = positive_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    else:
        selected = df.head(TOP_WINDOWS)["window"].astype(int).tolist()

    return selected, df

# ---------------- STATE INIT ----------------
def init_state():
    if "live_initialized" not in st.session_state:
        st.session_state.live_initialized = False

    if "processed_until" not in st.session_state:
        st.session_state.processed_until = None

    if "profit" not in st.session_state:
        st.session_state.profit = 0.0

    if "last_trade" not in st.session_state:
        st.session_state.last_trade = -999

    if "hits" not in st.session_state:
        st.session_state.hits = []

    if "history_rows" not in st.session_state:
        st.session_state.history_rows = []

    if "locked_windows" not in st.session_state:
        st.session_state.locked_windows = []

    if "scan_df_locked" not in st.session_state:
        st.session_state.scan_df_locked = pd.DataFrame()

    if "base_data_len" not in st.session_state:
        st.session_state.base_data_len = None

init_state()

# ---------------- RESET ----------------
if st.button("🔄 Reset Session"):
    keys_to_clear = [
        "live_initialized",
        "processed_until",
        "profit",
        "last_trade",
        "hits",
        "history_rows",
        "locked_windows",
        "scan_df_locked",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# Nếu dữ liệu bị giảm thì reset để tránh lệch state
if (
    st.session_state.base_data_len is not None
    and len(groups) < st.session_state.base_data_len
):
    keys_to_clear = [
        "live_initialized",
        "processed_until",
        "profit",
        "last_trade",
        "hits",
        "history_rows",
        "locked_windows",
        "scan_df_locked",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- INITIAL LOCK ONLY ONCE ----------------
start_index = TRAIN_SCAN

if not st.session_state.live_initialized:
    train_groups = groups[:TRAIN_SCAN]
    locked_windows, scan_df_locked = select_windows_from_train(train_groups)

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_locked = scan_df_locked
    st.session_state.processed_until = TRAIN_SCAN - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
scan_df_locked = st.session_state.scan_df_locked
processed_until = st.session_state.processed_until

for i in range(processed_until + 1, len(groups)):
    if i < start_index:
        continue

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= VOTE_REQUIRED
    distance = i - last_trade

    if profit >= PROFIT_TARGET:
        signal = False
        trade = False
        can_bet = False
        state = "STOP"
    else:
        trade = signal and distance >= GAP
        can_bet = trade
        state = "TRADE" if trade else ("SIGNAL" if signal else "WAIT")

    bet_group = vote if can_bet else None
    hit = None

    if trade:
        last_trade = i

        if groups[i] == vote:
            hit = 1
            profit += WIN
            hits.append(1)
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

    history_rows.append(
        {
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "vote": vote,
            "confidence": confidence,
            "signal": signal,
            "trade": trade,
            "bet_group": bet_group,
            "hit": hit,
            "state": state,
            "profit": profit,
            "locked_windows": ", ".join(map(str, locked_windows)),
        }
    )

    processed_until = i

st.session_state.profit = profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.history_rows = history_rows
st.session_state.locked_windows = locked_windows
st.session_state.scan_df_locked = scan_df_locked
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)

hist = pd.DataFrame(history_rows)

# ---------------- NEXT BET ----------------
next_round = len(groups)
preds = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

raw_signal = confidence >= VOTE_REQUIRED if vote is not None else False

if profit >= PROFIT_TARGET:
    signal = False
    can_bet = False
    next_state = "STOP"
else:
    signal = raw_signal
    can_bet = signal and distance >= GAP
    next_state = "NEXT"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": False,
    "bet_group": vote if can_bet else None,
    "hit": None,
    "state": next_state,
    "profit": profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Prediction Engine - Fixed Lock + Profit Target")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)
st.write("Locked Windows:", locked_windows)
st.write("Train Scan:", TRAIN_SCAN)
st.write("Profit Target:", PROFIT_TARGET)
st.write("Processed Until Round:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;
    padding:20px;
    border-radius:10px;
    text-align:center;
    font-size:28px;
    font-weight:bold;">
    NEXT GROUP → {vote if vote is not None else "-"} (Vote Strength: {confidence})
    </div>
    """,
    unsafe_allow_html=True,
)

if profit >= PROFIT_TARGET:
    st.error(f"🛑 STOP - Reached Profit Target {PROFIT_TARGET}")
elif can_bet and vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;
        padding:25px;
        border-radius:10px;
        text-align:center;
        font-size:32px;
        color:white;
        font-weight:bold;">
        BET GROUP → {vote}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT (conditions not met)")

# ---------------- SESSION STATS ----------------
st.subheader("Session Statistics")
s1, s2, s3 = st.columns(3)
s1.metric("Profit", profit)
s2.metric("Trades", len(hits))
s3.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)

# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["profit"])

# ---------------- LOCKED WINDOW SCAN ----------------
st.subheader("Initial Window Scan (locked once)")
st.dataframe(scan_df_locked, use_container_width=True)

# ---------------- HISTORY ----------------
st.subheader("History")

def highlight_trade(row):
    if row["state"] == "NEXT":
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "STOP":
        return ["background-color: #d9534f; color:white"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

# ---------------- DEBUG ----------------
st.write("Locked Windows (fixed):", locked_windows)
st.write("Total Rows:", len(numbers))
