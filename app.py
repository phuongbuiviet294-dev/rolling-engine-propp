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

# tìm round lock tốt nhất trong khoảng này
LOCK_ROUND_START = 144
LOCK_ROUND_END = 180

# tối ưu lại: ưu tiên window ngắn-trung bình
WINDOW_MIN = 6
WINDOW_MAX = 18

TOP_WINDOWS = 4
VOTE_REQUIRED = 3
MIN_POSITIVE_WINDOWS = 3
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 30
STOP_LOSS = -10

# keep tổng cộng 4 vòng, tính luôn vòng trade thua
KEEP_AFTER_LOSS_ROUNDS = 4

# bộ lọc mạnh hơn
MIN_PROFIT_STRONG = 5.0
MIN_WINRATE_STRONG = 0.31
MIN_TRADES_STRONG = 80

# fallback nhẹ nếu chưa đủ 4 window
MIN_PROFIT_WEAK = 0.0
MIN_WINRATE_WEAK = 0.29
MIN_TRADES_WEAK = 60

# phạt window dài mạnh hơn
WINDOW_PENALTY = 0.60

# ép diversity mạnh hơn
MIN_WINDOW_GAP = 4

# nếu 5 lệnh gần nhất <= 1 win thì dừng
RECENT_HITS_CHECK = 26
RECENT_HITS_MIN_WIN = 1

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
if len(groups) <= LOCK_ROUND_START:
    st.error(
        f"Chưa đủ dữ liệu. Cần nhiều hơn {LOCK_ROUND_START} rounds, hiện có {len(groups)}."
    )
    st.stop()

effective_lock_round_end = min(LOCK_ROUND_END, len(groups))
if effective_lock_round_end < LOCK_ROUND_START:
    st.error("Khoảng round lock không hợp lệ.")
    st.stop()

# ---------------- WINDOW EVAL ----------------
def evaluate_window(seq_groups, w):
    profit = 0.0
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

    winrate = wins / trades if trades > 0 else 0.0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999.0
    adjusted_score = score - WINDOW_PENALTY * w

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "adjusted_score": adjusted_score,
    }

def pick_diverse_windows(df_source: pd.DataFrame, selected_rows: list, selected_windows: set, max_count: int):
    if df_source.empty:
        return selected_rows, selected_windows

    for _, row in df_source.iterrows():
        w = int(row["window"])
        if w in selected_windows:
            continue

        if all(abs(w - int(r["window"])) >= MIN_WINDOW_GAP for r in selected_rows):
            selected_rows.append(row.to_dict())
            selected_windows.add(w)

        if len(selected_rows) >= max_count:
            break

    return selected_rows, selected_windows

