# app.py
import streamlit as st
import pandas as pd
import numpy as np
import math
from collections import Counter, defaultdict
from io import StringIO
import requests

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

TRAIN_SCAN = 168
WINDOW_MIN = 6
WINDOW_MAX = 26
TOP_WINDOWS = 8
VOTE_REQUIRED = 5
RELOCK_EVERY = 30

WIN_PROFIT = 2.5
LOSE_LOSS = -1.0
GAP = 1

PROFIT_TARGET = 7.0

# =========================
# GROUP MAP
# =========================
def to_group(n):
    try:
        n = int(n)
    except:
        return None

    if 1 <= n <= 3:
        return 1
    if 4 <= n <= 6:
        return 2
    if 7 <= n <= 9:
        return 3
    if 10 <= n <= 12:
        return 4
    return None


def load_data():
    r = requests.get(CSV_URL, timeout=15)
    r.raise_for_status()
    df = pd.read_csv(StringIO(r.text))

    first_col = df.columns[0]
    df = df[[first_col]].copy()
    df.columns = ["number"]

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    df = df.dropna(subset=["number"])
    df["number"] = df["number"].astype(int)

    df = df[df["number"].between(1, 12)].reset_index(drop=True)
    df["group"] = df["number"].apply(to_group)
    df["round"] = np.arange(1, len(df) + 1)

    return df


def predict_by_window(groups, idx, window):
    """
    Dự đoán group tại idx dựa trên window trước đó.
    Không dùng dữ liệu tương lai.
    """
    if idx < window:
        return None

    past = groups[idx - window:idx]
    cnt = Counter(past)

    if not cnt:
        return None

    max_count = max(cnt.values())
    candidates = [g for g, c in cnt.items() if c == max_count]

    # Nếu hòa, lấy group gần nhất xuất hiện trong window
    for g in reversed(past):
        if g in candidates:
            return g

    return candidates[0]


def backtest_single_window(groups, window, start_idx, end_idx):
    profit = 0.0
    win = 0
    lose = 0
    trades = 0

    for i in range(start_idx, end_idx):
        pred = predict_by_window(groups, i, window)
        if pred is None:
            continue

        actual = groups[i]
        trades += 1

        if pred == actual:
            win += 1
            profit += WIN_PROFIT
        else:
            lose += 1
            profit += LOSE_LOSS

    wr = win / trades if trades else 0
    ev = wr * WIN_PROFIT + (1 - wr) * LOSE_LOSS if trades else 0

    score = profit * wr * math.log(trades + 1) if trades else -999

    return {
        "window": window,
        "profit": profit,
        "win": win,
        "lose": lose,
        "trades": trades,
        "wr": wr,
        "ev": ev,
        "score": score,
    }


def scan_top_windows(groups, end_idx):
    """
    Scan window 6-20 trên đoạn TRAIN_SCAN gần nhất.
    """
    start_idx = max(WINDOW_MAX, end_idx - TRAIN_SCAN)
    results = []

    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        rs = backtest_single_window(groups, w, start_idx, end_idx)
        if rs["profit"] > 0 and rs["trades"] > 0:
            results.append(rs)

    results = sorted(results, key=lambda x: x["score"], reverse=True)

    return results[:TOP_WINDOWS]


def vote_next_group(groups, idx, locked_windows):
    votes = []

    for item in locked_windows:
        w = item["window"]
        pred = predict_by_window(groups, idx, w)
        if pred is not None:
            votes.append(pred)

    if not votes:
        return None, 0, {}

    vote_count = Counter(votes)
    next_group, vote_strength = vote_count.most_common(1)[0]

    return next_group, vote_strength, dict(vote_count)


def calc_phase_profit_seed(groups, end_idx, locked_windows):
    """
    Tính profit theo từng group trong phase hiện tại,
    dùng đoạn train gần nhất để làm điều kiện ban đầu.

    Chỉ group nào profit > 0 mới được phép READY BET.
    """
    phase_profit_group = defaultdict(float)

    start_idx = max(WINDOW_MAX, end_idx - TRAIN_SCAN)

    for i in range(start_idx, end_idx):
        pred, vote_strength, _ = vote_next_group(groups, i, locked_windows)

        if pred is None:
            continue

        if vote_strength < VOTE_REQUIRED:
            continue

        actual = groups[i]

        if pred == actual:
            phase_profit_group[pred] += WIN_PROFIT
        else:
            phase_profit_group[pred] += LOSE_LOSS

    return phase_profit_group


