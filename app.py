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

PHASE_BET_UNIT = 1.0
LIVE_BET_UNIT = 1.0

PHASE_STOP_WIN = 999999.0
PHASE_STOP_LOSS = -3.0

SESSION_STOP_WIN = 200.0
SESSION_STOP_LOSS = -200.0

ENABLE_TIMEOUT_RELOCK = True
TIMEOUT_RELOCK_ROUNDS = 80

MIN_PHASE_PROFIT_TO_LIVE = 1.5
RECENT_PHASE_CHECK = 5
MIN_RECENT_PHASE_PNL = 0.0

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

DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID
SENT_FILE = "/tmp/telegram_sent_phase_live_final_optimize.json"


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


def get_valid_group_preds(seq_groups, i, windows):
    preds = []
    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = seq_groups[i - w]
            if seq_groups[i - 1] != pred:
                preds.append(pred)
    return preds


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

            phase_quality_pass = (
                train_bt["profit_group"] >= MIN_PHASE_BACKTEST_PROFIT
                and train_bt["winrate_group"] >= MIN_PHASE_BACKTEST_WR
                and train_bt["max_drawdown_group"] >= MAX_PHASE_BACKTEST_DD
            )

            final_score = (
                train_bt["profit_group"]
                + train_bt["winrate_group"] * 10.0
                + train_bt["recent_profit_group"]
                - abs(train_bt["max_drawdown_group"])
                + train_bt["streak_score"] * 1.5
                + validate_bt["profit_group"] * 2.0
                + validate_bt["winrate_group"] * 8.0
                - abs(validate_bt["max_drawdown_group"])
                + validate_bt["streak_score"] * 1.5
            )

            if final_score > local_fallback_score:
                local_fallback_score = final_score
                local_fallback_windows = selected_windows
                local_fallback_mode = mode
                local_fallback_scan_df = df_all
                local_fallback_filtered_df = filtered_df

            if validate_pass and phase_quality_pass and final_score > local_best_score:
                local_best_score = final_score
                local_best_windows = selected_windows
                local_best_mode = mode
                local_best_scan_df = df_all
                local_best_filtered_df = filtered_df
                local_lock_mode = "validated_phase_quality"

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


