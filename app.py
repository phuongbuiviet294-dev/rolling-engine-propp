import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

WINDOW_MIN = 6
WINDOW_MAX = 20
TOP_WINDOWS = 6
VOTE_REQUIRED = 4

GAP = 1
WIN = 2.5
LOSS = -1.0


@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower().strip() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet phải có column tên là number")

    nums = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()
    return [x for x in nums if 1 <= x <= 12]


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def get_valid_preds(groups, i, windows):
    """
    Logic vote PHẢI giống logic scan:
    pred = group tại i-w
    chỉ lấy pred nếu pred khác group ván trước.
    """
    preds = []

    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = groups[i - w]

            if groups[i - 1] != pred:
                preds.append(pred)

    return preds


def evaluate_window(groups, w):
    profit = 0.0
    trades = 0
    wins = 0

    for i in range(w, len(groups)):
        pred = groups[i - w]

        # Điều kiện này phải giống live
        if groups[i - 1] != pred:
            trades += 1

            if groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

    wr = wins / trades if trades > 0 else 0
    score = profit + wr * 10 + np.log(trades + 1)

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "wr": wr,
        "score": score,
    }


def pick_windows(groups):
    rows = [evaluate_window(groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    df = df.sort_values(
        ["score", "profit", "wr", "trades"],
        ascending=[False, False, False, False],
    )

    return df.head(TOP_WINDOWS)["window"].astype(int).tolist(), df


def run_engine(numbers):
    groups = [group_of(x) for x in numbers]

    if len(groups) < LOCK_ROUND_END:
        return None, None, None

    train_groups = groups[:LOCK_ROUND_END]
    windows, scan_df = pick_windows(train_groups)

    hist = []

    paper_profit = 0.0
    live_profit = 0.0
    last_live_trade_idx = -999999

    for i in range(LOCK_ROUND_END, len(groups)):
        preds = get_valid_preds(groups, i, windows)

        if preds:
            vote, confidence = Counter(preds).most_common(1)[0]
            signal = confidence >= VOTE_REQUIRED
        else:
            vote = None
            confidence = 0
            signal = False

        # SIGNAL PNL: tính giả lập cho mọi signal
        if signal:
            if groups[i] == vote:
                signal_hit = 1
                signal_pnl = WIN
            else:
                signal_hit = 0
                signal_pnl = LOSS
        else:
            signal_hit = None
            signal_pnl = 0.0

        paper_profit += signal_pnl

        # Lấy kết quả signal của ván ngay trước đó
        if len(hist) > 0:
            prev_signal_pnl = float(hist[-1]["signal_pnl"])
        else:
            prev_signal_pnl = 0.0

        distance = i - last_live_trade_idx

        # LIVE BET RULE CHUẨN
        live_trade = (
            signal
            and prev_signal_pnl > 0
            and distance >= GAP
        )

        if live_trade:
            last_live_trade_idx = i

            if groups[i] == vote:
                live_hit = 1
                live_pnl = WIN
            else:
                live_hit = 0
                live_pnl = LOSS

            live_profit += live_pnl
        else:
            live_hit = None
            live_pnl = 0.0

        hist.append({
            "round": i + 1,
            "number": numbers[i],
            "group": groups[i],
            "prev_group": groups[i - 1],
            "vote": vote,
            "confidence": confidence,
            "signal": signal,
            "signal_hit": signal_hit,
            "signal_pnl": signal_pnl,
            "prev_signal_pnl": prev_signal_pnl,
            "paper_profit": paper_profit,
            "live_trade": live_trade,
            "live_hit": live_hit,
            "live_pnl": live_pnl,
            "live_profit": live_profit,
            "profit_gap": paper_profit - live_profit,
            "valid_preds": preds,
        })

    return pd.DataFrame(hist), windows, scan_df


# =========================
# RUN
# =========================
numbers = load_numbers()
groups = [group_of(x) for x in numbers]

result = run_engine(numbers)

if result[0] is None:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(numbers)}, cần tối thiểu {LOCK_ROUND_END}.")
    st.stop()

hist, windows, scan_df = result

# =========================
# NEXT ROUND
# =========================
i = len(groups)
preds = get_valid_preds(groups, i, windows)

if preds:
    next_vote, next_confidence = Counter(preds).most_common(1)[0]
    next_signal = next_confidence >= VOTE_REQUIRED
else:
    next_vote = None
    next_confidence = 0
    next_signal = False

prev_signal_pnl = float(hist.iloc[-1]["signal_pnl"]) if not hist.empty else 0.0

last_live_rows = hist[hist["live_trade"] == True]
if len(last_live_rows) > 0:
    last_live_round = int(last_live_rows["round"].max())
else:
    last_live_round = -999999

next_round = len(groups) + 1
distance = next_round - last_live_round

can_bet = (
    next_signal
    and prev_signal_pnl > 0
    and distance >= GAP
)

# =========================
# UI
# =========================
st.title("SAFE LIVE ENGINE - FIXED VOTE LOGIC")

c1, c2, c3 = st.columns(3)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", groups[-1])
c3.metric("Next Group", next_vote if next_vote is not None else "-")

st.write("Windows:", windows)
st.write("Valid Preds:", preds)
st.write("Signal:", next_signal)
st.write("Vote Strength:", next_confidence)
st.write("Previous Signal PNL:", prev_signal_pnl)
st.write("Distance:", distance)
st.write("Can Bet:", can_bet)

if can_bet:
    st.success(f"READY BET GROUP {next_vote}")
else:
    st.warning("WAIT")

st.subheader("Profit Compare")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Paper Profit", round(float(hist["paper_profit"].iloc[-1]), 2))
p2.metric("Live Profit", round(float(hist["live_profit"].iloc[-1]), 2))
p3.metric("Profit Gap", round(float(hist["
