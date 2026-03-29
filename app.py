import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================
# AUTO REFRESH
# =========================
st_autorefresh(interval=10000, key="refresh")

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# rolling adaptive lock
ROLLING_SCAN = 182
WINDOW_MIN = 6
WINDOW_MAX = 20

# luôn lock 5 và vote 4
TOP_WINDOWS = 5
VOTE_REQUIRED = 4
GAP = 0

WIN = 2.5
LOSS = -1

PROFIT_TARGET = 3
STOP_LOSS = -8

# guard gần nhất
RECENT_TRADE_LOOKBACK = 10
RECENT_LOSS_LIMIT = -4
RECENT_WINRATE_MIN = 0.25

# fallback chỉ lấy window không quá xấu
FALLBACK_MIN_PROFIT = -5

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
if len(groups) <= ROLLING_SCAN:
    st.error(
        f"Chưa đủ dữ liệu. Cần nhiều hơn {ROLLING_SCAN} rounds, hiện có {len(groups)}."
    )
    st.stop()

# =========================
# WINDOW EVAL
# =========================
def evaluate_window(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0

    down_streak = 0
    max_down_streak = 0
    prev_profit = 0.0
    curve = []

    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]

        if seq_groups[i - 1] != pred:
            trades += 1

            if seq_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

            curve.append(profit)

            if profit < prev_profit:
                down_streak += 1
            else:
                down_streak = 0

            max_down_streak = max(max_down_streak, down_streak)
            prev_profit = profit

    winrate = wins / trades if trades > 0 else 0.0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999.0
    ev = winrate * WIN - (1 - winrate) * abs(LOSS) if trades > 0 else -999999.0
    curve_std = float(np.std(curve)) if len(curve) > 1 else 0.0

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "ev": ev,
        "max_down_streak": max_down_streak,
        "curve_std": curve_std,
    }


