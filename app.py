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

# relock động theo vùng gần hiện tại:
# current_round - LOCK_LOOKBACK_MAX  -> current_round - LOCK_LOOKBACK_MIN
LOCK_LOOKBACK_MIN = 144
LOCK_LOOKBACK_MAX = 180

WINDOW_MIN = 6
WINDOW_MAX = 26

TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3
VOTE_REQUIRED = 3
GAP = 0

WIN = 2.5
LOSS = -1

# target mỗi chu kỳ
CYCLE_PROFIT_TARGET = 4

# keep tổng cộng 4 vòng, tính luôn vòng trade thua
KEEP_AFTER_LOSS_ROUNDS = 4

# lọc window dương
MIN_TRADES_PER_WINDOW = 26

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
min_needed_rows = max(WINDOW_MAX + 1, LOCK_LOOKBACK_MAX + 1)
if len(groups) < min_needed_rows:
    st.error(
        f"Chưa đủ dữ liệu. Cần ít nhất {min_needed_rows} rounds, hiện có {len(groups)}."
    )
    st.stop()

# ---------------- HELPERS ----------------
def get_dynamic_lock_range(current_round: int):
    """
    current_round là round sắp chạy / round hiện tại của engine.
    scan vùng lùi lại phía sau current_round.
    """
    lock_start = max(WINDOW_MAX + 1, current_round - LOCK_LOOKBACK_MAX)
    lock_end = max(lock_start, current_round - LOCK_LOOKBACK_MIN)
    return lock_start, lock_end

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
    rows = []
    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        rows.append(evaluate_window(train_groups, w))

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

    # CHỈ lấy window dương, không được nhét window âm để đủ số lượng
    selected_df = positive_df.head(TOP_WINDOWS).copy()

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

    round_score = (
        total_profit * 1.0
        + avg_winrate * 10.0
        + np.log(max(total_trades, 1.0))
        + avg_score * 0.2
    )
    return round_score

def find_best_lock_round_nearest(current_round: int):
    lock_start, lock_end = get_dynamic_lock_range(current_round)

    candidates = []

    for r in range(lock_start, lock_end + 1):
        train_groups = groups[:r]
        tmp_windows, tmp_all, tmp_positive, tmp_selected = build_window_tables(train_groups)

        pos_count = len(tmp_positive)
        round_score = -999999.0

        if pos_count >= MIN_POSITIVE_WINDOWS and not tmp_selected.empty:
            round_score = calc_round_score(tmp_selected)

        candidates.append(
            {
                "lock_round": r,
                "positive_windows": pos_count,
                "selected_count": len(tmp_selected),
                "selected_windows": ", ".join(map(str, tmp_windows)),
                "round_score": round_score,
                "windows": tmp_windows,
                "scan_all": tmp_all,
                "scan_positive": tmp_positive,
                "scan_selected": tmp_selected,
            }
        )

    round_eval_df = pd.DataFrame(
        [
            {
                "lock_round": x["lock_round"],
                "positive_windows": x["positive_windows"],
                "selected_count": x["selected_count"],
                "selected_windows": x["selected_windows"],
                "round_score": x["round_score"],
            }
            for x in candidates
        ]
    )

    valid = [
        x for x in candidates
        if x["positive_windows"] >= MIN_POSITIVE_WINDOWS and len(x["windows"]) > 0
    ]

    if not valid:
        return None, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), round_eval_df

    # ưu tiên score cao; nếu gần nhau thì round lớn hơn sẽ được ưu tiên
    valid_sorted = sorted(
        valid,
        key=lambda x: (x["round_score"], x["lock_round"]),
        reverse=True
    )

    best = valid_sorted[0]

    return (
        best["lock_round"],
        best["windows"],
        best["scan_all"],
        best["scan_positive"],
        best["scan_selected"],
        round_eval_df.sort_values(
            ["round_score", "lock_round"],
            ascending=[False, False]
        ).reset_index(drop=True),
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
        "base_data_len": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "cycle_id": 1,
        "cycle_start_round": None,
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
        "total_profit",
        "cycle_profit",
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
        "cycle_id",
        "cycle_start_round",
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
        "total_profit",
        "cycle_profit",
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
        "cycle_id",
        "cycle_start_round",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- RELock helper ----------------
def do_relock(current_processed_until: int):
    current_round = current_processed_until + 1

    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
    ) = find_best_lock_round_nearest(current_round)

    if lock_round_used is None:
        return False

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used

    st.session_state.cycle_id += 1
    st.session_state.cycle_profit = 0.0
    st.session_state.keep_bet_group = None
    st.session_state.keep_rounds_left = 0
    st.session_state.last_trade_was_loss = False
    st.session_state.cycle_start_round = current_round

    return True

