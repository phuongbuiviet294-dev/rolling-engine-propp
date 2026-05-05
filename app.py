import time
import json
import os
from collections import Counter

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180
REPLAY_FROM = 180

MODES = [
    {"name": "4v3", "top_windows": 4, "vote_required": 3, "window_min": 6, "window_max": 22},
    {"name": "5v3", "top_windows": 5, "vote_required": 3, "window_min": 6, "window_max": 22},
    {"name": "6v4", "top_windows": 6, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "8v5", "top_windows": 8, "vote_required": 5, "window_min": 6, "window_max": 22},
]

GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0
WIN_COLOR = 1.5
LOSS_COLOR = -1.0

PHASE_STOP_WIN = 999999.0
PHASE_STOP_LOSS = -6.0

SESSION_STOP_WIN = 200.0
SESSION_STOP_LOSS = -200.0

MIN_PHASE_SIGNAL_PROFIT_TO_BET = 2.5
MIN_EXTRA_VOTE_TO_BET = 1

ENABLE_TIMEOUT_RELOCK = True
TIMEOUT_RELOCK_ROUNDS = 80

MIN_TRADES_PER_WINDOW = 16
RECENT_WINDOW_SIZE = 26
MIN_WINDOW_SPACING = 5
MAX_CANDIDATE_WINDOWS = 10

VALIDATE_LEN = 24
MIN_TRAIN_LEN = 120
MIN_VALIDATE_TRADES = 2
VALIDATE_MIN_DRAWDOWN = -6.0

RELOCK_SCAN_LEN = 6
RELOCK_BUFFER = 0

SHOW_HISTORY_ROWS = 120
SHOW_DEBUG_TABLES = False

ENABLE_DOUBLE_BET_COLOR = False
REQUIRE_COLOR_CONFIRM = False

DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID

SENT_FILE = "/tmp/telegram_sent_rounds_optimized_live.json"


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


@st.cache_data(ttl=30, show_spinner=False)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet must contain column 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    return [x for x in nums if 1 <= x <= 12]


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


def get_valid_group_preds(seq_groups, i, windows):
    preds = []
    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = seq_groups[i - w]
            if seq_groups[i - 1] != pred:
                preds.append(pred)
    return preds