def build_window_tables(train_groups):
    rows = []
    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        rows.append(evaluate_window(train_groups, w))

    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["adjusted_score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    positive_df = df[df["profit"] > 0].copy()
    positive_df = positive_df.sort_values(
        ["adjusted_score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    strong_df = df[
        (df["profit"] >= MIN_PROFIT_STRONG) &
        (df["winrate"] >= MIN_WINRATE_STRONG) &
        (df["trades"] >= MIN_TRADES_STRONG)
    ].copy()

    strong_df = strong_df.sort_values(
        ["adjusted_score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    weak_df = df[
        (df["profit"] > MIN_PROFIT_WEAK) &
        (df["winrate"] >= MIN_WINRATE_WEAK) &
        (df["trades"] >= MIN_TRADES_WEAK)
    ].copy()

    weak_df = weak_df.sort_values(
        ["adjusted_score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    selected_rows = []
    selected_windows = set()

    selected_rows, selected_windows = pick_diverse_windows(
        strong_df, selected_rows, selected_windows, TOP_WINDOWS
    )

    if len(selected_rows) < TOP_WINDOWS:
        selected_rows, selected_windows = pick_diverse_windows(
            weak_df, selected_rows, selected_windows, TOP_WINDOWS
        )

    if len(selected_rows) < TOP_WINDOWS:
        selected_rows, selected_windows = pick_diverse_windows(
            df_all, selected_rows, selected_windows, TOP_WINDOWS
        )

    selected_df = pd.DataFrame(selected_rows)
    if not selected_df.empty:
        selected_df = selected_df.sort_values(
            ["adjusted_score", "profit", "winrate", "trades"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

    selected = selected_df["window"].astype(int).tolist() if not selected_df.empty else []

    return selected, df_all, positive_df, selected_df

def calc_round_score(selected_df: pd.DataFrame) -> float:
    if selected_df.empty:
        return -999999.0

    total_profit = float(selected_df["profit"].sum())
    avg_winrate = float(selected_df["winrate"].mean())
    total_trades = float(selected_df["trades"].sum())
    avg_adjusted_score = float(selected_df["adjusted_score"].mean())
    avg_window = float(selected_df["window"].mean())

    round_score = (
        total_profit * 1.4
        + avg_winrate * 14.0
        + np.log(max(total_trades, 1.0))
        + avg_adjusted_score * 0.40
        - avg_window * 0.08
    )
    return round_score

def find_best_lock_round(all_groups):
    best_round = None
    best_score = -999999.0
    best_windows = []
    best_scan_all = pd.DataFrame()
    best_positive = pd.DataFrame()
    best_selected = pd.DataFrame()

    round_eval_rows = []

    for r in range(LOCK_ROUND_START, effective_lock_round_end + 1):
        train_groups = all_groups[:r]
        tmp_windows, tmp_all, tmp_positive, tmp_selected = build_window_tables(train_groups)

        pos_count = len(tmp_positive)
        round_score = -999999.0

        if pos_count >= MIN_POSITIVE_WINDOWS and not tmp_selected.empty:
            round_score = calc_round_score(tmp_selected)

            if round_score > best_score:
                best_score = round_score
                best_round = r
                best_windows = tmp_windows
                best_scan_all = tmp_all
                best_positive = tmp_positive
                best_selected = tmp_selected

        round_eval_rows.append(
            {
                "lock_round": r,
                "positive_windows": pos_count,
                "selected_count": len(tmp_selected),
                "selected_windows": ", ".join(map(str, tmp_windows)),
                "round_score": round_score,
            }
        )

    round_eval_df = pd.DataFrame(round_eval_rows).sort_values(
        ["round_score", "positive_windows", "lock_round"],
        ascending=[False, False, True]
    ).reset_index(drop=True)

    return (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_df,
    )

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
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,
        "base_data_len": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "stop_due_to_loss": False,
        "stop_due_to_recent_hits": False,
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
        "round_eval_df",
        "lock_round_used",
        "base_data_len",
        "keep_bet_group",
        "keep_rounds_left",
        "last_trade_was_loss",
        "stop_due_to_loss",
        "stop_due_to_recent_hits",
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
        "round_eval_df",
        "lock_round_used",
        "base_data_len",
        "keep_bet_group",
        "keep_rounds_left",
        "last_trade_was_loss",
        "stop_due_to_loss",
        "stop_due_to_recent_hits",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- FIND BEST LOCK ROUND ----------------
if not st.session_state.live_initialized:
    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
    ) = find_best_lock_round(groups)

    if lock_round_used is None:
        st.error(
            f"Không tìm được round nào từ {LOCK_ROUND_START} đến {effective_lock_round_end} có ít nhất {MIN_POSITIVE_WINDOWS} window profit dương."
        )
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
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
round_eval_df = st.session_state.round_eval_df
lock_round_used = st.session_state.lock_round_used
processed_until = st.session_state.processed_until
stop_due_to_loss = st.session_state.stop_due_to_loss
stop_due_to_recent_hits = st.session_state.stop_due_to_recent_hits

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

    if new_signal:
        keep_rounds_left = 0
        keep_bet_group = None
        last_trade_was_loss = False
        final_vote = vote
    else:
        if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
            final_vote = keep_bet_group
            used_keep = True

    final_signal = new_signal or used_keep

    if profit >= PROFIT_TARGET:
        final_signal = False
        trade = False
        can_bet = False
        state = "STOP_TARGET"
    elif profit <= STOP_LOSS:
        stop_due_to_loss = True
        final_signal = False
        trade = False
        can_bet = False
        state = "STOP_LOSS"
    elif stop_due_to_recent_hits:
        final_signal = False
        trade = False
        can_bet = False
        state = "STOP_RECENT_HITS"
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

            last_trade_was_loss = False
            keep_rounds_left = 0
            keep_bet_group = None
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

            if used_keep:
                if keep_rounds_left <= 0:
                    last_trade_was_loss = False
                    keep_bet_group = None
                else:
                    last_trade_was_loss = True
            else:
                last_trade_was_loss = True
                keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                keep_bet_group = final_vote

        if len(hits) >= RECENT_HITS_CHECK and sum(hits[-RECENT_HITS_CHECK:]) <= RECENT_HITS_MIN_WIN:
            stop_due_to_recent_hits = True

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
st.session_state.round_eval_df = round_eval_df
st.session_state.lock_round_used = lock_round_used
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)
st.session_state.keep_bet_group = keep_bet_group
st.session_state.keep_rounds_left = keep_rounds_left
st.session_state.last_trade_was_loss = last_trade_was_loss
st.session_state.stop_due_to_loss = stop_due_to_loss
st.session_state.stop_due_to_recent_hits = stop_due_to_recent_hits

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
    next_state = "STOP_TARGET"
elif profit <= STOP_LOSS:
    signal = False
    can_bet = False
    next_state = "STOP_LOSS"
elif stop_due_to_recent_hits:
    signal = False
    can_bet = False
    next_state = "STOP_RECENT_HITS"
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
st.title("🎯 Optimized 6-18 Lock + 4 vote 3 + Keep")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", final_vote if final_vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Locked Windows:", locked_windows)
st.write("Locked Window Count:", len(locked_windows))
st.write("Vote Required:", VOTE_REQUIRED)
st.write("Lock Round Range:", f"{LOCK_ROUND_START} -> {effective_lock_round_end}")
st.write("Lock Round Used:", lock_round_used)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Window Range:", f"{WINDOW_MIN} -> {WINDOW_MAX}")
st.write("Min Trades Strong:", MIN_TRADES_STRONG)
st.write("Window Penalty:", WINDOW_PENALTY)
st.write("Min Window Gap:", MIN_WINDOW_GAP)
st.write("Profit Target:", PROFIT_TARGET)
st.write("Stop Loss:", STOP_LOSS)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Stop Recent Hits:", stop_due_to_recent_hits)
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
elif profit <= STOP_LOSS:
    st.error(f"🛑 STOP - Hit Stop Loss {STOP_LOSS}")
elif stop_due_to_recent_hits:
    st.error(f"🛑 STOP - Last {RECENT_HITS_CHECK} trades <= {RECENT_HITS_MIN_WIN} win")
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

# ---------------- ROUND EVAL ----------------
st.subheader("Round Evaluation")
st.dataframe(round_eval_df, use_container_width=True)

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
    if row["state"] in ("STOP_TARGET", "STOP_LOSS", "STOP_RECENT_HITS"):
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
