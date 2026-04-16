import time
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1500, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# Lock scan range
LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

# Window range
WINDOW_MIN = 6
WINDOW_MAX = 26
TOP_WINDOWS = 4
MAX_CANDIDATE_WINDOWS = 10
MIN_WINDOW_SPACING = 2

# Vote
VOTE_REQUIRED = 3
GAP = 1

# PnL
WIN_GROUP = 2.5
LOSS_GROUP = -1.0
WIN_COLOR = 1.5
LOSS_COLOR = -1.0

# Live risk control
PAUSE_AFTER_2_LOSSES = 0
GROUP_MAX_LOSS_STREAK = 5
GROUP_PROFIT_STOP = 6.0

# Window filter
MIN_TRADES_PER_WINDOW = 20
RECENT_WINDOW_SIZE = 20

# Train / validate (2 tầng)
VALIDATE1_LEN = 20
VALIDATE2_LEN = 20
MIN_TRAIN_LEN = 120
MIN_VALIDATE_TRADES = 3
VALIDATE_MIN_PROFIT = 0.0
VALIDATE_MIN_DRAWDOWN = -4.0

# Single window score
WINDOW_SCORE_WINRATE_WEIGHT = 8.0
WINDOW_SCORE_TRADES_WEIGHT = 1.2
WINDOW_SCORE_RECENT_WEIGHT = 0.8
WINDOW_SCORE_DRAWDOWN_PENALTY = 0.7

# Bundle train score
BUNDLE_SCORE_PROFIT_WEIGHT = 1.0
BUNDLE_SCORE_WINRATE_WEIGHT = 10.0
BUNDLE_SCORE_TRADES_WEIGHT = 1.5
BUNDLE_SCORE_DRAWDOWN_PENALTY = 1.0
BUNDLE_SCORE_RECENT_WEIGHT = 1.0

# Final score after validate1 + validate2
FINAL_VAL1_PROFIT_WEIGHT = 1.5
FINAL_VAL2_PROFIT_WEIGHT = 2.0
FINAL_VAL2_WINRATE_WEIGHT = 8.0
FINAL_VAL1_DD_PENALTY = 1.0
FINAL_VAL2_DD_PENALTY = 1.2

# Run-pattern PRO
RUN_MIN_LEN = 2
RUN_MAX_LEN = 5
RUN_MIN_SAMPLES = 5
RUN_MIN_PROB = 0.42
RUN_STRONG_PROB = 0.60
RUN_OVERRIDE_PROB = 0.70

# Regime filter
REGIME_LOOKBACK = 30
REGIME_MIN_TRADES = 3
REGIME_MIN_PROFIT = -2.0
REGIME_MIN_DRAWDOWN = -4.0

# Hybrid score
BET_SCORE = 0.78
BET_SMALL_SCORE = 0.58

SHOW_HISTORY_ROWS = 150

# ================= LOAD DATA =================
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Sheet must contain column 'number'")
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]
    return nums

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

def color_of(n: int) -> str:
    if n <= 4:
        return "red"
    if n <= 8:
        return "green"
    return "blue"

def group_color_match(group_vote: int, color_vote: str) -> bool:
    group_to_numbers = {
        1: {1, 2, 3},
        2: {4, 5, 6},
        3: {7, 8, 9},
        4: {10, 11, 12},
    }
    color_to_numbers = {
        "red": {1, 2, 3, 4},
        "green": {5, 6, 7, 8},
        "blue": {9, 10, 11, 12},
    }
    if group_vote not in group_to_numbers or color_vote not in color_to_numbers:
        return False
    return len(group_to_numbers[group_vote] & color_to_numbers[color_vote]) > 0

groups = [group_of(n) for n in numbers]
colors = [color_of(n) for n in numbers]

# ================= GUARD =================
if len(groups) < LOCK_ROUND_START:
    st.error(
        f"Chưa đủ dữ liệu để scan vùng {LOCK_ROUND_START} → {LOCK_ROUND_END}. "
        f"Hiện chỉ có {len(groups)} rounds."
    )
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

def bucket_of_window(w: int) -> str:
    if w <= 10:
        return "short"
    if w <= 17:
        return "mid"
    return "long"

def pick_spaced_windows(df_sorted, top_n, min_spacing):
    selected_rows = []
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if all(abs(w - int(x["window"])) >= min_spacing for x in selected_rows):
            selected_rows.append(row.to_dict())
            if len(selected_rows) >= top_n:
                break
    return pd.DataFrame(selected_rows)

def get_current_run(seq):
    if not seq:
        return None, 0
    cur = seq[-1]
    run_len = 1
    j = len(seq) - 2
    while j >= 0 and seq[j] == cur:
        run_len += 1
        j -= 1
    return cur, run_len

# ================= RUN PATTERN PRO =================
def build_run_pattern_stats(seq, min_run_len=2, max_run_len=5):
    stats = defaultdict(Counter)
    n = len(seq)
    i = 0
    while i < n:
        run_value = seq[i]
        j = i
        while j < n and seq[j] == run_value:
            j += 1
        run_len = j - i
        if j < n:
            next_value = seq[j]
            for rl in range(min_run_len, min(run_len, max_run_len) + 1):
                stats[(run_value, rl)][next_value] += 1
        i = j
    return stats

