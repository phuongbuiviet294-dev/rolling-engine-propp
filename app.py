import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1500, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# vùng lock gốc ban đầu
LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

WINDOW_MIN = 6
WINDOW_MAX = 26

TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3
VOTE_REQUIRED = 3
GAP = 1

WIN = 2.5
LOSS = -1.0

# relock theo chu kỳ
CYCLE_PROFIT_TARGET = 6.0
CYCLE_LOSS_TARGET = -8.0

# keep sau thua
KEEP_AFTER_LOSS_ROUNDS = 2

# thua 2 lệnh liên tiếp thì nghỉ
PAUSE_AFTER_2_LOSSES = 4

# lọc window tránh ăn may
MIN_TRADES_PER_WINDOW = 30

# ================= LOAD DATA =================
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url, usecols=["number"])
    df.columns = ["number"]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

# ================= GROUP =================
def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

groups = [group(n) for n in numbers]

# ================= GUARD =================
if len(groups) <= LOCK_ROUND_START:
    st.error(
        f"Chưa đủ dữ liệu. Cần nhiều hơn {LOCK_ROUND_START} rounds, hiện có {len(groups)}."
    )
    st.stop()

LOCK_SPAN = LOCK_ROUND_END - LOCK_ROUND_START

def get_dynamic_lock_range(current_round: int, max_len: int):
    """
    Lần đầu ưu tiên vùng 168 -> 180.
    Các lần relock sau sẽ trượt vùng lock theo round hiện tại.
    """
    if current_round <= LOCK_ROUND_END:
        start = LOCK_ROUND_START
        end = min(LOCK_ROUND_END, max_len)
    else:
        end = min(current_round, max_len)
        start = max(LOCK_ROUND_START, end - LOCK_SPAN)

    if end < start:
        end = start
    return start, end

# ================= WINDOW EVAL =================
def evaluate_window(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0

    s = seq_groups
    n = len(s)
    for i in range(w, n):
        pred = s[i - w]
        if s[i - 1] != pred:
            trades += 1
            if s[i] == pred:
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
        total_profit
        + avg_winrate * 10.0
        + np.log(max(total_trades, 1.0))
        + avg_score * 0.2
    )

def find_best_lock_round(all_groups, current_round):
    lock_start, lock_end = get_dynamic_lock_range(current_round, len(all_groups))

    best_round = None
    best_score = -999999.0
    best_windows = []
    best_scan_all = pd.DataFrame()
    best_positive = pd.DataFrame()
    best_selected = pd.DataFrame()
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
        lock_start,
        lock_end,
    )

# ================= STATE INIT =================
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,

        # tổng
        "total_profit": 0.0,
        "last_trade": -999,
        "hits": [],

        # chu kỳ hiện tại
        "cycle_profit": 0.0,
        "cycle_id": 1,
        "cycle_start_round": None,
        "cycle_closed_count": 0,

        # history
        "history_rows": [],
        "cycle_summary_rows": [],

        # lock
        "locked_windows": [],
        "scan_df_all": pd.DataFrame(),
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,
        "lock_range_start": None,
        "lock_range_end": None,

        "base_data_len": None,

        # keep / pause
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "consecutive_losses": 0,
        "pause_rounds_left": 0,

        # relock
        "relock_count": 0,
        "last_relock_round": None,
        "last_relock_reason": None,
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ================= RESET =================
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

# ================= HELPERS =================
def run_relock(current_round: int, reason: str):
    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
        lock_range_start,
        lock_range_end,
    ) = find_best_lock_round(groups, current_round)

    if lock_round_used is None or not locked_windows:
        return False, None

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.lock_range_start = lock_range_start
    st.session_state.lock_range_end = lock_range_end

    # reset tactical state
    st.session_state.keep_bet_group = None
    st.session_state.keep_rounds_left = 0
    st.session_state.last_trade_was_loss = False
    st.session_state.consecutive_losses = 0
    st.session_state.pause_rounds_left = 0

    st.session_state.relock_count += 1
    st.session_state.last_relock_round = current_round
    st.session_state.last_relock_reason = reason

    return True, {
        "relock_round": current_round,
        "reason": reason,
        "lock_round_used": lock_round_used,
        "lock_range_start": lock_range_start,
        "lock_range_end": lock_range_end,
        "locked_windows": ", ".join(map(str, locked_windows)),
    }

def close_cycle(end_round: int, reason: str):
    st.session_state.cycle_summary_rows.append(
        {
            "cycle_id": st.session_state.cycle_id,
            "cycle_start_round": st.session_state.cycle_start_round,
            "cycle_end_round": end_round,
            "lock_round_used": st.session_state.lock_round_used,
            "lock_range": f"{st.session_state.lock_range_start}->{st.session_state.lock_range_end}",
            "locked_windows": ", ".join(map(str, st.session_state.locked_windows)),
            "cycle_profit": st.session_state.cycle_profit,
            "close_reason": reason,
        }
    )
    st.session_state.cycle_closed_count += 1

