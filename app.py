import time
import json
import os
from collections import Counter
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Auto Relock Engine | Patched", layout="wide")
st_autorefresh(interval=8000, key="refresh")

# =========================================================
# DATA SOURCE
# =========================================================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
LOCAL_CSV_PATH = os.environ.get("LOCAL_CSV_PATH", "numbers.csv")

# =========================================================
# LOCK / REPLAY
# =========================================================
LOCK_ROUND_START = 168
LOCK_ROUND_END = 180
REPLAY_FROM = 180

MODES = [
    {"name": "5v3", "top_windows": 5, "vote_required": 3, "window_min": 6, "window_max": 22},
    {"name": "6v4", "top_windows": 6, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "8v5", "top_windows": 8, "vote_required": 5, "window_min": 6, "window_max": 22},
]

GAP = 1

# =========================================================
# PAYOUT
# =========================================================
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

ENABLE_COLOR_BET = False
WIN_COLOR = 1.5
LOSS_COLOR = -1.0
COLOR_VOTE_OFFSET = 0  # color_vote_required = max(2, vote_required + offset)

PHASE_BET_UNIT = 1.0
COLOR_BET_UNIT = 1.0

# =========================================================
# PROFILES
# Mặc định dùng "balanced". Có thể đổi bằng:
# ENGINE_PROFILE=safe streamlit run app_patched.py
# =========================================================
PARAMETER_PRESETS = {
    "safe": {
        "VOTE_DOMINANCE_RATIO": 0.67,
        "PHASE_MIN_RECENT_PNL_TO_TRADE": 0.0,
        "PHASE_MIN_TOTAL_PNL_TO_TRADE": 0.0,      # FIX 2: guard trực tiếp theo tổng phase
        "PHASE_STOP_WIN": 2.5,                    # FIX 5: dùng stop-win thật
        "PHASE_STOP_LOSS": -2.0,
        "PHASE_LOSS_STREAK_RELOCK": 2,
        "MAX_PHASE_TRADES": 4,
        "VALIDATE_MIN_DRAWDOWN": -1.0,            # FIX 5: nới drawdown validate
        "KEEP_AFTER_LOSS_ROUNDS": 0,              # FIX 3: semantics đã sửa, mặc định an toàn vẫn để 0
        "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK": True,   # FIX 2: phase âm + có signal => relock
        "NEGATIVE_PHASE_EXTRA_VOTE": 1,
        "NEGATIVE_PHASE_DOMINANCE_RATIO": 0.67,
    },
    "balanced": {
        "VOTE_DOMINANCE_RATIO": 0.60,
        "PHASE_MIN_RECENT_PNL_TO_TRADE": 0.0,
        "PHASE_MIN_TOTAL_PNL_TO_TRADE": 0.0,
        "PHASE_STOP_WIN": 2.5,
        "PHASE_STOP_LOSS": -2.0,
        "PHASE_LOSS_STREAK_RELOCK": 2,
        "MAX_PHASE_TRADES": 5,
        "VALIDATE_MIN_DRAWDOWN": -1.0,
        "KEEP_AFTER_LOSS_ROUNDS": 0,
        "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK": True,
        "NEGATIVE_PHASE_EXTRA_VOTE": 1,
        "NEGATIVE_PHASE_DOMINANCE_RATIO": 0.60,
    },
    "aggressive": {
        "VOTE_DOMINANCE_RATIO": 0.50,
        "PHASE_MIN_RECENT_PNL_TO_TRADE": 0.0,
        "PHASE_MIN_TOTAL_PNL_TO_TRADE": -0.5,
        "PHASE_STOP_WIN": 5.0,
        "PHASE_STOP_LOSS": -2.0,
        "PHASE_LOSS_STREAK_RELOCK": 2,
        "MAX_PHASE_TRADES": 6,
        "VALIDATE_MIN_DRAWDOWN": -1.5,
        "KEEP_AFTER_LOSS_ROUNDS": 1,
        "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK": False,
        "NEGATIVE_PHASE_EXTRA_VOTE": 1,
        "NEGATIVE_PHASE_DOMINANCE_RATIO": 0.60,
    },
}

ACTIVE_PROFILE = os.environ.get("ENGINE_PROFILE", "balanced").lower().strip()
if ACTIVE_PROFILE not in PARAMETER_PRESETS:
    ACTIVE_PROFILE = "balanced"
PROFILE = PARAMETER_PRESETS[ACTIVE_PROFILE]

# =========================================================
# PHASE / SESSION POLICY
# =========================================================
ENABLE_TIMEOUT_RELOCK = False
TIMEOUT_RELOCK_ROUNDS = 40

RECENT_PHASE_CHECK = 4
PHASE_MIN_RECENT_PNL_TO_TRADE = PROFILE["PHASE_MIN_RECENT_PNL_TO_TRADE"]
PHASE_MIN_TOTAL_PNL_TO_TRADE = PROFILE["PHASE_MIN_TOTAL_PNL_TO_TRADE"]  # FIX 2

MIN_PHASE_AGE_TO_TRADE = 3
MAX_PHASE_TRADES = PROFILE["MAX_PHASE_TRADES"]
VOTE_DOMINANCE_RATIO = PROFILE["VOTE_DOMINANCE_RATIO"]

KEEP_AFTER_LOSS_ROUNDS = PROFILE["KEEP_AFTER_LOSS_ROUNDS"]  # FIX 3
ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK = PROFILE["ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK"]  # FIX 2
NEGATIVE_PHASE_EXTRA_VOTE = PROFILE["NEGATIVE_PHASE_EXTRA_VOTE"]
NEGATIVE_PHASE_DOMINANCE_RATIO = PROFILE["NEGATIVE_PHASE_DOMINANCE_RATIO"]

PHASE_STOP_WIN = PROFILE["PHASE_STOP_WIN"]   # FIX 5
PHASE_STOP_LOSS = PROFILE["PHASE_STOP_LOSS"]
PHASE_LOSS_STREAK_RELOCK = PROFILE["PHASE_LOSS_STREAK_RELOCK"]

SESSION_STOP_WIN = 4.0
SESSION_STOP_LOSS = -13.0

MIN_FALLBACK_SCORE = 0

# =========================================================
# WINDOW / VALIDATION
# =========================================================
MIN_TRADES_PER_WINDOW = 18
RECENT_WINDOW_SIZE = 33
MIN_WINDOW_SPACING = 1
AUTO_SCAN_WINDOW_SPACING = True
WINDOW_SPACING_MIN = 1
WINDOW_SPACING_MAX = 5
MAX_CANDIDATE_WINDOWS = 10

