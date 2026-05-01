import time
import json
import os
from collections import Counter

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= REFRESH =================
st_autorefresh(interval=5000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

MODES = [
    {"name": "4v3", "top_windows": 4, "vote_required": 3, "window_min": 6, "window_max": 22},
    {"name": "6v4", "top_windows": 6, "vote_required": 4, "window_min": 6, "window_max": 22},

   {"name": "8v5", "top_windows": 8, "vote_required": 5, "window_min": 6, "window_max": 22}, 
    
]

GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WIN_COLOR = 1.5
LOSS_COLOR = -1.0

PHASE_STOP_WIN = 3.5
PHASE_STOP_LOSS = -2.0

SESSION_STOP_WIN = 200.0
SESSION_STOP_LOSS = -200.0

# STOP RIÊNG THEO GROUP PROFIT
GROUP_SESSION_STOP_WIN = 15.0
GROUP_SESSION_STOP_LOSS = -80.0

KEEP_AFTER_LOSS_ROUNDS = 1

MIN_TRADES_PER_WINDOW = 16
RECENT_WINDOW_SIZE = 26
MIN_WINDOW_SPACING = 1
MAX_CANDIDATE_WINDOWS = 10

VALIDATE_LEN = 24
MIN_TRAIN_LEN = 120
MIN_VALIDATE_TRADES = 2
VALIDATE_MIN_DRAWDOWN = -6.0

RELOCK_SCAN_LEN = 6
RELOCK_BUFFER = 0

REPLAY_FROM = 180
SHOW_DEBUG_TABLES = False
SHOW_STYLED_HISTORY = False
SHOW_HISTORY_ROWS = 40

ENABLE_DOUBLE_BET_COLOR = True
REQUIRE_COLOR_CONFIRM = False

# ================= PATTERN FILTER - GROUP ONLY =================
ENABLE_PATTERN_FILTER = True
PATTERN_REQUIRED = True

# ================= TELEGRAM =================
DEFAULT_BOT_TOKEN = "8582950075:AAGgGD_HZ67D8Tq_tGutYf-c3BjT2do4hso"
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID

TELEGRAM_SEND_MODE = "READY_ONLY"
SENT_FILE = "/tmp/telegram_sent_rounds_pattern_group_only.json"


def telegram_enabled():
    return bool(BOT_TOKEN and CHAT_ID)


def send_telegram(msg):
    if not telegram_enabled():
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=5)
        return r.ok
    except Exception:
        return False


def send_signal_once(signal_name, current_round, msg):
    if TELEGRAM_SEND_MODE == "READY_ONLY" and signal_name != "READY":
        return False

    signal_key = f"{signal_name}|ROUND_{current_round}"

    if "sent_round_keys" not in st.session_state:
        st.session_state.sent_round_keys = set()

    if signal_key in st.session_state.sent_round_keys:
        return False

    try:
        if os.path.exists(SENT_FILE):
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                sent_keys = set(json.load(f))
        else:
            sent_keys = set()
    except Exception:
        sent_keys = set()

    if signal_key in sent_keys:
        st.session_state.sent_round_keys.add(signal_key)
        return False

    ok = send_telegram(msg)

    if ok:
        st.session_state.sent_round_keys.add(signal_key)
        sent_keys.add(signal_key)
        try:
            with open(SENT_FILE, "w", encoding="utf-8") as f:
                json.dump(list(sent_keys)[-500:], f)
        except Exception:
            pass

    return ok


# ================= LOAD DATA =================
@st.cache_data(ttl=30, show_spinner=False)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet must contain column 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def color_of_number(n):
    if n <= 4:
        return 1
    if n <= 8:
        return 2
    return 3


def color_text(c):
    if c == 1:
        return "RED"
    if c == 2:
        return "GREEN"
    if c == 3:
        return "BLUE"
    return "-"


def color_icon(c):
    if c == 1:
        return "🔴 RED"
    if c == 2:
        return "🟢 GREEN"
    if c == 3:
        return "🔵 BLUE"
    return "-"