def get_color_preds(seq_colors, i, windows):
    return [seq_colors[i - w] for w in windows if i - w >= 0]


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
        ["streak_score", "score", "recent_profit", "profit", "winrate", "trades", "max_loss_streak"],
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

    if not spaced_candidate_df.empty and "window" in spaced_candidate_df.columns:
        candidate_windows = spaced_candidate_df["window"].astype(int).tolist()
    else:
        candidate_windows = []

    need = max(m["top_windows"] for m in MODES)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(selected_seed, need, MIN_WINDOW_SPACING)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(df_all, need, 1)

    return candidate_windows, df_all, filtered_df


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
        preds = get_valid_group_preds(seq_groups, i, windows)

        if not preds:
            continue

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
        return best_round, best_windows, best_mode, best_scan_df, best_filtered_df, round_eval_df, best_lock_mode

    if fallback_round is not None:
        return fallback_round, fallback_windows, fallback_mode, fallback_scan_df, fallback_filtered_df, round_eval_df, "fallback"

    return None, [], None, pd.DataFrame(), pd.DataFrame(), round_eval_df, "not_found"


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
        "total_profit_all": 0.0,
        "total_hits_group": [],
        "total_hits_color": [],
        "total_signal_profit": 0.0,
        "locked_windows": [],
        "selected_lock_round": None,
        "selected_mode": None,
        "lock_mode": "",
        "scan_df_all": pd.DataFrame(),
        "scan_df_filtered": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_scan_start": None,
        "lock_scan_end": None,
        "phase_index": 1,
        "session_stop": False,
        "session_stop_reason": None,
        "relock_count": 0,
        "last_relock_trigger_round": None,
        "phase_summary_df": pd.DataFrame(),
        "phase_signal_profit": 0.0,
        "phase_start_round": None,
        "last_signal_pnl_in_phase": 0.0,
        "last_signal_round_in_phase": None,
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

    phase_signal_profit = 0.0
    total_signal_profit = 0.0

    total_profit_group = 0.0
    total_profit_color = 0.0
    total_profit_all = 0.0
    total_hits_group = []
    total_hits_color = []

    last_trade = -999999
    last_signal_pnl_in_phase = 0.0
    last_signal_round_in_phase = None

    phase_index = 1
    relock_count = 0
    last_relock_trigger_round = None

    lock_scan_start = LOCK_ROUND_START
    lock_scan_end = LOCK_ROUND_END

    history_rows = []
    phase_summary_rows = []

    start_replay = max(LOCK_ROUND_END, REPLAY_FROM)
    phase_start_round = start_replay + 1
    current_mode = selected_mode

    for i in range(start_replay, len(groups)):
        round_no = i + 1

        if total_profit_all >= SESSION_STOP_WIN:
            break
        if total_profit_all <= SESSION_STOP_LOSS:
            break

        vote_required = current_mode["vote_required"]
        min_vote_strength_to_bet = vote_required + MIN_EXTRA_VOTE_TO_BET

        preds_group = get_valid_group_preds(groups, i, locked_windows)
        preds_color = get_color_preds(colors, i, locked_windows)

        if preds_group:
            vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
            final_signal = confidence_group >= vote_required
        else:
            vote_group = None
            confidence_group = 0
            final_signal = False

        if preds_color:
            vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
        else:
            vote_color = None
            confidence_color = 0

        color_signal = confidence_color >= vote_required if vote_color is not None else False

        final_vote_group = vote_group
        final_vote_color = vote_color

        prev_signal_pnl_in_phase = last_signal_pnl_in_phase
        prev_signal_round_in_phase = last_signal_round_in_phase

        distance = i - last_trade

        can_trade_group = (
            final_signal
            and confidence_group >= min_vote_strength_to_bet
            and prev_signal_pnl_in_phase > 0
            and phase_signal_profit >= MIN_PHASE_SIGNAL_PROFIT_TO_BET
            and distance >= GAP
            and round_no > LOCK_ROUND_END
        )

        if ENABLE_DOUBLE_BET_COLOR and REQUIRE_COLOR_CONFIRM:
            trade = can_trade_group and color_signal
        else:
            trade = can_trade_group

        if final_signal:
            if groups[i] == final_vote_group:
                signal_hit_group = 1
                signal_pnl_group = WIN_GROUP
            else:
                signal_hit_group = 0
                signal_pnl_group = LOSS_GROUP
        else:
            signal_hit_group = None
            signal_pnl_group = 0.0

        hit_group = None
        hit_color = None
        pnl_group = 0.0
        pnl_color = 0.0
        pnl_total = 0.0

        if trade:
            last_trade = i

            if groups[i] == final_vote_group:
                hit_group = 1
                pnl_group = WIN_GROUP
            else:
                hit_group = 0
                pnl_group = LOSS_GROUP

            if ENABLE_DOUBLE_BET_COLOR:
                if final_vote_color is not None and colors[i] == final_vote_color:
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
            total_profit_all += pnl_total

            phase_hits_group.append(hit_group)
            total_hits_group.append(hit_group)

            if ENABLE_DOUBLE_BET_COLOR:
                phase_hits_color.append(hit_color)
                total_hits_color.append(hit_color)

            state = "LIVE_BET"
        else:
            if final_signal and confidence_group < min_vote_strength_to_bet:
                state = "WAIT_VOTE_NOT_STRONG_ENOUGH"
            elif final_signal and prev_signal_pnl_in_phase <= 0:
                state = "WAIT_PREV_SIGNAL_IN_PHASE_NOT_POSITIVE"
            elif final_signal and phase_signal_profit < MIN_PHASE_SIGNAL_PROFIT_TO_BET:
                state = "WAIT_PHASE_SIGNAL_PROFIT_NOT_ENOUGH"
            elif final_signal:
                state = "SIGNAL_ONLY"
            else:
                state = "WAIT_NO_SIGNAL"

        phase_signal_profit += signal_pnl_group
        total_signal_profit += signal_pnl_group

        if final_signal:
            last_signal_pnl_in_phase = signal_pnl_group
            last_signal_round_in_phase = round_no

        relock_triggered_now = False
        relock_reason_now = None

        if phase_profit_group <= PHASE_STOP_LOSS:
            relock_triggered_now = True
            relock_reason_now = "PHASE_GROUP_STOP_LOSS"
            state = "AUTO_RELOCK_GROUP_LOSS"

        phase_age = round_no - phase_start_round + 1

        if (
            not relock_triggered_now
            and ENABLE_TIMEOUT_RELOCK
            and phase_age >= TIMEOUT_RELOCK_ROUNDS
            and phase_profit_group <= 0
        ):
            relock_triggered_now = True
            relock_reason_now = "TIMEOUT_RELOCK_PHASE_GROUP_NOT_POSITIVE"
            state = "AUTO_RELOCK_TIMEOUT"

        history_rows.append(
            {
                "phase": phase_index,
                "round": round_no,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "mode": current_mode["name"],
                "vote_required": current_mode["vote_required"],
                "top_windows": current_mode["top_windows"],
                "min_vote_strength_to_bet": min_vote_strength_to_bet,
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "vote_color": color_text(vote_color),
                "confidence_color": confidence_color,
                "color_signal": color_signal,
                "signal": final_signal,
                "signal_hit_group": signal_hit_group,
                "signal_pnl_group": signal_pnl_group,
                "prev_signal_pnl_in_phase": prev_signal_pnl_in_phase,
                "prev_signal_round_in_phase": prev_signal_round_in_phase,
                "phase_signal_profit": phase_signal_profit,
                "total_signal_profit": total_signal_profit,
                "trade": trade,
                "bet_group": final_vote_group if trade else None,
                "bet_color": color_text(final_vote_color) if trade else "-",
                "hit_group": hit_group,
                "hit_color": hit_color,
                "pnl_group": pnl_group,
                "pnl_color": pnl_color,
                "pnl_total": pnl_total,
                "state": state,
                "phase_profit_group": phase_profit_group,
                "phase_profit_color": phase_profit_color,
                "phase_profit_total": phase_profit_total,
                "phase_age": phase_age,
                "total_profit_group": total_profit_group,
                "total_profit_color": total_profit_color,
                "total_profit_all": total_profit_all,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "lock_mode": lock_mode,
                "lock_scan_start": lock_scan_start,
                "lock_scan_end": lock_scan_end,
                "relock_count": relock_count,
                "relock_triggered_now": relock_triggered_now,
                "relock_reason": relock_reason_now,
            }
        )

        if relock_triggered_now:
            phase_summary_rows.append(
                {
                    "phase": phase_index,
                    "start_round": phase_start_round,
                    "end_round": round_no,
                    "reason": relock_reason_now,
                    "mode": current_mode["name"],
                    "vote_required": current_mode["vote_required"],
                    "top_windows": current_mode["top_windows"],
                    "locked_windows": ", ".join(map(str, locked_windows)),
                    "lock_mode": lock_mode,
                    "lock_scan_start": lock_scan_start,
                    "lock_scan_end": lock_scan_end,
                    "lock_round": selected_lock_round,
                    "phase_age": phase_age,
                    "phase_live_trades": len(phase_hits_group),
                    "phase_profit_group": phase_profit_group,
                    "phase_profit_color": phase_profit_color,
                    "phase_profit_total": phase_profit_total,
                    "phase_signal_profit": phase_signal_profit,
                    "total_signal_profit_after_phase": total_signal_profit,
                    "phase_winrate_group": round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0.0,
                    "total_profit_group_after_phase": total_profit_group,
                    "total_profit_color_after_phase": total_profit_color,
                    "total_profit_all_after_phase": total_profit_all,
                }
            )

            scan_end = i
            scan_start = max(LOCK_ROUND_START, scan_end - RELOCK_SCAN_LEN + 1 - RELOCK_BUFFER)

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
                last_relock_trigger_round = round_no

                locked_windows = new_locked_windows
                selected_lock_round = round_no
                selected_mode = new_selected_mode
                current_mode = new_selected_mode
                scan_df_all = new_scan_df_all
                scan_df_filtered = new_scan_df_filtered
                round_eval_df = new_round_eval_df
                lock_mode = new_lock_mode
                lock_scan_start = scan_start
                lock_scan_end = scan_end

                phase_index += 1
                phase_start_round = round_no + 1

                phase_profit_group = 0.0
                phase_profit_color = 0.0
                phase_profit_total = 0.0
                phase_hits_group = []
                phase_hits_color = []

                phase_signal_profit = 0.0
                last_signal_pnl_in_phase = 0.0
                last_signal_round_in_phase = None

                last_trade = i

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    session_stop = total_profit_all >= SESSION_STOP_WIN or total_profit_all <= SESSION_STOP_LOSS

    session_stop_reason = (
        "SESSION_STOP_WIN"
        if total_profit_all >= SESSION_STOP_WIN
        else "SESSION_STOP_LOSS"
        if total_profit_all <= SESSION_STOP_LOSS
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
            "total_profit_all": total_profit_all,
            "total_hits_group": total_hits_group,
            "total_hits_color": total_hits_color,
            "total_signal_profit": total_signal_profit,
            "locked_windows": locked_windows,
            "selected_lock_round": selected_lock_round,
            "selected_mode": selected_mode,
            "lock_mode": lock_mode,
            "scan_df_all": scan_df_all,
            "scan_df_filtered": scan_df_filtered,
            "round_eval_df": round_eval_df,
            "lock_scan_start": lock_scan_start,
            "lock_scan_end": lock_scan_end,
            "phase_index": phase_index,
            "session_stop": session_stop,
            "session_stop_reason": session_stop_reason,
            "relock_count": relock_count,
            "last_relock_trigger_round": last_relock_trigger_round,
            "phase_summary_df": phase_summary_df,
            "phase_signal_profit": phase_signal_profit,
            "phase_start_round": phase_start_round,
            "last_signal_pnl_in_phase": last_signal_pnl_in_phase,
            "last_signal_round_in_phase": last_signal_round_in_phase,
        }
    )

    return result


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_engine(numbers_tuple):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    cols = [color_of_number(n) for n in nums]
    return simulate_engine(nums, grps, cols)


numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

sim = cached_simulate_engine(tuple(numbers))
hist = sim["hist"]

if hist.empty:
    st.error("Không tìm được bộ lock phù hợp.")
    st.stop()

phase_profit_group = sim["phase_profit_group"]
phase_profit_color = sim["phase_profit_color"]
phase_profit_total = sim["phase_profit_total"]
phase_hits_group = sim["phase_hits_group"]
phase_hits_color = sim["phase_hits_color"]

total_profit_group = sim["total_profit_group"]
total_profit_color = sim["total_profit_color"]
total_profit_all = sim["total_profit_all"]
total_hits_group = sim["total_hits_group"]
total_hits_color = sim["total_hits_color"]
total_signal_profit = sim["total_signal_profit"]

locked_windows = sim["locked_windows"]
selected_lock_round = sim["selected_lock_round"]
selected_mode = sim["selected_mode"]
lock_mode = sim["lock_mode"]
scan_df_all = sim["scan_df_all"]
scan_df_filtered = sim["scan_df_filtered"]
round_eval_df = sim["round_eval_df"]
lock_scan_start = sim["lock_scan_start"]
lock_scan_end = sim["lock_scan_end"]

phase_index = sim["phase_index"]
session_stop = sim["session_stop"]
session_stop_reason = sim["session_stop_reason"]
relock_count = sim["relock_count"]
last_relock_trigger_round = sim["last_relock_trigger_round"]
phase_summary_df = sim["phase_summary_df"]
phase_signal_profit = sim["phase_signal_profit"]
phase_start_round = sim["phase_start_round"]
last_signal_pnl_in_phase = sim["last_signal_pnl_in_phase"]
last_signal_round_in_phase = sim["last_signal_round_in_phase"]

