import time
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=1000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# Phase 1: scan cố định ban đầu
LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

# Phase 1
PHASE1_TOP_WINDOWS = 6
PHASE1_VOTE_REQUIRED = 4

# Phase 2
PHASE2_TOP_WINDOWS = 8
PHASE2_VOTE_REQUIRED = 5

WINDOW_MIN = 6
WINDOW_MAX = 26
GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

KEEP_AFTER_LOSS_ROUNDS = 2
PAUSE_AFTER_2_LOSSES = 0
GROUP_MAX_LOSS_STREAK = 4
GROUP_PROFIT_STOP = 4.0

MIN_TRADES_PER_WINDOW = 12
RECENT_WINDOW_SIZE = 20
MIN_WINDOW_SPACING = 2
MAX_CANDIDATE_WINDOWS = 12

VALIDATE_LEN = 20
MIN_TRAIN_LEN = 120
MIN_VALIDATE_TRADES = 2
VALIDATE_MIN_DRAWDOWN = -6.0

# ===== tối ưu tốc độ theo yêu cầu =====
REPLAY_FROM = 180
SHOW_DEBUG_TABLES = False
SHOW_STYLED_HISTORY = False
SHOW_HISTORY_ROWS = 60

# Relock
RELOCK_TRIGGER_LOSS_STREAK = 3
RELOCK_TRIGGER_PROFIT = -3.0
RESET_PROFIT_ON_RELOCK = True

# Scan gần hiện tại khi relock
RELOCK_SCAN_LEN = 13
RELOCK_BUFFER = 0

# ================= LOAD =================
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Sheet phải có cột 'number'")
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

# ================= MAP =================
def group_of(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

# ================= HELPERS =================
def compute_profit_path(results, win_value, loss_value):
    p = 0.0
    out = []
    for r in results:
        p += win_value if r == 1 else loss_value
        out.append(p)
    return out

def compute_max_drawdown(results, win_value, loss_value):
    if not results:
        return 0.0
    path = compute_profit_path(results, win_value, loss_value)
    peak = -10**18
    max_dd = 0.0
    for x in path:
        peak = max(peak, x)
        dd = x - peak
        max_dd = min(max_dd, dd)
    return float(max_dd)

def compute_recent_profit(results, recent_n, win_value, loss_value):
    if not results:
        return 0.0
    tail = results[-recent_n:]
    return float(sum(win_value if r == 1 else loss_value for r in tail))

def compute_streak_metrics(results):
    if not results:
        return {
            "max_hit_streak": 0,
            "max_loss_streak": 0,
            "count_hit_streak_ge2": 0,
            "count_loss_streak_ge2": 0,
            "streak_score": -999999.0,
        }

    max_hit_streak = 0
    max_loss_streak = 0
    count_hit_streak_ge2 = 0
    count_loss_streak_ge2 = 0

    cur_val = results[0]
    cur_len = 1

    for x in results[1:]:
        if x == cur_val:
            cur_len += 1
        else:
            if cur_val == 1:
                max_hit_streak = max(max_hit_streak, cur_len)
                if cur_len >= 2:
                    count_hit_streak_ge2 += 1
            else:
                max_loss_streak = max(max_loss_streak, cur_len)
                if cur_len >= 2:
                    count_loss_streak_ge2 += 1
            cur_val = x
            cur_len = 1

    if cur_val == 1:
        max_hit_streak = max(max_hit_streak, cur_len)
        if cur_len >= 2:
            count_hit_streak_ge2 += 1
    else:
        max_loss_streak = max(max_loss_streak, cur_len)
        if cur_len >= 2:
            count_loss_streak_ge2 += 1

    streak_score = (
        max_hit_streak * 2.0
        + count_hit_streak_ge2 * 1.5
        - max_loss_streak * 1.5
        - count_loss_streak_ge2 * 1.0
    )

    return {
        "max_hit_streak": max_hit_streak,
        "max_loss_streak": max_loss_streak,
        "count_hit_streak_ge2": count_hit_streak_ge2,
        "count_loss_streak_ge2": count_loss_streak_ge2,
        "streak_score": streak_score,
    }

def pick_spaced_windows(df_sorted, top_n, min_spacing):
    selected_rows = []
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if all(abs(w - int(x["window"])) >= min_spacing for x in selected_rows):
            selected_rows.append(row.to_dict())
            if len(selected_rows) >= top_n:
                break
    return pd.DataFrame(selected_rows)

def enforce_spacing_from_df(df_sorted: pd.DataFrame, top_n: int, min_spacing: int) -> list[int]:
    out = []
    if df_sorted.empty:
        return out
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if all(abs(w - x) >= min_spacing for x in out):
            out.append(w)
            if len(out) >= top_n:
                break
    return out

# ================= BACKTEST RAW =================
def backtest_bundle_vote_range(seq_groups, windows, start_idx, end_idx, vote_required):
    results_group = []
    trades = 0
    wins_group = 0
    last_trade = -999999
    effective_start = max(start_idx, max(windows))

    for i in range(effective_start, end_idx):
        preds_group = [seq_groups[i - w] for w in windows]
        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        signal = confidence_group >= vote_required

        if signal and (i - last_trade >= GAP):
            last_trade = i
            trades += 1
            group_hit = 1 if seq_groups[i] == vote_group else 0
            wins_group += group_hit
            results_group.append(group_hit)

    profit_group = float(sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results_group))
    winrate_group = wins_group / trades if trades > 0 else 0.0
    max_drawdown_group = compute_max_drawdown(results_group, WIN_GROUP, LOSS_GROUP)
    recent_profit_group = compute_recent_profit(results_group, RECENT_WINDOW_SIZE, WIN_GROUP, LOSS_GROUP)
    streak_metrics = compute_streak_metrics(results_group)

    return {
        "trades": trades,
        "profit_group": profit_group,
        "winrate_group": winrate_group,
        "max_drawdown_group": max_drawdown_group,
        "recent_profit_group": recent_profit_group,
        "max_hit_streak": streak_metrics["max_hit_streak"],
        "max_loss_streak": streak_metrics["max_loss_streak"],
        "count_hit_streak_ge2": streak_metrics["count_hit_streak_ge2"],
        "streak_score": streak_metrics["streak_score"],
    }

