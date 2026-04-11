import math
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================================================
# PAGE / AUTO REFRESH
# =========================================================
st.set_page_config(page_title="Rolling Engine PRO MAX", layout="wide")
st_autorefresh(interval=5000, key="refresh")

# =========================================================
# CONFIG
# =========================================================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# vùng lock gần hiện tại
LOCK_LOOKBACK_MIN = 144
LOCK_LOOKBACK_MAX = 180

# window scan
WINDOW_MIN = 6
WINDOW_MAX = 26
TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3

# anti-overfit
MIN_TRADES_PER_WINDOW = 26
MIN_WINRATE_PER_WINDOW = 0.28

# trade
GAP = 0
WIN = 2.5
LOSS = -1.0

# relock
CYCLE_PROFIT_TARGET = 4.0
CYCLE_STOP_LOSS = -8.0

# recent relock
RECENT_HITS_WINDOW = 20
RECENT_WINRATE_FLOOR = 0.27

# keep
KEEP_AFTER_LOSS_ROUNDS = 4

# pro max
USE_WEIGHTED_VOTE = True
FULL_VOTE_ONLY = True
USE_EV_FILTER = True
EV_MIN_THRESHOLD = 0.0
RELOCK_COOLDOWN_ROUNDS = 1

# display
MAX_HISTORY_ROWS = 80
MAX_DEBUG_ROWS = 30
SHOW_DEBUG_DEFAULT = True

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Google Sheet phải có cột 'number'")
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

# =========================================================
# BASIC HELPERS
# =========================================================
def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

def get_dynamic_lock_range(current_round: int):
    lock_start = max(WINDOW_MAX + 1, current_round - LOCK_LOOKBACK_MAX)
    lock_end = max(lock_start, current_round - LOCK_LOOKBACK_MIN)
    return lock_start, lock_end

def recent_winrate(hit_list, n):
    if not hit_list:
        return 0.0
    arr = hit_list[-n:] if len(hit_list) >= n else hit_list
    return float(np.mean(arr)) if len(arr) > 0 else 0.0

def calc_ev(winrate: float):
    return winrate * WIN - (1.0 - winrate) * abs(LOSS)

def full_vote_required(lock_count: int) -> int:
    return max(1, lock_count)

def weighted_vote(pred_rows):
    """
    pred_rows: list of dict
    each item:
    {
      "window": int,
      "pred_group": int,
      "score": float,
      "profit": float,
      "winrate": float,
      "trades": int,
      "weight": float
    }
    """
    if not pred_rows:
        return None, 0, {}

    group_weights = {}
    group_counts = {}

    for row in pred_rows:
        g = row["pred_group"]
        w = row["weight"]
        group_weights[g] = group_weights.get(g, 0.0) + w
        group_counts[g] = group_counts.get(g, 0) + 1

    best_group = max(group_weights.items(), key=lambda x: (x[1], group_counts.get(x[0], 0)))[0]
    best_count = group_counts.get(best_group, 0)

    return best_group, best_count, group_weights