def start_new_cycle(start_round: int):
    st.session_state.cycle_id += 1
    st.session_state.cycle_profit = 0.0
    st.session_state.cycle_start_round = start_round

# ================= INITIAL LOCK =================
if not st.session_state.live_initialized:
    ok, info = run_relock(min(len(groups), LOCK_ROUND_END), "INITIAL")
    if not ok:
        st.error("Không tìm được bộ window phù hợp ở lần lock đầu.")
        st.stop()

    st.session_state.processed_until = st.session_state.lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True
    st.session_state.cycle_start_round = st.session_state.lock_round_used

# ================= LOAD LOCAL STATE =================
total_profit = st.session_state.total_profit
cycle_profit = st.session_state.cycle_profit
cycle_id = st.session_state.cycle_id
cycle_start_round = st.session_state.cycle_start_round
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
consecutive_losses = st.session_state.consecutive_losses
pause_rounds_left = st.session_state.pause_rounds_left

relock_count = st.session_state.relock_count
last_relock_round = st.session_state.last_relock_round
last_relock_reason = st.session_state.last_relock_reason

# ================= MAIN LOOP =================
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
    trade = False
    can_bet = False
    bet_group = None
    hit = None
    state = "WAIT"
    relock_event = ""

    if pause_rounds_left > 0:
        pause_rounds_left -= 1
        state = "PAUSE"

        history_rows.append(
            {
                "cycle_id": cycle_id,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "vote": vote,
                "confidence": confidence,
                "new_signal": new_signal,
                "used_keep": False,
                "keep_group": None,
                "keep_left": 0,
                "final_vote": final_vote,
                "signal": False,
                "trade": False,
                "bet_group": None,
                "hit": None,
                "state": state,
                "total_profit": total_profit,
                "cycle_profit": cycle_profit,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "consecutive_losses": consecutive_losses,
                "pause_left": pause_rounds_left,
                "lock_round_used": lock_round_used,
                "lock_range": f"{lock_range_start}->{lock_range_end}",
                "relock_event": "",
            }
        )
        processed_until = i
        continue

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
            consecutive_losses = 0
        else:
            hit = 0
            total_profit += LOSS
            cycle_profit += LOSS
            hits.append(0)
            consecutive_losses += 1

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

            if consecutive_losses >= 2:
                pause_rounds_left = PAUSE_AFTER_2_LOSSES
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False
                consecutive_losses = 0
                state = "PAUSE_TRIGGER"

    else:
        if used_keep and keep_rounds_left <= 0:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False

    # relock theo chu kỳ: +6 hoặc -8
    need_relock = False
    relock_reason = None

    if cycle_profit >= CYCLE_PROFIT_TARGET:
        need_relock = True
        relock_reason = "TARGET_REACHED"
    elif cycle_profit <= CYCLE_LOSS_TARGET:
        need_relock = True
        relock_reason = "LOSS_REACHED"

    if need_relock:
        close_cycle(i, relock_reason)

        ok, info = run_relock(i, relock_reason)
        if ok:
            relock_event = f"relock@{i}"
            state = "RELOCK_TARGET" if relock_reason == "TARGET_REACHED" else "RELOCK_LOSS"

            locked_windows = st.session_state.locked_windows
            scan_df_all = st.session_state.scan_df_all
            scan_df_positive = st.session_state.scan_df_positive
            scan_df_selected = st.session_state.scan_df_selected
            round_eval_df = st.session_state.round_eval_df
            lock_round_used = st.session_state.lock_round_used
            lock_range_start = st.session_state.lock_range_start
            lock_range_end = st.session_state.lock_range_end
            keep_bet_group = st.session_state.keep_bet_group
            keep_rounds_left = st.session_state.keep_rounds_left
            last_trade_was_loss = st.session_state.last_trade_was_loss
            consecutive_losses = st.session_state.consecutive_losses
            pause_rounds_left = st.session_state.pause_rounds_left
            relock_count = st.session_state.relock_count
            last_relock_round = st.session_state.last_relock_round
            last_relock_reason = st.session_state.last_relock_reason

            start_new_cycle(i + 1)
            cycle_id = st.session_state.cycle_id
            cycle_profit = st.session_state.cycle_profit
            cycle_start_round = st.session_state.cycle_start_round

    history_rows.append(
        {
            "cycle_id": cycle_id,
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
            "total_profit": total_profit,
            "cycle_profit": cycle_profit,
            "locked_windows": ", ".join(map(str, locked_windows)),
            "consecutive_losses": consecutive_losses,
            "pause_left": pause_rounds_left,
            "lock_round_used": lock_round_used,
            "lock_range": f"{lock_range_start}->{lock_range_end}",
            "relock_event": relock_event,
        }
    )

    processed_until = i