# ================= WINDOW EVAL =================
def evaluate_window_group(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0
    results = []
    n = len(seq_groups)

    for i in range(w, n):
        pred = seq_groups[i - w]
        if seq_groups[i - 1] != pred:
            trades += 1
            if seq_groups[i] == pred:
                profit += WIN_GROUP
                wins += 1
                results.append(1)
            else:
                profit += LOSS_GROUP
                results.append(0)

    winrate = wins / trades if trades > 0 else 0.0
    max_drawdown = compute_max_drawdown(results, WIN_GROUP, LOSS_GROUP)
    recent_profit = compute_recent_profit(results, RECENT_WINDOW_SIZE, WIN_GROUP, LOSS_GROUP)
    streak_metrics = compute_streak_metrics(results)

    if trades > 0:
        score = (
            profit
            + winrate * 8.0
            + np.log(trades + 1) * 1.2
            + recent_profit * 0.8
            - abs(max_drawdown) * 0.7
            + streak_metrics["streak_score"] * 1.2
        )
    else:
        score = -999999.0

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "max_drawdown": max_drawdown,
        "recent_profit": recent_profit,
        "max_hit_streak": streak_metrics["max_hit_streak"],
        "max_loss_streak": streak_metrics["max_loss_streak"],
        "count_hit_streak_ge2": streak_metrics["count_hit_streak_ge2"],
        "streak_score": streak_metrics["streak_score"],
        "score": score,
    }