def run_engine(df):
    groups = df["group"].tolist()
    n = len(groups)

    history = []
    lock_history = []

    locked_windows = []
    phase_profit_group = defaultdict(float)

    total_profit = 0.0
    live_profit = 0.0
    last_trade_idx = -999999
    stopped = False

    for i in range(n):
        round_no = i + 1
        number = df.loc[i, "number"]
        actual_group = df.loc[i, "group"]

        relock = False

        if i >= TRAIN_SCAN:
            if not locked_windows:
                relock = True
            elif (i - TRAIN_SCAN) % RELOCK_EVERY == 0:
                relock = True

        if relock:
            locked_windows = scan_top_windows(groups, i)
            phase_profit_group = calc_phase_profit_seed(groups, i, locked_windows)

            lock_history.append({
                "round": round_no,
                "locked_windows": [x["window"] for x in locked_windows],
                "top_profit": locked_windows[0]["profit"] if locked_windows else 0,
                "top_wr": locked_windows[0]["wr"] if locked_windows else 0,
                "top_ev": locked_windows[0]["ev"] if locked_windows else 0,
            })

        next_group, vote_strength, vote_detail = vote_next_group(groups, i, locked_windows)

        signal = "WAIT"
        trade = "WAIT"
        hit = None
        profit = 0.0
        reason = ""

        if i < TRAIN_SCAN:
            reason = "TRAINING"
        elif not locked_windows:
            reason = "NO POSITIVE WINDOW"
        elif next_group is None:
            reason = "NO SIGNAL"
        elif vote_strength < VOTE_REQUIRED:
            reason = f"LOW VOTE {vote_strength}/{VOTE_REQUIRED}"
        elif stopped:
            reason = "PROFIT TARGET STOP"
        else:
            prev_phase_profit = phase_profit_group[next_group]

            if prev_phase_profit <= 0:
                reason = f"PHASE GROUP {next_group} PROFIT <= 0"
                signal = f"NEXT GROUP {next_group}"
                trade = "WAIT"
            elif i - last_trade_idx < GAP:
                reason = f"GAP WAIT"
                signal = f"NEXT GROUP {next_group}"
                trade = "WAIT"
            else:
                signal = f"NEXT GROUP {next_group}"
                trade = "BET"

                if next_group == actual_group:
                    hit = 1
                    profit = WIN_PROFIT
                else:
                    hit = 0
                    profit = LOSE_LOSS

                live_profit += profit
                total_profit += profit
                phase_profit_group[next_group] += profit
                last_trade_idx = i

                if live_profit >= PROFIT_TARGET:
                    stopped = True

                reason = "BET BY POSITIVE PHASE PROFIT"

        history.append({
            "round": round_no,
            "number": number,
            "actual_group": actual_group,
            "next_group": next_group,
            "vote_strength": vote_strength,
            "vote_detail": vote_detail,
            "signal": signal,
            "trade": trade,
            "hit": hit,
            "profit": profit,
            "live_profit": live_profit,
            "phase_profit_g1": phase_profit_group[1],
            "phase_profit_g2": phase_profit_group[2],
            "phase_profit_g3": phase_profit_group[3],
            "phase_profit_g4": phase_profit_group[4],
            "locked_windows": [x["window"] for x in locked_windows],
            "reason": reason,
        })

    return pd.DataFrame(history), pd.DataFrame(lock_history)


# =========================
# STREAMLIT UI
# =========================
st.set_page_config(
    page_title="Rolling Prediction Engine FINAL",
    layout="wide"
)

st.title("Rolling Prediction Engine - FINAL")

with st.sidebar:
    st.header("Config")
    st.write(f"TRAIN_SCAN = {TRAIN_SCAN}")
    st.write(f"WINDOW RANGE = {WINDOW_MIN} - {WINDOW_MAX}")
    st.write(f"TOP_WINDOWS = {TOP_WINDOWS}")
    st.write(f"VOTE_REQUIRED = {VOTE_REQUIRED}")
    st.write(f"RELOCK_EVERY = {RELOCK_EVERY}")
    st.write(f"WIN = {WIN_PROFIT}")
    st.write(f"LOSE = {LOSE_LOSS}")
    st.write(f"GAP = {GAP}")
    st.write(f"PROFIT_TARGET = {PROFIT_TARGET}")

try:
    df = load_data()

    if len(df) < TRAIN_SCAN + WINDOW_MAX:
        st.error("Dữ liệu chưa đủ để chạy engine.")
        st.stop()

    history, lock_df = run_engine(df)

    latest = history.iloc[-1]

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("Current Number", int(latest["number"]))
    c2.metric("Actual Group", int(latest["actual_group"]))

    if pd.notna(latest["next_group"]):
        c3.metric("Next Group", int(latest["next_group"]))
    else:
        c3.metric("Next Group", "WAIT")

    c4.metric("Vote Strength", int(latest["vote_strength"]))
    c5.metric("Live Profit", round(float(latest["live_profit"]), 2))

    st.divider()

    st.subheader("Current Status")

    status_col1, status_col2, status_col3 = st.columns(3)

    status_col1.write("Signal")
    status_col1.success(latest["signal"])

    status_col2.write("Trade")
    if latest["trade"] == "BET":
        status_col2.error("READY BET")
    else:
        status_col2.info("WAIT")

    status_col3.write("Reason")
    status_col3.warning(latest["reason"])

    st.divider()

    st.subheader("Phase Profit By Group")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Group 1", round(float(latest["phase_profit_g1"]), 2))
    p2.metric("Group 2", round(float(latest["phase_profit_g2"]), 2))
    p3.metric("Group 3", round(float(latest["phase_profit_g3"]), 2))
    p4.metric("Group 4", round(float(latest["phase_profit_g4"]), 2))

    st.divider()

    st.subheader("Locked Windows")

    st.write(latest["locked_windows"])

    if not lock_df.empty:
        st.dataframe(lock_df.tail(20), use_container_width=True)

    st.divider()

    st.subheader("History")

    show_cols = [
        "round",
        "number",
        "actual_group",
        "next_group",
        "vote_strength",
        "signal",
        "trade",
        "hit",
        "profit",
        "live_profit",
        "phase_profit_g1",
        "phase_profit_g2",
        "phase_profit_g3",
        "phase_profit_g4",
        "reason",
        "locked_windows"
    ]

    st.dataframe(
        history[show_cols].tail(300).sort_values("round", ascending=False),
        use_container_width=True
    )

    st.divider()

    st.subheader("Profit Chart")
    st.line_chart(history.set_index("round")["live_profit"])

    st.subheader("Trade Only")
    trade_df = history[history["trade"] == "BET"].copy()
    st.dataframe(
        trade_df[show_cols].tail(200).sort_values("round", ascending=False),
        use_container_width=True
    )

    st.download_button(
        "Download History CSV",
        history.to_csv(index=False).encode("utf-8"),
        file_name="rolling_prediction_history_final.csv",
        mime="text/csv"
    )

except Exception as e:
    st.error(f"Lỗi chạy app: {e}")
