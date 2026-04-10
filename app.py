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

# bắt đầu tìm lock từ round này
START_FIND_ROUND = 168

WINDOW_MIN = 6
WINDOW_MAX = 18

TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3
VOTE_REQUIRED = 3
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 10

# KEEP: tổng cộng 4 vòng, tính luôn vòng trade thua
KEEP_AFTER_LOSS_ROUNDS = 4

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
if len(groups) <= START_FIND_ROUND:
    st.error(
        f"Chưa đủ dữ liệu. Cần nhiều hơn {START_FIND_ROUND} rounds, hiện có {len(groups)}."
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

    df = pd.DataFrame(rows)

    # bảng full
    df_all = df.sort_values(
        ["profit", "score", "winrate"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    # nhóm profit dương
    positive_df = df[df["profit"] > 0].copy()
    positive_df = positive_df.sort_values(
        ["score", "profit", "winrate"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    # chọn tối đa 4 window dương
    selected_df = positive_df.head(TOP_WINDOWS).copy()

    # nếu có >=3 window dương nhưng chưa đủ 4 thì lấy thêm window tốt nhất còn lại
    if len(positive_df) >= MIN_POSITIVE_WINDOWS and len(selected_df) < TOP_WINDOWS:
        selected_windows = set(selected_df["window"].tolist()) if not selected_df.empty else set()

        remain_df = df[~df["window"].isin(selected_windows)].copy()
        remain_df = remain_df.sort_values(
            ["score", "profit", "winrate"],
            ascending=[False, False, False]
        ).reset_index(drop=True)

        need = TOP_WINDOWS - len(selected_df)
        if need > 0 and len(remain_df) > 0:
            selected_df = pd.concat([selected_df, remain_df.head(need)], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected_df = selected_df.sort_values(
        ["score", "profit", "winrate"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    selected = selected_df["window"].astype(int).tolist()

    return selected, df_all, positive_df, selected_df

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
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "lock_round_used": None,
        "base_data_len": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
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
        "scan_df_positive",
        "scan_df_selected",
        "lock_round_used",
        "base_data_len",
        "keep_bet_group",
        "keep_rounds_left",
        "last_trade_was_loss",
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
        "scan_df_positive",
        "scan_df_selected",
        "lock_round_used",
        "base_data_len",
        "keep_bet_group",
        "keep_rounds_left",
        "last_trade_was_loss",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- FIND LOCK ROUND FROM 168 ----------------
if not st.session_state.live_initialized:
    lock_round_used = None
    locked_windows = []
    scan_df_all = pd.DataFrame()
    scan_df_positive = pd.DataFrame()
    scan_df_selected = pd.DataFrame()

    for r in range(START_FIND_ROUND, len(groups) + 1):
        train_groups = groups[:r]
        tmp_windows, tmp_all, tmp_positive, tmp_selected = select_windows_from_train(train_groups)

        if len(tmp_positive) >= MIN_POSITIVE_WINDOWS:
            lock_round_used = r
            locked_windows = tmp_windows
            scan_df_all = tmp_all
            scan_df_positive = tmp_positive
            scan_df_selected = tmp_selected
            break

    if lock_round_used is None:
        st.error(
            f"Không tìm được round nào từ {START_FIND_ROUND} trở đi có ít nhất {MIN_POSITIVE_WINDOWS} window profit dương để lock."
        )
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.lock_round_used = lock_round_used
    st.session_state.processed_until = lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
scan_df_all = st.session_state.scan_df_all
scan_df_positive = st.session_state.scan_df_positive
scan_df_selected = st.session_state.scan_df_selected
lock_round_used = st.session_state.lock_round_used
processed_until = st.session_state.processed_until

keep_bet_group = st.session_state.keep_bet_group
keep_rounds_left = st.session_state.keep_rounds_left
last_trade_was_loss = st.session_state.last_trade_was_loss

for i in range(processed_until + 1, len(groups)):
    if i < lock_round_used:
        continue

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]
    new_signal = confidence >= VOTE_REQUIRED
    distance = i - last_trade

    final_vote = vote
    used_keep = False

    # có signal mới -> bỏ keep ngay
    if new_signal:
        keep_rounds_left = 0
        keep_bet_group = None
        last_trade_was_loss = False
        final_vote = vote
    else:
        # không có signal mới -> nếu đang keep thì dùng keep
        if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
            final_vote = keep_bet_group
            used_keep = True

    final_signal = new_signal or used_keep

    if profit >= PROFIT_TARGET:
        final_signal = False
        trade = False
        can_bet = False
        state = "STOP"
    else:
        trade = final_signal and distance >= GAP
        can_bet = trade
        if trade and used_keep:
            state = "TRADE_KEEP"
        elif trade:
            state = "TRADE"
        elif new_signal:
            state = "SIGNAL"
        elif used_keep:
            state = "KEEP_WAIT"
        else:
            state = "WAIT"

    bet_group = final_vote if can_bet else None
    hit = None

    # dùng keep ở round này thì trừ keep ngay
    if used_keep:
        keep_rounds_left -= 1
        if keep_rounds_left < 0:
            keep_rounds_left = 0

    if trade:
        last_trade = i

        if groups[i] == final_vote:
            hit = 1
            profit += WIN
            hits.append(1)

            # thắng thì tắt keep
            last_trade_was_loss = False
            keep_rounds_left = 0
            keep_bet_group = None
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

            if used_keep:
                # đang keep mà vẫn thua
                if keep_rounds_left <= 0:
                    last_trade_was_loss = False
                    keep_bet_group = None
                else:
                    last_trade_was_loss = True
            else:
                # thua mới -> bật keep
                # tổng keep = 4, tính luôn round thua
                last_trade_was_loss = True
                keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                keep_bet_group = final_vote
    else:
        if used_keep and keep_rounds_left <= 0:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False

    history_rows.append(
        {
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "vote": vote,
            "confidence": confidence,
            "new_signal": new_signal,
            "used_keep": used_keep,
            "keep_group": keep_bet_group,
            "keep_left": keep_rounds_left,
            "final_vote": final_vote,
            "signal": final_signal,
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
st.session_state.scan_df_positive = scan_df_positive
st.session_state.scan_df_selected = scan_df_selected
st.session_state.lock_round_used = lock_round_used
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)
st.session_state.keep_bet_group = keep_bet_group
st.session_state.keep_rounds_left = keep_rounds_left
st.session_state.last_trade_was_loss = last_trade_was_loss

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

new_signal = confidence >= VOTE_REQUIRED if vote is not None else False
used_keep_next = False
final_vote = vote

if new_signal:
    next_keep_bet_group = None
    next_keep_rounds_left = 0
else:
    next_keep_bet_group = keep_bet_group
    next_keep_rounds_left = keep_rounds_left
    if last_trade_was_loss and next_keep_rounds_left > 0 and next_keep_bet_group is not None:
        final_vote = next_keep_bet_group
        used_keep_next = True

final_signal = new_signal or used_keep_next

if profit >= PROFIT_TARGET:
    signal = False
    can_bet = False
    next_state = "STOP"
else:
    signal = final_signal
    can_bet = signal and distance >= GAP
    next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "new_signal": new_signal,
    "used_keep": used_keep_next,
    "keep_group": next_keep_bet_group,
    "keep_left": next_keep_rounds_left,
    "final_vote": final_vote,
    "signal": signal,
    "trade": False,
    "bet_group": final_vote if can_bet else None,
    "hit": None,
    "state": next_state,
    "profit": profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Lock from round 168 when >=3 positive windows -> trade 4 vote 3 + keep")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", final_vote if final_vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Locked Windows:", locked_windows)
st.write("Locked Window Count:", len(locked_windows))
st.write("Vote Required:", VOTE_REQUIRED)
st.write("Start Find Round:", START_FIND_ROUND)
st.write("Lock Round Used:", lock_round_used)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Profit Target:", PROFIT_TARGET)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Processed Until Round:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;
    padding:20px;
    border-radius:10px;
    text-align:center;
    font-size:28px;
    font-weight:bold;">
    NEXT GROUP → {final_vote if final_vote is not None else "-"} (Vote Strength: {confidence})
    </div>
    """,
    unsafe_allow_html=True,
)

if profit >= PROFIT_TARGET:
    st.error(f"🛑 STOP - Reached Profit Target {PROFIT_TARGET}")
elif can_bet and final_vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;
        padding:25px;
        border-radius:10px;
        text-align:center;
        font-size:32px;
        color:white;
        font-weight:bold;">
        BET GROUP → {final_vote}
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
st.subheader("Window Scan All")
st.dataframe(scan_df_all, use_container_width=True)

st.subheader("All Positive Windows")
st.dataframe(scan_df_positive, use_container_width=True)

st.subheader("Locked Windows")
st.dataframe(scan_df_selected, use_container_width=True)

# ---------------- HISTORY ----------------
st.subheader("History")

def highlight_trade(row):
    if row["state"] in ("NEXT", "NEXT_KEEP"):
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "STOP":
        return ["background-color: #d9534f; color:white"] * len(row)
    if row["state"] == "TRADE_KEEP":
        return ["background-color: #ffb347; color:black"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

# ---------------- DEBUG ----------------
st.write("Locked Windows:", locked_windows)
st.write("Total Rows:", len(numbers))
