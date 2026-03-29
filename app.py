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

TRAIN_SCAN = 190
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 5
VOTE_REQUIRED = 3
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 3

# chỉ dùng cho window âm khi thiếu window dương
MIN_WINDOW_PROFIT = -15

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(f"Load Google Sheet failed: {e}")
        st.stop()

    df.columns = [c.lower().strip() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet thiếu cột 'number'")
        st.write("Columns found:", df.columns.tolist())
        st.stop()

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    numbers = df["number"].dropna().astype(int).tolist()

    if not numbers:
        st.error("Không đọc được dữ liệu number từ sheet")
        st.stop()

    return numbers


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
    profit_curve = []

    down_streak = 0
    max_down_streak = 0
    prev_profit = 0

    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]

        if seq_groups[i - 1] != pred:
            trades += 1

            if seq_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

            profit_curve.append(profit)

            if profit < prev_profit:
                down_streak += 1
            else:
                down_streak = 0

            max_down_streak = max(max_down_streak, down_streak)
            prev_profit = profit

    winrate = wins / trades if trades > 0 else 0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999

    # chỉ để tham khảo/xếp hạng tổng thể, không phạt quá mạnh
    hybrid_score = (profit * 5.0) + (winrate * 10.0) - (max_down_streak * 1.0)

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "hybrid_score": hybrid_score,
        "max_down_streak": max_down_streak,
        "profit_curve": profit_curve,
    }


def select_windows_from_train(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    # bảng full để hiển thị
    full_rank_df = df.sort_values(
        ["profit", "hybrid_score", "score", "winrate", "max_down_streak"],
        ascending=[False, False, False, False, True]
    ).reset_index(drop=True)

    # 1) Ưu tiên window profit dương trước
    positive_df = df[df["profit"] > 0].copy()
    positive_df = positive_df.sort_values(
        ["profit", "max_down_streak", "score", "winrate"],
        ascending=[False, True, False, False]
    ).reset_index(drop=True)

    selected_parts = []

    if len(positive_df) >= TOP_WINDOWS:
        selected_df = positive_df.head(TOP_WINDOWS).copy()
        selected_df["pick_source"] = "positive"

    else:
        if len(positive_df) > 0:
            tmp = positive_df.copy()
            tmp["pick_source"] = "positive"
            selected_parts.append(tmp)

        need_more = TOP_WINDOWS - len(positive_df)

        # 2) Nếu chưa đủ 5 thì lấy window âm nhưng ÍT NHIỄU trước
        negative_df = df[
            (df["profit"] <= 0) &
            (df["profit"] > MIN_WINDOW_PROFIT)
        ].copy()

        # Rule quan trọng:
        # - ưu tiên max_down_streak thấp trước
        # - rồi profit đỡ âm hơn
        # - rồi score / winrate
        negative_df = negative_df.sort_values(
            ["max_down_streak", "profit", "score", "winrate"],
            ascending=[True, False, False, False]
        ).reset_index(drop=True)

        if need_more > 0 and len(negative_df) > 0:
            neg_take = negative_df.head(need_more).copy()
            neg_take["pick_source"] = "negative_low_noise"
            selected_parts.append(neg_take)

        selected_df = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()

        # 3) Nếu vẫn chưa đủ thì lấy tiếp phần còn lại theo ít nhiễu trước
        if len(selected_df) < TOP_WINDOWS:
            already = set(selected_df["window"].tolist()) if not selected_df.empty else set()

            fallback_df = df[~df["window"].isin(already)].copy()
            fallback_df = fallback_df.sort_values(
                ["max_down_streak", "profit", "score", "winrate"],
                ascending=[True, False, False, False]
            ).reset_index(drop=True)

            need_last = TOP_WINDOWS - len(selected_df)
            if need_last > 0 and len(fallback_df) > 0:
                fb_take = fallback_df.head(need_last).copy()
                fb_take["pick_source"] = "fallback_low_noise"
                selected_df = pd.concat([selected_df, fb_take], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected = selected_df["window"].astype(int).tolist()

    return selected, full_rank_df, selected_df


# ---------------- STATE INIT ----------------
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,
        "profit": 0.0,
        "last_trade": -999,
        "hits": [],
        "history_rows": [],
        "locked_windows": [],
        "scan_df_all": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "base_data_len": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


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
        "scan_df_all",
        "scan_df_selected",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# nếu dữ liệu bị giảm thì reset để tránh lệch state
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
        "scan_df_all",
        "scan_df_selected",
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
    locked_windows, scan_df_all, scan_df_selected = select_windows_from_train(train_groups)

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.processed_until = TRAIN_SCAN - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
scan_df_all = st.session_state.scan_df_all
scan_df_selected = st.session_state.scan_df_selected
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
st.session_state.scan_df_all = scan_df_all
st.session_state.scan_df_selected = scan_df_selected
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
st.title("🎯 Rolling Prediction Engine - 5 window ít nhiễu, ưu tiên profit dương")

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
st.write("Vote Required:", VOTE_REQUIRED)
st.write("Min Window Profit:", MIN_WINDOW_PROFIT)
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

# ---------------- WINDOW SCAN ----------------
st.subheader("Initial Window Scan (all windows)")
scan_df_show = scan_df_all.drop(columns=["profit_curve"], errors="ignore")
st.dataframe(scan_df_show, use_container_width=True)

st.subheader("Selected Window Scan")
scan_selected_show = scan_df_selected.drop(columns=["profit_curve"], errors="ignore")
st.dataframe(scan_selected_show, use_container_width=True)

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
