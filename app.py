import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================
# AUTO REFRESH
# =========================
st_autorefresh(interval=1000, key="refresh")

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

START_LOCK_ROUND = 168
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS =3
VOTE_REQUIRED = 2
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 3

# cần tối thiểu 4 window profit >= 0
MIN_POSITIVE_WINDOWS = 3

# window thứ 5 nếu thiếu sẽ lấy theo ít nhiễu
FALLBACK_MIN_PROFIT = -5
FALLBACK_MIN_WINRATE = 0.26

# =========================
# LOAD DATA
# =========================
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

# =========================
# GROUP
# =========================
def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


groups = [group(n) for n in numbers]

# =========================
# GUARD
# =========================
if len(groups) <= START_LOCK_ROUND:
    st.error(
        f"Chưa đủ dữ liệu. Cần nhiều hơn {START_LOCK_ROUND} rounds, hiện có {len(groups)}."
    )
    st.stop()

# =========================
# WINDOW EVAL
# =========================
def evaluate_window(seq_groups, w):
    profit = 0
    trades = 0
    wins = 0

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

            if profit < prev_profit:
                down_streak += 1
            else:
                down_streak = 0

            max_down_streak = max(max_down_streak, down_streak)
            prev_profit = profit

    winrate = wins / trades if trades > 0 else 0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999
    ev = winrate * WIN - (1 - winrate) * abs(LOSS) if trades > 0 else -999999

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "ev": ev,
        "max_down_streak": max_down_streak,
    }


def select_windows_from_round(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    # 1) lấy các window profit >= 0 trước
    positive_df = df[df["profit"] >= 0].copy()
    positive_df = positive_df.sort_values(
        ["profit", "max_down_streak", "score", "winrate"],
        ascending=[False, True, False, False]
    ).reset_index(drop=True)

    selected = pd.DataFrame()

    if len(positive_df) >= MIN_POSITIVE_WINDOWS:
        selected = positive_df.head(MIN_POSITIVE_WINDOWS).copy()
        selected["pick_source"] = "positive"

    # 2) nếu chưa đủ 4 window dương thì coi như round này không đạt điều kiện
    if len(selected) < MIN_POSITIVE_WINDOWS:
        return [], df, pd.DataFrame()

    # 3) lấy thêm 1 window để đủ 5, ưu tiên ít nhiễu
    selected_windows = set(selected["window"].tolist())

    remain_df = df[~df["window"].isin(selected_windows)].copy()
    remain_df = remain_df[
        (remain_df["profit"] > FALLBACK_MIN_PROFIT) &
        (remain_df["winrate"] >= FALLBACK_MIN_WINRATE)
    ].copy()

    remain_df = remain_df.sort_values(
        ["max_down_streak", "profit", "score", "winrate"],
        ascending=[True, False, False, False]
    ).reset_index(drop=True)

    if len(remain_df) > 0:
        extra = remain_df.head(1).copy()
        extra["pick_source"] = "fallback_safe"
        selected = pd.concat([selected, extra], ignore_index=True)

    # 4) nếu vẫn chưa đủ 5 thì lấy tiếp ít nhiễu nhất bất kể nhẹ âm
    if len(selected) < TOP_WINDOWS:
        selected_windows = set(selected["window"].tolist())

        remain_df_2 = df[~df["window"].isin(selected_windows)].copy()
        remain_df_2 = remain_df_2.sort_values(
            ["max_down_streak", "profit", "score", "winrate"],
            ascending=[True, False, False, False]
        ).reset_index(drop=True)

        need = TOP_WINDOWS - len(selected)
        if need > 0 and len(remain_df_2) > 0:
            extra2 = remain_df_2.head(need).copy()
            extra2["pick_source"] = "last_resort"
            selected = pd.concat([selected, extra2], ignore_index=True)

    selected = selected.head(TOP_WINDOWS).copy()
    locked_windows = selected["window"].astype(int).tolist()

    return locked_windows, df.sort_values(
        ["profit", "max_down_streak", "score", "winrate"],
        ascending=[False, True, False, False]
    ).reset_index(drop=True), selected


# =========================
# STATE INIT
# =========================
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
        "lock_round_used": None,
        "base_data_len": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()

# =========================
# RESET
# =========================
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
        "lock_round_used",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

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
        "lock_round_used",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# =========================
# INITIAL LOCK ONLY ONCE
# =========================
if not st.session_state.live_initialized:
    lock_round_used = None
    locked_windows = []
    scan_df_all = pd.DataFrame()
    scan_df_selected = pd.DataFrame()

    # bắt đầu từ mốc 168, tìm round đầu tiên có ít nhất 4 window profit >= 0
    for r in range(START_LOCK_ROUND, len(groups)):
        train_groups = groups[:r]
        tmp_windows, tmp_scan_all, tmp_selected = select_windows_from_round(train_groups)

        if len(tmp_windows) >= TOP_WINDOWS:
            lock_round_used = r
            locked_windows = tmp_windows
            scan_df_all = tmp_scan_all
            scan_df_selected = tmp_selected
            break

    if lock_round_used is None:
        st.error("Không tìm được round nào từ mốc 168 trở đi có đủ 4 window profit >= 0 để lock.")
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.lock_round_used = lock_round_used
    st.session_state.processed_until = lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# =========================
# PROCESS ONLY NEW ROUNDS
# =========================
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
scan_df_all = st.session_state.scan_df_all
scan_df_selected = st.session_state.scan_df_selected
lock_round_used = st.session_state.lock_round_used
processed_until = st.session_state.processed_until

for i in range(processed_until + 1, len(groups)):
    if i < lock_round_used:
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
st.session_state.lock_round_used = lock_round_used
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)

hist = pd.DataFrame(history_rows)

# =========================
# NEXT BET
# =========================
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

# =========================
# UI
# =========================
st.title("🎯 Rolling Prediction Engine - Start 168, find 4 positive windows, run 5 vote 4")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)
st.write("Lock Round Used:", lock_round_used)
st.write("Locked Windows:", locked_windows)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Vote Required:", VOTE_REQUIRED)
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

# =========================
# STATS
# =========================
st.subheader("Session Statistics")
s1, s2, s3 = st.columns(3)
s1.metric("Profit", profit)
s2.metric("Trades", len(hits))
s3.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)

# =========================
# PROFIT CURVE
# =========================
st.subheader("Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["profit"])

# =========================
# WINDOW TABLES
# =========================
st.subheader("Window Scan All")
st.dataframe(scan_df_all, use_container_width=True)

st.subheader("Locked Window Scan")
st.dataframe(scan_df_selected, use_container_width=True)

# =========================
# HISTORY
# =========================
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

# =========================
# DEBUG
# =========================
st.write("Locked Windows:", locked_windows)
st.write("Total Rows:", len(numbers))