live_rows = hist.copy()
live_rows["live_ready"] = live_rows["trade"].astype(bool)
live_rows["live_hit_group"] = live_rows["hit_group"]
live_rows["live_pnl_group"] = live_rows["pnl_group"]
live_rows["live_profit_group"] = live_rows["pnl_group"].cumsum()

live_ready_trades = int(live_rows["live_ready"].sum()) if not live_rows.empty else 0
live_profit_group = float(live_rows["live_profit_group"].iloc[-1]) if not live_rows.empty else 0.0
live_wr_group = (
    round(live_rows.loc[live_rows["live_ready"], "live_hit_group"].mean() * 100, 2)
    if live_ready_trades > 0
    else 0.0
)

next_idx = len(groups)
next_round = len(groups) + 1
current_round = len(numbers)

preds_group = get_valid_group_preds(groups, next_idx, locked_windows)
preds_color = get_color_preds(colors, next_idx, locked_windows)

if preds_group and selected_mode is not None:
    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_required = selected_mode["vote_required"]
else:
    vote_group, confidence_group = None, 0
    vote_required = 0

min_vote_strength_to_bet = vote_required + MIN_EXTRA_VOTE_TO_BET

if preds_color:
    vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
else:
    vote_color, confidence_color = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None
current_color = colors[-1] if colors else None