# ================= PATTERN GROUP ONLY =================
def detect_pattern_next_group(seq_groups):
    n = len(seq_groups)
    if n < 2:
        return None, "NO_PATTERN"

    tail2 = seq_groups[-2:] if n >= 2 else []
    tail3 = seq_groups[-3:] if n >= 3 else []
    tail4 = seq_groups[-4:] if n >= 4 else []
    tail6 = seq_groups[-6:] if n >= 6 else []
    tail7 = seq_groups[-7:] if n >= 7 else []

    # A,A,A,A -> A
    if n >= 4 and tail4[0] == tail4[1] == tail4[2] == tail4[3]:
        return tail4[3], "REPEAT_4"

    # A,A,A -> A
    if n >= 3 and tail3[0] == tail3[1] == tail3[2]:
        return tail3[2], "REPEAT_3"

  

    # A,B,A,B -> A / B,A,B,A -> B
    if n >= 4:
        a, b, c, d = tail4
        if a == c and b == d and a != b:
            return a, "ALTERNATE_ABAB"

    # A,A,B,B -> A / B,B,A,A -> B
    if n >= 4:
        a, b, c, d = tail4
        if a == b and c == d and a != c:
            return a, "BLOCK_AABB"

    # A,A,A,B,B,B -> A / B,B,B,A,A,A -> B
    if n >= 6:
        a, b, c, d, e, f = tail6
        if a == b == c and d == e == f and a != d:
            return a, "BLOCK_AAABBB"

    # B,B,B,A,B,B,A -> B
    if n >= 7:
        a, b, c, d, e, f, g = tail7
        if a == b == c and e == f and d == g and a == e and a != d:
            return a, "PATTERN_BBBABBA"

    return None, "NO_PATTERN"


numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

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
        max_dd = min(max_dd, x - peak)

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
    selected = []
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if all(abs(w - int(x["window"])) >= min_spacing for x in selected):
            selected.append(row.to_dict())
            if len(selected) >= top_n:
                break
    return pd.DataFrame(selected)


def enforce_spacing_from_df(df_sorted, top_n, min_spacing):
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


# ================= BACKTEST GROUP ONLY =================
def backtest_bundle_vote_range(seq_groups, windows, vote_required, start_idx, end_idx):
    results_group = []
    trades = 0
    wins_group = 0
    last_trade = -999999

    if not windows:
        return {
            "trades": 0,
            "profit_group": 0.0,
            "winrate_group": 0.0,
            "max_drawdown_group": 0.0,
            "recent_profit_group": 0.0,
            "max_hit_streak": 0,
            "max_loss_streak": 0,
            "count_hit_streak_ge2": 0,
            "streak_score": -999999.0,
        }

    effective_start = max(start_idx, max(windows))

    for i in range(effective_start, end_idx):
        preds = [seq_groups[i - w] for w in windows]
        vote_group, confidence_group = Counter(preds).most_common(1)[0]

        if confidence_group >= vote_required and (i - last_trade >= GAP):
            last_trade = i
            trades += 1
            hit = 1 if seq_groups[i] == vote_group else 0
            wins_group += hit
            results_group.append(hit)

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


def evaluate_window_group(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0
    results = []

    for i in range(w, len(seq_groups)):
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


def build_window_tables(train_groups, window_min, window_max):
    rows = [evaluate_window_group(train_groups, w) for w in range(window_min, window_max + 1)]
    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["score", "streak_score", "recent_profit", "profit", "winrate", "trades"],
        ascending=[False, False, False, False, False, False],
    ).reset_index(drop=True)

    filtered_df = df[
        (df["trades"] >= MIN_TRADES_PER_WINDOW)
        & ((df["count_hit_streak_ge2"] >= 1) | (df["max_hit_streak"] >= 2))
        & (df["max_loss_streak"] <= 6)
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
        ascending=[False, False, False, False, False, False, True],
    ).reset_index(drop=True)

    if filtered_df.empty:
        filtered_df = df_all.head(MAX_CANDIDATE_WINDOWS).copy()

    selected_seed = filtered_df.head(MAX_CANDIDATE_WINDOWS).copy()

    candidate_df = selected_seed.sort_values(
        ["streak_score", "score", "recent_profit", "profit", "winrate", "trades"],
        ascending=[False, False, False, False, False, False],
    ).reset_index(drop=True)

    spaced_candidate_df = pick_spaced_windows(candidate_df, MAX_CANDIDATE_WINDOWS, MIN_WINDOW_SPACING)
    candidate_windows = spaced_candidate_df["window"].astype(int).tolist()

    need = max(m["top_windows"] for m in MODES)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(selected_seed, need, MIN_WINDOW_SPACING)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(df_all, need, 1)

    return candidate_windows, df_all, filtered_df