# =========================================================
# WINDOW EVAL
# =========================================================
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
    score = profit * winrate * math.log(trades) if trades > 0 else -999999.0
    ev = calc_ev(winrate) if trades > 0 else -999999.0

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "ev": ev,
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
        (df["trades"] >= MIN_TRADES_PER_WINDOW) &
        (df["winrate"] >= MIN_WINRATE_PER_WINDOW)
    ].copy()

    positive_df = positive_df.sort_values(
        ["score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

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
    avg_ev = float(selected_df["ev"].mean())

    return (
        total_profit * 1.0
        + avg_winrate * 10.0
        + math.log(max(total_trades, 1.0))
        + avg_score * 0.2
        + avg_ev * 8.0
    )

# =========================================================
# CACHE LOCK SEARCH
# =========================================================
@st.cache_data(ttl=30)
def find_best_lock_round_dynamic_cached(groups_tuple, current_round: int):
    all_groups = list(groups_tuple)
    lock_start, lock_end = get_dynamic_lock_range(current_round)

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
            if (round_score > best_score) or (
                round_score == best_score and (best_round is None or r > best_round)
            ):
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

    round_eval_df = pd.DataFrame(round_eval_rows).sort_values(
        ["round_score", "positive_windows", "lock_round"],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    return (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_df.to_dict("records"),
        lock_start,
        lock_end,
    )

def find_best_lock_round_dynamic(groups, current_round: int):
    (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_rows,
        lock_start,
        lock_end,
    ) = find_best_lock_round_dynamic_cached(tuple(groups), current_round)

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

# =========================================================
# STATE
# =========================================================
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
        "vote_required": 1,
        "scan_df_all": pd.DataFrame(),
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,
        "lock_range_start": None,
        "lock_range_end": None,
        "base_data_len": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "cycle_id": 1,
        "cycle_start_round": None,
        "last_relock_reason": "INIT",
        "engine_status": "RUNNING",
        "cooldown_until_round": -1,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

def clear_state():
    keys = list(st.session_state.keys())
    for k in keys:
        del st.session_state[k]

if st.button("🔄 Reset Session"):
    clear_state()
    st.rerun()

# =========================================================
# LOAD REAL DATA
# =========================================================
try:
    numbers = load_numbers()
except Exception as e:
    st.error(f"Lỗi đọc dữ liệu: {e}")
    st.stop()

groups = [group(n) for n in numbers]

min_needed_rows = max(WINDOW_MAX + 1, LOCK_LOOKBACK_MAX + 1)
if len(groups) < min_needed_rows:
    st.error(f"Chưa đủ dữ liệu. Cần ít nhất {min_needed_rows} rounds, hiện có {len(groups)}.")
    st.stop()

if (
    st.session_state.base_data_len is not None
    and len(groups) < st.session_state.base_data_len
):
    clear_state()
    st.rerun()

# =========================================================
# RELock ACTION
# =========================================================
def do_relock(current_round_start: int, reason: str):
    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
        lock_range_start,
        lock_range_end,
    ) = find_best_lock_round_dynamic(groups, current_round_start)

    if lock_round_used is None or len(locked_windows) < MIN_POSITIVE_WINDOWS:
        return False

    vote_required = full_vote_required(len(locked_windows)) if FULL_VOTE_ONLY else max(2, len(locked_windows) - 1)

    st.session_state.locked_windows = locked_windows
    st.session_state.vote_required = vote_required
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.lock_range_start = lock_range_start
    st.session_state.lock_range_end = lock_range_end

    st.session_state.cycle_profit = 0.0
    st.session_state.keep_bet_group = None
    st.session_state.keep_rounds_left = 0
    st.session_state.last_trade_was_loss = False
    st.session_state.cycle_start_round = current_round_start
    st.session_state.cycle_id += 1
    st.session_state.last_relock_reason = reason
    st.session_state.engine_status = "RUNNING"
    st.session_state.cooldown_until_round = current_round_start + RELOCK_COOLDOWN_ROUNDS - 1

    return True

# =========================================================
# FIRST LOCK
# =========================================================
if not st.session_state.live_initialized:
    initial_current_round = len(groups)

    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        round_eval_df,
        lock_range_start,
        lock_range_end,
    ) = find_best_lock_round_dynamic(groups, initial_current_round)

    if lock_round_used is None or len(locked_windows) < MIN_POSITIVE_WINDOWS:
        st.error("Không tìm được bộ lock hợp lệ gần hiện tại.")
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.vote_required = full_vote_required(len(locked_windows)) if FULL_VOTE_ONLY else max(2, len(locked_windows) - 1)
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.lock_range_start = lock_range_start
    st.session_state.lock_range_end = lock_range_end
    st.session_state.processed_until = lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True
    st.session_state.cycle_id = 1
    st.session_state.cycle_start_round = lock_round_used
    st.session_state.last_relock_reason = "INIT"
    st.session_state.engine_status = "RUNNING"
    st.session_state.cooldown_until_round = lock_round_used + RELOCK_COOLDOWN_ROUNDS - 1

# =========================================================
# LOAD STATE
# =========================================================
total_profit = st.session_state.total_profit
cycle_profit = st.session_state.cycle_profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
vote_required = st.session_state.vote_required
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
cycle_id = st.session_state.cycle_id
cycle_start_round = st.session_state.cycle_start_round
last_relock_reason = st.session_state.last_relock_reason
engine_status = st.session_state.engine_status
cooldown_until_round = st.session_state.cooldown_until_round

# =========================================================
# FAST LOOKUP WINDOW META
# =========================================================
selected_window_meta = {}
if not scan_df_selected.empty:
    for _, row in scan_df_selected.iterrows():
        selected_window_meta[int(row["window"])] = {
            "score": float(row["score"]),
            "profit": float(row["profit"]),
            "winrate": float(row["winrate"]),
            "trades": int(row["trades"]),
            "ev": float(row["ev"]) if "ev" in row else calc_ev(float(row["winrate"])),
        }

# =========================================================
# PROCESS NEW ROUNDS ONLY
# =========================================================
for i in range(processed_until + 1, len(groups)):
    recent_wr = recent_winrate(hits, RECENT_HITS_WINDOW)

    need_relock = False
    relock_reason = None

    if cycle_profit >= CYCLE_PROFIT_TARGET:
        need_relock = True
        relock_reason = "TARGET_REACHED"
    elif cycle_profit <= CYCLE_STOP_LOSS:
        need_relock = True
        relock_reason = "LOSS_REACHED"
    elif len(hits) >= RECENT_HITS_WINDOW and recent_wr < RECENT_WINRATE_FLOOR:
        need_relock = True
        relock_reason = "RECENT_WR_LOW"

    # RELock ngay, bỏ qua round hiện tại
    if need_relock:
        ok = do_relock(i, relock_reason)
        if ok:
            cycle_profit = st.session_state.cycle_profit
            locked_windows = st.session_state.locked_windows
            vote_required = st.session_state.vote_required
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
            cycle_id = st.session_state.cycle_id
            cycle_start_round = st.session_state.cycle_start_round
            last_relock_reason = st.session_state.last_relock_reason
            engine_status = st.session_state.engine_status
            cooldown_until_round = st.session_state.cooldown_until_round

            selected_window_meta = {}
            if not scan_df_selected.empty:
                for _, row in scan_df_selected.iterrows():
                    selected_window_meta[int(row["window"])] = {
                        "score": float(row["score"]),
                        "profit": float(row["profit"]),
                        "winrate": float(row["winrate"]),
                        "trades": int(row["trades"]),
                        "ev": float(row["ev"]) if "ev" in row else calc_ev(float(row["winrate"])),
                    }

            processed_until = i - 1
            continue

    if i < lock_round_used:
        continue

    pred_rows = []
    for w in locked_windows:
        if i - w >= 0:
            meta = selected_window_meta.get(
                int(w),
                {
                    "score": 0.0,
                    "profit": 0.0,
                    "winrate": 0.0,
                    "trades": 0,
                    "ev": 0.0,
                },
            )
            score_val = max(meta["score"], 0.01)
            weight = (
                score_val * 0.6
                + max(meta["profit"], 0.0) * 0.25
                + max(meta["winrate"], 0.0) * 10.0 * 0.15
            )
            pred_rows.append(
                {
                    "window": int(w),
                    "pred_group": groups[i - w],
                    "score": meta["score"],
                    "profit": meta["profit"],
                    "winrate": meta["winrate"],
                    "trades": meta["trades"],
                    "ev": meta["ev"],
                    "weight": weight,
                }
            )

    if not pred_rows:
        processed_until = i
        continue

    if USE_WEIGHTED_VOTE:
        vote, confidence, group_weights = weighted_vote(pred_rows)
    else:
        raw_preds = [x["pred_group"] for x in pred_rows]
        vote, confidence = Counter(raw_preds).most_common(1)[0]
        group_weights = {}

    distance = i - last_trade

    # EV của nhóm thắng: trung bình theo các window bỏ phiếu cho nhóm đó
    winning_rows = [x for x in pred_rows if x["pred_group"] == vote]
    avg_ev = float(np.mean([x["ev"] for x in winning_rows])) if winning_rows else -999999.0

    # full vote
    new_signal = confidence >= vote_required

    final_vote = vote
    used_keep = False

    # signal mới sẽ hủy keep
    if new_signal:
        keep_rounds_left = 0
        keep_bet_group = None
        last_trade_was_loss = False
    else:
        if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
            final_vote = keep_bet_group
            used_keep = True

    final_signal = new_signal or used_keep

    # cooldown
    in_cooldown = i <= cooldown_until_round

    # can_bet chuẩn PRO MAX
    can_bet = (
        final_signal
        and distance >= GAP
        and not in_cooldown
    )

    # chỉ cho bet khi signal mới đủ full vote
    if new_signal:
        can_bet = can_bet and (confidence >= vote_required)

    # EV filter chỉ áp vào signal mới
    if new_signal and USE_EV_FILTER:
        can_bet = can_bet and (avg_ev >= EV_MIN_THRESHOLD)

    trade = can_bet

    if trade and used_keep:
        state = "TRADE_KEEP"
    elif trade:
        state = "TRADE"
    elif in_cooldown:
        state = "COOLDOWN"
    elif new_signal:
        state = "SIGNAL"
    elif used_keep:
        state = "KEEP_WAIT"
    else:
        state = "WAIT"

    bet_group = final_vote if trade else None
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
            "lock_range_start": lock_range_start,
            "lock_range_end": lock_range_end,
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "vote": vote,
            "confidence": confidence,
            "vote_required": vote_required,
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
            "avg_ev": avg_ev,
            "cycle_profit": cycle_profit,
            "total_profit": total_profit,
            "locked_windows": ", ".join(map(str, locked_windows)),
            "relock_reason": last_relock_reason,
        }
    )

    processed_until = i