signal = confidence_group >= vote_required if vote_group is not None else False
color_signal = confidence_color >= vote_required if vote_color is not None else False

prev_signal_pnl_in_phase = last_signal_pnl_in_phase
prev_signal_round_in_phase = last_signal_round_in_phase

last_trade_rows = hist[hist["trade"] == True]
if len(last_trade_rows) > 0:
    last_trade_round = int(last_trade_rows["round"].max())
else:
    last_trade_round = -999999

distance = next_round - last_trade_round

final_vote_group = vote_group
final_vote_color = vote_color

can_bet_group = (
    signal
    and confidence_group >= min_vote_strength_to_bet
    and prev_signal_pnl_in_phase > 0
    and phase_signal_profit >= MIN_PHASE_SIGNAL_PROFIT_TO_BET
    and distance >= GAP
    and next_round > LOCK_ROUND_END
)

if ENABLE_DOUBLE_BET_COLOR and REQUIRE_COLOR_CONFIRM:
    can_bet = can_bet_group and color_signal
else:
    can_bet = can_bet_group

if session_stop:
    signal = False
    can_bet = False
    next_state = session_stop_reason
elif can_bet:
    next_state = "READY"
elif signal and confidence_group < min_vote_strength_to_bet:
    next_state = "WAIT_VOTE_NOT_STRONG_ENOUGH"
elif signal and prev_signal_pnl_in_phase <= 0:
    next_state = "WAIT_PREV_SIGNAL_IN_PHASE_NOT_POSITIVE"
elif signal and phase_signal_profit < MIN_PHASE_SIGNAL_PROFIT_TO_BET:
    next_state = "WAIT_PHASE_SIGNAL_PROFIT_NOT_ENOUGH"
elif not signal:
    next_state = "WAIT_NO_SIGNAL"
else:
    next_state = "WAIT"

hist_display = hist.copy()

if telegram_enabled() and can_bet and final_vote_group is not None:
    ready_msg = (
        f"READY LIVE BET\n"
        f"Round: {current_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Bet Group: {final_vote_group}\n"
        f"Mode: {selected_mode['name'] if selected_mode else '-'}\n"
        f"Vote Strength: {confidence_group}/{vote_required}\n"
        f"Min Vote To Bet: {min_vote_strength_to_bet}\n"
        f"Prev Signal Round: {prev_signal_round_in_phase}\n"
        f"Prev Signal PNL: {prev_signal_pnl_in_phase}\n"
        f"Phase Signal Profit: {phase_signal_profit}\n"
        f"Live Profit Group: {live_profit_group}\n"
        f"Total Profit Group: {total_profit_group}"
    )
    send_signal_once("READY", current_round, ready_msg)

st.title("Auto Relock Engine | OPTIMIZED LIVE GROUP")

st.subheader("LIVE BET NOW")

b1, b2, b3, b4 = st.columns(4)
b1.metric("LIVE STATUS", "READY" if can_bet else "WAIT")
b2.metric("BET GROUP", final_vote_group if can_bet else "-")
b3.metric("Vote", f"{confidence_group}/{vote_required}")
b4.metric("Min Vote Bet", min_vote_strength_to_bet)