# =========================
# PRIORITIZE POSITIVE PROFIT FIRST
# =========================
def select_adaptive_windows(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    ranked_df = df.sort_values(
        ["profit", "ev", "max_down_streak", "score", "winrate"],
        ascending=[False, False, True, False, False]
    ).reset_index(drop=True)

    # 1) ưu tiên window profit dương trước
    positive_df = ranked_df[ranked_df["profit"] > 0].copy()
    positive_df = positive_df.sort_values(
        ["profit", "ev", "max_down_streak", "score", "winrate"],
        ascending=[False, False, True, False, False]
    ).reset_index(drop=True)

    selected_parts = []

    if len(positive_df) > 0:
        pos_take = positive_df.head(TOP_WINDOWS).copy()
        pos_take["pick_source"] = "positive"
        selected_parts.append(pos_take)

    selected_df = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()

    # 2) nếu chưa đủ 5 thì thêm các window còn lại theo ưu tiên:
    # ev cao hơn -> profit đỡ âm hơn -> down streak thấp hơn
    if len(selected_df) < TOP_WINDOWS:
        selected_windows = set(selected_df["window"].tolist()) if not selected_df.empty else set()

        fallback_df = ranked_df[
            (~ranked_df["window"].isin(selected_windows)) &
            (ranked_df["profit"] > FALLBACK_MIN_PROFIT)
        ].copy()

        fallback_df = fallback_df.sort_values(
            ["ev", "profit", "max_down_streak", "score", "winrate"],
            ascending=[False, False, True, False, False]
        ).reset_index(drop=True)

        need = TOP_WINDOWS - len(selected_df)
        if need > 0 and len(fallback_df) > 0:
            fb_take = fallback_df.head(need).copy()
            fb_take["pick_source"] = "fallback_after_positive"
            selected_df = pd.concat([selected_df, fb_take], ignore_index=True)

    # 3) nếu vẫn thiếu thì lấy phần còn lại ít xấu nhất để đủ 5
    if len(selected_df) < TOP_WINDOWS:
        selected_windows = set(selected_df["window"].tolist()) if not selected_df.empty else set()

        remain_df = ranked_df[~ranked_df["window"].isin(selected_windows)].copy()
        remain_df = remain_df.sort_values(
            ["profit", "ev", "max_down_streak", "score", "winrate"],
            ascending=[False, False, True, False, False]
        ).reset_index(drop=True)

        need = TOP_WINDOWS - len(selected_df)
        if need > 0 and len(remain_df) > 0:
            rm_take = remain_df.head(need).copy()
            rm_take["pick_source"] = "last_resort"
            selected_df = pd.concat([selected_df, rm_take], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected_windows = selected_df["window"].astype(int).tolist()

    return selected_windows, ranked_df, selected_df


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
        "trade_profits": [],
        "history_rows": [],
        "last_scan_df_all": pd.DataFrame(),
        "last_scan_df_selected": pd.DataFrame(),
        "last_locked_windows": [],
        "is_disabled": False,
        "disable_reason": "",
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
        "trade_profits",
        "history_rows",
        "last_scan_df_all",
        "last_scan_df_selected",
        "last_locked_windows",
        "is_disabled",
        "disable_reason",
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
        "trade_profits",
        "history_rows",
        "last_scan_df_all",
        "last_scan_df_selected",
        "last_locked_windows",
        "is_disabled",
        "disable_reason",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# =========================
# RECENT GUARD
# =========================
def recent_guard(trade_profits):
    if len(trade_profits) < RECENT_TRADE_LOOKBACK:
        return False, ""

    recent = trade_profits[-RECENT_TRADE_LOOKBACK:]
    recent_profit = sum(recent)
    recent_hits = [(1 if x > 0 else 0) for x in recent]
    recent_wr = sum(recent_hits) / len(recent_hits)

    if recent_profit <= RECENT_LOSS_LIMIT:
        return True, f"Recent {RECENT_TRADE_LOOKBACK} trades profit = {recent_profit}"

    if recent_wr < RECENT_WINRATE_MIN:
        return True, f"Recent {RECENT_TRADE_LOOKBACK} trades winrate = {recent_wr:.2%}"

    return False, ""


# =========================
# INITIAL STATE
# =========================
start_index = ROLLING_SCAN

if not st.session_state.live_initialized:
    st.session_state.processed_until = ROLLING_SCAN - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# =========================
# PROCESS ONLY NEW ROUNDS
# =========================
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
trade_profits = st.session_state.trade_profits
history_rows = st.session_state.history_rows
processed_until = st.session_state.processed_until
is_disabled = st.session_state.is_disabled
disable_reason = st.session_state.disable_reason

for i in range(processed_until + 1, len(groups)):
    if i < start_index:
        continue

    # rolling adaptive lock dùng 168 round gần nhất trước round i
    train_groups = groups[i - ROLLING_SCAN:i]

    locked_windows, scan_df_all, scan_df_selected = select_adaptive_windows(train_groups)

    st.session_state.last_scan_df_all = scan_df_all
    st.session_state.last_scan_df_selected = scan_df_selected
    st.session_state.last_locked_windows = locked_windows

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        history_rows.append(
            {
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "vote": None,
                "confidence": 0,
                "signal": False,
                "trade": False,
                "bet_group": None,
                "hit": None,
                "state": "WAIT_NO_PRED",
                "profit": profit,
                "locked_windows": ", ".join(map(str, locked_windows)),
            }
        )
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]
    signal = confidence >= VOTE_REQUIRED
    distance = i - last_trade

    if profit >= PROFIT_TARGET:
        is_disabled = True
        disable_reason = f"Reached profit target {PROFIT_TARGET}"

    if profit <= STOP_LOSS:
        is_disabled = True
        disable_reason = f"Hit stop loss {STOP_LOSS}"

    guard_hit, guard_reason = recent_guard(trade_profits)
    if guard_hit:
        is_disabled = True
        disable_reason = guard_reason

    if is_disabled:
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
            trade_profit = WIN
            profit += WIN
            hits.append(1)
            trade_profits.append(trade_profit)
        else:
            hit = 0
            trade_profit = LOSS
            profit += LOSS
            hits.append(0)
            trade_profits.append(trade_profit)

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

# save state
st.session_state.profit = profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.trade_profits = trade_profits
st.session_state.history_rows = history_rows
st.session_state.processed_until = processed_until
st.session_state.is_disabled = is_disabled
st.session_state.disable_reason = disable_reason
st.session_state.base_data_len = len(groups)

hist = pd.DataFrame(history_rows)

# =========================
# NEXT BET
# =========================
next_round = len(groups)

next_locked_windows = []
next_scan_all = pd.DataFrame()
next_scan_selected = pd.DataFrame()
vote = None
confidence = 0

if next_round >= ROLLING_SCAN:
    next_train_groups = groups[next_round - ROLLING_SCAN:next_round]
    next_locked_windows, next_scan_all, next_scan_selected = select_adaptive_windows(next_train_groups)

    preds = [groups[next_round - w] for w in next_locked_windows if next_round - w >= 0]
    if preds:
        vote, confidence = Counter(preds).most_common(1)[0]

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

raw_signal = (vote is not None) and (confidence >= VOTE_REQUIRED)

next_disabled = is_disabled
next_disable_reason = disable_reason

if profit >= PROFIT_TARGET:
    next_disabled = True
    next_disable_reason = f"Reached profit target {PROFIT_TARGET}"
elif profit <= STOP_LOSS:
    next_disabled = True
    next_disable_reason = f"Hit stop loss {STOP_LOSS}"
else:
    guard_hit, guard_reason = recent_guard(trade_profits)
    if guard_hit:
        next_disabled = True
        next_disable_reason = guard_reason

if next_disabled:
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
    "locked_windows": ", ".join(map(str, next_locked_windows)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# =========================
# UI
# =========================
st.title("🎯 Adaptive Engine - Profit Positive First")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)
st.write("Rolling Scan:", ROLLING_SCAN)
st.write("Next Locked Windows:", next_locked_windows)
st.write("Vote Required:", VOTE_REQUIRED)
st.write("Profit Target:", PROFIT_TARGET)
st.write("Stop Loss:", STOP_LOSS)
st.write("Processed Until Round:", processed_until)

if next_disabled:
    st.error(f"🛑 STOP - {next_disable_reason}")
else:
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

    if can_bet and vote is not None:
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
st.dataframe(next_scan_all, use_container_width=True)

st.subheader("Adaptive Locked Window Scan")
st.dataframe(next_scan_selected, use_container_width=True)

# =========================
# HISTORY
# =========================
st.subheader("History")

def highlight_trade(row):
    if row["state"] == "NEXT":
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "STOP":
        return ["background-color: #d9534f; color:white"] * len(row)
    if row["state"] == "TRADE":
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

# =========================
# DEBUG
# =========================
st.write("Recent trade profits:", trade_profits[-RECENT_TRADE_LOOKBACK:])
st.write("Total Rows:", len(numbers))