# =========================================================
# SAVE STATE
# =========================================================
st.session_state.total_profit = total_profit
st.session_state.cycle_profit = cycle_profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.history_rows = history_rows
st.session_state.locked_windows = locked_windows
st.session_state.vote_required = vote_required
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
st.session_state.cycle_id = cycle_id
st.session_state.cycle_start_round = cycle_start_round
st.session_state.last_relock_reason = last_relock_reason
st.session_state.engine_status = engine_status
st.session_state.cooldown_until_round = cooldown_until_round

hist = pd.DataFrame(history_rows)

# =========================================================
# NEXT BET
# =========================================================
next_round = len(groups)

pred_rows_next = []
for w in locked_windows:
    if next_round - w >= 0:
        meta = selected_window_meta.get(
            int(w),
            {
                "score": 0.0,
                "profit": 0.0,
                "winrate": 0.0,
                "trades": 0,
                "ev": 0.0,
            },
        )
        score_val = max(meta["score"], 0.01)
        weight = (
            score_val * 0.6
            + max(meta["profit"], 0.0) * 0.25
            + max(meta["winrate"], 0.0) * 10.0 * 0.15
        )
        pred_rows_next.append(
            {
                "window": int(w),
                "pred_group": groups[next_round - w],
                "score": meta["score"],
                "profit": meta["profit"],
                "winrate": meta["winrate"],
                "trades": meta["trades"],
                "ev": meta["ev"],
                "weight": weight,
            }
        )

