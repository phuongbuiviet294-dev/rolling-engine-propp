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

TRAIN_SCAN = 180
RELOCK_EVERY = 30

WINDOW_MIN = 6
WINDOW_MAX = 20
TOP_WINDOWS = 8

VOTE_REQUIRED = 5
GAP = 1

WIN = 2.5
LOSS = -1

PROFIT_TARGET = 7

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

    if "relock_log" not in st.session_state:
        st.session_state.relock_log = []

    if "current_top_windows" not in st.session_state:
        st.session_state.current_top_windows = []

    if "current_scan_df" not in st.session_state:
        st.session_state.current_scan_df = pd.DataFrame()

    if "base_data_len" not in st.session_state:
        st.session_state.base_data_len = None

init_state()

# ---------------- RESET IF DATA SHRINKS / MANUAL ----------------
if st.button("🔄 Reset Live State"):
    keys_to_clear = [
        "live_initialized",
        "processed_until",
        "profit",
        "last_trade",
        "hits",
        "history_rows",
        "relock_log",
        "current_top_windows",
        "current_scan_df",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# Nếu sheet bị sửa/giảm số dòng thì reset để tránh lệch
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
        "relock_log",
        "current_top_windows",
        "current_scan_df",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- LIVE ENGINE INIT ----------------
start_index = TRAIN_SCAN

if not st.session_state.live_initialized:
    # Re-lock đầu tiên tại round TRAIN_SCAN
    train_start = 0
    train_end = TRAIN_SCAN
    train_groups = groups[train_start:train_end]

    current_top_windows, current_scan_df = select_windows_from_train(train_groups)

    st.session_state.current_top_windows = current_top_windows
    st.session_state.current_scan_df = current_scan_df
    st.session_state.relock_log = [
        {
            "relock_round": TRAIN_SCAN,
            "train_from": train_start,
            "train_to": train_end - 1,
            "top_windows": ", ".join(map(str, current_top_windows)),
        }
    ]

    # round cuối đã xử lý = TRAIN_SCAN - 1
    st.session_state.processed_until = TRAIN_SCAN - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
relock_log = st.session_state.relock_log
current_top_windows = st.session_state.current_top_windows
current_scan_df = st.session_state.current_scan_df
processed_until = st.session_state.processed_until

for i in range(processed_until + 1, len(groups)):
    if i < start_index:
        continue

    # re-lock tại round đầu block mới
    if ((i - start_index) % RELOCK_EVERY == 0) and (i != start_index):
        train_start = max(0, i - TRAIN_SCAN)
        train_end = i
        train_groups = groups[train_start:train_end]

        current_top_windows, current_scan_df = select_windows_from_train(train_groups)

        relock_log.append(
            {
                "relock_round": i,
                "train_from": train_start,
                "train_to": train_end - 1,
                "top_windows": ", ".join(map(str, current_top_windows)),
            }
        )

    preds = [groups[i - w] for w in current_top_windows if i - w >= 0]
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
    else:
        trade = signal and distance >= GAP
        can_bet = trade

    bet_group = vote if can_bet else None
    hit = None
    state = "WAIT"

    if signal:
        state = "SIGNAL"

    if profit >= PROFIT_TARGET:
        state = "STOP"

    if trade:
        state = "TRADE"
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
            "locked_windows": ", ".join(map(str, current_top_windows)),
        }
    )

    processed_until = i

# save state back
st.session_state.profit = profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.history_rows = history_rows
st.session_state.relock_log = relock_log
st.session_state.current_top_windows = current_top_windows
st.session_state.current_scan_df = current_scan_df
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)

hist = pd.DataFrame(history_rows)
relock_df = pd.DataFrame(relock_log)
scan_df_now = current_scan_df
top_windows_now = current_top_windows

# ---------------- NEXT BET ----------------
next_round = len(groups)

# nếu round kế tiếp đúng mốc re-lock thì phải scan lại trước khi predict
if (
    next_round >= start_index
    and (next_round - start_index) % RELOCK_EVERY == 0
):
    train_start = max(0, next_round - TRAIN_SCAN)
    train_end = next_round
    train_groups = groups[train_start:train_end]
    top_windows_pred, scan_df_pred = select_windows_from_train(train_groups)
else:
    top_windows_pred = top_windows_now
    scan_df_pred = scan_df_now

preds = [groups[next_round - w] for w in top_windows_pred if next_round - w >= 0]

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
    "locked_windows": ", ".join(map(str, top_windows_pred)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Prediction Engine - LIVE Incremental")