def find_best_auto_mode_in_range(all_groups, scan_start, scan_end):
    effective_scan_end = min(scan_end, len(all_groups) - 1)

    if effective_scan_end < scan_start:
        return None, [], None, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "no_scan_range"

    best_round = None
    best_windows = []
    best_mode = None
    best_scan_df = pd.DataFrame()
    best_filtered_df = pd.DataFrame()
    best_score = -999999.0
    best_lock_mode = "not_found"

    fallback_round = None
    fallback_windows = []
    fallback_mode = None
    fallback_scan_df = pd.DataFrame()
    fallback_filtered_df = pd.DataFrame()
    fallback_score = -999999.0

    round_eval_rows = []

    for r in range(scan_start, effective_scan_end + 1):
        if r < VALIDATE_LEN + MIN_TRAIN_LEN:
            continue

        train_end = r - VALIDATE_LEN
        validate_start = train_end
        validate_end = r

        train_groups = all_groups[:train_end]
        validate_groups = all_groups[:validate_end]

        local_best_score = -999999.0
        local_best_windows = []
        local_best_mode = None
        local_best_scan_df = pd.DataFrame()
        local_best_filtered_df = pd.DataFrame()
        local_lock_mode = "not_found"

        local_fallback_score = -999999.0
        local_fallback_windows = []
        local_fallback_mode = None
        local_fallback_scan_df = pd.DataFrame()
        local_fallback_filtered_df = pd.DataFrame()

        for mode in MODES:
            top_windows = mode["top_windows"]
            vote_required = mode["vote_required"]

            candidate_windows, df_all, filtered_df = build_window_tables(
                train_groups,
                mode["window_min"],
                mode["window_max"],
            )

            if len(candidate_windows) < top_windows:
                continue

            selected_windows = candidate_windows[:top_windows]

            train_bt = backtest_bundle_vote_range(
                train_groups,
                selected_windows,
                vote_required,
                0,
                len(train_groups),
            )

            validate_bt = backtest_bundle_vote_range(
                validate_groups,
                selected_windows,
                vote_required,
                validate_start,
                validate_end,
            )

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

            if final_score > local_fallback_score:
                local_fallback_score = final_score
                local_fallback_windows = selected_windows
                local_fallback_mode = mode
                local_fallback_scan_df = df_all
                local_fallback_filtered_df = filtered_df

            if validate_pass and final_score > local_best_score:
                local_best_score = final_score
                local_best_windows = selected_windows
                local_best_mode = mode
                local_best_scan_df = df_all
                local_best_filtered_df = filtered_df
                local_lock_mode = "validated"

        if local_best_mode is not None:
            round_eval_rows.append(
                {
                    "lock_round": r,
                    "mode": local_best_mode["name"],
                    "selected_windows": ", ".join(map(str, local_best_windows)),
                    "bundle_score": local_best_score,
                    "lock_mode": local_lock_mode,
                }
            )

            if local_best_score > best_score:
                best_score = local_best_score
                best_round = r
                best_windows = local_best_windows
                best_mode = local_best_mode
                best_scan_df = local_best_scan_df
                best_filtered_df = local_best_filtered_df
                best_lock_mode = local_lock_mode

        elif local_fallback_mode is not None:
            round_eval_rows.append(
                {
                    "lock_round": r,
                    "mode": local_fallback_mode["name"],
                    "selected_windows": ", ".join(map(str, local_fallback_windows)),
                    "bundle_score": local_fallback_score,
                    "lock_mode": "fallback",
                }
            )

            if local_fallback_score > fallback_score:
                fallback_score = local_fallback_score
                fallback_round = r
                fallback_windows = local_fallback_windows
                fallback_mode = local_fallback_mode
                fallback_scan_df = local_fallback_scan_df
                fallback_filtered_df = local_fallback_filtered_df

    round_eval_df = pd.DataFrame(round_eval_rows)

    if best_round is not None:
        return (
            best_round,
            best_windows,
            best_mode,
            best_scan_df,
            best_filtered_df,
            round_eval_df,
            best_lock_mode,
        )

    if fallback_round is not None:
        return (
            fallback_round,
            fallback_windows,
            fallback_mode,
            fallback_scan_df,
            fallback_filtered_df,
            round_eval_df,
            "fallback",
        )

    return None, [], None, pd.DataFrame(), pd.DataFrame(), round_eval_df, "not_found"