if pred_rows_next:
    if USE_WEIGHTED_VOTE:
        vote, confidence, group_weights_next = weighted_vote(pred_rows_next)
    else:
        raw_preds = [x["pred_group"] for x in pred_rows_next]
        vote, confidence = Counter(raw_preds).most_common(1)[0]
        group_weights_next = {}
else:
    vote, confidence, group_weights_next = None, 0, {}

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

winning_rows_next = [x for x in pred_rows_next if x["pred_group"] == vote] if vote is not None else []
avg_ev_next = float(np.mean([x["ev"] for x in winning_rows_next])) if winning_rows_next else -999999.0

new_signal = confidence >= vote_required if vote is not None else False
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
curr_recent_wr = recent_winrate(hits, RECENT_HITS_WINDOW)
in_cooldown_next = next_round <= cooldown_until_round

if cycle_profit >= CYCLE_PROFIT_TARGET:
    can_bet = False
    next_state = "RELOCK_READY_TARGET"
elif cycle_profit <= CYCLE_STOP_LOSS:
    can_bet = False
    next_state = "RELOCK_READY_LOSS"
elif len(hits) >= RECENT_HITS_WINDOW and curr_recent_wr < RECENT_WINRATE_FLOOR:
    can_bet = False
    next_state = "RELOCK_READY_RECENT_WR"
else:
    can_bet = final_signal and distance >= GAP and not in_cooldown_next

    if new_signal:
        can_bet = can_bet and (confidence >= vote_required)

    if new_signal and USE_EV_FILTER:
        can_bet = can_bet and (avg_ev_next >= EV_MIN_THRESHOLD)

    if in_cooldown_next:
        next_state = "COOLDOWN"
    else:
        next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "cycle_id": cycle_id,
    "cycle_start_round": cycle_start_round,
    "lock_round_used": lock_round_used,
    "lock_range_start": lock_range_start,
    "lock_range_end": lock_range_end,
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "vote_required": vote_required,
    "new_signal": new_signal,
    "used_keep": used_keep_next,
    "keep_group": next_keep_bet_group,
    "keep_left": next_keep_rounds_left,
    "final_vote": final_vote,
    "signal": final_signal,
    "trade": False,
    "bet_group": final_vote if can_bet else None,
    "hit": None,
    "state": next_state,
    "avg_ev": avg_ev_next,
    "cycle_profit": cycle_profit,
    "total_profit": total_profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
    "relock_reason": last_relock_reason,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True) if not hist.empty else pd.DataFrame([next_row])