def get_run_signal(seq, min_run_len=2, max_run_len=5, min_samples=5, min_prob=0.42):
    if len(seq) < 10:
        return None

    stats = build_run_pattern_stats(seq, min_run_len, max_run_len)
    cur, run_len = get_current_run(seq)
    capped = min(run_len, max_run_len)

    # exact run
    for rl in range(capped, min_run_len - 1, -1):
        key = (cur, rl)
        if key in stats:
            cnt = stats[key]
            total = sum(cnt.values())
            if total >= min_samples:
                nxt, c = cnt.most_common(1)[0]
                prob = c / total
                if prob >= min_prob:
                    return {
                        "run_value": cur,
                        "run_len": rl,
                        "next_value": nxt,
                        "samples": total,
                        "prob": prob,
                        "mode": "run_exact",
                        "dist": dict(cnt)
                    }

    # fallback cùng group
    candidates = []
    for (rv, rl), cnt in stats.items():
        if rv == cur:
            total = sum(cnt.values())
            if total >= min_samples:
                nxt, c = cnt.most_common(1)[0]
                prob = c / total
                if prob >= min_prob:
                    edge = 0.0
                    ranked = cnt.most_common(2)
                    if len(ranked) > 1:
                        edge = ranked[0][1] / total - ranked[1][1] / total
                    candidates.append({
                        "run_value": rv,
                        "run_len": rl,
                        "next_value": nxt,
                        "samples": total,
                        "prob": prob,
                        "edge": edge,
                        "mode": "run_fallback",
                        "dist": dict(cnt)
                    })
    if candidates:
        candidates.sort(key=lambda x: (x["prob"], x["edge"], x["samples"], x["run_len"]), reverse=True)
        return candidates[0]

    return None

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

    if trades > 0:
        score = (
            profit * 1.0
            + winrate * WINDOW_SCORE_WINRATE_WEIGHT
            + np.log(trades + 1) * WINDOW_SCORE_TRADES_WEIGHT
            + recent_profit * WINDOW_SCORE_RECENT_WEIGHT
            - abs(max_drawdown) * WINDOW_SCORE_DRAWDOWN_PENALTY
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
        "score": score,
    }

def build_window_tables(train_groups):
    rows = [evaluate_window_group(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["score", "recent_profit", "profit", "winrate", "trades"],
        ascending=[False, False, False, False, False]
    ).reset_index(drop=True)

    positive_df = df[
        (df["profit"] > 0) &
        (df["trades"] >= MIN_TRADES_PER_WINDOW)
    ].copy()

    positive_df = positive_df.sort_values(
        ["score", "recent_profit", "profit", "winrate", "trades", "max_drawdown"],
        ascending=[False, False, False, False, False, False]
    ).reset_index(drop=True)

    selected_seed = positive_df.head(MAX_CANDIDATE_WINDOWS).copy()

    if len(selected_seed) < MAX_CANDIDATE_WINDOWS:
        selected_windows = set(selected_seed["window"].tolist()) if not selected_seed.empty else set()
        remain_df = df[
            (df["trades"] >= MIN_TRADES_PER_WINDOW) &
            (~df["window"].isin(selected_windows))
        ].copy()
        remain_df = remain_df.sort_values(
            ["score", "recent_profit", "profit", "winrate", "trades", "max_drawdown"],
            ascending=[False, False, False, False, False, False]
        ).reset_index(drop=True)
        need = MAX_CANDIDATE_WINDOWS - len(selected_seed)
        if need > 0 and len(remain_df) > 0:
            selected_seed = pd.concat([selected_seed, remain_df.head(need)], ignore_index=True)

    if len(selected_seed) < MAX_CANDIDATE_WINDOWS:
        selected_windows = set(selected_seed["window"].tolist()) if not selected_seed.empty else set()
        remain_df = df[~df["window"].isin(selected_windows)].copy()
        remain_df = remain_df.sort_values(
            ["score", "recent_profit", "profit", "winrate", "trades", "max_drawdown"],
            ascending=[False, False, False, False, False, False]
        ).reset_index(drop=True)
        need = MAX_CANDIDATE_WINDOWS - len(selected_seed)
        if need > 0 and len(remain_df) > 0:
            selected_seed = pd.concat([selected_seed, remain_df.head(need)], ignore_index=True)

    candidate_df = selected_seed.sort_values(
        ["score", "recent_profit", "profit", "winrate", "trades", "max_drawdown"],
        ascending=[False, False, False, False, False, False]
    ).reset_index(drop=True)

    spaced_candidate_df = pick_spaced_windows(candidate_df, MAX_CANDIDATE_WINDOWS, MIN_WINDOW_SPACING)
    candidate_windows = spaced_candidate_df["window"].astype(int).tolist()

    if len(candidate_windows) < TOP_WINDOWS:
        candidate_windows = selected_seed["window"].astype(int).tolist()[:MAX_CANDIDATE_WINDOWS]

    selected_df = df[df["window"].isin(candidate_windows)].copy()
    selected_df = selected_df.sort_values("window").reset_index(drop=True)

    return candidate_windows, df_all, positive_df, selected_df, spaced_candidate_df

# ================= BUNDLE BACKTEST =================
def backtest_bundle_vote_range(seq_groups, seq_colors, windows, start_idx, end_idx):
    results_group = []
    results_color = []
    trades = 0
    wins_group = 0
    wins_color = 0
    last_trade = -999999

    effective_start = max(start_idx, max(windows))

    for i in range(effective_start, end_idx):
        preds_group = [seq_groups[i - w] for w in windows]
        preds_color = [seq_colors[i - w] for w in windows]

        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        vote_color, _ = Counter(preds_color).most_common(1)[0]

        signal = confidence_group >= VOTE_REQUIRED
        gc_ok = group_color_match(vote_group, vote_color)

        if signal and gc_ok and (i - last_trade >= GAP):
            last_trade = i
            trades += 1

            group_hit = 1 if seq_groups[i] == vote_group else 0
            color_hit = 1 if seq_colors[i] == vote_color else 0

            wins_group += group_hit
            wins_color += color_hit
            results_group.append(group_hit)
            results_color.append(color_hit)

    profit_group = float(sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results_group))
    profit_color = float(sum(WIN_COLOR if r == 1 else LOSS_COLOR for r in results_color))
    winrate_group = wins_group / trades if trades > 0 else 0.0
    winrate_color = wins_color / trades if trades > 0 else 0.0
    max_drawdown_group = compute_max_drawdown(results_group, WIN_GROUP, LOSS_GROUP)
    recent_profit_group = compute_recent_profit(results_group, RECENT_WINDOW_SIZE, WIN_GROUP, LOSS_GROUP)

    return {
        "trades": trades,
        "wins_group": wins_group,
        "wins_color": wins_color,
        "profit_group": profit_group,
        "profit_color": profit_color,
        "winrate_group": winrate_group,
        "winrate_color": winrate_color,
        "max_drawdown_group": max_drawdown_group,
        "recent_profit_group": recent_profit_group,
    }