def simulate_engine(numbers, groups):
    result = {
        "hist": pd.DataFrame(),
        "phase_profit_group": 0.0,
        "phase_live_profit_group": 0.0,
        "total_profit_group": 0.0,
        "total_phase_profit_group": 0.0,
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
        "phase_summary_df": pd.DataFrame(),
        "relock_count": 0,
        "session_stop": False,
        "session_stop_reason": None,
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
    phase_live_profit_group = 0.0
    total_profit_group = 0.0
    total_phase_profit_group = 0.0

    phase_hits_group = []
    live_hits_group = []

    last_signal_pnl_in_phase = 0.0
    last_signal_round_in_phase = None
    last_live_trade_idx = -999999

    phase_index = 1
    relock_count = 0

    lock_scan_start = LOCK_ROUND_START
    lock_scan_end = LOCK_ROUND_END

    history_rows = []
    phase_summary_rows = []

    start_replay = max(LOCK_ROUND_END, REPLAY_FROM)
    phase_start_round = start_replay + 1
    current_mode = selected_mode

    for i in range(start_replay, len(groups)):
        round_no = i + 1

        if total_profit_group >= SESSION_STOP_WIN:
            break
        if total_profit_group <= SESSION_STOP_LOSS:
            break

        vote_required = current_mode["vote_required"]
        preds_group = get_valid_group_preds(groups, i, locked_windows)

        if preds_group:
            vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
            signal = confidence_group >= vote_required
        else:
            vote_group = None
            confidence_group = 0
            signal = False

        prev_signal_pnl_in_phase = last_signal_pnl_in_phase
        prev_signal_round_in_phase = last_signal_round_in_phase

        if signal:
            if groups[i] == vote_group:
                phase_hit_group = 1
                raw_signal_pnl_group = WIN_GROUP
                phase_pnl_group = WIN_GROUP * PHASE_BET_UNIT
            else:
                phase_hit_group = 0
                raw_signal_pnl_group = LOSS_GROUP
                phase_pnl_group = LOSS_GROUP * PHASE_BET_UNIT
        else:
            phase_hit_group = None
            raw_signal_pnl_group = 0.0
            phase_pnl_group = 0.0

        distance = i - last_live_trade_idx

        if len(history_rows) >= RECENT_PHASE_CHECK:
            recent_phase_pnl = sum(
                float(x["phase_pnl_group"])
                for x in history_rows[-RECENT_PHASE_CHECK:]
                if int(x["phase"]) == phase_index
            )
        else:
            recent_phase_pnl = phase_profit_group

        live_trade = (
            signal
            and prev_signal_pnl_in_phase > 0
            and phase_profit_group >= MIN_PHASE_PROFIT_TO_LIVE
            and recent_phase_pnl >= MIN_RECENT_PHASE_PNL
            and distance >= GAP
            and round_no > LOCK_ROUND_END
        )

        if live_trade:
            last_live_trade_idx = i

            if groups[i] == vote_group:
                live_hit_group = 1
                live_pnl_group = WIN_GROUP * LIVE_BET_UNIT
            else:
                live_hit_group = 0
                live_pnl_group = LOSS_GROUP * LIVE_BET_UNIT

            phase_live_profit_group += live_pnl_group
            total_profit_group += live_pnl_group
            live_hits_group.append(live_hit_group)
            state = "LIVE_BET"
        else:
            live_hit_group = None
            live_pnl_group = 0.0

            if signal and prev_signal_pnl_in_phase <= 0:
                state = "PHASE_BET_ONLY_WAIT_PREV_SIGNAL_NOT_POSITIVE"
            elif signal and phase_profit_group < MIN_PHASE_PROFIT_TO_LIVE:
                state = "PHASE_BET_ONLY_WAIT_PHASE_PROFIT_LOW"
            elif signal and recent_phase_pnl < MIN_RECENT_PHASE_PNL:
                state = "PHASE_BET_ONLY_WAIT_RECENT_PHASE_WEAK"
            elif signal:
                state = "PHASE_BET_ONLY"
            else:
                state = "WAIT_NO_SIGNAL"

        phase_profit_group += phase_pnl_group
        total_phase_profit_group += phase_pnl_group

        if signal:
            phase_hits_group.append(phase_hit_group)
            last_signal_pnl_in_phase = raw_signal_pnl_group
            last_signal_round_in_phase = round_no

        relock_triggered_now = False
        relock_reason_now = None

        if phase_profit_group <= PHASE_STOP_LOSS:
            relock_triggered_now = True
            relock_reason_now = "PHASE_BET_GROUP_STOP_LOSS"
            state = "AUTO_RELOCK_PHASE_BET_GROUP_LOSS"

        phase_age = round_no - phase_start_round + 1

        if (
            not relock_triggered_now
            and ENABLE_TIMEOUT_RELOCK
            and phase_age >= TIMEOUT_RELOCK_ROUNDS
            and phase_profit_group <= 0
        ):
            relock_triggered_now = True
            relock_reason_now = "TIMEOUT_RELOCK_PHASE_BET_NOT_POSITIVE"
            state = "AUTO_RELOCK_TIMEOUT"

        history_rows.append(
            {
                "phase": phase_index,
                "round": round_no,
                "number": numbers[i],
                "group": groups[i],
                "mode": current_mode["name"],
                "vote_required": vote_required,
                "top_windows": current_mode["top_windows"],
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "signal": signal,
                "PHASE_BET": signal,
                "phase_bet_group": vote_group if signal else None,
                "phase_hit_group": phase_hit_group,
                "phase_pnl_group": phase_pnl_group,
                "phase_profit_group": phase_profit_group,
                "recent_phase_pnl": recent_phase_pnl,
                "total_phase_profit_group": total_phase_profit_group,
                "prev_signal_round_in_phase": prev_signal_round_in_phase,
                "prev_signal_pnl_in_phase": prev_signal_pnl_in_phase,
                "LIVE_BET": live_trade,
                "live_bet_group": vote_group if live_trade else None,
                "live_hit_group": live_hit_group,
                "live_pnl_group": live_pnl_group,
                "phase_live_profit_group": phase_live_profit_group,
                "total_profit_group": total_profit_group,
                "phase_age": phase_age,
                "state": state,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "lock_mode": lock_mode,
                "lock_scan_start": lock_scan_start,
                "lock_scan_end": lock_scan_end,
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
                    "vote_required": vote_required,
                    "top_windows": current_mode["top_windows"],
                    "locked_windows": ", ".join(map(str, locked_windows)),
                    "lock_mode": lock_mode,
                    "lock_scan_start": lock_scan_start,
                    "lock_scan_end": lock_scan_end,
                    "lock_round": selected_lock_round,
                    "phase_age": phase_age,
                    "phase_bet_trades": len(phase_hits_group),
                    "phase_bet_profit": phase_profit_group,
                    "phase_bet_wr": round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0.0,
                    "live_trades": len(live_hits_group),
                    "live_profit": phase_live_profit_group,
                    "live_wr": round(np.mean(live_hits_group) * 100, 2) if live_hits_group else 0.0,
                    "total_live_profit_after_phase": total_profit_group,
                    "total_phase_profit_after_phase": total_phase_profit_group,
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
                phase_live_profit_group = 0.0
                phase_hits_group = []
                live_hits_group = []

                last_signal_pnl_in_phase = 0.0
                last_signal_round_in_phase = None
                last_live_trade_idx = i

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    session_stop = total_profit_group >= SESSION_STOP_WIN or total_profit_group <= SESSION_STOP_LOSS

    session_stop_reason = (
        "SESSION_STOP_WIN"
        if total_profit_group >= SESSION_STOP_WIN
        else "SESSION_STOP_LOSS"
        if total_profit_group <= SESSION_STOP_LOSS
        else None
    )

    result.update(
        {
            "hist": hist,
            "phase_profit_group": phase_profit_group,
            "phase_live_profit_group": phase_live_profit_group,
            "total_profit_group": total_profit_group,
            "total_phase_profit_group": total_phase_profit_group,
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
            "phase_summary_df": phase_summary_df,
            "relock_count": relock_count,
            "session_stop": session_stop,
            "session_stop_reason": session_stop_reason,
            "last_signal_pnl_in_phase": last_signal_pnl_in_phase,
            "last_signal_round_in_phase": last_signal_round_in_phase,
        }
    )

    return result


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_engine(numbers_tuple):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    return simulate_engine(nums, grps)


numbers = load_numbers()
groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

if st.sidebar.button("Clear cache & rerun"):
    st.cache_data.clear()
    st.rerun()

sim = cached_simulate_engine(tuple(numbers))
hist = sim["hist"]

if hist.empty:
    st.error("Không tìm được bộ lock phù hợp.")
    st.stop()

phase_profit_group = sim["phase_profit_group"]
phase_live_profit_group = sim["phase_live_profit_group"]
total_profit_group = sim["total_profit_group"]
total_phase_profit_group = sim["total_phase_profit_group"]

locked_windows = sim["locked_windows"]
selected_mode = sim["selected_mode"]
selected_lock_round = sim["selected_lock_round"]
lock_mode = sim["lock_mode"]
lock_scan_start = sim["lock_scan_start"]
lock_scan_end = sim["lock_scan_end"]
scan_df_all = sim["scan_df_all"]
round_eval_df = sim["round_eval_df"]
scan_df_filtered = sim["scan_df_filtered"]

phase_summary_df = sim["phase_summary_df"]
relock_count = sim["relock_count"]
session_stop = sim["session_stop"]
session_stop_reason = sim["session_stop_reason"]

last_signal_pnl_in_phase = sim["last_signal_pnl_in_phase"]
last_signal_round_in_phase = sim["last_signal_round_in_phase"]

next_idx = len(groups)
next_round = len(groups) + 1
current_round = len(numbers)

preds_group = get_valid_group_preds(groups, next_idx, locked_windows)

if preds_group and selected_mode is not None:
    vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_required = selected_mode["vote_required"]
else:
    vote_group, confidence_group = None, 0
    vote_required = 0

signal = confidence_group >= vote_required if vote_group is not None else False

last_live_rows = hist[hist["LIVE_BET"] == True]
if len(last_live_rows) > 0:
    last_live_round = int(last_live_rows["round"].max())
else:
    last_live_round = -999999

distance = next_round - last_live_round

if len(hist) >= RECENT_PHASE_CHECK:
    current_phase = int(hist.iloc[-1]["phase"])
    recent_df = hist.iloc[-RECENT_PHASE_CHECK:]
    recent_phase_pnl_next = float(
        recent_df[recent_df["phase"] == current_phase]["phase_pnl_group"].sum()
    )
else:
    recent_phase_pnl_next = phase_profit_group

can_live_bet = (
    signal
    and last_signal_pnl_in_phase > 0
    and phase_profit_group >= MIN_PHASE_PROFIT_TO_LIVE
    and recent_phase_pnl_next >= MIN_RECENT_PHASE_PNL
    and distance >= GAP
    and next_round > LOCK_ROUND_END
)

if session_stop:
    signal = False
    can_live_bet = False
    next_state = session_stop_reason
elif can_live_bet:
    next_state = "READY_LIVE_BET"
elif signal and last_signal_pnl_in_phase <= 0:
    next_state = "PHASE_BET_ONLY_WAIT_PREV_SIGNAL_NOT_POSITIVE"
elif signal and phase_profit_group < MIN_PHASE_PROFIT_TO_LIVE:
    next_state = "PHASE_BET_ONLY_WAIT_PHASE_PROFIT_LOW"
elif signal and recent_phase_pnl_next < MIN_RECENT_PHASE_PNL:
    next_state = "PHASE_BET_ONLY_WAIT_RECENT_PHASE_WEAK"
elif signal:
    next_state = "PHASE_BET_ONLY"
else:
    next_state = "WAIT_NO_SIGNAL"

if telegram_enabled() and can_live_bet and vote_group is not None:
    ready_msg = (
        f"READY LIVE BET\n"
        f"Round: {current_round}\n"
        f"Current Number: {numbers[-1]}\n"
        f"Current Group: {groups[-1]}\n"
        f"Live Bet Group: {vote_group}\n"
        f"Phase Bet Group: {vote_group if signal else '-'}\n"
        f"Vote Strength: {confidence_group}/{vote_required}\n"
        f"Prev Signal Round: {last_signal_round_in_phase}\n"
        f"Prev Signal PNL: {last_signal_pnl_in_phase}\n"
        f"Phase Profit: {phase_profit_group}\n"
        f"Recent Phase PNL: {recent_phase_pnl_next}\n"
        f"Total Live Profit: {total_profit_group}\n"
        f"Total Phase Profit: {total_phase_profit_group}"
    )
    send_signal_once("READY", current_round, ready_msg)

st.title("Auto Relock Engine | PHASE BET vs LIVE BET OPTIMIZED")

st.subheader("LAST ROUND RESULT")

last = hist.iloc[-1]

r1, r2, r3, r4 = st.columns(4)
r1.metric("Last Round", int(last["round"]))
r2.metric("Last Signal", "YES" if bool(last["signal"]) else "NO")
r3.metric("Last Phase Bet", "YES" if bool(last["PHASE_BET"]) else "NO")
r4.metric("Last Live Bet", "YES" if bool(last["LIVE_BET"]) else "NO")

r5, r6, r7, r8 = st.columns(4)
r5.metric("Last Phase PNL", float(last["phase_pnl_group"]))
r6.metric("Last Live PNL", float(last["live_pnl_group"]))
r7.metric("Phase Profit Now", phase_profit_group)
r8.metric("Live Profit Now", phase_live_profit_group)

st.write("Last State:", str(last["state"]))

st.subheader("NEXT ROUND BET")

b1, b2, b3, b4 = st.columns(4)
b1.metric("NEXT PHASE BET", "YES" if signal else "NO")
b2.metric("NEXT PHASE GROUP", vote_group if signal else "-")
b3.metric("NEXT LIVE BET", "YES" if can_live_bet else "NO")
b4.metric("NEXT LIVE GROUP", vote_group if can_live_bet else "-")

if can_live_bet and vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff3333;padding:26px;border-radius:14px;text-align:center;
        font-size:32px;color:white;font-weight:bold;">
        NEXT LIVE READY BET<br>
        GROUP {vote_group}<br>
        PREV SIGNAL PNL = {last_signal_pnl_in_phase}<br>
        PHASE PROFIT NOW = {phase_profit_group}<br>
        RECENT PHASE PNL = {recent_phase_pnl_next}
        </div>
        """,
        unsafe_allow_html=True,
    )
elif signal and vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#1f77b4;padding:24px;border-radius:14px;text-align:center;
        font-size:28px;color:white;font-weight:bold;">
        NEXT PHASE BET ONLY<br>
        GROUP {vote_group}<br>
        NEXT LIVE WAIT<br>
        REASON: {next_state}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div style="background:#333;padding:22px;border-radius:14px;text-align:center;
        font-size:26px;color:white;font-weight:bold;">
        NEXT WAIT<br>
        STATE: {next_state}
        </div>
        """,
        unsafe_allow_html=True,
    )

st.subheader("NEXT ROUND DEBUG")

d1, d2, d3, d4 = st.columns(4)
d1.metric("Next Round", next_round)
d2.metric("Next Signal", "YES" if signal else "NO")
d3.metric("Vote Strength", f"{confidence_group}/{vote_required}")
d4.metric("Distance", distance)

st.write("Next Vote Group:", vote_group if vote_group is not None else "-")
st.write("Previous Signal Round In Phase:", last_signal_round_in_phase)
st.write("Previous Signal PNL In Phase:", last_signal_pnl_in_phase)
st.write("Phase Profit Now:", phase_profit_group)
st.write("Recent Phase PNL Next:", recent_phase_pnl_next)
st.write("MIN_PHASE_PROFIT_TO_LIVE:", MIN_PHASE_PROFIT_TO_LIVE)
st.write("RECENT_PHASE_CHECK:", RECENT_PHASE_CHECK)
st.write("MIN_RECENT_PHASE_PNL:", MIN_RECENT_PHASE_PNL)
st.write("Can Live Bet:", can_live_bet)
st.write("Next State:", next_state)

st.subheader("Lock Info")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", groups[-1])
c3.metric("Selected Mode", selected_mode["name"] if selected_mode else "-")
c4.metric("Relock Count", relock_count)

st.write("Locked Windows:", locked_windows)
st.write("Best Lock Round:", selected_lock_round)
st.write("Scan Range:", f"{lock_scan_start} -> {lock_scan_end}")
st.write("Lock Mode:", lock_mode)
st.write("Relock Rule:", f"phase_profit_group <= {PHASE_STOP_LOSS}")
st.write("Telegram Enabled:", telegram_enabled())

st.subheader("Profit Compare")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Phase Current Profit", phase_profit_group)
p2.metric("Live Current Profit", phase_live_profit_group)
p3.metric("Total Phase Profit", total_phase_profit_group)
p4.metric("Total Live Profit", total_profit_group)

st.subheader("Trade Stats")

phase_trades = int(hist["PHASE_BET"].sum()) if "PHASE_BET" in hist.columns else 0
live_trades = int(hist["LIVE_BET"].sum()) if "LIVE_BET" in hist.columns else 0

phase_wr = (
    round(hist.loc[hist["PHASE_BET"], "phase_hit_group"].mean() * 100, 2)
    if phase_trades > 0
    else 0
)

live_wr = (
    round(hist.loc[hist["LIVE_BET"], "live_hit_group"].mean() * 100, 2)
    if live_trades > 0
    else 0
)

s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Trades", phase_trades)
s2.metric("Phase WR %", phase_wr)
s3.metric("Live Trades", live_trades)
s4.metric("Live WR %", live_wr)

st.subheader("Profit Curve")

chart_cols = [
    "phase_profit_group",
    "phase_live_profit_group",
    "total_phase_profit_group",
    "total_profit_group",
]

exist_chart_cols = [c for c in chart_cols if c in hist.columns]

if exist_chart_cols:
    st.line_chart(hist[exist_chart_cols].reset_index(drop=True))

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
    "signal",
    "PHASE_BET",
    "phase_bet_group",
    "phase_hit_group",
    "phase_pnl_group",
    "phase_profit_group",
    "recent_phase_pnl",
    "total_phase_profit_group",
    "prev_signal_round_in_phase",
    "prev_signal_pnl_in_phase",
    "LIVE_BET",
    "live_bet_group",
    "live_hit_group",
    "live_pnl_group",
    "phase_live_profit_group",
    "total_profit_group",
    "state",
    "locked_windows",
    "relock_triggered_now",
    "relock_reason",
]

show_cols = [c for c in history_cols if c in hist.columns]

st.dataframe(
    hist[show_cols].iloc[::-1].head(SHOW_HISTORY_ROWS),
    use_container_width=True,
)