def build_window_tables(train_groups, top_windows):
    rows = [evaluate_window_group(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["score", "streak_score", "recent_profit", "profit", "winrate", "trades"],
        ascending=[False, False, False, False, False, False]
    ).reset_index(drop=True)

    filtered_df = df[
        (df["trades"] >= MIN_TRADES_PER_WINDOW) &
        (
            (df["count_hit_streak_ge2"] >= 1)
            | (df["max_hit_streak"] >= 2)
        ) &
        (df["max_loss_streak"] <= 6)
    ].copy()

    filtered_df = filtered_df.sort_values(
        [
            "streak_score",
            "score",
            "recent_profit",
            "profit",
            "winrate",
            "trades",
            "max_loss_streak",
        ],
        ascending=[False, False, False, False, False, False, True]
    ).reset_index(drop=True)

    if filtered_df.empty:
        filtered_df = df_all.head(MAX_CANDIDATE_WINDOWS).copy()

    selected_seed = filtered_df.head(MAX_CANDIDATE_WINDOWS).copy()

    candidate_df = selected_seed.sort_values(
        ["streak_score", "score", "recent_profit", "profit", "winrate", "trades"],
        ascending=[False, False, False, False, False, False]
    ).reset_index(drop=True)

    spaced_candidate_df = pick_spaced_windows(candidate_df, MAX_CANDIDATE_WINDOWS, MIN_WINDOW_SPACING)
    candidate_windows = spaced_candidate_df["window"].astype(int).tolist()

    if len(candidate_windows) < top_windows:
        candidate_windows = enforce_spacing_from_df(selected_seed, top_windows, MIN_WINDOW_SPACING)

    if len(candidate_windows) < top_windows:
        candidate_windows = enforce_spacing_from_df(df_all, top_windows, 1)

    return candidate_windows, df_all, filtered_df

def find_best_lock_in_range(all_groups, scan_start, scan_end, top_windows, vote_required):
    effective_scan_end = min(scan_end, len(all_groups) - 1)
    if effective_scan_end < scan_start:
        return None, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "no_scan_range"

    best_round = None
    best_score = -999999.0
    best_windows = []
    best_scan_df = pd.DataFrame()
    best_filtered_df = pd.DataFrame()
    round_eval_rows = []

    fallback_round = None
    fallback_windows = []
    fallback_scan_df = pd.DataFrame()
    fallback_filtered_df = pd.DataFrame()
    fallback_score = -999999.0

    for r in range(scan_start, effective_scan_end + 1):
        if r < VALIDATE_LEN + MIN_TRAIN_LEN:
            continue

        train_end = r - VALIDATE_LEN
        validate_start = train_end
        validate_end = r

        train_groups = all_groups[:train_end]
        validate_groups = all_groups[:validate_end]

        candidate_windows, scan_df, filtered_df = build_window_tables(train_groups, top_windows)
        if len(candidate_windows) < top_windows:
            continue

        bundle_rows = []
        for combo in combinations(candidate_windows, top_windows):
            combo = sorted(combo)

            train_bt = backtest_bundle_vote_range(train_groups, combo, 0, len(train_groups), vote_required)
            validate_bt = backtest_bundle_vote_range(validate_groups, combo, validate_start, validate_end, vote_required)

            validate_pass = (
                validate_bt["trades"] >= MIN_VALIDATE_TRADES
                and validate_bt["max_drawdown_group"] >= VALIDATE_MIN_DRAWDOWN
            )

            final_score = (
                train_bt["profit_group"] * 1.0
                + train_bt["winrate_group"] * 10.0
                + train_bt["recent_profit_group"] * 1.0
                - abs(train_bt["max_drawdown_group"]) * 1.0
                + train_bt["streak_score"] * 1.5
                + validate_bt["profit_group"] * 2.0
                + validate_bt["winrate_group"] * 8.0
                - abs(validate_bt["max_drawdown_group"]) * 1.0
                + validate_bt["streak_score"] * 1.5
            )

            bundle_rows.append({
                "windows": ", ".join(map(str, combo)),
                "validate_pass": validate_pass,
                "final_score": final_score,
                "validate_profit_group": validate_bt["profit_group"],
                "validate_winrate_group": validate_bt["winrate_group"],
                "validate_max_drawdown_group": validate_bt["max_drawdown_group"],
                "validate_streak_score": validate_bt["streak_score"],
            })

        bundle_df = pd.DataFrame(bundle_rows)
        if bundle_df.empty:
            continue

        bundle_all_sorted = bundle_df.sort_values(
            ["final_score", "validate_streak_score", "validate_profit_group", "validate_winrate_group"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

        best_any_row = bundle_all_sorted.iloc[0]
        any_windows = [int(x) for x in best_any_row["windows"].split(", ")]
        any_score = float(best_any_row["final_score"])

        if any_score > fallback_score:
            fallback_score = any_score
            fallback_round = r
            fallback_windows = any_windows
            fallback_scan_df = scan_df
            fallback_filtered_df = filtered_df

        passed_df = bundle_df[bundle_df["validate_pass"] == True].copy()
        if passed_df.empty:
            round_eval_rows.append({
                "lock_round": r,
                "selected_windows": ", ".join(map(str, any_windows)),
                "bundle_score": any_score,
                "pass_count": 0,
            })
            continue

        passed_df = passed_df.sort_values(
            ["final_score", "validate_streak_score", "validate_profit_group", "validate_winrate_group"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

        best_row = passed_df.iloc[0]
        selected_windows = [int(x) for x in best_row["windows"].split(", ")]
        bundle_score = float(best_row["final_score"])

        round_eval_rows.append({
            "lock_round": r,
            "selected_windows": ", ".join(map(str, selected_windows)),
            "bundle_score": bundle_score,
            "pass_count": len(passed_df),
        })

        if bundle_score > best_score:
            best_score = bundle_score
            best_round = r
            best_windows = selected_windows
            best_scan_df = scan_df
            best_filtered_df = filtered_df

    round_eval_df = pd.DataFrame(round_eval_rows)

    if best_round is not None:
        return best_round, best_windows, best_scan_df, best_filtered_df, round_eval_df, "validated"

    if fallback_round is not None:
        return fallback_round, fallback_windows, fallback_scan_df, fallback_filtered_df, round_eval_df, "fallback"

    return None, [], pd.DataFrame(), pd.DataFrame(), round_eval_df, "not_found"

# ================= REPLAY ENGINE =================
def simulate_engine(numbers, groups):
    result = {
        "hist": pd.DataFrame(),
        "current_phase": 1,
        "phase_profit_group": 0.0,
        "phase_hits_group": [],
        "total_profit_all_phase": 0.0,
        "total_hits_all_phase": [],
        "locked_windows": [],
        "selected_lock_round": None,
        "lock_mode": "",
        "scan_df_all": pd.DataFrame(),
        "scan_df_filtered": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_scan_start": None,
        "lock_scan_end": None,
        "lock_vote_required": PHASE1_VOTE_REQUIRED,
        "lock_top_windows": PHASE1_TOP_WINDOWS,
        "relocked": False,
        "relock_round": None,
        "group_pause": False,
        "pause_rounds_left": 0,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "consecutive_losses": 0,
        "group_consecutive_losses": 0,
        "phase_last_trade": -999,
    }

    (
        selected_lock_round,
        locked_windows,
        scan_df_all,
        scan_df_filtered,
        round_eval_df,
        lock_mode,
    ) = find_best_lock_in_range(
        groups,
        LOCK_ROUND_START,
        LOCK_ROUND_END,
        PHASE1_TOP_WINDOWS,
        PHASE1_VOTE_REQUIRED,
    )

    if selected_lock_round is None:
        return result

    phase = 1
    phase_profit_group = 0.0
    phase_hits_group = []
    total_profit_all_phase = 0.0
    total_hits_all_phase = []
    phase_last_trade = -999

    keep_bet_group = None
    keep_rounds_left = 0
    last_trade_was_loss = False
    consecutive_losses = 0
    pause_rounds_left = 0
    group_consecutive_losses = 0
    group_pause = False

    relocked = False
    relock_round = None

    lock_scan_start = LOCK_ROUND_START
    lock_scan_end = LOCK_ROUND_END
    lock_vote_required = PHASE1_VOTE_REQUIRED
    lock_top_windows = PHASE1_TOP_WINDOWS

    history_rows = []

    start_replay = max(LOCK_ROUND_END + 1, REPLAY_FROM + 1)

    for i in range(start_replay, len(groups)):
        preds_group = [groups[i - w] for w in locked_windows if i - w >= 0]
        if not preds_group:
            continue

        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        new_signal = confidence_group >= lock_vote_required
        distance = i - phase_last_trade

        final_vote_group = vote_group
        used_keep = False
        trade = False
        can_bet = False
        hit_group = None
        state = "WAIT"
        relock_triggered_now = False
        phase_before_trade = phase

        if phase_profit_group >= GROUP_PROFIT_STOP:
            group_pause = True

        if pause_rounds_left > 0:
            pause_rounds_left -= 1
            state = "PAUSE"
            history_rows.append({
                "phase": phase_before_trade,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "vote_required": lock_vote_required,
                "new_signal": new_signal,
                "used_keep": False,
                "keep_group": None,
                "keep_left": 0,
                "final_vote_group": final_vote_group,
                "signal": False,
                "trade": False,
                "bet_group": None,
                "hit_group": None,
                "state": state,
                "phase_profit_group": phase_profit_group,
                "total_profit_all_phase": total_profit_all_phase,
                "consecutive_losses": consecutive_losses,
                "pause_left": pause_rounds_left,
                "group_consecutive_losses": group_consecutive_losses,
                "group_pause": group_pause,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "relocked": relocked,
                "relock_triggered_now": False,
            })
            continue

        if new_signal:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False
            final_vote_group = vote_group
        else:
            if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
                final_vote_group = keep_bet_group
                used_keep = True

        final_signal = new_signal or used_keep
        trade = (not group_pause) and final_signal and distance >= GAP
        can_bet = trade

        if trade and used_keep:
            state = "TRADE_KEEP"
        elif trade:
            state = "TRADE"
        elif group_pause:
            state = "GROUP_PAUSED"
        elif new_signal:
            state = "SIGNAL"
        elif used_keep:
            state = "KEEP_WAIT"
        else:
            state = "WAIT"

        bet_group = final_vote_group if can_bet else None

        if used_keep:
            keep_rounds_left -= 1
            if keep_rounds_left < 0:
                keep_rounds_left = 0

        if trade:
            phase_last_trade = i

            if groups[i] == final_vote_group:
                hit_group = 1
                phase_profit_group += WIN_GROUP
                total_profit_all_phase += WIN_GROUP
                phase_hits_group.append(1)
                total_hits_all_phase.append(1)

                last_trade_was_loss = False
                keep_rounds_left = 0
                keep_bet_group = None
                consecutive_losses = 0
                group_consecutive_losses = 0

                if phase_profit_group >= GROUP_PROFIT_STOP:
                    group_pause = True
                    state = "GROUP_PAUSE_PROFIT"
            else:
                hit_group = 0
                phase_profit_group += LOSS_GROUP
                total_profit_all_phase += LOSS_GROUP
                phase_hits_group.append(0)
                total_hits_all_phase.append(0)

                consecutive_losses += 1
                group_consecutive_losses += 1

                if used_keep:
                    if keep_rounds_left <= 0:
                        last_trade_was_loss = False
                        keep_bet_group = None
                    else:
                        last_trade_was_loss = True
                else:
                    last_trade_was_loss = True
                    keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                    keep_bet_group = final_vote_group

                if consecutive_losses >= 2:
                    pause_rounds_left = PAUSE_AFTER_2_LOSSES
                    keep_rounds_left = 0
                    keep_bet_group = None
                    last_trade_was_loss = False
                    consecutive_losses = 0
                    state = "PAUSE_TRIGGER"

                if group_consecutive_losses >= GROUP_MAX_LOSS_STREAK:
                    group_pause = True
                    keep_rounds_left = 0
                    keep_bet_group = None
                    last_trade_was_loss = False
                    state = "GROUP_PAUSE_LOSS"

            if (
                phase == 1
                and (not relocked)
                and len(phase_hits_group) >= RELOCK_TRIGGER_LOSS_STREAK
                and phase_hits_group[-RELOCK_TRIGGER_LOSS_STREAK:] == [0] * RELOCK_TRIGGER_LOSS_STREAK
                and phase_profit_group <= RELOCK_TRIGGER_PROFIT
            ):
                current_round = i
                scan_end = current_round
                scan_start = max(LOCK_ROUND_START, scan_end - RELOCK_SCAN_LEN + 1 - RELOCK_BUFFER)

                (
                    new_selected_lock_round,
                    new_locked_windows,
                    new_scan_df_all,
                    new_scan_df_filtered,
                    new_round_eval_df,
                    new_lock_mode,
                ) = find_best_lock_in_range(
                    groups,
                    scan_start,
                    scan_end,
                    PHASE2_TOP_WINDOWS,
                    PHASE2_VOTE_REQUIRED,
                )

                if new_selected_lock_round is not None and len(new_locked_windows) == PHASE2_TOP_WINDOWS:
                    relock_triggered_now = True
                    relocked = True
                    relock_round = current_round

                    phase = 2
                    locked_windows = new_locked_windows
                    selected_lock_round = new_selected_lock_round
                    lock_mode = new_lock_mode
                    scan_df_all = new_scan_df_all
                    scan_df_filtered = new_scan_df_filtered
                    round_eval_df = new_round_eval_df
                    lock_scan_start = scan_start
                    lock_scan_end = scan_end
                    lock_vote_required = PHASE2_VOTE_REQUIRED
                    lock_top_windows = PHASE2_TOP_WINDOWS

                    if RESET_PROFIT_ON_RELOCK:
                        phase_profit_group = 0.0
                        phase_hits_group = []

                    phase_last_trade = current_round
                    keep_bet_group = None
                    keep_rounds_left = 0
                    last_trade_was_loss = False
                    consecutive_losses = 0
                    pause_rounds_left = 0
                    group_consecutive_losses = 0
                    group_pause = False
                    state = "RELOCK_TO_PHASE2"

        else:
            if used_keep and keep_rounds_left <= 0:
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False

        history_rows.append({
            "phase": phase_before_trade if not relock_triggered_now else 2,
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "vote_group": vote_group,
            "confidence_group": confidence_group,
            "vote_required": lock_vote_required if not relock_triggered_now else PHASE2_VOTE_REQUIRED,
            "new_signal": new_signal,
            "used_keep": used_keep,
            "keep_group": keep_bet_group,
            "keep_left": keep_rounds_left,
            "final_vote_group": final_vote_group,
            "signal": final_signal,
            "trade": trade,
            "bet_group": bet_group,
            "hit_group": hit_group,
            "state": state,
            "phase_profit_group": phase_profit_group,
            "total_profit_all_phase": total_profit_all_phase,
            "consecutive_losses": consecutive_losses,
            "pause_left": pause_rounds_left,
            "group_consecutive_losses": group_consecutive_losses,
            "group_pause": group_pause,
            "locked_windows": ", ".join(map(str, locked_windows)),
            "relocked": relocked,
            "relock_triggered_now": relock_triggered_now,
        })

    hist = pd.DataFrame(history_rows)

    result.update({
        "hist": hist,
        "current_phase": phase,
        "phase_profit_group": phase_profit_group,
        "phase_hits_group": phase_hits_group,
        "total_profit_all_phase": total_profit_all_phase,
        "total_hits_all_phase": total_hits_all_phase,
        "locked_windows": locked_windows,
        "selected_lock_round": selected_lock_round,
        "lock_mode": lock_mode,
        "scan_df_all": scan_df_all,
        "scan_df_filtered": scan_df_filtered,
        "round_eval_df": round_eval_df,
        "lock_scan_start": lock_scan_start,
        "lock_scan_end": lock_scan_end,
        "lock_vote_required": lock_vote_required,
        "lock_top_windows": lock_top_windows,
        "relocked": relocked,
        "relock_round": relock_round,
        "group_pause": group_pause,
        "pause_rounds_left": pause_rounds_left,
        "keep_bet_group": keep_bet_group,
        "keep_rounds_left": keep_rounds_left,
        "last_trade_was_loss": last_trade_was_loss,
        "consecutive_losses": consecutive_losses,
        "group_consecutive_losses": group_consecutive_losses,
        "phase_last_trade": phase_last_trade,
    })
    return result

# ================= RUN REPLAY =================
sim = simulate_engine(numbers, groups)

hist = sim["hist"]
phase = sim["current_phase"]
phase_profit_group = sim["phase_profit_group"]
phase_hits_group = sim["phase_hits_group"]
total_profit_all_phase = sim["total_profit_all_phase"]
total_hits_all_phase = sim["total_hits_all_phase"]

locked_windows = sim["locked_windows"]
selected_lock_round = sim["selected_lock_round"]
lock_mode = sim["lock_mode"]
scan_df_all = sim["scan_df_all"]
scan_df_filtered = sim["scan_df_filtered"]
round_eval_df = sim["round_eval_df"]
lock_scan_start = sim["lock_scan_start"]
lock_scan_end = sim["lock_scan_end"]
lock_vote_required = sim["lock_vote_required"]
lock_top_windows = sim["lock_top_windows"]
relocked = sim["relocked"]
relock_round = sim["relock_round"]
group_pause = sim["group_pause"]
pause_rounds_left = sim["pause_rounds_left"]
keep_bet_group = sim["keep_bet_group"]
keep_rounds_left = sim["keep_rounds_left"]
last_trade_was_loss = sim["last_trade_was_loss"]
consecutive_losses = sim["consecutive_losses"]
group_consecutive_losses = sim["group_consecutive_losses"]
phase_last_trade = sim["phase_last_trade"]

# ================= CURRENT LOCK RAW CHECK =================
scan_range_bt = {"trades": 0, "profit_group": 0.0, "winrate_group": 0.0, "max_drawdown_group": 0.0}
post_lock_bt = {"trades": 0, "profit_group": 0.0, "winrate_group": 0.0, "max_drawdown_group": 0.0}

if (
    locked_windows
    and lock_scan_start is not None
    and lock_scan_end is not None
    and lock_vote_required is not None
):
    scan_end_exclusive = min(lock_scan_end + 1, len(groups))
    post_start = min(lock_scan_end + 1, len(groups))

    scan_range_bt = backtest_bundle_vote_range(
        groups, locked_windows, lock_scan_start, scan_end_exclusive, lock_vote_required
    )
    post_lock_bt = backtest_bundle_vote_range(
        groups, locked_windows, post_start, len(groups), lock_vote_required
    )

# ================= NEXT BET (LIVE EVALUATION) =================
next_round = len(groups)
preds_group = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds_group:
    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
else:
    vote_group, confidence_group = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

new_signal = confidence_group >= lock_vote_required if vote_group is not None else False
used_keep_next = False
final_vote_group = vote_group

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
            final_vote_group = next_keep_bet_group
            used_keep_next = True

    final_signal = new_signal or used_keep_next
    signal = final_signal
    can_bet = (not group_pause) and signal and distance >= GAP and next_round > (lock_scan_end or 0)

    if group_pause:
        next_state = "GROUP_PAUSED"
    else:
        next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "phase": phase,
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "vote_group": vote_group,
    "confidence_group": confidence_group,
    "vote_required": lock_vote_required,
    "new_signal": new_signal,
    "used_keep": used_keep_next,
    "keep_group": next_keep_bet_group,
    "keep_left": next_keep_rounds_left,
    "final_vote_group": final_vote_group,
    "signal": signal,
    "trade": False,
    "bet_group": final_vote_group if can_bet else None,
    "hit_group": None,
    "state": next_state,
    "phase_profit_group": phase_profit_group,
    "total_profit_all_phase": total_profit_all_phase,
    "consecutive_losses": consecutive_losses,
    "pause_left": pause_rounds_left,
    "group_consecutive_losses": group_consecutive_losses,
    "group_pause": group_pause,
    "locked_windows": ", ".join(map(str, locked_windows)),
    "relocked": relocked,
    "relock_triggered_now": False,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= UI =================
st.title("🎯 Replay đúng quá khứ + Live đánh giá hiện tại")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number if current_number is not None else "-")
c2.metric("Current Group", current_group if current_group is not None else "-")
c3.metric("Phase", phase)
c4.metric("Next Group", final_vote_group if final_vote_group is not None else "-")

st.write("Locked Windows:", locked_windows)
st.write("Vote Required:", lock_vote_required)
st.write("Top Windows:", lock_top_windows)
st.write("Vote Strength:", confidence_group)
st.write("Best Lock Round:", selected_lock_round)
st.write("Scan Range:", f"{lock_scan_start} -> {lock_scan_end}")
st.write("Lock Mode:", lock_mode)
st.write("Relocked:", relocked)
st.write("Relock Round:", relock_round)
st.write("Group Pause:", group_pause)
st.write("Pause Left:", pause_rounds_left)

if lock_mode == "fallback":
    st.warning("Đang dùng bộ lock fallback.")

if group_pause:
    st.warning("⛔ GROUP PAUSED")
elif pause_rounds_left > 0:
    st.warning(f"⏸ PAUSE {pause_rounds_left}")
elif can_bet and final_vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:22px;border-radius:10px;text-align:center;font-size:30px;color:white;font-weight:bold;">
        BET GROUP → {final_vote_group}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT")

st.subheader("Stats")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Profit", phase_profit_group)
s2.metric("Phase Trades", len(phase_hits_group))
s3.metric("Phase Winrate %", round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0)
s4.metric("Loss Streak", group_consecutive_losses)

t1, t2, t3 = st.columns(3)
t1.metric("Total Profit All Phase", total_profit_all_phase)
t2.metric("Total Trades All Phase", len(total_hits_all_phase))
t3.metric("Total Winrate All Phase %", round(np.mean(total_hits_all_phase) * 100, 2) if total_hits_all_phase else 0)

st.subheader("Current Lock Backtest Check")

b1, b2, b3, b4 = st.columns(4)
b1.metric(f"Scan {lock_scan_start}-{lock_scan_end} Trades", scan_range_bt["trades"])
b2.metric(f"Scan {lock_scan_start}-{lock_scan_end} Profit", scan_range_bt["profit_group"])
b3.metric(f"Scan {lock_scan_start}-{lock_scan_end} Winrate %", round(scan_range_bt["winrate_group"] * 100, 2))
b4.metric(f"Scan {lock_scan_start}-{lock_scan_end} MaxDD", scan_range_bt["max_drawdown_group"])

d1, d2, d3, d4 = st.columns(4)
d1.metric(f"Post-{lock_scan_end} Trades", post_lock_bt["trades"])
d2.metric(f"Post-{lock_scan_end} Profit", post_lock_bt["profit_group"])
d3.metric(f"Post-{lock_scan_end} Winrate %", round(post_lock_bt["winrate_group"] * 100, 2))
d4.metric(f"Post-{lock_scan_end} MaxDD", post_lock_bt["max_drawdown_group"])

st.subheader("Phase Profit Curve (Current Phase Only)")
if not hist_display.empty:
    current_phase_df = hist_display[hist_display["phase"] == phase].copy()
    if not current_phase_df.empty:
        st.line_chart(current_phase_df["phase_profit_group"].reset_index(drop=True))

st.subheader("Total Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_all_phase"].reset_index(drop=True))

if SHOW_DEBUG_TABLES:
    with st.expander("Phase Summary"):
        if not hist.empty:
            trade_hist = hist[hist["trade"] == True].copy()
            if not trade_hist.empty:
                phase_summary = (
                    trade_hist.groupby("phase")
                    .agg(
                        trades=("hit_group", lambda s: s.notna().sum()),
                        wins=("hit_group", lambda s: (s == 1).sum()),
                        total_profit=("total_profit_all_phase", "last"),
                    )
                    .reset_index()
                )
                st.dataframe(phase_summary, use_container_width=True)

    with st.expander("Round Evaluation"):
        st.dataframe(round_eval_df, use_container_width=True)

    with st.expander("Locked Windows"):
        if not scan_df_all.empty:
            st.dataframe(
                scan_df_all[scan_df_all["window"].isin(locked_windows)].sort_values("window"),
                use_container_width=True,
            )

    with st.expander("Filtered Windows"):
        st.dataframe(scan_df_filtered.head(25), use_container_width=True)

st.subheader("History")

history_view = hist_display.iloc[::-1].head(SHOW_HISTORY_ROWS).copy()

if SHOW_STYLED_HISTORY:
    def highlight_trade(row):
        if row["state"] in ("NEXT", "NEXT_KEEP"):
            return ["background-color: #ffd700"] * len(row)
        if row["state"] == "TRADE_KEEP":
            return ["background-color: #ffb347; color:black"] * len(row)
        if row["state"] == "PAUSE":
            return ["background-color: #87ceeb; color:black"] * len(row)
        if row["state"] == "PAUSE_TRIGGER":
            return ["background-color: #9370db; color:white"] * len(row)
        if row["state"] == "RELOCK_TO_PHASE2":
            return ["background-color: #32cd32; color:black"] * len(row)
        if row["state"] in ("GROUP_PAUSE_PROFIT", "GROUP_PAUSE_LOSS", "GROUP_PAUSED"):
            return ["background-color: #d9534f; color:white"] * len(row)
        if row["trade"]:
            return ["background-color: #ff4b4b; color:white"] * len(row)
        return [""] * len(row)

    st.dataframe(
        history_view.style.apply(highlight_trade, axis=1),
        use_container_width=True,
    )
else:
    st.dataframe(history_view, use_container_width=True)
