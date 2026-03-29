import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=10000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

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
st.write("Data loaded:", len(numbers))

TRAIN_SCAN = 190
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 5
BASE_VOTE_REQUIRED = 3
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 3

# chỉ loại window quá xấu
MIN_WINDOW_PROFIT = -15

# trọng số stability
STABILITY_PROFIT_WEIGHT = 3.0
STABILITY_WINRATE_WEIGHT = 10.0
STABILITY_STREAK_PENALTY = 4.0

# market regime
BAD_MARKET_STREAK_AVG = 12      # nếu streak TB của top windows >= ngưỡng này
WEAK_MARKET_STREAK_AVG = 8      # nếu streak TB >= ngưỡng này thì tăng vote
BAD_MARKET_PROFIT_AVG = -5      # nếu profit TB của top windows <= ngưỡng này

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
    base_score = profit * winrate * np.log(trades) if trades > 0 else -999999

    stability_score = (
        profit * STABILITY_PROFIT_WEIGHT
        + winrate * STABILITY_WINRATE_WEIGHT
        - max_down_streak * STABILITY_STREAK_PENALTY
    )

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": base_score,
        "stability_score": stability_score,
        "max_down_streak": max_down_streak,
        "profit_curve": profit_curve,
    }


def select_windows_from_train(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    usable_df = df[df["profit"] > MIN_WINDOW_PROFIT].copy()
    if len(usable_df) == 0:
        usable_df = df.copy()

    usable_df = usable_df.sort_values(
        ["stability_score", "profit", "winrate"],
        ascending=False
    ).reset_index(drop=True)

    selected_df = usable_df.head(TOP_WINDOWS).copy()
    selected = selected_df["window"].astype(int).tolist()

    full_rank_df = df.sort_values(
        ["stability_score", "profit", "winrate"],
        ascending=False
    ).reset_index(drop=True)

    return selected, full_rank_df, selected_df


def get_market_mode(selected_df: pd.DataFrame) -> str:
    if selected_df.empty:
        return "BAD"

    avg_streak = selected_df["max_down_streak"].mean()
    avg_profit = selected_df["profit"].mean()

    if avg_streak >= BAD_MARKET_STREAK_AVG or avg_profit <= BAD_MARKET_PROFIT_AVG:
        return "BAD"
    if avg_streak >= WEAK_MARKET_STREAK_AVG:
        return "WEAK"
    return "NORMAL"


def get_effective_vote_required(window_count: int, market_mode: str) -> int:
    base = BASE_VOTE_REQUIRED

    # market yếu thì tăng ngưỡng
    if market_mode == "WEAK":
        base += 1
    elif market_mode == "BAD":
        # vẫn tính, nhưng thường sẽ bị chặn trade ở dưới
        base += 2

    return min(max(1, base), max(1, window_count))


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
        "market_mode": "NORMAL",
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
        "market_mode",
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
        "market_mode",
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
    market_mode = get_market_mode(scan_df_selected)

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.market_mode = market_mode
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
market_mode = st.session_state.market_mode
processed_until = st.session_state.processed_until

effective_vote_required = get_effective_vote_required(len(locked_windows), market_mode)

for i in range(processed_until + 1, len(groups)):
    if i < start_index:
        continue

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= effective_vote_required
    distance = i - last_trade

    if profit >= PROFIT_TARGET:
        signal = False
        trade = False
        can_bet = False
        state = "STOP"
    elif market_mode == "BAD":
        signal = False
        trade = False
        can_bet = False
        state = "WAIT_BAD_MARKET"
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
st.session_state.market_mode = market_mode
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

raw_signal = confidence >= effective_vote_required if vote is not None else False

if profit >= PROFIT_TARGET:
    signal = False
    can_bet = False
    next_state = "STOP"
elif market_mode == "BAD":
    signal = False
    can_bet = False
    next_state = "WAIT_BAD_MARKET"
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
st.title("🎯 Rolling Prediction Engine - Top 5 ít nhiễu + Dynamic Vote")

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
st.write("Vote Required (base):", BASE_VOTE_REQUIRED)
st.write("Vote Required (effective):", effective_vote_required)
st.write("Market Mode:", market_mode)
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
elif market_mode == "BAD":
    st.warning("⚠️ Market đang xấu, tạm không bet")
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

st.subheader("Selected Stable Window Scan")
scan_selected_show = scan_df_selected.drop(columns=["profit_curve"], errors="ignore")
st.dataframe(scan_selected_show, use_container_width=True)

# ---------------- HISTORY ----------------
st.subheader("History")

def highlight_trade(row):
    if row["state"] == "NEXT":
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "STOP":
        return ["background-color: #d9534f; color:white"] * len(row)
    if row["state"] == "WAIT_BAD_MARKET":
        return ["background-color: #fff3cd"] * len(row)
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