if can_bet and final_vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff3333;padding:26px;border-radius:14px;text-align:center;
        font-size:32px;color:white;font-weight:bold;">
        READY BET<br>
        GROUP {final_vote_group}<br>
        VOTE {confidence_group}/{vote_required}<br>
        PHASE SIGNAL PROFIT = {phase_signal_profit}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div style="background:#333;padding:22px;border-radius:14px;text-align:center;
        font-size:26px;color:white;font-weight:bold;">
        WAIT<br>
        STATE: {next_state}<br>
        SIGNAL = {signal}<br>
        PREV SIGNAL PNL = {prev_signal_pnl_in_phase}<br>
        PHASE SIGNAL PROFIT = {phase_signal_profit}
        </div>
        """,
        unsafe_allow_html=True,
    )

st.subheader("Current Signal")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number if current_number is not None else "-")
c2.metric("Current Group", current_group if current_group is not None else "-")
c3.metric("Current Color", color_text(current_color))
c4.metric("Next Group", final_vote_group if final_vote_group is not None else "-")

st.write("Selected Mode:", selected_mode["name"] if selected_mode else "-")
st.write("Vote Required:", vote_required)
st.write("Min Vote Strength To Bet:", min_vote_strength_to_bet)
st.write("Group Vote Strength:", confidence_group)
st.write("Signal:", signal)
st.write("Prev Signal Round In Phase:", prev_signal_round_in_phase)
st.write("Prev Signal PNL In Phase:", prev_signal_pnl_in_phase)
st.write("Phase Signal Profit:", phase_signal_profit)
st.write("Min Phase Signal Profit To Bet:", MIN_PHASE_SIGNAL_PROFIT_TO_BET)
st.write("Can Bet:", can_bet)
st.write("State:", next_state)
st.write("Locked Windows:", locked_windows)
st.write("Best Lock Round:", selected_lock_round)
st.write("Scan Range:", f"{lock_scan_start} -> {lock_scan_end}")
st.write("Lock Mode:", lock_mode)
st.write("Relock Count:", relock_count)
st.write("Phase Start Round:", phase_start_round)
st.write("Telegram Enabled:", telegram_enabled())

st.subheader("Live Profit Stats")

l1, l2, l3, l4 = st.columns(4)
l1.metric("Live Group Profit", live_profit_group)
l2.metric("Live Trades", live_ready_trades)
l3.metric("Live WR Group %", live_wr_group)
l4.metric("Total Profit All", total_profit_all)

st.subheader("Current Phase Stats")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Group Profit", phase_profit_group)
s2.metric("Phase Signal Profit", phase_signal_profit)
s3.metric("Phase Age", hist_display["phase_age"].iloc[-1] if "phase_age" in hist_display.columns else 0)
s4.metric("Total Signal Profit", total_signal_profit)

st.subheader("Session Stats")

t1, t2, t3 = st.columns(3)
t1.metric("Total Profit Group", total_profit_group)
t2.metric("Total Profit Color", total_profit_color)
t3.metric("Total Profit All", total_profit_all)

st.subheader("Profit Curve")

chart_cols = [
    "total_signal_profit",
    "phase_signal_profit",
    "phase_profit_group",
    "total_profit_group",
    "total_profit_all",
]

exist_chart_cols = [c for c in chart_cols if c in hist_display.columns]

if exist_chart_cols:
    st.line_chart(hist_display[exist_chart_cols].reset_index(drop=True))

with st.expander("Phase Summary"):
    st.dataframe(phase_summary_df, use_container_width=True)

with st.expander("Current Locked Window Detail"):
    if not scan_df_all.empty and locked_windows:
        st.dataframe(
            scan_df_all[scan_df_all["window"].isin(locked_windows)].sort_values("window"),
            use_container_width=True,
        )

if SHOW_DEBUG_TABLES:
    with st.expander("Round Evaluation"):
        st.dataframe(round_eval_df, use_container_width=True)

    with st.expander("Filtered Windows"):
        st.dataframe(scan_df_filtered.head(25), use_container_width=True)

st.subheader("History")

history_cols = [
    "round",
    "phase",
    "number",
    "group",
    "vote_group",
    "confidence_group",
    "min_vote_strength_to_bet",
    "signal",
    "signal_hit_group",
    "signal_pnl_group",
    "prev_signal_round_in_phase",
    "prev_signal_pnl_in_phase",
    "phase_signal_profit",
    "total_signal_profit",
    "trade",
    "bet_group",
    "hit_group",
    "pnl_group",
    "phase_profit_group",
    "total_profit_group",
    "total_profit_all",
    "state",
    "locked_windows",
    "relock_triggered_now",
    "relock_reason",
]

show_cols = [c for c in history_cols if c in hist_display.columns]
st.dataframe(hist_display[show_cols].iloc[::-1].head(SHOW_HISTORY_ROWS), use_container_width=True)