# ================= SESSION ENGINE =================
def simulate_engine(numbers, groups, colors):
    result = {
        "hist": pd.DataFrame(),
        "phase_profit_group": 0.0,
        "phase_profit_color": 0.0,
        "phase_profit_total": 0.0,
        "phase_hits_group": [],
        "phase_hits_color": [],
        "total_profit_group": 0.0,
        "total_profit_color": 0.0,
        "total_profit_all_phase": 0.0,
        "total_hits_group": [],
        "total_hits_color": [],
        "locked_windows": [],
        "selected_lock_round": None,
        "selected_mode": None,
        "lock_mode": "",
        "scan_df_all": pd.DataFrame(),
        "scan_df_filtered": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_scan_start": None,
        "lock_scan_end": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "consecutive_losses": 0,
        "phase_loss_streak": 0,
        "last_trade": -999,
        "phase_index": 1,
        "session_stop": False,
        "session_stop_reason": None,
        "relock_count": 0,
        "last_relock_trigger_round": None,
        "phase_summary_df": pd.DataFrame(),
    }

    (
        selected_lock_round,
        locked_windows,
        selected_mode,
        scan_df_all,
        scan_df_filtered,
        round_eval_df,
        lock_mode,
    ) = find_best_auto_mode_in_range(groups, LOCK_ROUND_START, LOCK_ROUND_END)

    if selected_lock_round is None or selected_mode is None:
        return result

    phase_profit_group = 0.0
    phase_profit_color = 0.0
    phase_profit_total = 0.0
    phase_hits_group = []
    phase_hits_color = []

    total_profit_group = 0.0
    total_profit_color = 0.0
    total_profit_all_phase = 0.0
    total_hits_group = []
    total_hits_color = []

    last_trade = -999
    keep_bet_group = None
    keep_rounds_left = 0
    last_trade_was_loss = False
    consecutive_losses = 0
    phase_loss_streak = 0

    phase_index = 1
    relock_count = 0
    last_relock_trigger_round = None

    lock_scan_start = LOCK_ROUND_START
    lock_scan_end = LOCK_ROUND_END

    history_rows = []
    phase_summary_rows = []

    start_replay = max(LOCK_ROUND_END + 1, REPLAY_FROM + 1)
    current_mode = selected_mode

    for i in range(start_replay, len(groups)):
        if total_profit_all_phase >= SESSION_STOP_WIN:
            break
        if total_profit_all_phase <= SESSION_STOP_LOSS:
            break
        if total_profit_group >= GROUP_SESSION_STOP_WIN:
            break
        if total_profit_group <= GROUP_SESSION_STOP_LOSS:
            break

        preds_group = [groups[i - w] for w in locked_windows if i - w >= 0]
        preds_color = [colors[i - w] for w in locked_windows if i - w >= 0]

        if not preds_group:
            continue

        vote_required = current_mode["vote_required"]

        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        vote_color, confidence_color = Counter(preds_color).most_common(1)[0] if preds_color else (None, 0)

        new_signal = confidence_group >= vote_required
        color_signal = confidence_color >= vote_required if vote_color is not None else False
        distance = i - last_trade

        final_vote_group = vote_group
        final_vote_color = vote_color

        pattern_group_runtime, pattern_type_runtime = detect_pattern_next_group(groups[:i])

        if ENABLE_PATTERN_FILTER:
            if pattern_group_runtime is not None:
                final_vote_group = pattern_group_runtime
                if not PATTERN_REQUIRED:
                    new_signal = True
            elif PATTERN_REQUIRED:
                new_signal = False

        used_keep = False
        trade = False
        hit_group = None
        hit_color = None
        pnl_group = 0.0
        pnl_color = 0.0
        pnl_total = 0.0
        state = "WAIT"
        relock_triggered_now = False
        relock_reason_now = None

        if new_signal:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False
        else:
            if last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
                final_vote_group = keep_bet_group
                used_keep = True

        final_signal = new_signal or used_keep
        can_trade_group = final_signal and distance >= GAP

        if ENABLE_DOUBLE_BET_COLOR and REQUIRE_COLOR_CONFIRM:
            trade = can_trade_group and color_signal
        else:
            trade = can_trade_group

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

        bet_group = final_vote_group if trade else None
        bet_color = final_vote_color if trade and ENABLE_DOUBLE_BET_COLOR else None

        if used_keep:
            keep_rounds_left = max(0, keep_rounds_left - 1)

        if trade:
            last_trade = i

            actual_group = groups[i]
            actual_color = colors[i]

            if actual_group == final_vote_group:
                hit_group = 1
                pnl_group = WIN_GROUP
            else:
                hit_group = 0
                pnl_group = LOSS_GROUP

            if ENABLE_DOUBLE_BET_COLOR:
                if final_vote_color is not None and actual_color == final_vote_color:
                    hit_color = 1
                    pnl_color = WIN_COLOR
                else:
                    hit_color = 0
                    pnl_color = LOSS_COLOR
            else:
                hit_color = None
                pnl_color = 0.0

            pnl_total = pnl_group + pnl_color

            phase_profit_group += pnl_group
            phase_profit_color += pnl_color
            phase_profit_total += pnl_total

            total_profit_group += pnl_group
            total_profit_color += pnl_color
            total_profit_all_phase += pnl_total

            phase_hits_group.append(hit_group)
            total_hits_group.append(hit_group)

            if ENABLE_DOUBLE_BET_COLOR:
                phase_hits_color.append(hit_color)
                total_hits_color.append(hit_color)

            if hit_group == 1:
                last_trade_was_loss = False
                keep_rounds_left = 0
                keep_bet_group = None
                consecutive_losses = 0
                phase_loss_streak = 0
            else:
                consecutive_losses += 1
                phase_loss_streak += 1

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

            if phase_profit_total <= PHASE_STOP_LOSS:
                relock_triggered_now = True
                relock_reason_now = "PHASE_STOP_LOSS"
                state = "AUTO_RELOCK_LOSS"
            elif phase_profit_total >= PHASE_STOP_WIN:
                relock_triggered_now = True
                relock_reason_now = "PHASE_TAKE_PROFIT"
                state = "AUTO_RELOCK_WIN"

            if relock_triggered_now:
                phase_summary_rows.append(
                    {
                        "phase": phase_index,
                        "end_round": i,
                        "reason": relock_reason_now,
                        "mode": current_mode["name"],
                        "vote_required": current_mode["vote_required"],
                        "top_windows": current_mode["top_windows"],
                        "lock_round": selected_lock_round,
                        "phase_trades": len(phase_hits_group),
                        "phase_profit_group": phase_profit_group,
                        "phase_profit_color": phase_profit_color,
                        "phase_profit_total": phase_profit_total,
                        "phase_winrate_group": round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0.0,
                        "phase_winrate_color": round(np.mean(phase_hits_color) * 100, 2) if phase_hits_color else 0.0,
                        "total_profit_group_after_phase": total_profit_group,
                        "total_profit_color_after_phase": total_profit_color,
                        "total_profit_after_phase": total_profit_all_phase,
                    }
                )

                current_round_i = i
                scan_end = current_round_i
                scan_start = max(
                    LOCK_ROUND_START,
                    scan_end - RELOCK_SCAN_LEN + 1 - RELOCK_BUFFER,
                )

                (
                    new_selected_lock_round,
                    new_locked_windows,
                    new_selected_mode,
                    new_scan_df_all,
                    new_scan_df_filtered,
                    new_round_eval_df,
                    new_lock_mode,
                ) = find_best_auto_mode_in_range(groups, scan_start, scan_end)

                if new_selected_lock_round is not None and new_selected_mode is not None:
                    relock_count += 1
                    last_relock_trigger_round = current_round_i

                    locked_windows = new_locked_windows
                    selected_lock_round = new_selected_lock_round
                    selected_mode = new_selected_mode
                    current_mode = new_selected_mode
                    scan_df_all = new_scan_df_all
                    scan_df_filtered = new_scan_df_filtered
                    round_eval_df = new_round_eval_df
                    lock_mode = new_lock_mode
                    lock_scan_start = scan_start
                    lock_scan_end = scan_end

                    phase_profit_group = 0.0
                    phase_profit_color = 0.0
                    phase_profit_total = 0.0
                    phase_hits_group = []
                    phase_hits_color = []

                    last_trade = current_round_i
                    keep_bet_group = None
                    keep_rounds_left = 0
                    last_trade_was_loss = False
                    consecutive_losses = 0
                    phase_loss_streak = 0
                    phase_index += 1

        else:
            if used_keep and keep_rounds_left <= 0:
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False

        history_rows.append(
            {
                "phase": phase_index,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "mode": current_mode["name"],
                "vote_required": current_mode["vote_required"],
                "top_windows": current_mode["top_windows"],
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "vote_color": color_text(vote_color),
                "confidence_color": confidence_color,
                "pattern_group": pattern_group_runtime,
                "pattern_type": pattern_type_runtime,
                "new_signal": new_signal,
                "color_signal": color_signal,
                "used_keep": used_keep,
                "keep_group": keep_bet_group,
                "keep_left": keep_rounds_left,
                "final_vote_group": final_vote_group,
                "final_vote_color": color_text(final_vote_color),
                "signal": final_signal,
                "trade": trade,
                "bet_group": bet_group,
                "bet_color": color_text(bet_color),
                "hit_group": hit_group,
                "hit_color": hit_color,
                "pnl_group": pnl_group,
                "pnl_color": pnl_color,
                "pnl_total": pnl_total,
                "state": state,
                "phase_profit_group": phase_profit_group,
                "phase_profit_color": phase_profit_color,
                "phase_profit_total": phase_profit_total,
                "total_profit_group": total_profit_group,
                "total_profit_color": total_profit_color,
                "total_profit_all_phase": total_profit_all_phase,
                "consecutive_losses": consecutive_losses,
                "phase_loss_streak": phase_loss_streak,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "relock_count": relock_count,
                "relock_triggered_now": relock_triggered_now,
            }
        )

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    session_stop = (
        total_profit_all_phase >= SESSION_STOP_WIN
        or total_profit_all_phase <= SESSION_STOP_LOSS
        or total_profit_group >= GROUP_SESSION_STOP_WIN
        or total_profit_group <= GROUP_SESSION_STOP_LOSS
    )

    session_stop_reason = (
        "SESSION_STOP_WIN"
        if total_profit_all_phase >= SESSION_STOP_WIN
        else "SESSION_STOP_LOSS"
        if total_profit_all_phase <= SESSION_STOP_LOSS
        else "GROUP_STOP_WIN"
        if total_profit_group >= GROUP_SESSION_STOP_WIN
        else "GROUP_STOP_LOSS"
        if total_profit_group <= GROUP_SESSION_STOP_LOSS
        else None
    )

    result.update(
        {
            "hist": hist,
            "phase_profit_group": phase_profit_group,
            "phase_profit_color": phase_profit_color,
            "phase_profit_total": phase_profit_total,
            "phase_hits_group": phase_hits_group,
            "phase_hits_color": phase_hits_color,
            "total_profit_group": total_profit_group,
            "total_profit_color": total_profit_color,
            "total_profit_all_phase": total_profit_all_phase,
            "total_hits_group": total_hits_group,
            "total_hits_color": total_hits_color,
            "locked_windows": locked_windows,
            "selected_lock_round": selected_lock_round,
            "selected_mode": selected_mode,
            "lock_mode": lock_mode,
            "scan_df_all": scan_df_all,
            "scan_df_filtered": scan_df_filtered,
            "round_eval_df": round_eval_df,
            "lock_scan_start": lock_scan_start,
            "lock_scan_end": lock_scan_end,
            "keep_bet_group": keep_bet_group,
            "keep_rounds_left": keep_rounds_left,
            "last_trade_was_loss": last_trade_was_loss,
            "consecutive_losses": consecutive_losses,
            "phase_loss_streak": phase_loss_streak,
            "last_trade": last_trade,
            "phase_index": phase_index,
            "session_stop": session_stop,
            "session_stop_reason": session_stop_reason,
            "relock_count": relock_count,
            "last_relock_trigger_round": last_relock_trigger_round,
            "phase_summary_df": phase_summary_df,
        }
    )

    return result


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_engine_pattern_group_only(numbers_tuple):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    cols = [color_of_number(n) for n in nums]
    return simulate_engine(nums, grps, cols)


