import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st.set_page_config(page_title="Fast Multi-Cycle Lock Engine", layout="wide")
st_autorefresh(interval=5000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 144
LOCK_ROUND_END = 180

WINDOW_MIN = 6
WINDOW_MAX = 26
TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3

VOTE_REQUIRED = 3
GAP = 0
WIN = 2.5
LOSS = -1.0

CYCLE_TARGET_PROFIT = 4.0
REENTRY_DRAWDOWN_PROFIT = -8.0

KEEP_AFTER_LOSS_ROUNDS = 4
MIN_TRADES_PER_WINDOW = 26

MAX_HISTORY_ROWS = 50
SHOW_DEBUG = st.sidebar.checkbox("Show Debug", value=False)

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=60)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={int(time.time() // 60)}"
    )
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Google Sheet phải có cột 'number'")
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

LOCK_SPAN = LOCK_ROUND_END - LOCK_ROUND_START

def get_lock_range(current_round: int):
    if current_round <= LOCK_ROUND_END:
        start = LOCK_ROUND_START
        end = min(LOCK_ROUND_END, current_round)
    else:
        end = current_round
        start = max(LOCK_ROUND_START, end - LOCK_SPAN)
    if end < start:
        end = start
    return start, end

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

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
    }

def build_window_tables(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["profit", "score", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    positive_df = df[
        (df["profit"] > 0) &
        (df["trades"] >= MIN_TRADES_PER_WINDOW)
    ].copy()

    positive_df = positive_df.sort_values(
        ["score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    selected_df = positive_df.head(TOP_WINDOWS).copy()

    if len(positive_df) >= MIN_POSITIVE_WINDOWS and len(selected_df) < TOP_WINDOWS:
        selected_windows = set(selected_df["window"].tolist()) if not selected_df.empty else set()
        remain_df = df[~df["window"].isin(selected_windows)].copy()
        remain_df = remain_df.sort_values(
            ["score", "profit", "winrate", "trades"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)
        need = TOP_WINDOWS - len(selected_df)
        if need > 0 and len(remain_df) > 0:
            selected_df = pd.concat([selected_df, remain_df.head(need)], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected_df = selected_df.sort_values(
        ["score", "profit", "winrate", "trades"],
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
    avg_score = float(selected_df["score"].mean())

    return (
        total_profit * 1.0
        + avg_winrate * 10.0
        + np.log(max(total_trades, 1.0))
        + avg_score * 0.2
    )

@st.cache_data(ttl=60)
def find_best_lock_round_cached(groups_tuple, current_round):
    all_groups = list(groups_tuple)
    lock_start, lock_end = get_lock_range(current_round)

    best_round = None
    best_score = -999999.0
    best_windows = []
    best_scan_all = []
    best_positive = []
    best_selected = []
    round_eval_rows = []

    for r in range(lock_start, lock_end + 1):
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
                best_scan_all = tmp_all.to_dict("records")
                best_positive = tmp_positive.to_dict("records")
                best_selected = tmp_selected.to_dict("records")

        round_eval_rows.append(
            {
                "lock_round": r,
                "positive_windows": pos_count,
                "selected_count": len(tmp_selected),
                "selected_windows": ", ".join(map(str, tmp_windows)),
                "round_score": round_score,
            }
        )

    return (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_rows,
        lock_start,
        lock_end,
    )

def find_best_lock_round(current_round):
    (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_rows,
        lock_start,
        lock_end,
    ) = find_best_lock_round_cached(tuple(groups), current_round)

    return (
        best_round,
        best_windows,
        pd.DataFrame(best_scan_all),
        pd.DataFrame(best_positive),
        pd.DataFrame(best_selected),
        pd.DataFrame(round_eval_rows),
        lock_start,
        lock_end,
    )

# ---------------- STATE INIT ----------------
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,

        "total_profit": 0.0,
        "cycle_profit": 0.0,
        "last_trade": -999,
        "hits": [],
        "history_rows": [],

        "locked_windows": [],
        "scan_df_all": pd.DataFrame(),
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,
        "lock_range_start": None,
        "lock_range_end": None,

        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,

        "engine_mode": "TRADE",

        "monitor_profit": 0.0,
        "monitor_last_trade": -999,
        "monitor_keep_bet_group": None,
        "monitor_keep_rounds_left": 0,
        "monitor_last_trade_was_loss": False,

        "cycle_id": 1,
        "cycle_start_round": None,
        "cycle_closed_rows": [],

        "base_data_len": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

if st.button("🔄 Reset Session"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

if (
    st.session_state.base_data_len is not None
    and len(groups) < st.session_state.base_data_len
):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ---------------- RELOCK ----------------
def relock_engine(current_round, next_cycle_id):
    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
        lock_start,
        lock_end,
    ) = find_best_lock_round(current_round)

    if lock_round_used is None:
        return False

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.lock_range_start = lock_start
    st.session_state.lock_range_end = lock_end

    st.session_state.engine_mode = "TRADE"

    st.session_state.cycle_id = next_cycle_id
    st.session_state.cycle_start_round = current_round
    st.session_state.cycle_profit = 0.0

    st.session_state.keep_bet_group = None
    st.session_state.keep_rounds_left = 0
    st.session_state.last_trade_was_loss = False

    st.session_state.monitor_profit = 0.0
    st.session_state.monitor_last_trade = -999
    st.session_state.monitor_keep_bet_group = None
    st.session_state.monitor_keep_rounds_left = 0
    st.session_state.monitor_last_trade_was_loss = False

    return True

# ---------------- INITIAL LOCK ----------------
if not st.session_state.live_initialized:
    ok = relock_engine(current_round=min(len(groups), LOCK_ROUND_END), next_cycle_id=1)
    if not ok:
        st.error("Không tìm được round lock ban đầu.")
        st.stop()

    st.session_state.processed_until = st.session_state.lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- LOAD STATE ----------------
total_profit = st.session_state.total_profit
cycle_profit = st.session_state.cycle_profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows

locked_windows = st.session_state.locked_windows
scan_df_all = st.session_state.scan_df_all
scan_df_positive = st.session_state.scan_df_positive
scan_df_selected = st.session_state.scan_df_selected
round_eval_df = st.session_state.round_eval_df
lock_round_used = st.session_state.lock_round_used
lock_range_start = st.session_state.lock_range_start
lock_range_end = st.session_state.lock_range_end

processed_until = st.session_state.processed_until

keep_bet_group = st.session_state.keep_bet_group
keep_rounds_left = st.session_state.keep_rounds_left
last_trade_was_loss = st.session_state.last_trade_was_loss

engine_mode = st.session_state.engine_mode

monitor_profit = st.session_state.monitor_profit
monitor_last_trade = st.session_state.monitor_last_trade
monitor_keep_bet_group = st.session_state.monitor_keep_bet_group
monitor_keep_rounds_left = st.session_state.monitor_keep_rounds_left
monitor_last_trade_was_loss = st.session_state.monitor_last_trade_was_loss

cycle_id = st.session_state.cycle_id
cycle_start_round = st.session_state.cycle_start_round
cycle_closed_rows = st.session_state.cycle_closed_rows

# ---------------- MAIN LOOP ----------------
for i in range(processed_until + 1, len(groups)):
    if i < lock_round_used:
        continue

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]
    new_signal = confidence >= VOTE_REQUIRED

    if engine_mode == "TRADE":
        distance = i - last_trade
        final_vote = vote
        used_keep = False

        if new_signal:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False
        else:
            if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
                final_vote = keep_bet_group
                used_keep = True

        final_signal = new_signal or used_keep
        trade = final_signal and distance >= GAP
        hit = None

        if used_keep:
            keep_rounds_left -= 1
            if keep_rounds_left < 0:
                keep_rounds_left = 0

        if trade:
            last_trade = i

            if groups[i] == final_vote:
                hit = 1
                total_profit += WIN
                cycle_profit += WIN
                hits.append(1)
                last_trade_was_loss = False
                keep_rounds_left = 0
                keep_bet_group = None
            else:
                hit = 0
                total_profit += LOSS
                cycle_profit += LOSS
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

        history_rows.append(
            {
                "cycle_id": cycle_id,
                "mode": engine_mode,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "vote": vote,
                "confidence": confidence,
                "final_vote": final_vote,
                "trade": trade,
                "hit": hit,
                "cycle_profit": cycle_profit,
                "total_profit": total_profit,
                "monitor_profit": monitor_profit,
            }
        )

        processed_until = i

        if cycle_profit >= CYCLE_TARGET_PROFIT:
            cycle_hits = [x["hit"] for x in history_rows if x["cycle_id"] == cycle_id and x["hit"] in (0, 1)]
            cycle_trades = len(cycle_hits)
            cycle_wr = round(float(np.mean(cycle_hits) * 100), 2) if cycle_hits else 0.0

            cycle_closed_rows.append(
                {
                    "cycle_id": cycle_id,
                    "cycle_start_round": cycle_start_round,
                    "cycle_end_round": i,
                    "lock_round_used": lock_round_used,
                    "lock_range": f"{lock_range_start}->{lock_range_end}",
                    "locked_windows": ", ".join(map(str, locked_windows)),
                    "cycle_profit": cycle_profit,
                    "trades": cycle_trades,
                    "winrate_pct": cycle_wr,
                    "status": "TARGET_HIT",
                    "total_profit_after_cycle": total_profit,
                }
            )

            engine_mode = "WAIT_DROP"
            monitor_profit = 0.0
            monitor_last_trade = -999
            monitor_keep_bet_group = None
            monitor_keep_rounds_left = 0
            monitor_last_trade_was_loss = False

    else:
        monitor_distance = i - monitor_last_trade
        monitor_final_vote = vote
        monitor_used_keep = False

        if new_signal:
            monitor_keep_rounds_left = 0
            monitor_keep_bet_group = None
            monitor_last_trade_was_loss = False
        else:
            if (
                monitor_last_trade_was_loss
                and monitor_keep_rounds_left > 0
                and monitor_keep_bet_group is not None
            ):
                monitor_final_vote = monitor_keep_bet_group
                monitor_used_keep = True

        monitor_signal = new_signal or monitor_used_keep
        monitor_trade = monitor_signal and monitor_distance >= GAP

        if monitor_used_keep:
            monitor_keep_rounds_left -= 1
            if monitor_keep_rounds_left < 0:
                monitor_keep_rounds_left = 0

        if monitor_trade:
            monitor_last_trade = i

            if groups[i] == monitor_final_vote:
                monitor_profit += WIN
                monitor_last_trade_was_loss = False
                monitor_keep_rounds_left = 0
                monitor_keep_bet_group = None
            else:
                monitor_profit += LOSS

                if monitor_used_keep:
                    if monitor_keep_rounds_left <= 0:
                        monitor_last_trade_was_loss = False
                        monitor_keep_bet_group = None
                    else:
                        monitor_last_trade_was_loss = True
                else:
                    monitor_last_trade_was_loss = True
                    monitor_keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                    monitor_keep_bet_group = monitor_final_vote

        history_rows.append(
            {
                "cycle_id": cycle_id,
                "mode": engine_mode,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "vote": vote,
                "confidence": confidence,
                "final_vote": monitor_final_vote,
                "trade": False,
                "hit": None,
                "cycle_profit": cycle_profit,
                "total_profit": total_profit,
                "monitor_profit": monitor_profit,
            }
        )

        processed_until = i

        if monitor_profit <= REENTRY_DRAWDOWN_PROFIT:
            ok = relock_engine(current_round=i, next_cycle_id=cycle_id + 1)
            if ok:
                locked_windows = st.session_state.locked_windows
                scan_df_all = st.session_state.scan_df_all
                scan_df_positive = st.session_state.scan_df_positive
                scan_df_selected = st.session_state.scan_df_selected
                round_eval_df = st.session_state.round_eval_df
                lock_round_used = st.session_state.lock_round_used
                lock_range_start = st.session_state.lock_range_start
                lock_range_end = st.session_state.lock_range_end
                engine_mode = st.session_state.engine_mode
                cycle_id = st.session_state.cycle_id
                cycle_start_round = st.session_state.cycle_start_round
                cycle_profit = st.session_state.cycle_profit
                keep_bet_group = st.session_state.keep_bet_group
                keep_rounds_left = st.session_state.keep_rounds_left
                last_trade_was_loss = st.session_state.last_trade_was_loss
                monitor_profit = st.session_state.monitor_profit
                monitor_last_trade = st.session_state.monitor_last_trade
                monitor_keep_bet_group = st.session_state.monitor_keep_bet_group
                monitor_keep_rounds_left = st.session_state.monitor_keep_rounds_left
                monitor_last_trade_was_loss = st.session_state.monitor_last_trade_was_loss

# ---------------- SAVE STATE ----------------
st.session_state.total_profit = total_profit
st.session_state.cycle_profit = cycle_profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.history_rows = history_rows
st.session_state.locked_windows = locked_windows
st.session_state.scan_df_all = scan_df_all
st.session_state.scan_df_positive = scan_df_positive
st.session_state.scan_df_selected = scan_df_selected
st.session_state.round_eval_df = round_eval_df
st.session_state.lock_round_used = lock_round_used
st.session_state.lock_range_start = lock_range_start
st.session_state.lock_range_end = lock_range_end
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)
st.session_state.keep_bet_group = keep_bet_group
st.session_state.keep_rounds_left = keep_rounds_left
st.session_state.last_trade_was_loss = last_trade_was_loss
st.session_state.engine_mode = engine_mode
st.session_state.monitor_profit = monitor_profit
st.session_state.monitor_last_trade = monitor_last_trade
st.session_state.monitor_keep_bet_group = monitor_keep_bet_group
st.session_state.monitor_keep_rounds_left = monitor_keep_rounds_left
st.session_state.monitor_last_trade_was_loss = monitor_last_trade_was_loss
st.session_state.cycle_id = cycle_id
st.session_state.cycle_start_round = cycle_start_round
st.session_state.cycle_closed_rows = cycle_closed_rows

hist = pd.DataFrame(history_rows)
cycle_df = pd.DataFrame(cycle_closed_rows)

# ---------------- NEXT BET ----------------
next_round = len(groups)
preds = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None
final_vote = vote
can_bet = False

if engine_mode == "TRADE":
    if not hist.empty:
        last_trade_rows = hist[(hist["trade"] == True) & (hist["mode"] == "TRADE")]
        distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
    else:
        distance = 999

    new_signal = confidence >= VOTE_REQUIRED if vote is not None else False
    used_keep_next = False

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
    can_bet = final_signal and distance >= GAP
    next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"
else:
    next_keep_bet_group = monitor_keep_bet_group
    next_keep_rounds_left = monitor_keep_rounds_left
    next_state = "WAIT_DROP"

# ---------------- UI ----------------
st.title("⚡ Fast Multi-Cycle Lock Engine")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Current Number", current_number if current_number is not None else "-")
m2.metric("Current Group", current_group if current_group is not None else "-")
m3.metric("Next Group", final_vote if final_vote is not None else "-")
m4.metric("Mode", engine_mode)

s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit", total_profit)
s2.metric("Cycle Profit", cycle_profit)
s3.metric("Monitor Profit", monitor_profit)
s4.metric("Closed Cycles", len(cycle_closed_rows))

st.write("Locked Windows:", locked_windows)
st.write("Lock Range:", f"{lock_range_start} -> {lock_range_end}")
st.write("Lock Round Used:", lock_round_used)
st.write("Cycle ID:", cycle_id)
st.write("Cycle Start Round:", cycle_start_round)

if engine_mode == "WAIT_DROP":
    st.warning(
        f"WAIT_DROP MODE: đã chốt +{CYCLE_TARGET_PROFIT}, đang chờ monitor_profit <= {REENTRY_DRAWDOWN_PROFIT}. "
        f"Monitor Profit hiện tại: {monitor_profit}"
    )
elif can_bet and final_vote is not None:
    st.error(f"BET GROUP → {final_vote}")
else:
    st.info("WAIT")

st.subheader("Profit Curve - Total")
if not hist.empty:
    st.line_chart(hist["total_profit"].ffill().tail(150))

st.subheader("Profit Curve - Cycle / Monitor")
if not hist.empty:
    if engine_mode == "TRADE":
        st.line_chart(hist["cycle_profit"].ffill().tail(150))
    else:
        st.line_chart(hist["monitor_profit"].ffill().tail(150))

st.subheader("Cycle Summary")
if not cycle_df.empty:
    st.dataframe(cycle_df.iloc[::-1].head(20), use_container_width=True)
else:
    st.info("Chưa có chu kỳ nào đóng.")

st.subheader("History")
if not hist.empty:
    st.dataframe(hist.iloc[::-1].head(MAX_HISTORY_ROWS), use_container_width=True)

if SHOW_DEBUG:
    st.subheader("Round Evaluation")
    st.dataframe(round_eval_df.head(20), use_container_width=True)

    st.subheader("Window Scan All")
    st.dataframe(scan_df_all.head(20), use_container_width=True)

    st.subheader("All Positive Windows")
    st.dataframe(scan_df_positive.head(20), use_container_width=True)

    st.subheader("Locked Windows Table")
    st.dataframe(scan_df_selected.head(20), use_container_width=True)