VALIDATE_LEN = 12
AUTO_SCAN_VALIDATE_LEN = True
VALIDATE_LEN_LIST = [16, 24]
MIN_TRAIN_LEN = 100
MIN_VALIDATE_TRADES = 1
VALIDATE_MIN_DRAWDOWN = PROFILE["VALIDATE_MIN_DRAWDOWN"]   # FIX 5

RELOCK_SCAN_LEN = 18
RELOCK_BUFFER = 0

SHOW_HISTORY_ROWS = 10
SHOW_DEBUG_TABLES = False

# =========================================================
# TELEGRAM
# =========================================================
DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID
SENT_FILE = "/tmp/telegram_sent_phase_group_color_keep.json"

# Cache fingerprint để đảm bảo đổi profile / params thì backtest cũng đổi theo.
ENGINE_CONFIG_FINGERPRINT = json.dumps(
    {
        "ACTIVE_PROFILE": ACTIVE_PROFILE,
        "GAP": GAP,
        "WIN_GROUP": WIN_GROUP,
        "LOSS_GROUP": LOSS_GROUP,
        "PHASE_STOP_WIN": PHASE_STOP_WIN,
        "PHASE_STOP_LOSS": PHASE_STOP_LOSS,
        "PHASE_LOSS_STREAK_RELOCK": PHASE_LOSS_STREAK_RELOCK,
        "PHASE_MIN_RECENT_PNL_TO_TRADE": PHASE_MIN_RECENT_PNL_TO_TRADE,
        "PHASE_MIN_TOTAL_PNL_TO_TRADE": PHASE_MIN_TOTAL_PNL_TO_TRADE,
        "MAX_PHASE_TRADES": MAX_PHASE_TRADES,
        "VOTE_DOMINANCE_RATIO": VOTE_DOMINANCE_RATIO,
        "KEEP_AFTER_LOSS_ROUNDS": KEEP_AFTER_LOSS_ROUNDS,
        "VALIDATE_MIN_DRAWDOWN": VALIDATE_MIN_DRAWDOWN,
        "ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK": ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK,
        "NEGATIVE_PHASE_EXTRA_VOTE": NEGATIVE_PHASE_EXTRA_VOTE,
        "NEGATIVE_PHASE_DOMINANCE_RATIO": NEGATIVE_PHASE_DOMINANCE_RATIO,
    },
    sort_keys=True,
)

# =========================================================
# NOTIFY / IO HELPERS
# =========================================================
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


def _normalize_numbers_from_df(df: pd.DataFrame) -> List[int]:
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Dữ liệu phải có cột 'number'")
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]
    if not nums:
        raise ValueError("Không tìm thấy numbers hợp lệ trong khoảng 1..12")
    return nums


@st.cache_data(ttl=60, show_spinner=False)
def load_numbers(sheet_id: str, local_csv_path: str) -> Tuple[List[int], str]:
    """
    Ưu tiên đọc từ Google Sheet.
    Nếu lỗi mạng / lỗi quyền / không có dữ liệu, fallback sang file CSV local.
    """
    errors = []

    if sheet_id:
        try:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&cache={time.time()}"
            df = pd.read_csv(url)
            nums = _normalize_numbers_from_df(df)
            return nums, f"google_sheet:{sheet_id}"
        except Exception as e:
            errors.append(f"google_sheet_error={e}")

    try:
        df_local = pd.read_csv(local_csv_path)
        nums = _normalize_numbers_from_df(df_local)
        return nums, f"local_csv:{local_csv_path}"
    except Exception as e:
        errors.append(f"local_csv_error={e}")

    raise ValueError("Không thể load dữ liệu. " + " | ".join(errors))


# =========================================================
# MAPPING
# =========================================================
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


# =========================================================
# CORE HELPERS
# =========================================================
def vote_dominance_ok(preds, confidence, min_ratio):
    if not preds:
        return False, 0.0
    ratio = confidence / len(preds)
    return ratio >= min_ratio, float(ratio)


def get_valid_group_preds(seq_groups, i, windows):
    preds = []
    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = seq_groups[i - w]
            if seq_groups[i - 1] != pred:
                preds.append(pred)
    return preds


def get_valid_color_preds(seq_colors, i, windows):
    preds = []
    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = seq_colors[i - w]
            if seq_colors[i - 1] != pred:
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


def compute_recent_trade_profit_from_hits(results, recent_n, win_value, loss_value):
    """
    FIX 1:
    Tính recent PNL theo TRADE HITS của phase hiện tại,
    không theo history rows / rounds.
    """
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
            profit * 0.8
            + winrate * 8.0
            + np.log(trades + 1) * 1.2
            + recent_profit * 1.5
            - abs(max_drawdown) * 0.8
            + streak_metrics["streak_score"] * 1.0
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