# ================= RUN ENGINE =================
sim = cached_simulate_engine_pattern_group_only(tuple(numbers))

hist = sim["hist"]
phase_profit_group = sim["phase_profit_group"]
phase_profit_color = sim["phase_profit_color"]
phase_profit_total = sim["phase_profit_total"]
phase_hits_group = sim["phase_hits_group"]
phase_hits_color = sim["phase_hits_color"]

total_profit_group = sim["total_profit_group"]
total_profit_color = sim["total_profit_color"]
total_profit_all_phase = sim["total_profit_all_phase"]
total_hits_group = sim["total_hits_group"]
total_hits_color = sim["total_hits_color"]

locked_windows = sim["locked_windows"]
selected_lock_round = sim["selected_lock_round"]
selected_mode = sim["selected_mode"]
lock_mode = sim["lock_mode"]
scan_df_all = sim["scan_df_all"]
scan_df_filtered = sim["scan_df_filtered"]
round_eval_df = sim["round_eval_df"]
lock_scan_start = sim["lock_scan_start"]
lock_scan_end = sim["lock_scan_end"]
keep_bet_group = sim["keep_bet_group"]
keep_rounds_left = sim["keep_rounds_left"]
last_trade_was_loss = sim["last_trade_was_loss"]
consecutive_losses = sim["consecutive_losses"]
phase_loss_streak = sim["phase_loss_streak"]
last_trade = sim["last_trade"]
phase_index = sim["phase_index"]
session_stop = sim["session_stop"]
session_stop_reason = sim["session_stop_reason"]
relock_count = sim["relock_count"]
last_relock_trigger_round = sim["last_relock_trigger_round"]
phase_summary_df = sim["phase_summary_df"]