# ================= SAVE STATE =================
st.session_state.total_profit = total_profit
st.session_state.cycle_profit = cycle_profit
st.session_state.cycle_id = cycle_id
st.session_state.cycle_start_round = cycle_start_round
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
st.session_state.consecutive_losses = consecutive_losses
st.session_state.pause_rounds_left = pause_rounds_left

st.session_state.relock_count = relock_count
st.session_state.last_relock_round = last_relock_round
st.session_state.last_relock_reason = last_relock_reason

hist = pd.DataFrame(history_rows)
cycle_summary = pd.DataFrame(st.session_state.cycle_summary_rows)

# ================= NEXT BET =================
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

if pause_rounds_left > 0:
    signal = False
    can_bet = False
    next_state = "PAUSE"
    next_keep_bet_group = None
    next_keep_rounds_left = 0
else:
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
    signal = final_signal
    can_bet = signal and distance >= GAP
    next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "cycle_id": cycle_id,
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
    "total_profit": total_profit,
    "cycle_profit": cycle_profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
    "consecutive_losses": consecutive_losses,
    "pause_left": pause_rounds_left,
    "lock_round_used": lock_round_used,
    "lock_range": f"{lock_range_start}->{lock_range_end}",
    "relock_event": "",
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= UI =================
st.title("🎯 Rolling Engine PRO - relock by cycle +6 / -8")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", final_vote if final_vote is not None else "-")
col4.metric("Cycle ID", cycle_id)

st.divider()
st.write("Vote Strength:", confidence)
st.write("Locked Windows:", locked_windows)
st.write("Lock Count:", len(locked_windows))
st.write("Current Lock Range:", f"{lock_range_start} -> {lock_range_end}")
st.write("Lock Round Used:", lock_round_used)
st.write("Cycle Profit Target:", CYCLE_PROFIT_TARGET)
st.write("Cycle Loss Target:", CYCLE_LOSS_TARGET)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Consecutive Losses:", consecutive_losses)
st.write("Pause Rounds Left:", pause_rounds_left)
st.write("Relock Count:", relock_count)
st.write("Last Relock Round:", last_relock_round)
st.write("Last Relock Reason:", last_relock_reason)
st.write("Processed Until:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT GROUP → {final_vote if final_vote is not None else "-"} (Vote Strength: {confidence})
    </div>
    """,
    unsafe_allow_html=True,
)

if pause_rounds_left > 0:
    st.warning(f"⏸ PAUSE - Đang nghỉ {pause_rounds_left} vòng do thua 2 lệnh liên tiếp")
elif can_bet and final_vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:25px;border-radius:10px;text-align:center;font-size:32px;color:white;font-weight:bold;">
        BET GROUP → {final_vote}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT (conditions not met)")

st.subheader("Session Statistics")
s1, s2, s3, s4, s5 = st.columns(5)
s1.metric("Total Profit", total_profit)
s2.metric("Cycle Profit", cycle_profit)
s3.metric("Trades", len(hits))
s4.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)
s5.metric("Closed Cycles", st.session_state.cycle_closed_count)

st.subheader("Profit Curve - Total")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"])

st.subheader("Profit Curve - Cycle")
if not hist_display.empty:
    st.line_chart(hist_display["cycle_profit"])

st.subheader("Cycle Summary")
if not cycle_summary.empty:
    st.dataframe(cycle_summary.iloc[::-1], use_container_width=True)
else:
    st.info("Chưa có cycle nào đóng.")

st.subheader("Round Evaluation")
st.dataframe(round_eval_df, use_container_width=True)

st.subheader("Window Scan All")
st.dataframe(scan_df_all, use_container_width=True)

st.subheader("All Positive Windows")
st.dataframe(scan_df_positive, use_container_width=True)

st.subheader("Locked Windows")
st.dataframe(scan_df_selected, use_container_width=True)

st.subheader("History")

def highlight_trade(row):
    if row["state"] in ("NEXT", "NEXT_KEEP"):
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "TRADE_KEEP":
        return ["background-color: #ffb347; color:black"] * len(row)
    if row["state"] == "PAUSE":
        return ["background-color: #87ceeb; color:black"] * len(row)
    if row["state"] == "PAUSE_TRIGGER":
        return ["background-color: #9370db; color:white"] * len(row)
    if row["state"] == "RELOCK_TARGET":
        return ["background-color: #32cd32; color:black"] * len(row)
    if row["state"] == "RELOCK_LOSS":
        return ["background-color: #1e90ff; color:white"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

st.write("Total Rows:", len(numbers))
