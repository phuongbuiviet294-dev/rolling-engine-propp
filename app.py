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
TEST_SCAN = 40

WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 8
VOTE_REQUIRED = 5
GAP = 1

WIN = 2.5
LOSS = -1


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


# ---------------- SINGLE WINDOW BACKTEST ----------------
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
    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
    }


# ---------------- WALK-FORWARD WINDOW SELECT ----------------
def walkforward_select_windows(groups):
    rows = []

    if len(groups) < TRAIN_SCAN + TEST_SCAN:
        return pd.DataFrame(columns=[
            "window", "train_profit", "train_winrate", "train_trades",
            "test_profit", "test_winrate", "test_trades", "wf_score"
        ])

    train_groups = groups[:TRAIN_SCAN]
    test_groups = groups[TRAIN_SCAN:TRAIN_SCAN + TEST_SCAN]

    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        train_res = evaluate_window(train_groups, w)
        test_res = evaluate_window(test_groups, w)

        train_profit = train_res["profit"]
        test_profit = test_res["profit"]
        train_trades = train_res["trades"]
        test_trades = test_res["trades"]
        train_wr = train_res["winrate"]
        test_wr = test_res["winrate"]

        # Chấm điểm ưu tiên:
        # - train dương
        # - test không gãy
        # - có đủ trades
        # - winrate test không quá thấp
        wf_score = (
            train_profit * 0.6
            + test_profit * 1.2
            + np.log(max(train_trades, 1)) * train_wr * 4
            + np.log(max(test_trades, 1)) * test_wr * 6
        )

        rows.append({
            "window": w,
            "train_profit": train_profit,
            "train_winrate": round(train_wr, 4),
            "train_trades": train_trades,
            "test_profit": test_profit,
            "test_winrate": round(test_wr, 4),
            "test_trades": test_trades,
            "wf_score": round(wf_score, 4),
        })

    df = pd.DataFrame(rows).sort_values("wf_score", ascending=False).reset_index(drop=True)
    return df


# ---------------- SELECT + LOCK WINDOWS ----------------
wf_df = walkforward_select_windows(groups)

if "top_windows" not in st.session_state:
    if not wf_df.empty:
        # ưu tiên window test không âm
        filtered = wf_df[wf_df["test_profit"] >= 0].copy()
        if len(filtered) >= TOP_WINDOWS:
            st.session_state.top_windows = filtered.head(TOP_WINDOWS)["window"].astype(int).tolist()
        else:
            st.session_state.top_windows = wf_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    else:
        st.session_state.top_windows = list(range(WINDOW_MIN, WINDOW_MIN + TOP_WINDOWS))

top_windows = st.session_state.top_windows

if st.button("🔄 Re-select Windows"):
    if not wf_df.empty:
        filtered = wf_df[wf_df["test_profit"] >= 0].copy()
        if len(filtered) >= TOP_WINDOWS:
            st.session_state.top_windows = filtered.head(TOP_WINDOWS)["window"].astype(int).tolist()
        else:
            st.session_state.top_windows = wf_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    st.rerun()


# ---------------- TRADE ENGINE ----------------
profit = 0
last_trade = -999
history = []
hits = []

start_index = TRAIN_SCAN

for i in range(start_index, len(groups)):
    preds = [groups[i - w] for w in top_windows if i - w >= 0]
    if not preds:
        continue

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= VOTE_REQUIRED
    distance = i - last_trade
    trade = signal and distance >= GAP

    bet_group = vote if trade else None
    hit = None
    state = "WAIT"

    if signal:
        state = "SIGNAL"

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

    history.append({
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
    })

hist = pd.DataFrame(history)


# ---------------- NEXT BET ----------------
i = len(groups)
preds = [groups[i - w] for w in top_windows if i - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = i - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

signal = confidence >= VOTE_REQUIRED if vote is not None else False

next_row = {
    "round": i,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": False,
    "bet_group": vote if signal else None,
    "hit": None,
    "state": "NEXT",
    "profit": profit,
}

hist = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)


# ---------------- UI ----------------
st.title("🎯 Rolling Engine - Walk Forward Test")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.write("Vote Strength:", confidence)
st.write("Distance:", distance)

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT GROUP → {vote if vote is not None else "-"}
    </div>
    """,
    unsafe_allow_html=True,
)

if signal and distance >= GAP and vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:25px;border-radius:10px;text-align:center;font-size:32px;color:white;font-weight:bold;">
        BET GROUP → {vote}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT")


# ---------------- STATS ----------------
st.subheader("Session Statistics")
c1, c2, c3 = st.columns(3)
c1.metric("Profit", profit)
c2.metric("Trades", len(hits))
c3.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)


# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve")
if not hist.empty:
    st.line_chart(hist["profit"])


# ---------------- WALK FORWARD TABLE ----------------
st.subheader("Walk Forward Window Score")
st.dataframe(wf_df, use_container_width=True)

st.write("Top Windows (locked):", top_windows)


# ---------------- HISTORY ----------------
def highlight_trade(row):
    if row["state"] == "NEXT":
        return ["background-color: #ffd700"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.subheader("History")
st.dataframe(
    hist.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)