# ================= CURRENT LOCK CHECK =================
scan_range_bt = {
    "trades": 0,
    "profit_group": 0.0,
    "winrate_group": 0.0,
    "max_drawdown_group": 0.0,
}

post_lock_bt = {
    "trades": 0,
    "profit_group": 0.0,
    "winrate_group": 0.0,
    "max_drawdown_group": 0.0,
}

if locked_windows and selected_mode is not None:
    vote_required = selected_mode["vote_required"]

    scan_range_bt = backtest_bundle_vote_range(
        groups,
        locked_windows,
        vote_required,
        lock_scan_start if lock_scan_start is not None else LOCK_ROUND_START,
        min((lock_scan_end if lock_scan_end is not None else LOCK_ROUND_END) + 1, len(groups)),
    )

    post_lock_bt = backtest_bundle_vote_range(
        groups,
        locked_windows,
        vote_required,
        min((lock_scan_end if lock_scan_end is not None else LOCK_ROUND_END) + 1, len(groups)),
        len(groups),
    )

# ================= NEXT STATUS =================
next_round = len(groups)
current_round = len(numbers)

preds_group = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]
preds_color = [colors[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds_group and selected_mode is not None:
    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_required = selected_mode["vote_required"]
else:
    vote_group, confidence_group = None, 0
    vote_required = 0

if preds_color:
    vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
else:
    vote_color, confidence_color = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None
current_color = colors[-1] if colors else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

new_signal = confidence_group >= vote_required if vote_group is not None else False
color_signal = confidence_color >= vote_required if vote_color is not None else False

used_keep_next = False
final_vote_group = vote_group
final_vote_color = vote_color

pattern_group, pattern_type = detect_pattern_next_group(groups)

if ENABLE_PATTERN_FILTER:
    if pattern_group is not None:
        final_vote_group = pattern_group
        if not PATTERN_REQUIRED:
            new_signal = True
    elif PATTERN_REQUIRED:
        new_signal = False

if session_stop:
    signal = False
    can_bet = False
    next_state = session_stop_reason
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

    can_bet_group = signal and distance >= GAP and next_round > LOCK_ROUND_END

    if ENABLE_DOUBLE_BET_COLOR and REQUIRE_COLOR_CONFIRM:
        can_bet = can_bet_group and color_signal
    else:
        can_bet = can_bet_group

    next_state = "READY" if can_bet else "WAIT"

next_row = {
    "phase": phase_index,
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "color": color_text(current_color),
    "mode": selected_mode["name"] if selected_mode else "-",
    "vote_required": selected_mode["vote_required"] if selected_mode else 0,
    "top_windows": selected_mode["top_windows"] if selected_mode else 0,
    "vote_group": vote_group,
    "confidence_group": confidence_group,
    "vote_color": color_text(vote_color),
    "confidence_color": confidence_color,
    "pattern_group": pattern_group,
    "pattern_type": pattern_type,
    "new_signal": new_signal,
    "color_signal": color_signal,
    "used_keep": used_keep_next,
    "keep_group": next_keep_bet_group,
    "keep_left": next_keep_rounds_left,
    "final_vote_group": final_vote_group,
    "final_vote_color": color_text(final_vote_color),
    "signal": signal,
    "trade": False,
    "bet_group": final_vote_group if can_bet else None,
    "bet_color": color_text(final_vote_color) if can_bet and ENABLE_DOUBLE_BET_COLOR else "-",
    "hit_group": None,
    "hit_color": None,
    "pnl_group": 0.0,
    "pnl_color": 0.0,
    "pnl_total": 0.0,
    "state": next_state,
    "phase_profit_group": phase_profit_group,
    "phase_profit_color": phase_profit_color,
    "phase_profit_total": phase_profit_total,
    "total_profit_group": total_profit_group,
    "total_profit_color": total_profit_color,
    "total_profit_all_phase": total_profit_all_phase,
    "consecutive_losses": consecutive_losses,
    "phase_loss_streak": phase_loss_streak,
    "locked_windows": ", ".join(map(str, locked_windows)),
    "relock_count": relock_count,
    "relock_triggered_now": False,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= TELEGRAM NOTIFY =================
if telegram_enabled() and can_bet and final_vote_group is not None:
    ready_msg = (
        f"READY DOUBLE BET\n"
        f"Round: {current_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Current Color: {color_icon(current_color)}\n"
        f"Bet Group: {final_vote_group}\n"
        f"Bet Color: {color_icon(final_vote_color) if ENABLE_DOUBLE_BET_COLOR else 'OFF'}\n"
        f"Pattern Group: {pattern_type} -> {pattern_group}\n"
        f"Mode: {selected_mode['name'] if selected_mode else '-'}\n"
        f"Vote Group Strength: {confidence_group}\n"
        f"Vote Color Strength: {confidence_color}\n"
        f"Phase Profit Total: {phase_profit_total}\n"
        f"Total Profit Group: {total_profit_group}\n"
        f"Total Profit All: {total_profit_all_phase}\n"
        f"Stop Reason: {session_stop_reason}"
    )

    send_signal_once(
        signal_name="READY",
        current_round=current_round,
        msg=ready_msg,
    )

# ================= UI =================
st.title("🎯 Auto Relock Engine | Pattern Group Only + Color Bet")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number if current_number is not None else "-")
c2.metric("Current Group", current_group if current_group is not None else "-")
c3.metric("Current Color", color_icon(current_color))
c4.metric("Next Group", final_vote_group if final_vote_group is not None else "-")

st.write("Next Color:", color_icon(final_vote_color) if ENABLE_DOUBLE_BET_COLOR else "OFF")
st.write("Pattern Group Type:", pattern_type)
st.write("Pattern Group:", pattern_group)
st.write("Selected Mode:", selected_mode["name"] if selected_mode else "-")
st.write("Vote Required:", selected_mode["vote_required"] if selected_mode else 0)
st.write("Top Windows:", selected_mode["top_windows"] if selected_mode else 0)
st.write("Window Range:", f'{selected_mode["window_min"]}-{selected_mode["window_max"]}' if selected_mode else "-")
st.write("Group Vote Strength:", confidence_group)
st.write("Color Vote Strength:", confidence_color)
st.write("Double Bet Color:", ENABLE_DOUBLE_BET_COLOR)
st.write("Require Color Confirm:", REQUIRE_COLOR_CONFIRM)
st.write("Pattern Filter:", ENABLE_PATTERN_FILTER)
st.write("Pattern Required:", PATTERN_REQUIRED)
st.write("Group Stop Win:", GROUP_SESSION_STOP_WIN)
st.write("Group Stop Loss:", GROUP_SESSION_STOP_LOSS)
st.write("Best Lock Round:", selected_lock_round)
st.write("Scan Range:", f"{lock_scan_start} -> {lock_scan_end}")
st.write("Lock Mode:", lock_mode)
st.write("Relock Count:", relock_count)
st.write("Last Relock Trigger Round:", last_relock_trigger_round)
st.write("Session Stop:", session_stop)
st.write("Session Stop Reason:", session_stop_reason)
st.write("Telegram Enabled:", telegram_enabled())

if lock_mode == "fallback":
    st.warning("Đang dùng bộ lock fallback.")

if session_stop:
    if session_stop_reason in ("SESSION_STOP_WIN", "GROUP_STOP_WIN"):
        st.success(f"✅ {session_stop_reason}")
    elif session_stop_reason in ("SESSION_STOP_LOSS", "GROUP_STOP_LOSS"):
        st.error(f"⛔ {session_stop_reason}")
elif can_bet and final_vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:22px;border-radius:10px;text-align:center;font-size:28px;color:white;font-weight:bold;">
        READY DOUBLE BET<br>
        GROUP {final_vote_group} | COLOR {color_icon(final_vote_color) if ENABLE_DOUBLE_BET_COLOR else "OFF"}<br>
        PATTERN GROUP → {pattern_type}<br>
        MODE → {selected_mode["name"] if selected_mode else "-"}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT")

st.subheader("Current Phase Stats")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Profit Group", phase_profit_group)
s2.metric("Phase Profit Color", phase_profit_color)
s3.metric("Phase Profit Total", phase_profit_total)
s4.metric("Phase Trades", len(phase_hits_group))

s5, s6, s7 = st.columns(3)
s5.metric("Phase WR Group %", round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0)
s6.metric("Phase WR Color %", round(np.mean(phase_hits_color) * 100, 2) if phase_hits_color else 0)
s7.metric("Phase Loss Streak", phase_loss_streak)

st.subheader("Session Stats")
t1, t2, t3, t4 = st.columns(4)
t1.metric("Total Profit Group", total_profit_group)
t2.metric("Total Profit Color", total_profit_color)
t3.metric("Total Profit All", total_profit_all_phase)
t4.metric("Last Trade Round", last_trade if last_trade is not None else "-")

t5, t6, t7 = st.columns(3)
t5.metric("Total Trades", len(total_hits_group))
t6.metric("Total WR Group %", round(np.mean(total_hits_group) * 100, 2) if total_hits_group else 0)
t7.metric("Total WR Color %", round(np.mean(total_hits_color) * 100, 2) if total_hits_color else 0)

st.subheader("Current Lock Backtest Check - Group Only")
b1, b2, b3, b4 = st.columns(4)
b1.metric("Scan Trades", scan_range_bt["trades"])
b2.metric("Scan Profit Group", scan_range_bt["profit_group"])
b3.metric("Scan Winrate Group %", round(scan_range_bt["winrate_group"] * 100, 2))
b4.metric("Scan MaxDD Group", scan_range_bt["max_drawdown_group"])

d1, d2, d3, d4 = st.columns(4)
d1.metric("Post-lock Trades", post_lock_bt["trades"])
d2.metric("Post-lock Profit Group", post_lock_bt["profit_group"])
d3.metric("Post-lock Winrate Group %", round(post_lock_bt["winrate_group"] * 100, 2))
d4.metric("Post-lock MaxDD Group", post_lock_bt["max_drawdown_group"])

st.subheader("Phase Profit Total Curve")
if not hist_display.empty:
    current_phase_df = hist_display[hist_display["phase"] == phase_index].copy()
    if not current_phase_df.empty:
        st.line_chart(current_phase_df["phase_profit_total"].reset_index(drop=True))

st.subheader("Total Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_all_phase"].reset_index(drop=True))

with st.expander("Phase Summary"):
    st.dataframe(phase_summary_df, use_container_width=True)

if SHOW_DEBUG_TABLES:
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
        if row["state"] in ("READY",):
            return ["background-color: #ffd700"] * len(row)
        if row["state"] == "TRADE_KEEP":
            return ["background-color: #ffb347; color:black"] * len(row)
        if row["state"] in ("AUTO_RELOCK_LOSS", "AUTO_RELOCK_WIN"):
            return ["background-color: #32cd32; color:black"] * len(row)
        if row["state"] in ("SESSION_STOP_WIN", "GROUP_STOP_WIN"):
            return ["background-color: #2e8b57; color:white"] * len(row)
        if row["state"] in ("SESSION_STOP_LOSS", "GROUP_STOP_LOSS"):
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
