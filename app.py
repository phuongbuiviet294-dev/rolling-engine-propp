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

TRAIN_SCAN = 168
RELOCK_EVERY = 26

WINDOW_MIN = 6
WINDOW_MAX = 18

TOP_WINDOWS = 8
VOTE_REQUIRED = 5
GAP = 1

WIN = 2.5
LOSS = -1

PROFIT_TARGET = 4.5

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
if len(groups) < TRAIN_SCAN:
    st.error(f"Chưa đủ dữ liệu để chạy. Cần ít nhất {TRAIN_SCAN} rounds, hiện có {len(groups)}.")
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


# ---------------- BUILD HISTORY WITH PERIODIC RE-LOCK ----------------
profit = 0
last_trade = -999
history = []
hits = []
relock_log = []

start_index = TRAIN_SCAN

current_top_windows = []
current_scan_df = pd.DataFrame()

for i in range(start_index, len(groups)):
    if (i == start_index) or ((i - start_index) % RELOCK_EVERY == 0):
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

    history.append(
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

hist = pd.DataFrame(history)
relock_df = pd.DataFrame(relock_log)

# ---------------- NEXT BET ----------------
top_windows_now = current_top_windows
scan_df_now = current_scan_df

i = len(groups)
preds = [groups[i - w] for w in top_windows_now if i - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

last_trade_rows = hist[hist["trade"] == True]
distance = i - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999

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
    "round": i,
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
    "locked_windows": ", ".join(map(str, top_windows_now)),
}

hist = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Prediction Engine - Re-lock + Profit Target")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)
st.write("Current Locked Windows:", top_windows_now)
st.write("Re-lock Every:", RELOCK_EVERY)
st.write("Profit Target:", PROFIT_TARGET)

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
if not hist.empty:
    st.line_chart(hist["profit"])

# ---------------- CURRENT WINDOW SCAN ----------------
st.subheader("Current Window Scan (same lock as current history block)")
st.dataframe(scan_df_now, use_container_width=True)

# ---------------- RE-LOCK LOG ----------------
st.subheader("Re-lock Log")
st.dataframe(relock_df, use_container_width=True)

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
    hist.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

# ---------------- DEBUG ----------------
st.write("Top Windows (current block):", top_windows_now)
st.write("Total Rows:", len(numbers))