# ---------------- FIRST LOCK ----------------
if not st.session_state.live_initialized:
    first_current_round = len(groups)
    ok = do_relock(first_current_round - 1)

    if not ok:
        st.error("Không tìm được vùng relock hợp lệ gần hiện tại.")
        st.stop()

    st.session_state.processed_until = st.session_state.lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
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
processed_until = st.session_state.processed_until
keep_bet_group = st.session_state.keep_bet_group
keep_rounds_left = st.session_state.keep_rounds_left
last_trade_was_loss = st.session_state.last_trade_was_loss
cycle_id = st.session_state.cycle_id
cycle_start_round = st.session_state.cycle_start_round

for i in range(processed_until + 1, len(groups)):
    # đạt target chu kỳ thì relock trước khi xử lý round mới
    if cycle_profit >= CYCLE_PROFIT_TARGET:
        relocked = do_relock(processed_until)
        if relocked:
            cycle_profit = st.session_state.cycle_profit
            keep_bet_group = st.session_state.keep_bet_group
            keep_rounds_left = st.session_state.keep_rounds_left
            last_trade_was_loss = st.session_state.last_trade_was_loss
            locked_windows = st.session_state.locked_windows
            scan_df_all = st.session_state.scan_df_all
            scan_df_positive = st.session_state.scan_df_positive
            scan_df_selected = st.session_state.scan_df_selected
            round_eval_df = st.session_state.round_eval_df
            lock_round_used = st.session_state.lock_round_used
            cycle_id = st.session_state.cycle_id
            cycle_start_round = st.session_state.cycle_start_round

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

    if cycle_profit >= CYCLE_PROFIT_TARGET:
        final_signal = False
        trade = False
        can_bet = False
        state = "RELOCK_READY"
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
    else:
        if used_keep and keep_rounds_left <= 0:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False

    history_rows.append(
        {
            "cycle_id": cycle_id,
            "cycle_start_round": cycle_start_round,
            "lock_round_used": lock_round_used,
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
            "cycle_profit": cycle_profit,
            "total_profit": total_profit,
            "locked_windows": ", ".join(map(str, locked_windows)),
        }
    )

    processed_until = i

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
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)
st.session_state.keep_bet_group = keep_bet_group
st.session_state.keep_rounds_left = keep_rounds_left
st.session_state.last_trade_was_loss = last_trade_was_loss
st.session_state.cycle_id = cycle_id
st.session_state.cycle_start_round = cycle_start_round

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

if cycle_profit >= CYCLE_PROFIT_TARGET:
    signal = False
    can_bet = False
    next_state = "RELOCK_READY"
else:
    signal = final_signal
    can_bet = signal and distance >= GAP
    next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "cycle_id": cycle_id,
    "cycle_start_round": cycle_start_round,
    "lock_round_used": lock_round_used,
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
    "cycle_profit": cycle_profit,
    "total_profit": total_profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Dynamic relock near current round + only positive windows")

dynamic_start, dynamic_end = get_dynamic_lock_range(processed_until + 1)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", final_vote if final_vote is not None else "-")
col4.metric("Cycle ID", cycle_id)

st.divider()
st.write("Vote Strength:", confidence)
st.write("Locked Windows:", locked_windows)
st.write("Locked Window Count:", len(locked_windows))
st.write("Vote Required:", VOTE_REQUIRED)
st.write("Dynamic Lock Range:", f"{dynamic_start} -> {dynamic_end}")
st.write("Lock Round Used:", lock_round_used)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Window Range:", f"{WINDOW_MIN} -> {WINDOW_MAX}")
st.write("Min Trades / Window:", MIN_TRADES_PER_WINDOW)
st.write("Cycle Profit Target:", CYCLE_PROFIT_TARGET)
st.write("Current Cycle Profit:", cycle_profit)
st.write("Total Profit:", total_profit)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Cycle Start Round:", cycle_start_round)
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

if cycle_profit >= CYCLE_PROFIT_TARGET:
    st.success(f"✅ Cycle reached target +{CYCLE_PROFIT_TARGET}. System will relock.")
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
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit", total_profit)
s2.metric("Cycle Profit", cycle_profit)
s3.metric("Trades", len(hits))
s4.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)

# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve (Total)")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"])

st.subheader("Profit Curve (Cycle)")
if not hist_display.empty:
    st.line_chart(hist_display["cycle_profit"])

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
    if row["state"] == "RELOCK_READY":
        return ["background-color: #90ee90; color:black"] * len(row)
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