def build_bundle_backtest(train_groups, train_colors, candidate_windows):
    bundle_rows = []

    if len(candidate_windows) >= TOP_WINDOWS:
        for combo in combinations(candidate_windows, TOP_WINDOWS):
            combo = sorted(combo)

            buckets = {bucket_of_window(w) for w in combo}
            if len(buckets) < 3:
                continue

            train_bt = backtest_bundle_vote_range(
                train_groups,
                train_colors,
                combo,
                0,
                len(train_groups),
            )

            if train_bt["trades"] > 0:
                train_score = (
                    train_bt["profit_group"] * BUNDLE_SCORE_PROFIT_WEIGHT
                    + train_bt["winrate_group"] * BUNDLE_SCORE_WINRATE_WEIGHT
                    + np.log(train_bt["trades"] + 1) * BUNDLE_SCORE_TRADES_WEIGHT
                    + train_bt["recent_profit_group"] * BUNDLE_SCORE_RECENT_WEIGHT
                    - abs(train_bt["max_drawdown_group"]) * BUNDLE_SCORE_DRAWDOWN_PENALTY
                )
            else:
                train_score = -999999.0

            bundle_rows.append(
                {
                    "windows": ", ".join(map(str, combo)),
                    "train_trades": train_bt["trades"],
                    "train_profit_group": train_bt["profit_group"],
                    "train_profit_color": train_bt["profit_color"],
                    "train_winrate_group": train_bt["winrate_group"],
                    "train_winrate_color": train_bt["winrate_color"],
                    "train_max_drawdown_group": train_bt["max_drawdown_group"],
                    "train_recent_profit_group": train_bt["recent_profit_group"],
                    "train_score": train_score,
                }
            )

    bundle_df = pd.DataFrame(bundle_rows)
    if not bundle_df.empty:
        bundle_df = bundle_df.sort_values(
            ["train_score", "train_profit_group", "train_winrate_group", "train_trades"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

    return bundle_df

# ================= LOCK SCAN =================
def find_best_lock_round_168_180(all_groups, all_colors):
    effective_lock_round_end = min(LOCK_ROUND_END, len(all_groups))
    if effective_lock_round_end < LOCK_ROUND_START:
        return None, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    best_round = None
    best_final_score = -999999.0
    best_windows = []
    best_scan_all = pd.DataFrame()
    best_positive = pd.DataFrame()
    best_selected = pd.DataFrame()
    best_bundle_df = pd.DataFrame()
    best_candidate_df = pd.DataFrame()

    round_eval_rows = []

    for r in range(LOCK_ROUND_START, effective_lock_round_end + 1):
        total_validate = VALIDATE1_LEN + VALIDATE2_LEN
        if r < total_validate + MIN_TRAIN_LEN:
            round_eval_rows.append(
                {
                    "lock_round": r,
                    "train_end": None,
                    "validate1_start": None,
                    "validate1_end": None,
                    "validate2_start": None,
                    "validate2_end": None,
                    "positive_windows": 0,
                    "selected_count": 0,
                    "selected_windows": "",
                    "bundle_score": -999999.0,
                    "validate_pass_count": 0,
                }
            )
            continue

        train_end = r - total_validate
        validate1_start = train_end
        validate1_end = train_end + VALIDATE1_LEN
        validate2_start = validate1_end
        validate2_end = r

        train_groups = all_groups[:train_end]
        train_colors = all_colors[:train_end]

        all_to_validate_groups = all_groups[:validate2_end]
        all_to_validate_colors = all_colors[:validate2_end]

        (
            candidate_windows,
            tmp_all,
            tmp_positive,
            _tmp_selected_candidates,
            tmp_candidate_df,
        ) = build_window_tables(train_groups)

        pos_count = len(tmp_positive)
        bundle_df = build_bundle_backtest(train_groups, train_colors, candidate_windows)

        passed_rows = []

        if not bundle_df.empty:
            for _, row in bundle_df.iterrows():
                windows = [int(x) for x in row["windows"].split(", ")]

                val1_bt = backtest_bundle_vote_range(
                    all_to_validate_groups, all_to_validate_colors, windows,
                    validate1_start, validate1_end
                )

                val2_bt = backtest_bundle_vote_range(
                    all_to_validate_groups, all_to_validate_colors, windows,
                    validate2_start, validate2_end
                )

                validate_pass = (
                    val1_bt["trades"] >= MIN_VALIDATE_TRADES
                    and val2_bt["trades"] >= MIN_VALIDATE_TRADES
                    and val1_bt["profit_group"] >= VALIDATE_MIN_PROFIT
                    and val2_bt["profit_group"] >= VALIDATE_MIN_PROFIT
                    and val1_bt["max_drawdown_group"] >= VALIDATE_MIN_DRAWDOWN
                    and val2_bt["max_drawdown_group"] >= VALIDATE_MIN_DRAWDOWN
                )

                final_score = -999999.0
                if validate_pass:
                    final_score = (
                        float(row["train_score"])
                        + val1_bt["profit_group"] * FINAL_VAL1_PROFIT_WEIGHT
                        + val2_bt["profit_group"] * FINAL_VAL2_PROFIT_WEIGHT
                        + val2_bt["winrate_group"] * FINAL_VAL2_WINRATE_WEIGHT
                        - abs(val1_bt["max_drawdown_group"]) * FINAL_VAL1_DD_PENALTY
                        - abs(val2_bt["max_drawdown_group"]) * FINAL_VAL2_DD_PENALTY
                    )

                passed_rows.append(
                    {
                        "windows": row["windows"],
                        "train_trades": row["train_trades"],
                        "train_profit_group": row["train_profit_group"],
                        "train_profit_color": row["train_profit_color"],
                        "train_winrate_group": row["train_winrate_group"],
                        "train_winrate_color": row["train_winrate_color"],
                        "train_max_drawdown_group": row["train_max_drawdown_group"],
                        "train_recent_profit_group": row["train_recent_profit_group"],
                        "train_score": row["train_score"],
                        "validate1_trades": val1_bt["trades"],
                        "validate1_profit_group": val1_bt["profit_group"],
                        "validate1_profit_color": val1_bt["profit_color"],
                        "validate1_winrate_group": val1_bt["winrate_group"],
                        "validate1_max_drawdown_group": val1_bt["max_drawdown_group"],
                        "validate2_trades": val2_bt["trades"],
                        "validate2_profit_group": val2_bt["profit_group"],
                        "validate2_profit_color": val2_bt["profit_color"],
                        "validate2_winrate_group": val2_bt["winrate_group"],
                        "validate2_max_drawdown_group": val2_bt["max_drawdown_group"],
                        "validate_pass": validate_pass,
                        "final_score": final_score,
                    }
                )

        final_bundle_df = pd.DataFrame(passed_rows)
        if not final_bundle_df.empty:
            final_bundle_df = final_bundle_df.sort_values(
                ["final_score", "validate2_profit_group", "train_profit_group", "validate2_winrate_group"],
                ascending=[False, False, False, False]
            ).reset_index(drop=True)

        validate_pass_count = int(final_bundle_df["validate_pass"].sum()) if not final_bundle_df.empty else 0

        selected_windows = []
        selected_df = pd.DataFrame()
        bundle_score = -999999.0

        if not final_bundle_df.empty and validate_pass_count > 0:
            best_row = final_bundle_df[final_bundle_df["validate_pass"] == True].iloc[0]
            selected_windows = [int(x) for x in best_row["windows"].split(", ")]
            selected_df = tmp_all[tmp_all["window"].isin(selected_windows)].copy().sort_values("window").reset_index(drop=True)
            bundle_score = float(best_row["final_score"])

        round_eval_rows.append(
            {
                "lock_round": r,
                "train_end": train_end,
                "validate1_start": validate1_start,
                "validate1_end": validate1_end,
                "validate2_start": validate2_start,
                "validate2_end": validate2_end,
                "positive_windows": pos_count,
                "selected_count": len(selected_windows),
                "selected_windows": ", ".join(map(str, selected_windows)),
                "bundle_score": bundle_score,
                "validate_pass_count": validate_pass_count,
            }
        )

        if (
            len(selected_windows) == TOP_WINDOWS
            and validate_pass_count > 0
            and bundle_score > best_final_score
        ):
            best_final_score = bundle_score
            best_round = r
            best_windows = selected_windows
            best_scan_all = tmp_all
            best_positive = tmp_positive
            best_selected = selected_df
            best_bundle_df = final_bundle_df
            best_candidate_df = tmp_candidate_df

    round_eval_df = pd.DataFrame(round_eval_rows)
    return (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        best_bundle_df,
        best_candidate_df,
        round_eval_df,
    )

# ================= STATE INIT =================
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,
        "total_profit_group": 0.0,
        "total_profit_color": 0.0,
        "last_trade": -999,
        "hits_group": [],
        "hits_color": [],
        "history_rows": [],
        "locked_windows": [],
        "scan_df_all": pd.DataFrame(),
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "bundle_df": pd.DataFrame(),
        "candidate_df": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,
        "base_data_len": None,
        "consecutive_losses": 0,
        "pause_rounds_left": 0,
        "group_consecutive_losses": 0,
        "group_pause": False,
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

if st.session_state.base_data_len is not None and len(groups) < st.session_state.base_data_len:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ================= INITIAL LOCK =================
if not st.session_state.live_initialized:
    (
        lock_round_used,
        locked_windows,
        scan_df_all,
        scan_df_positive,
        scan_df_selected,
        bundle_df,
        candidate_df,
        round_eval_df,
    ) = find_best_lock_round_168_180(groups, colors)

    if lock_round_used is None:
        st.error("Không tìm được bộ lock tốt trong vùng 168 → 180 theo train/validate.")
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.bundle_df = bundle_df
    st.session_state.candidate_df = candidate_df
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.processed_until = lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ================= LOAD STATE =================
total_profit_group = st.session_state.total_profit_group
total_profit_color = st.session_state.total_profit_color
last_trade = st.session_state.last_trade
hits_group = st.session_state.hits_group
hits_color = st.session_state.hits_color
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
scan_df_all = st.session_state.scan_df_all
scan_df_positive = st.session_state.scan_df_positive
scan_df_selected = st.session_state.scan_df_selected
bundle_df = st.session_state.bundle_df
candidate_df = st.session_state.candidate_df
round_eval_df = st.session_state.round_eval_df
lock_round_used = st.session_state.lock_round_used
processed_until = st.session_state.processed_until
consecutive_losses = st.session_state.consecutive_losses
pause_rounds_left = st.session_state.pause_rounds_left
group_consecutive_losses = st.session_state.group_consecutive_losses
group_pause = st.session_state.group_pause

# ================= LIVE LOOP =================
for i in range(processed_until + 1, len(groups)):
    if i < lock_round_used:
        continue

    preds_group = [groups[i - w] for w in locked_windows if i - w >= 0]
    preds_color = [colors[i - w] for w in locked_windows if i - w >= 0]

    if not preds_group:
        processed_until = i
        continue

    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_color, confidence_color = Counter(preds_color).most_common(1)[0]

    # ===== RUN PRO =====
    run_group_signal = get_run_signal(groups[:i], RUN_MIN_LEN, RUN_MAX_LEN, RUN_MIN_SAMPLES, RUN_MIN_PROB)
    run_color_signal = get_run_signal(colors[:i], RUN_MIN_LEN, RUN_MAX_LEN, RUN_MIN_SAMPLES, RUN_MIN_PROB)

    run_group_ok = True
    run_color_ok = True
    run_group_prob = None
    run_color_prob = None

    if run_group_signal is not None:
        run_group_prob = round(run_group_signal["prob"], 4)
        run_group_ok = (run_group_signal["next_value"] == vote_group)

    if run_color_signal is not None:
        run_color_prob = round(run_color_signal["prob"], 4)
        run_color_ok = (run_color_signal["next_value"] == vote_color)

    # override nếu run quá mạnh
    final_vote_group = vote_group
    final_vote_color = vote_color
    run_override = False

    if run_group_signal is not None and run_group_signal["prob"] >= RUN_OVERRIDE_PROB:
        final_vote_group = run_group_signal["next_value"]
        run_override = True

    if run_color_signal is not None and run_color_signal["prob"] >= RUN_OVERRIDE_PROB:
        final_vote_color = run_color_signal["next_value"]

    group_color_ok = group_color_match(final_vote_group, final_vote_color)

    # current run penalty / bonus
    current_group_run_value, current_group_run_len = get_current_run(groups[:i])
    current_color_run_value, current_color_run_len = get_current_run(colors[:i])

    # regime
    recent_health = backtest_bundle_vote_range(
        groups[:i], colors[:i], locked_windows,
        max(0, i - REGIME_LOOKBACK), i
    )
    regime_ok = (
        recent_health["trades"] >= REGIME_MIN_TRADES
        and recent_health["profit_group"] >= REGIME_MIN_PROFIT
        and recent_health["max_drawdown_group"] >= REGIME_MIN_DRAWDOWN
    )

    new_signal = confidence_group >= VOTE_REQUIRED
    distance = i - last_trade

    if total_profit_group >= GROUP_PROFIT_STOP:
        group_pause = True

    if pause_rounds_left > 0:
        pause_rounds_left -= 1
        history_rows.append(
            {
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "color": colors[i],
                "vote_group": vote_group,
                "vote_color": vote_color,
                "final_vote_group": final_vote_group,
                "final_vote_color": final_vote_color,
                "confidence_group": confidence_group,
                "confidence_color": confidence_color,
                "group_color_ok": group_color_ok,
                "run_group_ok": run_group_ok,
                "run_color_ok": run_color_ok,
                "run_group_prob": run_group_prob,
                "run_color_prob": run_color_prob,
                "run_override": run_override,
                "regime_ok": regime_ok,
                "signal": False,
                "trade": False,
                "action": "WAIT",
                "bet_group": None,
                "bet_color": None,
                "hit_group": None,
                "hit_color": None,
                "state": "PAUSE",
                "hybrid_score": 0.0,
                "total_profit_group": total_profit_group,
                "total_profit_color": total_profit_color,
                "pause_left": pause_rounds_left,
                "group_consecutive_losses": group_consecutive_losses,
                "group_pause": group_pause,
                "current_group_run_len": current_group_run_len,
                "current_color_run_len": current_color_run_len,
            }
        )
        processed_until = i
        continue

    # ===== HYBRID SCORE PRO =====
    hybrid_score = 0.0

    # nền chính vẫn là window
    if confidence_group >= VOTE_REQUIRED:
        hybrid_score += 0.38

    if confidence_color >= 2:
        hybrid_score += 0.08

    # group/color khớp
    if group_color_ok:
        hybrid_score += 0.16

    # run thật
    if run_group_signal is not None:
        if run_group_ok:
            hybrid_score += 0.12
        else:
            hybrid_score -= 0.10

        if run_group_signal["prob"] >= RUN_STRONG_PROB:
            hybrid_score += 0.06

    if run_color_signal is not None:
        if run_color_ok:
            hybrid_score += 0.08
        else:
            hybrid_score -= 0.06

    # regime
    if regime_ok:
        hybrid_score += 0.10
    else:
        hybrid_score -= 0.10

    # anti overfit: quá đẹp thì trừ nhẹ
    if confidence_group >= VOTE_REQUIRED and run_group_ok and regime_ok:
        hybrid_score -= 0.08

    # anti chase trend: run quá dài
    if current_group_run_len >= 3:
        hybrid_score -= 0.10
    if current_group_run_len >= 4:
        hybrid_score -= 0.08

    # nếu vừa override bởi run rất mạnh thì cộng lại
    if run_override:
        hybrid_score += 0.08

    # streak xấu
    if group_consecutive_losses >= 1:
        hybrid_score -= 0.08
    if group_consecutive_losses >= 2:
        hybrid_score -= 0.15

    # clamp
    hybrid_score = max(0.0, min(1.0, hybrid_score))

    action = "WAIT"
    if hybrid_score >= BET_SCORE:
        action = "BET"
    elif hybrid_score >= BET_SMALL_SCORE:
        action = "BET_SMALL"

    trade = (
        (not group_pause)
        and new_signal
        and distance >= GAP
        and group_color_ok
        and regime_ok
        and action in ("BET", "BET_SMALL")
    )

    bet_group = final_vote_group if trade else None
    bet_color = final_vote_color if trade else None
    hit_group = None
    hit_color = None
    state = "WAIT"

    if trade:
        last_trade = i

        if groups[i] == final_vote_group:
            hit_group = 1
            total_profit_group += WIN_GROUP
            hits_group.append(1)
            consecutive_losses = 0
            group_consecutive_losses = 0
            state = action
            if total_profit_group >= GROUP_PROFIT_STOP:
                group_pause = True
                state = "GROUP_PAUSE_PROFIT"
        else:
            hit_group = 0
            total_profit_group += LOSS_GROUP
            hits_group.append(0)
            consecutive_losses += 1
            group_consecutive_losses += 1
            state = action

            if consecutive_losses >= 2:
                pause_rounds_left = PAUSE_AFTER_2_LOSSES
                consecutive_losses = 0
                state = "PAUSE_TRIGGER"

            if group_consecutive_losses >= GROUP_MAX_LOSS_STREAK:
                group_pause = True
                state = "GROUP_PAUSE_LOSS"

        if colors[i] == final_vote_color:
            hit_color = 1
            total_profit_color += WIN_COLOR
            hits_color.append(1)
        else:
            hit_color = 0
            total_profit_color += LOSS_COLOR
            hits_color.append(0)
    else:
        if group_pause:
            state = "GROUP_PAUSED"
        elif not group_color_ok:
            state = "GROUP_COLOR_MISMATCH"
        elif not regime_ok:
            state = "REGIME_BLOCK"
        elif new_signal:
            state = "SIGNAL_ONLY"
        else:
            state = "WAIT"

    history_rows.append(
        {
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "color": colors[i],
            "vote_group": vote_group,
            "vote_color": vote_color,
            "final_vote_group": final_vote_group,
            "final_vote_color": final_vote_color,
            "confidence_group": confidence_group,
            "confidence_color": confidence_color,
            "group_color_ok": group_color_ok,
            "run_group_ok": run_group_ok,
            "run_color_ok": run_color_ok,
            "run_group_prob": run_group_prob,
            "run_color_prob": run_color_prob,
            "run_override": run_override,
            "regime_ok": regime_ok,
            "signal": new_signal,
            "trade": trade,
            "action": action,
            "bet_group": bet_group,
            "bet_color": bet_color,
            "hit_group": hit_group,
            "hit_color": hit_color,
            "state": state,
            "hybrid_score": round(hybrid_score, 4),
            "total_profit_group": total_profit_group,
            "total_profit_color": total_profit_color,
            "pause_left": pause_rounds_left,
            "group_consecutive_losses": group_consecutive_losses,
            "group_pause": group_pause,
            "current_group_run_len": current_group_run_len,
            "current_color_run_len": current_color_run_len,
        }
    )

    processed_until = i

# ================= SAVE STATE =================
st.session_state.total_profit_group = total_profit_group
st.session_state.total_profit_color = total_profit_color
st.session_state.last_trade = last_trade
st.session_state.hits_group = hits_group
st.session_state.hits_color = hits_color
st.session_state.history_rows = history_rows
st.session_state.locked_windows = locked_windows
st.session_state.scan_df_all = scan_df_all
st.session_state.scan_df_positive = scan_df_positive
st.session_state.scan_df_selected = scan_df_selected
st.session_state.bundle_df = bundle_df
st.session_state.candidate_df = candidate_df
st.session_state.round_eval_df = round_eval_df
st.session_state.lock_round_used = lock_round_used
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)
st.session_state.consecutive_losses = consecutive_losses
st.session_state.pause_rounds_left = pause_rounds_left
st.session_state.group_consecutive_losses = group_consecutive_losses
st.session_state.group_pause = group_pause

hist = pd.DataFrame(history_rows)

# ================= NEXT BET =================
next_round = len(groups)
preds_group = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]
preds_color = [colors[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds_group:
    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
else:
    vote_group, confidence_group = None, 0
    vote_color, confidence_color = None, 0

run_group_signal = get_run_signal(groups, RUN_MIN_LEN, RUN_MAX_LEN, RUN_MIN_SAMPLES, RUN_MIN_PROB)
run_color_signal = get_run_signal(colors, RUN_MIN_LEN, RUN_MAX_LEN, RUN_MIN_SAMPLES, RUN_MIN_PROB)

run_group_ok = True
run_color_ok = True
run_group_prob = None
run_color_prob = None

if run_group_signal is not None and vote_group is not None:
    run_group_prob = round(run_group_signal["prob"], 4)
    run_group_ok = (run_group_signal["next_value"] == vote_group)

if run_color_signal is not None and vote_color is not None:
    run_color_prob = round(run_color_signal["prob"], 4)
    run_color_ok = (run_color_signal["next_value"] == vote_color)

final_vote_group = vote_group
final_vote_color = vote_color
run_override = False

if run_group_signal is not None and run_group_signal["prob"] >= RUN_OVERRIDE_PROB:
    final_vote_group = run_group_signal["next_value"]
    run_override = True

if run_color_signal is not None and run_color_signal["prob"] >= RUN_OVERRIDE_PROB:
    final_vote_color = run_color_signal["next_value"]

group_color_ok = group_color_match(final_vote_group, final_vote_color)

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None
current_color = colors[-1] if colors else None
_, current_group_run_len = get_current_run(groups)
_, current_color_run_len = get_current_run(colors)

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

recent_health = backtest_bundle_vote_range(
    groups, colors, locked_windows,
    max(0, len(groups) - REGIME_LOOKBACK), len(groups)
)
regime_ok = (
    recent_health["trades"] >= REGIME_MIN_TRADES
    and recent_health["profit_group"] >= REGIME_MIN_PROFIT
    and recent_health["max_drawdown_group"] >= REGIME_MIN_DRAWDOWN
)

new_signal = confidence_group >= VOTE_REQUIRED if vote_group is not None else False

hybrid_score = 0.0
if confidence_group >= VOTE_REQUIRED:
    hybrid_score += 0.38
if confidence_color >= 2:
    hybrid_score += 0.08
if group_color_ok:
    hybrid_score += 0.16
if run_group_signal is not None:
    if final_vote_group == run_group_signal["next_value"]:
        hybrid_score += 0.12
    else:
        hybrid_score -= 0.10
    if run_group_signal["prob"] >= RUN_STRONG_PROB:
        hybrid_score += 0.06
if run_color_signal is not None:
    if final_vote_color == run_color_signal["next_value"]:
        hybrid_score += 0.08
    else:
        hybrid_score -= 0.06
if regime_ok:
    hybrid_score += 0.10
else:
    hybrid_score -= 0.10
if confidence_group >= VOTE_REQUIRED and regime_ok:
    hybrid_score -= 0.08
if current_group_run_len >= 3:
    hybrid_score -= 0.10
if current_group_run_len >= 4:
    hybrid_score -= 0.08
if run_override:
    hybrid_score += 0.08
if group_consecutive_losses >= 1:
    hybrid_score -= 0.08
if group_consecutive_losses >= 2:
    hybrid_score -= 0.15

hybrid_score = max(0.0, min(1.0, hybrid_score))

next_action = "WAIT"
if hybrid_score >= BET_SCORE:
    next_action = "BET"
elif hybrid_score >= BET_SMALL_SCORE:
    next_action = "BET_SMALL"

can_bet = (
    pause_rounds_left == 0
    and (not group_pause)
    and new_signal
    and distance >= GAP
    and group_color_ok
    and regime_ok
    and next_action in ("BET", "BET_SMALL")
)

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "color": current_color,
    "vote_group": vote_group,
    "vote_color": vote_color,
    "final_vote_group": final_vote_group,
    "final_vote_color": final_vote_color,
    "confidence_group": confidence_group,
    "confidence_color": confidence_color,
    "group_color_ok": group_color_ok,
    "run_group_ok": run_group_ok,
    "run_color_ok": run_color_ok,
    "run_group_prob": run_group_prob,
    "run_color_prob": run_color_prob,
    "run_override": run_override,
    "regime_ok": regime_ok,
    "signal": new_signal,
    "trade": False,
    "action": next_action,
    "bet_group": final_vote_group if can_bet else None,
    "bet_color": final_vote_color if can_bet else None,
    "hit_group": None,
    "hit_color": None,
    "state": next_action if can_bet else "WAIT",
    "hybrid_score": round(hybrid_score, 4),
    "total_profit_group": total_profit_group,
    "total_profit_color": total_profit_color,
    "pause_left": pause_rounds_left,
    "group_consecutive_losses": group_consecutive_losses,
    "group_pause": group_pause,
    "current_group_run_len": current_group_run_len,
    "current_color_run_len": current_color_run_len,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= UI =================
st.title("🎯 PRO RUN THẬT + LOCK WINDOW")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Current Color", current_color if current_color is not None else "-")
col4.metric("Lock Round Used", lock_round_used if lock_round_used is not None else "-")

st.divider()
st.write("Vote Strength Group:", confidence_group)
st.write("Vote Strength Color:", confidence_color)
st.write("Window Vote Group:", vote_group)
st.write("Window Vote Color:", vote_color)
st.write("Final Vote Group:", final_vote_group)
st.write("Final Vote Color:", final_vote_color)
st.write("Group/Color Match:", group_color_ok)
st.write("Run Group Prob:", run_group_prob)
st.write("Run Color Prob:", run_color_prob)
st.write("Run Override:", run_override)
st.write("Current Group Run Len:", current_group_run_len)
st.write("Current Color Run Len:", current_color_run_len)
st.write("Regime OK:", regime_ok)
st.write("Hybrid Score:", round(hybrid_score, 4))
st.write("Next Action:", next_action)
st.write("Locked Windows:", locked_windows)
st.write("Pause Rounds Left:", pause_rounds_left)
st.write("Group Pause:", group_pause)
st.write("Processed Until:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT → {next_action} | GROUP {final_vote_group if final_vote_group is not None else "-"} | COLOR {final_vote_color if final_vote_color is not None else "-"}
    </div>
    """,
    unsafe_allow_html=True,
)

if group_pause:
    st.warning("⛔ GROUP PAUSED")
elif pause_rounds_left > 0:
    st.warning(f"⏸ PAUSE - nghỉ {pause_rounds_left} vòng")
elif can_bet and next_action == "BET":
    st.error(f"🔥 BET FULL → GROUP {final_vote_group} | COLOR {final_vote_color}")
elif can_bet and next_action == "BET_SMALL":
    st.warning(f"⚠️ BET SMALL → GROUP {final_vote_group} | COLOR {final_vote_color}")
else:
    st.info("WAIT")

st.subheader("Session Statistics (LIVE ONLY)")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit Group", round(total_profit_group, 2))
s2.metric("Trades Group", len(hits_group))
s3.metric("Winrate Group %", round(np.mean(hits_group) * 100, 2) if hits_group else 0)
s4.metric("Pause Left", pause_rounds_left)

s5, s6, s7 = st.columns(3)
s5.metric("Total Profit Color", round(total_profit_color, 2))
s6.metric("Trades Color", len(hits_color))
s7.metric("Winrate Color %", round(np.mean(hits_color) * 100, 2) if hits_color else 0)

st.subheader("Profit Curve - Total Group (LIVE ONLY)")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_group"])

st.subheader("Profit Curve - Total Color (LIVE ONLY)")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_color"])

with st.expander("Round Evaluation"):
    st.dataframe(round_eval_df, use_container_width=True)

with st.expander("Window Scan All (Train)"):
    st.dataframe(scan_df_all, use_container_width=True)

with st.expander("All Positive Windows (Train)"):
    st.dataframe(scan_df_positive, use_container_width=True)

with st.expander("Candidate Windows (spaced)"):
    st.dataframe(candidate_df, use_container_width=True)

with st.expander("Bundle Backtest (Train + Validate1 + Validate2)"):
    st.dataframe(bundle_df, use_container_width=True)

with st.expander("Locked Windows"):
    st.dataframe(scan_df_selected, use_container_width=True)

st.subheader("History")

def highlight_trade(row):
    if row["state"] == "BET":
        return ["background-color: #ff4b4b; color:white"] * len(row)
    if row["state"] == "BET_SMALL":
        return ["background-color: #ffb347; color:black"] * len(row)
    if row["state"] == "PAUSE":
        return ["background-color: #87ceeb; color:black"] * len(row)
    if row["state"] == "PAUSE_TRIGGER":
        return ["background-color: #9370db; color:white"] * len(row)
    if row["state"] in ("GROUP_PAUSE_PROFIT", "GROUP_PAUSE_LOSS", "GROUP_PAUSED"):
        return ["background-color: #d9534f; color:white"] * len(row)
    return [""] * len(row)

if not hist_display.empty:
    st.dataframe(
        hist_display.iloc[::-1].head(SHOW_HISTORY_ROWS).style.apply(highlight_trade, axis=1),
        use_container_width=True,
    )