def build_window_tables(train_groups, window_min, window_max, min_window_spacing=None):
    if min_window_spacing is None:
        min_window_spacing = MIN_WINDOW_SPACING

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

    spaced_candidate_df = pick_spaced_windows(candidate_df, MAX_CANDIDATE_WINDOWS, min_window_spacing)

    if not spaced_candidate_df.empty and "window" in spaced_candidate_df.columns:
        candidate_windows = spaced_candidate_df["window"].astype(int).tolist()
    else:
        candidate_windows = []

    need = max(m["top_windows"] for m in MODES)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(selected_seed, need, min_window_spacing)

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

    validate_values = VALIDATE_LEN_LIST if AUTO_SCAN_VALIDATE_LEN else [VALIDATE_LEN]

    for validate_len in validate_values:
        if validate_len < 0:
            continue

        for r in range(scan_start, effective_scan_end + 1):
            if r < validate_len + MIN_TRAIN_LEN:
                continue

            train_end = r - validate_len
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

                spacing_values = (
                    range(WINDOW_SPACING_MIN, WINDOW_SPACING_MAX + 1)
                    if AUTO_SCAN_WINDOW_SPACING
                    else [MIN_WINDOW_SPACING]
                )

                for spacing in spacing_values:
                    candidate_windows, df_all, filtered_df = build_window_tables(
                        train_groups,
                        mode["window_min"],
                        mode["window_max"],
                        min_window_spacing=spacing,
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

                    # FIX 5:
                    # max_drawdown_group luôn là 0 hoặc âm.
                    # Vì vậy VALIDATE_MIN_DRAWDOWN phải là số âm hợp lý, ví dụ -1.0.
                    validate_pass = (
                        validate_bt["trades"] >= MIN_VALIDATE_TRADES
                        and validate_bt["max_drawdown_group"] >= VALIDATE_MIN_DRAWDOWN
                    )

                    final_score = (
                        train_bt["profit_group"] * 0.8
                        + train_bt["winrate_group"] * 8.0
                        + train_bt["recent_profit_group"] * 1.5
                        - abs(train_bt["max_drawdown_group"]) * 0.8
                        + train_bt["streak_score"] * 1.0
                        + validate_bt["profit_group"] * 3.0
                        + validate_bt["winrate_group"] * 10.0
                        - abs(validate_bt["max_drawdown_group"]) * 1.5
                        + validate_bt["streak_score"] * 1.0
                    )

                    mode_with_params = dict(mode)
                    mode_with_params["spacing"] = spacing
                    mode_with_params["validate_len"] = validate_len

                    if final_score > local_fallback_score:
                        local_fallback_score = final_score
                        local_fallback_windows = selected_windows
                        local_fallback_mode = mode_with_params
                        local_fallback_scan_df = df_all.copy()
                        local_fallback_scan_df["selected_spacing"] = spacing
                        local_fallback_scan_df["selected_validate_len"] = validate_len
                        local_fallback_filtered_df = filtered_df.copy()
                        local_fallback_filtered_df["selected_spacing"] = spacing
                        local_fallback_filtered_df["selected_validate_len"] = validate_len

                    if validate_pass and final_score > local_best_score:
                        local_best_score = final_score
                        local_best_windows = selected_windows
                        local_best_mode = mode_with_params
                        local_best_scan_df = local_fallback_scan_df.copy()
                        local_best_filtered_df = local_fallback_filtered_df.copy()
                        local_lock_mode = "validated"

            if local_best_mode is not None:
                round_eval_rows.append(
                    {
                        "lock_round": r,
                        "mode": local_best_mode["name"],
                        "selected_windows": ", ".join(map(str, local_best_windows)),
                        "spacing": local_best_mode.get("spacing", MIN_WINDOW_SPACING),
                        "validate_len": local_best_mode.get("validate_len", VALIDATE_LEN),
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

            elif local_fallback_mode is not None and local_fallback_score >= MIN_FALLBACK_SCORE:
                round_eval_rows.append(
                    {
                        "lock_round": r,
                        "mode": local_fallback_mode["name"],
                        "selected_windows": ", ".join(map(str, local_fallback_windows)),
                        "spacing": local_fallback_mode.get("spacing", MIN_WINDOW_SPACING),
                        "validate_len": local_fallback_mode.get("validate_len", VALIDATE_LEN),
                        "bundle_score": local_fallback_score,
                        "lock_mode": "fallback_soft",
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

    if fallback_round is not None and fallback_score >= MIN_FALLBACK_SCORE:
        return fallback_round, fallback_windows, fallback_mode, fallback_scan_df, fallback_filtered_df, round_eval_df, "fallback_soft"

    return None, [], None, pd.DataFrame(), pd.DataFrame(), round_eval_df, "not_found"


def compute_live_next_preview(
    numbers: List[int],
    groups: List[int],
    colors: List[int],
    locked_windows: List[int],
    current_mode: Optional[Dict[str, Any]],
    phase_start_round: Optional[int],
    phase_index: int,
    phase_profit_group: float,
    phase_profit_color: float,
    phase_profit_total: float,
    total_phase_profit_all: float,
    phase_hits_group: List[int],
    keep_phase_group: Optional[int],
    keep_phase_color: Optional[int],
    keep_phase_left: int,
    last_phase_bet_was_loss: bool,
    last_phase_trade_idx: int,
    session_stop: bool,
    session_stop_reason: Optional[str],
) -> Dict[str, Any]:
    """
    FIX 4:
    Tạo preview NEXT ROUND từ live-state thật của engine
    thay vì suy luận từ hist.iloc[-1] (dễ stale sau relock).
    """
    preview = {
        "current_round": len(numbers),
        "next_round": len(numbers) + 1,
        "vote_group": None,
        "confidence_group": 0,
        "dominance_ratio": 0.0,
        "dominance_ok": False,
        "vote_color": None,
        "confidence_color": 0,
        "signal_group": False,
        "signal_color": False,
        "used_keep_phase": False,
        "final_phase_group": None,
        "final_phase_color": None,
        "phase_next_allowed": False,
        "next_state": "NO_ACTIVE_LOCK",
        "recent_phase_pnl": 0.0,
        "current_phase_age_next": 1,
        "current_phase_trade_count": len(phase_hits_group),
        "distance_from_last_trade": None,
        "phase_profit_group": phase_profit_group,
        "phase_profit_color": phase_profit_color,
        "phase_profit_total": phase_profit_total,
        "total_phase_profit_all": total_phase_profit_all,
    }

    if current_mode is None or not locked_windows:
        return preview

    next_idx = len(groups)
    next_round = next_idx + 1
    vote_required = current_mode["vote_required"]
    color_vote_required = max(2, vote_required + COLOR_VOTE_OFFSET)

    preds_group = get_valid_group_preds(groups, next_idx, locked_windows)
    preds_color = get_valid_color_preds(colors, next_idx, locked_windows)

    if preds_group:
        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        dominance_ok_next, dominance_ratio_next = vote_dominance_ok(
            preds_group,
            confidence_group,
            VOTE_DOMINANCE_RATIO,
        )
    else:
        vote_group, confidence_group = None, 0
        dominance_ok_next, dominance_ratio_next = False, 0.0

    if preds_color:
        vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
    else:
        vote_color, confidence_color = None, 0

    signal_group = (confidence_group >= vote_required and dominance_ok_next) if vote_group is not None else False
    signal_color = confidence_color >= color_vote_required if vote_color is not None else False

    recent_phase_pnl_next = compute_recent_trade_profit_from_hits(
        phase_hits_group,
        RECENT_PHASE_CHECK,
        WIN_GROUP * PHASE_BET_UNIT,
        LOSS_GROUP * PHASE_BET_UNIT,
    )

    current_phase_age_next = (
        next_round - phase_start_round + 1
        if phase_start_round is not None
        else 1
    )

    current_phase_trade_count = len(phase_hits_group)
    phase_warmup_block_next = current_phase_age_next < MIN_PHASE_AGE_TO_TRADE
    max_phase_trades_block_next = current_phase_trade_count >= MAX_PHASE_TRADES

    used_keep_phase_next = False
    final_phase_group_next = vote_group
    final_phase_color_next = vote_color if signal_color else None

    keep_active_next = (
        last_phase_bet_was_loss
        and keep_phase_left > 0
        and keep_phase_group is not None
    )

    # FIX 3:
    # KEEP chỉ được dùng nếu current signal vẫn cùng hướng với keep group.
    if keep_active_next and signal_group and vote_group == keep_phase_group:
        used_keep_phase_next = True
        final_phase_group_next = keep_phase_group

        if signal_color and keep_phase_color is not None and vote_color == keep_phase_color:
            final_phase_color_next = keep_phase_color
        else:
            final_phase_color_next = vote_color if signal_color else None

    phase_next_allowed = (
        signal_group
        and recent_phase_pnl_next >= PHASE_MIN_RECENT_PNL_TO_TRADE
        and phase_profit_group >= PHASE_MIN_TOTAL_PNL_TO_TRADE
    )

    negative_phase_pretrade_relock_ready = (
        ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK
        and signal_group
        and phase_profit_group < 0
    )

    if (
        not ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK
        and signal_group
        and phase_profit_group < 0
        and phase_next_allowed
    ):
        # Nếu profile cho phép trade nhẹ khi phase âm, phải siết tín hiệu hơn.
        phase_next_allowed = (
            confidence_group >= (vote_required + NEGATIVE_PHASE_EXTRA_VOTE)
            and dominance_ratio_next >= NEGATIVE_PHASE_DOMINANCE_RATIO
        )

    if phase_next_allowed and phase_warmup_block_next:
        phase_next_allowed = False

    if phase_next_allowed and max_phase_trades_block_next:
        phase_next_allowed = False

    distance = next_idx - last_phase_trade_idx
    if phase_next_allowed and distance < GAP:
        phase_next_allowed = False

    if session_stop:
        next_state = session_stop_reason
        phase_next_allowed = False
    elif negative_phase_pretrade_relock_ready:
        next_state = "READY_AUTO_RELOCK_NEGATIVE_PHASE"
        phase_next_allowed = False
    elif phase_next_allowed and used_keep_phase_next:
        next_state = "READY_PHASE_KEEP_BET"
    elif phase_next_allowed:
        next_state = "READY_PHASE_BET"
    elif signal_group and phase_warmup_block_next:
        next_state = "WAIT_PHASE_WARMUP"
    elif signal_group and max_phase_trades_block_next:
        next_state = "WAIT_MAX_PHASE_TRADES"
    elif vote_group is not None and not dominance_ok_next:
        next_state = "WAIT_VOTE_DOMINANCE_WEAK"
    elif keep_active_next and signal_group and vote_group != keep_phase_group:
        next_state = "WAIT_KEEP_SIGNAL_MISMATCH"
    elif signal_group and phase_profit_group < PHASE_MIN_TOTAL_PNL_TO_TRADE:
        next_state = "WAIT_PHASE_TOTAL_PNL_TOO_LOW"
    elif signal_group and recent_phase_pnl_next < PHASE_MIN_RECENT_PNL_TO_TRADE:
        next_state = "WAIT_RECENT_PHASE_TRADES_TOO_WEAK"
    elif not signal_group:
        next_state = "WAIT_NO_GROUP_SIGNAL"
    else:
        next_state = "WAIT"

    preview.update(
        {
            "current_round": len(numbers),
            "next_round": next_round,
            "vote_required": vote_required,
            "color_vote_required": color_vote_required,
            "vote_group": vote_group,
            "confidence_group": confidence_group,
            "dominance_ratio": dominance_ratio_next,
            "dominance_ok": dominance_ok_next,
            "vote_color": vote_color,
            "confidence_color": confidence_color,
            "signal_group": signal_group,
            "signal_color": signal_color,
            "used_keep_phase": used_keep_phase_next,
            "final_phase_group": final_phase_group_next,
            "final_phase_color": final_phase_color_next,
            "phase_next_allowed": phase_next_allowed,
            "next_state": next_state,
            "recent_phase_pnl": recent_phase_pnl_next,
            "current_phase_age_next": current_phase_age_next,
            "current_phase_trade_count": current_phase_trade_count,
            "distance_from_last_trade": distance,
            "negative_phase_pretrade_relock_ready": negative_phase_pretrade_relock_ready,
        }
    )
    return preview


def simulate_engine(numbers, groups, colors):
    result = {
        "hist": pd.DataFrame(),
        "phase_profit_group": 0.0,
        "phase_profit_color": 0.0,
        "phase_profit_total": 0.0,
        "total_phase_profit_group": 0.0,
        "total_phase_profit_color": 0.0,
        "total_phase_profit_all": 0.0,
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
        "phase_consecutive_losses": 0,
        "keep_phase_group": None,
        "keep_phase_color": None,
        "keep_phase_left": 0,
        "last_phase_bet_was_loss": False,
        "next_preview": {},
        "phase_start_round": None,
        "phase_trade_count": 0,
        "recent_phase_trade_pnl": 0.0,
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

    total_phase_profit_group = 0.0
    total_phase_profit_color = 0.0
    total_phase_profit_all = 0.0

    phase_hits_group = []
    phase_hits_color = []

    last_signal_pnl_in_phase = 0.0
    last_signal_round_in_phase = None

    phase_consecutive_losses = 0
    keep_phase_group = None
    keep_phase_color = None
    keep_phase_left = 0
    last_phase_bet_was_loss = False
    last_phase_trade_idx = -999999

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

        if total_phase_profit_all >= SESSION_STOP_WIN:
            break
        if total_phase_profit_all <= SESSION_STOP_LOSS:
            break

        vote_required = current_mode["vote_required"]
        color_vote_required = max(2, vote_required + COLOR_VOTE_OFFSET)

        preds_group = get_valid_group_preds(groups, i, locked_windows)
        preds_color = get_valid_color_preds(colors, i, locked_windows)

        if preds_group:
            vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
            dominance_ok, dominance_ratio = vote_dominance_ok(
                preds_group,
                confidence_group,
                VOTE_DOMINANCE_RATIO,
            )
            signal_group = confidence_group >= vote_required and dominance_ok
        else:
            vote_group = None
            confidence_group = 0
            dominance_ratio = 0.0
            dominance_ok = False
            signal_group = False

        if preds_color:
            vote_color, confidence_color = Counter(preds_color).most_common(1)[0]
            signal_color = confidence_color >= color_vote_required
        else:
            vote_color = None
            confidence_color = 0
            signal_color = False

        phase_age = round_no - phase_start_round + 1

        # FIX 1:
        # recent_phase_pnl phải tính theo TRADE của phase hiện tại, không theo số round gần nhất.
        recent_phase_pnl = compute_recent_trade_profit_from_hits(
            phase_hits_group,
            RECENT_PHASE_CHECK,
            WIN_GROUP * PHASE_BET_UNIT,
            LOSS_GROUP * PHASE_BET_UNIT,
        )

        prev_signal_pnl_in_phase = last_signal_pnl_in_phase
        prev_signal_round_in_phase = last_signal_round_in_phase

        phase_trade_count_before = len(phase_hits_group)
        phase_warmup_block = phase_age < MIN_PHASE_AGE_TO_TRADE
        max_phase_trades_block = phase_trade_count_before >= MAX_PHASE_TRADES

        keep_active_before_round = (
            last_phase_bet_was_loss
            and keep_phase_left > 0
            and keep_phase_group is not None
        )

        used_keep_phase = False
        final_phase_group = vote_group
        final_phase_color = vote_color if signal_color else None

        # FIX 3:
        # KEEP chỉ có hiệu lực nếu current signal vẫn cùng group với lệnh vừa thua.
        if keep_active_before_round and signal_group and vote_group == keep_phase_group:
            used_keep_phase = True
            final_phase_group = keep_phase_group

            if signal_color and keep_phase_color is not None and vote_color == keep_phase_color:
                final_phase_color = keep_phase_color
            else:
                final_phase_color = vote_color if signal_color else None

        # FIX 2:
        # guard trực tiếp theo tổng phase.
        phase_trade_allowed = (
            signal_group
            and recent_phase_pnl >= PHASE_MIN_RECENT_PNL_TO_TRADE
            and phase_profit_group >= PHASE_MIN_TOTAL_PNL_TO_TRADE
        )

        negative_phase_pretrade_relock_ready = (
            ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK
            and signal_group
            and phase_profit_group < 0
        )

        # Nếu profile cho trade mềm khi phase âm (ví dụ aggressive), phải siết tín hiệu hơn.
        if (
            not ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK
            and signal_group
            and phase_profit_group < 0
            and phase_trade_allowed
        ):
            phase_trade_allowed = (
                confidence_group >= (vote_required + NEGATIVE_PHASE_EXTRA_VOTE)
                and dominance_ratio >= NEGATIVE_PHASE_DOMINANCE_RATIO
            )

        if phase_trade_allowed and phase_warmup_block:
            phase_trade_allowed = False

        if phase_trade_allowed and max_phase_trades_block:
            phase_trade_allowed = False

        distance = i - last_phase_trade_idx
        if phase_trade_allowed and distance < GAP:
            phase_trade_allowed = False

        phase_hit_group = None
        phase_hit_color = None
        phase_pnl_group = 0.0
        phase_pnl_color = 0.0
        phase_pnl_total = 0.0

        relock_triggered_now = False
        relock_reason_now = None
        state = "WAIT"
        new_keep_assigned_this_round = False

        # FIX 2:
        # phase âm mà có signal -> relock ngay trước trade, nếu option được bật.
        if negative_phase_pretrade_relock_ready:
            relock_triggered_now = True
            relock_reason_now = "NEGATIVE_PHASE_PRETRADE_RELOCK"
            state = "AUTO_RELOCK_NEGATIVE_PHASE"
            phase_trade_allowed = False

        elif phase_trade_allowed:
            last_phase_trade_idx = i

            if groups[i] == final_phase_group:
                phase_hit_group = 1
                phase_pnl_group = WIN_GROUP * PHASE_BET_UNIT
            else:
                phase_hit_group = 0
                phase_pnl_group = LOSS_GROUP * PHASE_BET_UNIT

            if ENABLE_COLOR_BET and final_phase_color is not None:
                if colors[i] == final_phase_color:
                    phase_hit_color = 1
                    phase_pnl_color = WIN_COLOR * COLOR_BET_UNIT
                else:
                    phase_hit_color = 0
                    phase_pnl_color = LOSS_COLOR * COLOR_BET_UNIT
            else:
                phase_hit_color = None
                phase_pnl_color = 0.0

            phase_pnl_total = phase_pnl_group + phase_pnl_color

            phase_profit_group += phase_pnl_group
            phase_profit_color += phase_pnl_color
            phase_profit_total += phase_pnl_total

            total_phase_profit_group += phase_pnl_group
            total_phase_profit_color += phase_pnl_color
            total_phase_profit_all += phase_pnl_total

            phase_hits_group.append(phase_hit_group)
            if phase_hit_color is not None:
                phase_hits_color.append(phase_hit_color)

            last_signal_pnl_in_phase = phase_pnl_group
            last_signal_round_in_phase = round_no

            if phase_hit_group == 1:
                phase_consecutive_losses = 0
                keep_phase_group = None
                keep_phase_color = None
                keep_phase_left = 0
                last_phase_bet_was_loss = False
            else:
                phase_consecutive_losses += 1

                # FIX 3:
                # KEEP bây giờ là "số rounds tiếp theo" được phép giữ ý tưởng cũ,
                # nhưng vẫn phải có signal cùng hướng.
                if KEEP_AFTER_LOSS_ROUNDS > 0:
                    keep_phase_group = final_phase_group
                    keep_phase_color = final_phase_color
                    keep_phase_left = KEEP_AFTER_LOSS_ROUNDS
                    last_phase_bet_was_loss = True
                    new_keep_assigned_this_round = True
                else:
                    keep_phase_group = None
                    keep_phase_color = None
                    keep_phase_left = 0
                    last_phase_bet_was_loss = False

            state = "PHASE_KEEP_BET" if used_keep_phase else "PHASE_BET"

        else:
            if signal_group and phase_warmup_block:
                state = "WAIT_PHASE_WARMUP"
            elif signal_group and max_phase_trades_block:
                state = "WAIT_MAX_PHASE_TRADES"
            elif vote_group is not None and not dominance_ok:
                state = "WAIT_VOTE_DOMINANCE_WEAK"
            elif keep_active_before_round and signal_group and vote_group != keep_phase_group:
                state = "WAIT_KEEP_SIGNAL_MISMATCH"
            elif signal_group and phase_profit_group < PHASE_MIN_TOTAL_PNL_TO_TRADE:
                state = "WAIT_PHASE_TOTAL_PNL_TOO_LOW"
            elif signal_group and recent_phase_pnl < PHASE_MIN_RECENT_PNL_TO_TRADE:
                state = "WAIT_RECENT_PHASE_TRADES_TOO_WEAK"
            elif not signal_group:
                state = "WAIT_NO_GROUP_SIGNAL"
            else:
                state = "WAIT"

        # FIX 3:
        # KEEP countdown giảm theo round, không phải chỉ theo lần trade.
        # Nếu vừa sinh KEEP mới từ lệnh thua hiện tại thì không giảm ngay.
        if keep_active_before_round and not new_keep_assigned_this_round and last_phase_bet_was_loss and keep_phase_group is not None:
            keep_phase_left = max(int(keep_phase_left) - 1, 0)
            if keep_phase_left <= 0:
                keep_phase_group = None
                keep_phase_color = None
                keep_phase_left = 0
                last_phase_bet_was_loss = False

        # FIX 5:
        # Kích hoạt stop-win thật sự.
        if not relock_triggered_now:
            if phase_profit_group >= PHASE_STOP_WIN:
                relock_triggered_now = True
                relock_reason_now = "PHASE_GROUP_STOP_WIN"
                state = "AUTO_RELOCK_PHASE_GROUP_WIN"

            elif phase_profit_group <= PHASE_STOP_LOSS:
                relock_triggered_now = True
                relock_reason_now = "PHASE_GROUP_STOP_LOSS"
                state = "AUTO_RELOCK_PHASE_GROUP_LOSS"

            elif phase_consecutive_losses >= PHASE_LOSS_STREAK_RELOCK:
                relock_triggered_now = True
                relock_reason_now = "PHASE_LOSS_STREAK_RELOCK"
                state = "AUTO_RELOCK_LOSS_STREAK"

            elif len(phase_hits_group) >= MAX_PHASE_TRADES:
                relock_triggered_now = True
                relock_reason_now = "MAX_PHASE_TRADES_RELOCK"
                state = "AUTO_RELOCK_MAX_PHASE_TRADES"

        if (
            not relock_triggered_now
            and ENABLE_TIMEOUT_RELOCK
            and phase_age >= TIMEOUT_RELOCK_ROUNDS
            and phase_profit_group <= 0
        ):
            relock_triggered_now = True
            relock_reason_now = "TIMEOUT_RELOCK_PHASE_NOT_POSITIVE"
            state = "AUTO_RELOCK_TIMEOUT"

        history_rows.append(
            {
                "phase": phase_index,
                "round": round_no,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "mode": current_mode["name"],
                "vote_required": vote_required,
                "color_vote_required": color_vote_required,
                "top_windows": current_mode["top_windows"],
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "dominance_ratio": dominance_ratio,
                "dominance_ok": dominance_ok,
                "signal_group": signal_group,
                "phase_warmup_block": phase_warmup_block,
                "max_phase_trades_block": max_phase_trades_block,
                "vote_color": color_text(vote_color),
                "confidence_color": confidence_color,
                "signal_color": signal_color,
                "PHASE_BET": phase_trade_allowed,
                "used_keep_phase": used_keep_phase,
                "phase_bet_group": final_phase_group if phase_trade_allowed else None,
                "phase_bet_color": color_text(final_phase_color) if phase_trade_allowed else "-",
                "phase_hit_group": phase_hit_group,
                "phase_hit_color": phase_hit_color,
                "phase_pnl_group": phase_pnl_group,
                "phase_pnl_color": phase_pnl_color,
                "phase_pnl_total": phase_pnl_total,
                "phase_profit_group": phase_profit_group,
                "phase_profit_color": phase_profit_color,
                "phase_profit_total": phase_profit_total,
                "phase_consecutive_losses": phase_consecutive_losses,
                "keep_phase_group": keep_phase_group,
                "keep_phase_color": color_text(keep_phase_color),
                "keep_phase_left": keep_phase_left,
                "last_phase_bet_was_loss": last_phase_bet_was_loss,
                "recent_phase_pnl": recent_phase_pnl,
                "total_phase_profit_group": total_phase_profit_group,
                "total_phase_profit_color": total_phase_profit_color,
                "total_phase_profit_all": total_phase_profit_all,
                "prev_signal_round_in_phase": prev_signal_round_in_phase,
                "prev_signal_pnl_in_phase": prev_signal_pnl_in_phase,
                "phase_age": phase_age,
                "phase_trade_count_before": phase_trade_count_before,
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
                    "spacing": current_mode.get("spacing", MIN_WINDOW_SPACING),
                    "validate_len": current_mode.get("validate_len", VALIDATE_LEN),
                    "locked_windows": ", ".join(map(str, locked_windows)),
                    "lock_mode": lock_mode,
                    "lock_scan_start": lock_scan_start,
                    "lock_scan_end": lock_scan_end,
                    "lock_round": selected_lock_round,
                    "phase_age": phase_age,
                    "phase_loss_streak": phase_consecutive_losses,
                    "max_phase_trades": MAX_PHASE_TRADES,
                    "min_phase_age_to_trade": MIN_PHASE_AGE_TO_TRADE,
                    "phase_bet_trades": len(phase_hits_group),
                    "phase_group_profit": phase_profit_group,
                    "phase_color_profit": phase_profit_color,
                    "phase_total_profit": phase_profit_total,
                    "phase_group_wr": round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0.0,
                    "phase_color_wr": round(np.mean(phase_hits_color) * 100, 2) if phase_hits_color else 0.0,
                    "total_phase_profit_after_phase": total_phase_profit_all,
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
                selected_lock_round = new_selected_lock_round
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

                phase_consecutive_losses = 0
                keep_phase_group = None
                keep_phase_color = None
                keep_phase_left = 0
                last_phase_bet_was_loss = False

                last_signal_pnl_in_phase = 0.0
                last_signal_round_in_phase = None

                # FIX 4b:
                # phase mới không nên bị dính last trade idx của phase cũ.
                last_phase_trade_idx = -999999

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    session_stop = total_phase_profit_all >= SESSION_STOP_WIN or total_phase_profit_all <= SESSION_STOP_LOSS
    session_stop_reason = (
        "SESSION_STOP_WIN"
        if total_phase_profit_all >= SESSION_STOP_WIN
        else "SESSION_STOP_LOSS"
        if total_phase_profit_all <= SESSION_STOP_LOSS
        else None
    )

    next_preview = compute_live_next_preview(
        numbers=numbers,
        groups=groups,
        colors=colors,
        locked_windows=locked_windows,
        current_mode=current_mode,
        phase_start_round=phase_start_round,
        phase_index=phase_index,
        phase_profit_group=phase_profit_group,
        phase_profit_color=phase_profit_color,
        phase_profit_total=phase_profit_total,
        total_phase_profit_all=total_phase_profit_all,
        phase_hits_group=phase_hits_group,
        keep_phase_group=keep_phase_group,
        keep_phase_color=keep_phase_color,
        keep_phase_left=keep_phase_left,
        last_phase_bet_was_loss=last_phase_bet_was_loss,
        last_phase_trade_idx=last_phase_trade_idx,
        session_stop=session_stop,
        session_stop_reason=session_stop_reason,
    )

    result.update(
        {
            "hist": hist,
            "phase_profit_group": phase_profit_group,
            "phase_profit_color": phase_profit_color,
            "phase_profit_total": phase_profit_total,
            "total_phase_profit_group": total_phase_profit_group,
            "total_phase_profit_color": total_phase_profit_color,
            "total_phase_profit_all": total_phase_profit_all,
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
            "phase_consecutive_losses": phase_consecutive_losses,
            "keep_phase_group": keep_phase_group,
            "keep_phase_color": keep_phase_color,
            "keep_phase_left": keep_phase_left,
            "last_phase_bet_was_loss": last_phase_bet_was_loss,
            "next_preview": next_preview,
            "phase_start_round": phase_start_round,
            "phase_trade_count": len(phase_hits_group),
            "recent_phase_trade_pnl": compute_recent_trade_profit_from_hits(
                phase_hits_group,
                RECENT_PHASE_CHECK,
                WIN_GROUP * PHASE_BET_UNIT,
                LOSS_GROUP * PHASE_BET_UNIT,
            ),
        }
    )

    return result


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_engine(numbers_tuple, config_fingerprint):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    cols = [color_of_number(n) for n in nums]
    return simulate_engine(nums, grps, cols)


# =========================================================
# APP START
# =========================================================
numbers, data_source = load_numbers(SHEET_ID, LOCAL_CSV_PATH)
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

if st.sidebar.button("Clear cache & rerun"):
    st.cache_data.clear()
    st.rerun()

sim = cached_simulate_engine(tuple(numbers), ENGINE_CONFIG_FINGERPRINT)
hist = sim["hist"]

if hist.empty:
    st.error("Không tìm được bộ lock phù hợp.")
    st.stop()

phase_profit_group = sim["phase_profit_group"]
phase_profit_color = sim["phase_profit_color"]
phase_profit_total = sim["phase_profit_total"]
total_phase_profit_group = sim["total_phase_profit_group"]
total_phase_profit_color = sim["total_phase_profit_color"]
total_phase_profit_all = sim["total_phase_profit_all"]

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
phase_consecutive_losses = sim["phase_consecutive_losses"]
keep_phase_group = sim.get("keep_phase_group", None)
keep_phase_color = sim.get("keep_phase_color", None)
keep_phase_left = sim.get("keep_phase_left", 0)
last_phase_bet_was_loss = sim.get("last_phase_bet_was_loss", False)

next_preview = sim["next_preview"]

current_round = next_preview["current_round"]
next_round = next_preview["next_round"]
vote_required = next_preview.get("vote_required", 0)
color_vote_required = next_preview.get("color_vote_required", 0)

vote_group = next_preview["vote_group"]
confidence_group = next_preview["confidence_group"]
dominance_ratio_next = next_preview["dominance_ratio"]
dominance_ok_next = next_preview["dominance_ok"]

vote_color = next_preview["vote_color"]
confidence_color = next_preview["confidence_color"]

signal_group = next_preview["signal_group"]
signal_color = next_preview["signal_color"]

used_keep_phase_next = next_preview["used_keep_phase"]
final_phase_group_next = next_preview["final_phase_group"]
final_phase_color_next = next_preview["final_phase_color"]
phase_next_allowed = next_preview["phase_next_allowed"]
next_state = next_preview["next_state"]

recent_phase_pnl_next = next_preview["recent_phase_pnl"]
current_phase_age_next = next_preview["current_phase_age_next"]
current_phase_trade_count = next_preview["current_phase_trade_count"]
distance_from_last_trade = next_preview["distance_from_last_trade"]

st.title("Auto Relock Engine | PHASE GROUP + COLOR | PATCHED")

st.caption(
    f"Profile: {ACTIVE_PROFILE} | Data Source: {data_source} | "
    f"Fixes: recent-trades, phase-total-guard, keep-semantics, live-preview, validate-dd, stop-win"
)

st.subheader("LAST ROUND RESULT")

last = hist.iloc[-1]

r1, r2, r3, r4 = st.columns(4)
r1.metric("Last Round", int(last["round"]))
r2.metric("Last Group Signal", "YES" if bool(last["signal_group"]) else "NO")
r3.metric("Last Phase Bet", "YES" if bool(last["PHASE_BET"]) else "NO")
r4.metric("Last Keep", "YES" if bool(last["used_keep_phase"]) else "NO")

r5, r6, r7, r8 = st.columns(4)
r5.metric("Last Group PNL", float(last["phase_pnl_group"]))
r6.metric("Last Color PNL", float(last["phase_pnl_color"]))
r7.metric("Last Total PNL", float(last["phase_pnl_total"]))
r8.metric("Loss Streak", phase_consecutive_losses)

st.write("Last State:", str(last["state"]))

st.subheader("NEXT ROUND BET")

b1, b2, b3, b4 = st.columns(4)
b1.metric("NEXT PHASE BET", "YES" if phase_next_allowed else "NO")
b2.metric("NEXT GROUP", final_phase_group_next if phase_next_allowed else "-")
b3.metric("NEXT COLOR", color_text(final_phase_color_next) if phase_next_allowed else "-")
b4.metric("USED KEEP", "YES" if used_keep_phase_next else "NO")

if phase_next_allowed and final_phase_group_next is not None:
    st.markdown(
        f"""
        <div style="background:#ff3333;padding:26px;border-radius:14px;text-align:center;
        font-size:32px;color:white;font-weight:bold;">
        READY PHASE BET<br>
        GROUP {final_phase_group_next} | COLOR {color_text(final_phase_color_next)}<br>
        KEEP = {used_keep_phase_next}<br>
        PHASE TOTAL PROFIT = {phase_profit_total}
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
        STATE: {next_state}
        </div>
        """,
        unsafe_allow_html=True,
    )

st.subheader("NEXT ROUND DEBUG")

d1, d2, d3, d4 = st.columns(4)
d1.metric("Next Round", next_round)
d2.metric("Group Vote", f"{confidence_group}/{vote_required}")
d3.metric("Dominance", round(dominance_ratio_next, 2))
d4.metric("Recent Phase PNL", recent_phase_pnl_next)

st.write("Next Group Vote:", vote_group if vote_group is not None else "-")
st.write("Next Color Vote:", color_text(vote_color))
st.write("Final Phase Group:", final_phase_group_next if final_phase_group_next is not None else "-")
st.write("Final Phase Color:", color_text(final_phase_color_next))
st.write("Used Keep Phase Next:", used_keep_phase_next)
st.write("Keep Phase Group:", keep_phase_group)
st.write("Keep Phase Color:", color_text(keep_phase_color))
st.write("Keep Phase Left:", keep_phase_left)
st.write("Last Phase Bet Was Loss:", last_phase_bet_was_loss)
st.write("PHASE_MIN_RECENT_PNL_TO_TRADE:", PHASE_MIN_RECENT_PNL_TO_TRADE)
st.write("PHASE_MIN_TOTAL_PNL_TO_TRADE:", PHASE_MIN_TOTAL_PNL_TO_TRADE)
st.write("MIN_PHASE_AGE_TO_TRADE:", MIN_PHASE_AGE_TO_TRADE)
st.write("Current Phase Age Next:", current_phase_age_next)
st.write("MAX_PHASE_TRADES:", MAX_PHASE_TRADES)
st.write("Current Phase Trade Count:", current_phase_trade_count)
st.write("Distance From Last Trade:", distance_from_last_trade)
st.write("VOTE_DOMINANCE_RATIO:", VOTE_DOMINANCE_RATIO)
st.write("Dominance OK Next:", dominance_ok_next)
st.write("Negative Phase Relock Enabled:", ENABLE_NEGATIVE_PHASE_PRETRADE_RELOCK)
st.write("Next State:", next_state)

st.subheader("Lock Info")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", groups[-1])
c3.metric("Current Color", color_text(colors[-1]))
c4.metric("Relock Count", relock_count)

st.write("Selected Mode:", selected_mode["name"] if selected_mode else "-")
st.write("Selected Window Spacing:", selected_mode.get("spacing", MIN_WINDOW_SPACING) if selected_mode else "-")
st.write("Selected Validate Len:", selected_mode.get("validate_len", VALIDATE_LEN) if selected_mode else "-")
st.write("Auto Scan Validate Len:", VALIDATE_LEN_LIST if AUTO_SCAN_VALIDATE_LEN else VALIDATE_LEN)
st.write("Auto Scan Window Spacing:", f"{WINDOW_SPACING_MIN} -> {WINDOW_SPACING_MAX}" if AUTO_SCAN_WINDOW_SPACING else MIN_WINDOW_SPACING)
st.write("Locked Windows:", locked_windows)
st.write("Best Lock Round:", selected_lock_round)
st.write("Scan Range:", f"{lock_scan_start} -> {lock_scan_end}")
st.write("Lock Mode:", lock_mode)
st.write("Relock Rule Loss Streak:", f">= {PHASE_LOSS_STREAK_RELOCK}")
st.write("Relock Rule Stop Loss:", f"phase_group_profit <= {PHASE_STOP_LOSS}")
st.write("Relock Rule Stop Win:", f"phase_group_profit >= {PHASE_STOP_WIN}")
st.write("Relock Rule Max Trades:", f">= {MAX_PHASE_TRADES}")
st.write("Timeout Relock:", f"{TIMEOUT_RELOCK_ROUNDS} rounds if phase group profit <= 0")
st.write("Telegram Enabled:", telegram_enabled())
st.caption("Telegram: set BOT_TOKEN and CHAT_ID in Streamlit secrets for production.")

st.subheader("Profit Compare")

p1, p2, p3, p4 = st.columns(4)
p1.metric("Phase Group Profit", phase_profit_group)
p2.metric("Phase Color Profit", phase_profit_color)
p3.metric("Phase Total Profit", phase_profit_total)
p4.metric("Total Phase All", total_phase_profit_all)

st.subheader("Trade Stats")

phase_trades = int(hist["PHASE_BET"].sum()) if "PHASE_BET" in hist.columns else 0

phase_group_wr = (
    round(hist.loc[hist["PHASE_BET"], "phase_hit_group"].mean() * 100, 2)
    if phase_trades > 0
    else 0
)

color_hit_df = hist[(hist["PHASE_BET"] == True) & (hist["phase_hit_color"].notna())]
phase_color_wr = round(color_hit_df["phase_hit_color"].mean() * 100, 2) if len(color_hit_df) > 0 else 0

s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Trades", phase_trades)
s2.metric("Group WR %", phase_group_wr)
s3.metric("Color WR %", phase_color_wr)
s4.metric("Keep After Loss", KEEP_AFTER_LOSS_ROUNDS)

st.subheader("Profit Curve")

chart_cols = [
    "phase_profit_group",
    "phase_profit_color",
    "phase_profit_total",
    "total_phase_profit_all",
]

exist_chart_cols = [c for c in chart_cols if c in hist.columns]

if exist_chart_cols:
    st.line_chart(hist[exist_chart_cols].reset_index(drop=True))

# Hỗ trợ so sánh baseline/patched bằng cách tải history CSV ra ngoài
hist_csv = hist.to_csv(index=False).encode("utf-8")
phase_summary_csv = phase_summary_df.to_csv(index=False).encode("utf-8") if not phase_summary_df.empty else b""

dl1, dl2 = st.columns(2)
with dl1:
    st.download_button(
        "Download History CSV",
        data=hist_csv,
        file_name=f"history_{ACTIVE_PROFILE}.csv",
        mime="text/csv",
    )
with dl2:
    st.download_button(
        "Download Phase Summary CSV",
        data=phase_summary_csv,
        file_name=f"phase_summary_{ACTIVE_PROFILE}.csv",
        mime="text/csv",
    )

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
    "color",
    "vote_group",
    "confidence_group",
    "dominance_ratio",
    "dominance_ok",
    "signal_group",
    "phase_warmup_block",
    "max_phase_trades_block",
    "vote_color",
    "confidence_color",
    "signal_color",
    "PHASE_BET",
    "used_keep_phase",
    "phase_bet_group",
    "phase_bet_color",
    "phase_hit_group",
    "phase_hit_color",
    "phase_pnl_group",
    "phase_pnl_color",
    "phase_pnl_total",
    "phase_profit_group",
    "phase_profit_color",
    "phase_profit_total",
    "phase_consecutive_losses",
    "keep_phase_group",
    "keep_phase_color",
    "keep_phase_left",
    "last_phase_bet_was_loss",
    "recent_phase_pnl",
    "total_phase_profit_all",
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

# Telegram preview signal
if telegram_enabled() and phase_next_allowed and final_phase_group_next is not None:
    ready_msg = (
        f"READY PHASE BET\n"
        f"Profile: {ACTIVE_PROFILE}\n"
        f"Round: {current_round}\n"
        f"Current Number: {numbers[-1]}\n"
        f"Current Group: {groups[-1]}\n"
        f"Current Color: {color_text(colors[-1])}\n"
        f"Phase Bet Group: {final_phase_group_next}\n"
        f"Phase Bet Color: {color_text(final_phase_color_next)}\n"
        f"Used Keep Phase: {used_keep_phase_next}\n"
        f"Keep Phase Left: {keep_phase_left}\n"
        f"Group Vote Strength: {confidence_group}/{vote_required}\n"
        f"Color Vote Strength: {confidence_color}/{color_vote_required}\n"
        f"Recent Phase PNL (trades): {recent_phase_pnl_next}\n"
        f"Phase Group Profit: {phase_profit_group}\n"
        f"Phase Color Profit: {phase_profit_color}\n"
        f"Phase Total Profit: {phase_profit_total}\n"
        f"Total Phase Profit All: {total_phase_profit_all}\n"
        f"State: {next_state}"
    )
    send_signal_once("READY_PHASE_PATCHED", current_round, ready_msg)