# =========================================================
# UI
# =========================================================
show_debug = st.checkbox("Show Debug", value=SHOW_DEBUG_DEFAULT)

st.title("🎯 Rolling Engine PRO MAX")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number if current_number is not None else "-")
c2.metric("Current Group", current_group if current_group is not None else "-")
c3.metric("Next Group", final_vote if final_vote is not None else "-")
c4.metric("Cycle ID", cycle_id)

st.divider()

st.write("Vote Strength:", confidence)
st.write("Vote Required:", vote_required)
st.write("Locked Windows:", locked_windows)
st.write("Locked Window Count:", len(locked_windows))
st.write("Dynamic Lock Range:", f"{lock_range_start} -> {lock_range_end}")
st.write("Lock Round Used:", lock_round_used)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Window Range:", f"{WINDOW_MIN} -> {WINDOW_MAX}")
st.write("Min Trades / Window:", MIN_TRADES_PER_WINDOW)
st.write("Min Winrate / Window:", MIN_WINRATE_PER_WINDOW)
st.write("Cycle Profit Target:", CYCLE_PROFIT_TARGET)
st.write("Cycle Loss Target:", CYCLE_STOP_LOSS)
st.write("Recent WR Floor:", RECENT_WINRATE_FLOOR)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Processed Until Round:", processed_until)
st.write("Cycle Start Round:", cycle_start_round)
st.write("Last Relock Reason:", last_relock_reason)
st.write("Cooldown Until Round:", cooldown_until_round)
st.write("Next EV:", round(avg_ev_next, 4) if avg_ev_next > -999 else "-")

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT GROUP → {final_vote if final_vote is not None else "-"} (Vote Strength: {confidence})
    </div>
    """,
    unsafe_allow_html=True,
)

if next_state == "RELOCK_READY_TARGET":
    st.success(f"✅ RELock ready - Cycle reached +{CYCLE_PROFIT_TARGET}")
elif next_state == "RELOCK_READY_LOSS":
    st.warning(f"⚠️ RELock ready - Cycle reached {CYCLE_STOP_LOSS}")
elif next_state == "RELOCK_READY_RECENT_WR":
    st.warning(f"⚠️ RELock ready - Recent winrate < {RECENT_WINRATE_FLOOR*100:.0f}%")
elif next_state == "COOLDOWN":
    st.info("COOLDOWN (just relocked, waiting)")
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
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit", total_profit)
s2.metric("Cycle Profit", cycle_profit)
s3.metric("Trades", len(hits))
s4.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)

st.subheader("Profit Curve (Total)")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"])

st.subheader("Profit Curve (Cycle)")
if not hist_display.empty:
    current_cycle_df = hist_display[hist_display["cycle_id"] == cycle_id].copy()
    if not current_cycle_df.empty:
        st.line_chart(current_cycle_df["cycle_profit"])

st.subheader("History")

def highlight_trade(row):
    if row["state"] in ("NEXT", "NEXT_KEEP"):
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "TRADE_KEEP":
        return ["background-color: #ffb347; color:black"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].head(MAX_HISTORY_ROWS).style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

if show_debug:
    st.subheader("Round Evaluation")
    st.dataframe(round_eval_df.head(MAX_DEBUG_ROWS), use_container_width=True)

    st.subheader("Window Scan All")
    st.dataframe(scan_df_all.head(MAX_DEBUG_ROWS), use_container_width=True)

    st.subheader("All Positive Windows")
    st.dataframe(scan_df_positive.head(MAX_DEBUG_ROWS), use_container_width=True)

    st.subheader("Locked Windows")
    st.dataframe(scan_df_selected.head(MAX_DEBUG_ROWS), use_container_width=True)

st.write("Locked Windows:", locked_windows)
st.write("Total Rows:", len(numbers))
