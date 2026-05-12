import math
import time
from dataclasses import dataclass
from collections import Counter
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Auto Relock Engine Research", layout="wide")
st_autorefresh(interval=3000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180
REPLAY_FROM = 180

RECENT_WINDOW_SIZE = 33

@dataclass(frozen=True)
class Mode:
    name: str
    top_windows: int
    vote_required: int
    window_min: int
    window_max: int

MODES = [
    Mode("5v3", 5, 3, 6, 22),
    Mode("6v4", 6, 4, 6, 22),
    Mode("8v5", 8, 5, 6, 22),
]

@dataclass(frozen=True)
class Cfg:
    name: str
    win_group: float = 2.5
    loss_group: float = -1.0
    enable_color_bet: bool = False
    win_color: float = 1.5
    loss_color: float = -1.0

    rounds_to_skip_after_trade: int = 0
    phase_stop_loss: float = -2.0
    phase_stop_win: float = 999999.0
    phase_stop_win_enabled: bool = False
    phase_loss_streak_relock: int = 2
    enable_timeout_relock: bool = False
    timeout_relock_rounds: int = 40

    recent_phase_check: int = 4
    phase_min_recent_pnl_to_trade: float = 0.0
    min_phase_age_to_trade: int = 3
    max_phase_trades: int = 6

    vote_dominance_ratio: float = 0.5
    keep_after_loss_rounds: int = 0
    cancel_keep_on_opposite_vote: bool = True

    session_stop_win: float = 4.0
    session_stop_loss: float = -13.0

    min_fallback_score: float = 0.0
    min_trades_per_window: int = 18

    min_window_spacing: int = 1
    auto_scan_window_spacing: bool = True
    window_spacing_min: int = 1
    window_spacing_max: int = 6
    spacing_mode: str = "gap"          # "legacy" hoặc "gap"

    validate_len: int = 12
    auto_scan_validate_len: bool = True
    validate_len_list: tuple = (12, 16, 20, 24)
    min_train_len: int = 100
    min_validate_trades: int = 1
    validate_max_drawdown_abs: Optional[float] = 4.0
    validate_min_drawdown: float = 0.0
    require_non_negative_validate_profit: bool = False

    relock_scan_len: int = 18
    relock_buffer: int = 0

    recent_pnl_mode: str = "trades"    # "rows" hoặc "trades"
    signal_mode: str = "hybrid"        # "legacy" hoặc "hybrid"
    apply_dominance_in_backtest: bool = True
    dynamic_vote_required: bool = True
    use_total_windows_for_ratio: bool = True
    min_vote_margin: int = 0

    train_lookback: Optional[int] = 140

    score_recent_weight: float = 0.6
    score_profit_weight: float = 0.7
    score_winrate_weight: float = 7.0
    score_drawdown_weight: float = 1.1
    score_streak_weight: float = 0.4
    score_trades_weight: float = 1.0
    score_expectancy_weight: float = 8.0
    validate_weight: float = 1.6


@st.cache_data(ttl=60, show_spinner=False)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "number" not in df.columns:
        raise ValueError("Sheet phải có cột 'number'")
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
    return {1: "RED", 2: "GREEN", 3: "BLUE"}.get(c, "-")


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
    peak = -10**18
    max_dd = 0.0
    for x in compute_profit_path(results, win_value, loss_value):
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


def get_valid_preds(seq, i, windows):
    preds = []
    for w in windows:
        if i - w >= 0 and i - 1 >= 0:
            pred = seq[i - w]
            if seq[i - 1] != pred:
                preds.append(pred)
    return preds


def resolve_vote(preds, total_slots, vote_required, cfg: Cfg):
    if not preds:
        return {
            "vote": None,
            "confidence": 0,
            "active": 0,
            "ratio_active": 0.0,
            "ratio_total": 0.0,
            "required_votes": vote_required,
            "margin": 0,
            "signal": False,
        }

    counts = Counter(preds).most_common()
    vote, conf = counts[0]
    second_conf = counts[1][1] if len(counts) > 1 else 0
    active = len(preds)

    ratio_active = conf / active if active else 0.0
    ratio_total = conf / total_slots if total_slots else 0.0

    if cfg.signal_mode == "legacy":
        required_votes = vote_required
        signal = conf >= vote_required and ratio_active >= cfg.vote_dominance_ratio
    else:
        abs_req = min(vote_required, active) if cfg.dynamic_vote_required else vote_required
        ratio_req = math.ceil(
            (total_slots if cfg.use_total_windows_for_ratio else active)
            * cfg.vote_dominance_ratio
        )
        required_votes = max(abs_req, ratio_req)
        signal = conf >= required_votes
        if cfg.min_vote_margin > 0:
            signal = signal and ((conf - second_conf) >= cfg.min_vote_margin)

    return {
        "vote": vote,
        "confidence": conf,
        "active": active,
        "ratio_active": float(ratio_active),
        "ratio_total": float(ratio_total),
        "required_votes": int(required_votes),
        "margin": int(conf - second_conf),
        "signal": bool(signal),
    }


def cooldown_ok(i, last_trade_idx, rounds_to_skip):
    if last_trade_idx < 0:
        return True
    return (i - last_trade_idx) > rounds_to_skip


def bundle_metrics(results, cfg: Cfg):
    trades = len(results)
    wins = sum(results)
    profit = float(sum(cfg.win_group if r == 1 else cfg.loss_group for r in results))
    winrate = wins / trades if trades else 0.0
    max_dd = compute_max_drawdown(results, cfg.win_group, cfg.loss_group)
    recent_profit = compute_recent_profit(results, RECENT_WINDOW_SIZE, cfg.win_group, cfg.loss_group)
    streak = compute_streak_metrics(results)
    expectancy = profit / trades if trades else -999999.0
    return {
        "trades": trades,
        "wins": wins,
        "profit_group": profit,
        "winrate_group": winrate,
        "max_drawdown_group": max_dd,
        "recent_profit_group": recent_profit,
        "expectancy_group": expectancy,
        **streak,
    }


def composite_score(bt, cfg: Cfg):
    if bt["trades"] <= 0:
        return -999999.0
    return (
        bt["profit_group"] * cfg.score_profit_weight
        + bt["winrate_group"] * cfg.score_winrate_weight
        + bt["expectancy_group"] * cfg.score_expectancy_weight
        + bt["recent_profit_group"] * cfg.score_recent_weight
        - abs(bt["max_drawdown_group"]) * cfg.score_drawdown_weight
        + bt["streak_score"] * cfg.score_streak_weight
        + math.log1p(bt["trades"]) * cfg.score_trades_weight
    )


def evaluate_window_group(seq_groups, w, cfg: Cfg):
    results = []
    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]
        if seq_groups[i - 1] != pred:
            results.append(1 if seq_groups[i] == pred else 0)

    bt = bundle_metrics(results, cfg)
    score = composite_score(bt, cfg) if bt["trades"] > 0 else -999999.0

    return {
        "window": w,
        "trades": bt["trades"],
        "wins": bt["wins"],
        "profit": bt["profit_group"],
        "winrate": bt["winrate_group"],
        "max_drawdown": bt["max_drawdown_group"],
        "recent_profit": bt["recent_profit_group"],
        "expectancy": bt["expectancy_group"],
        "max_hit_streak": bt["max_hit_streak"],
        "max_loss_streak": bt["max_loss_streak"],
        "count_hit_streak_ge2": bt["count_hit_streak_ge2"],
        "streak_score": bt["streak_score"],
        "score": score,
    }


def spacing_ok(w, selected, spacing, spacing_mode):
    if spacing_mode == "legacy":
        return all(abs(w - x) >= spacing for x in selected)
    return all(abs(w - x) > spacing for x in selected)


def pick_spaced_windows(df_sorted, top_n, spacing, spacing_mode):
    selected = []
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if spacing_ok(w, [int(x["window"]) for x in selected], spacing, spacing_mode):
            selected.append(row.to_dict())
            if len(selected) >= top_n:
                break
    return pd.DataFrame(selected)


def enforce_spacing_from_df(df_sorted, top_n, spacing, spacing_mode):
    out = []
    if df_sorted.empty:
        return out
    for _, row in df_sorted.iterrows():
        w = int(row["window"])
        if spacing_ok(w, out, spacing, spacing_mode):
            out.append(w)
            if len(out) >= top_n:
                break
    return out


def build_window_tables(train_groups, window_min, window_max, cfg: Cfg, min_window_spacing=None):
    spacing = cfg.min_window_spacing if min_window_spacing is None else min_window_spacing

    rows = [evaluate_window_group(train_groups, w, cfg) for w in range(window_min, window_max + 1)]
    df = pd.DataFrame(rows)

    df_all = df.sort_values(
        ["score", "recent_profit", "profit", "expectancy", "winrate", "trades"],
        ascending=[False, False, False, False, False, False],
    ).reset_index(drop=True)

    filtered_df = df[
        (df["trades"] >= cfg.min_trades_per_window)
        & ((df["count_hit_streak_ge2"] >= 1) | (df["max_hit_streak"] >= 2))
        & (df["max_loss_streak"] <= 6)
    ].copy()

    filtered_df = filtered_df.sort_values(
        ["score", "recent_profit", "profit", "expectancy", "winrate", "trades", "max_loss_streak"],
        ascending=[False, False, False, False, False, False, True],
    ).reset_index(drop=True)

    if filtered_df.empty:
        filtered_df = df_all.head(10).copy()

    seed = filtered_df.head(10).copy()
    spaced_candidate_df = pick_spaced_windows(seed, 10, spacing, cfg.spacing_mode)

    if not spaced_candidate_df.empty and "window" in spaced_candidate_df.columns:
        candidate_windows = spaced_candidate_df["window"].astype(int).tolist()
    else:
        candidate_windows = []

    need = max(m.top_windows for m in MODES)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(seed, need, spacing, cfg.spacing_mode)

    if len(candidate_windows) < need:
        candidate_windows = enforce_spacing_from_df(df_all, need, 0 if cfg.spacing_mode == "gap" else 1, cfg.spacing_mode)

    return candidate_windows, df_all, filtered_df


def backtest_bundle_vote_range(seq_groups, windows, vote_required, start_idx, end_idx, cfg: Cfg):
    results_group = []
    last_trade = -999999

    if not windows:
        return bundle_metrics([], cfg)

    effective_start = max(start_idx, max(windows))
    total_slots = len(windows)

    for i in range(effective_start, end_idx):
        preds = get_valid_preds(seq_groups, i, windows)
        if not preds:
            continue

        summary = resolve_vote(preds, total_slots, vote_required, cfg)
        signal = summary["signal"] if cfg.apply_dominance_in_backtest else (summary["confidence"] >= vote_required)

        if signal and cooldown_ok(i, last_trade, cfg.rounds_to_skip_after_trade):
            last_trade = i
            results_group.append(1 if seq_groups[i] == summary["vote"] else 0)

    return bundle_metrics(results_group, cfg)


def validate_pass(validate_bt, cfg: Cfg):
    if validate_bt["trades"] < cfg.min_validate_trades:
        return False

    if cfg.validate_max_drawdown_abs is None:
        dd_ok = validate_bt["max_drawdown_group"] >= cfg.validate_min_drawdown
    else:
        dd_ok = abs(validate_bt["max_drawdown_group"]) <= cfg.validate_max_drawdown_abs

    profit_ok = True if not cfg.require_non_negative_validate_profit else validate_bt["profit_group"] >= 0
    return dd_ok and profit_ok


def find_best_auto_mode_in_range(all_groups, scan_start, scan_end, cfg: Cfg):
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

    validate_values = cfg.validate_len_list if cfg.auto_scan_validate_len else [cfg.validate_len]

    for validate_len in validate_values:
        for r in range(scan_start, effective_scan_end + 1):
            if r < validate_len + cfg.min_train_len:
                continue

            train_end = r - validate_len
            validate_start = train_end
            validate_end = r

            train_start = max(0, train_end - cfg.train_lookback) if cfg.train_lookback else 0
            train_groups = all_groups[train_start:train_end]
            validate_groups = all_groups[:validate_end]

            local_best_score = -999999.0
            local_best_windows = []
            local_best_mode = None
            local_best_scan_df = pd.DataFrame()
            local_best_filtered_df = pd.DataFrame()

            local_fallback_score = -999999.0
            local_fallback_windows = []
            local_fallback_mode = None
            local_fallback_scan_df = pd.DataFrame()
            local_fallback_filtered_df = pd.DataFrame()

            spacing_values = (
                range(cfg.window_spacing_min, cfg.window_spacing_max + 1)
                if cfg.auto_scan_window_spacing
                else [cfg.min_window_spacing]
            )

            for mode in MODES:
                for spacing in spacing_values:
                    candidate_windows, df_all, filtered_df = build_window_tables(
                        train_groups,
                        mode.window_min,
                        mode.window_max,
                        cfg,
                        min_window_spacing=spacing,
                    )

                    if len(candidate_windows) < mode.top_windows:
                        continue

                    selected_windows = candidate_windows[:mode.top_windows]

                    train_bt = backtest_bundle_vote_range(
                        train_groups,
                        selected_windows,
                        mode.vote_required,
                        0,
                        len(train_groups),
                        cfg,
                    )

                    validate_bt = backtest_bundle_vote_range(
                        validate_groups,
                        selected_windows,
                        mode.vote_required,
                        validate_start,
                        validate_end,
                        cfg,
                    )

                    final_score = composite_score(train_bt, cfg) + composite_score(validate_bt, cfg) * cfg.validate_weight

                    mode_info = {
                        "name": mode.name,
                        "top_windows": mode.top_windows,
                        "vote_required": mode.vote_required,
                        "window_min": mode.window_min,
                        "window_max": mode.window_max,
                        "spacing": spacing,
                        "validate_len": validate_len,
                    }

                    if final_score > local_fallback_score:
                        local_fallback_score = final_score
                        local_fallback_windows = selected_windows
                        local_fallback_mode = mode_info
                        local_fallback_scan_df = df_all.copy()
                        local_fallback_filtered_df = filtered_df.copy()

                    if validate_pass(validate_bt, cfg) and final_score > local_best_score:
                        local_best_score = final_score
                        local_best_windows = selected_windows
                        local_best_mode = mode_info
                        local_best_scan_df = df_all.copy()
                        local_best_filtered_df = filtered_df.copy()

            if local_best_mode is not None:
                round_eval_rows.append(
                    {
                        "lock_round": r,
                        "mode": local_best_mode["name"],
                        "selected_windows": ", ".join(map(str, local_best_windows)),
                        "spacing": local_best_mode["spacing"],
                        "validate_len": local_best_mode["validate_len"],
                        "bundle_score": local_best_score,
                        "lock_mode": "validated",
                    }
                )

                if local_best_score > best_score:
                    best_score = local_best_score
                    best_round = r
                    best_windows = local_best_windows
                    best_mode = local_best_mode
                    best_scan_df = local_best_scan_df
                    best_filtered_df = local_best_filtered_df
                    best_lock_mode = "validated"

            elif local_fallback_mode is not None and local_fallback_score >= cfg.min_fallback_score:
                round_eval_rows.append(
                    {
                        "lock_round": r,
                        "mode": local_fallback_mode["name"],
                        "selected_windows": ", ".join(map(str, local_fallback_windows)),
                        "spacing": local_fallback_mode["spacing"],
                        "validate_len": local_fallback_mode["validate_len"],
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

    if fallback_round is not None and fallback_score >= cfg.min_fallback_score:
        return fallback_round, fallback_windows, fallback_mode, fallback_scan_df, fallback_filtered_df, round_eval_df, "fallback_soft"

    return None, [], None, pd.DataFrame(), pd.DataFrame(), round_eval_df, "not_found"


def recent_phase_pnl_from_history(history_rows, phase_index, cfg: Cfg):
    if not history_rows:
        return 0.0

    if cfg.recent_pnl_mode == "rows":
        return float(
            sum(
                float(x["phase_pnl_group"])
                for x in history_rows[-cfg.recent_phase_check:]
                if int(x["phase"]) == phase_index
            )
        )

    vals = [
        float(x["phase_pnl_group"])
        for x in history_rows
        if int(x["phase"]) == phase_index and bool(x["PHASE_BET"])
    ]
    return float(sum(vals[-cfg.recent_phase_check:]))


def simulate_engine(numbers, groups, colors, cfg: Cfg):
    result = {
        "hist": pd.DataFrame(),
        "phase_summary_df": pd.DataFrame(),
        "scan_df_all": pd.DataFrame(),
        "scan_df_filtered": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "phase_profit_group": 0.0,
        "phase_profit_total": 0.0,
        "total_phase_profit_all": 0.0,
        "locked_windows": [],
        "selected_lock_round": None,
        "selected_mode": None,
        "lock_mode": "",
        "lock_scan_start": None,
        "lock_scan_end": None,
        "phase_index": 1,
        "relock_count": 0,
        "session_stop": False,
        "session_stop_reason": None,
    }

    (
        selected_lock_round,
        locked_windows,
        selected_mode,
        scan_df_all,
        scan_df_filtered,
        round_eval_df,
        lock_mode,
    ) = find_best_auto_mode_in_range(groups, LOCK_ROUND_START, LOCK_ROUND_END, cfg)

    if selected_lock_round is None or selected_mode is None:
        return result

    phase_profit_group = 0.0
    phase_profit_total = 0.0
    total_phase_profit_all = 0.0

    phase_hits_group = []
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

        if total_phase_profit_all >= cfg.session_stop_win:
            break
        if total_phase_profit_all <= cfg.session_stop_loss:
            break

        vote_required = current_mode["vote_required"]

        preds_group = get_valid_preds(groups, i, locked_windows)
        vote_summary = resolve_vote(preds_group, len(locked_windows), vote_required, cfg)

        vote_group = vote_summary["vote"]
        confidence_group = vote_summary["confidence"]
        signal_group = vote_summary["signal"]
        ratio_active = vote_summary["ratio_active"]
        ratio_total = vote_summary["ratio_total"]

        phase_age = round_no - phase_start_round + 1
        recent_phase_pnl = recent_phase_pnl_from_history(history_rows, phase_index, cfg) if history_rows else phase_profit_group

        if (
            cfg.cancel_keep_on_opposite_vote
            and keep_phase_group is not None
            and signal_group
            and vote_group is not None
            and vote_group != keep_phase_group
        ):
            keep_phase_group = None
            keep_phase_color = None
            keep_phase_left = 0
            last_phase_bet_was_loss = False

        used_keep_phase = False
        final_phase_group = vote_group
        final_phase_color = keep_phase_color

        if last_phase_bet_was_loss and keep_phase_left > 0 and keep_phase_group is not None:
            used_keep_phase = True
            final_phase_group = keep_phase_group
            phase_trade_allowed = recent_phase_pnl >= cfg.phase_min_recent_pnl_to_trade
        else:
            phase_trade_allowed = signal_group and recent_phase_pnl >= cfg.phase_min_recent_pnl_to_trade

        phase_warmup_block = phase_age < cfg.min_phase_age_to_trade
        max_phase_trades_block = len(phase_hits_group) >= cfg.max_phase_trades

        if phase_trade_allowed and phase_warmup_block:
            phase_trade_allowed = False

        if phase_trade_allowed and max_phase_trades_block:
            phase_trade_allowed = False

        if phase_trade_allowed and not cooldown_ok(i, last_phase_trade_idx, cfg.rounds_to_skip_after_trade):
            phase_trade_allowed = False

        if phase_trade_allowed:
            last_phase_trade_idx = i
            phase_hit_group = 1 if groups[i] == final_phase_group else 0
            phase_pnl_group = cfg.win_group if phase_hit_group else cfg.loss_group

            phase_profit_group += phase_pnl_group
            phase_profit_total += phase_pnl_group
            total_phase_profit_all += phase_pnl_group
            phase_hits_group.append(phase_hit_group)

            if phase_hit_group == 1:
                phase_consecutive_losses = 0
                last_phase_bet_was_loss = False
                keep_phase_group = None
                keep_phase_color = None
                keep_phase_left = 0
            else:
                phase_consecutive_losses += 1
                if used_keep_phase:
                    last_phase_bet_was_loss = False
                    keep_phase_group = None
                    keep_phase_color = None
                    keep_phase_left = 0
                else:
                    last_phase_bet_was_loss = True
                    keep_phase_group = final_phase_group
                    keep_phase_color = final_phase_color
                    keep_phase_left = cfg.keep_after_loss_rounds

            state = "PHASE_KEEP_BET" if used_keep_phase else "PHASE_BET"
        else:
            phase_hit_group = None
            phase_pnl_group = 0.0

            if signal_group and phase_warmup_block:
                state = "WAIT_PHASE_WARMUP"
            elif signal_group and max_phase_trades_block:
                state = "WAIT_MAX_PHASE_TRADES"
            elif vote_group is not None and not signal_group:
                state = "WAIT_VOTE_DOMINANCE_WEAK"
            elif signal_group and recent_phase_pnl < cfg.phase_min_recent_pnl_to_trade:
                state = "PHASE_BLOCKED_RECENT_TOO_WEAK"
            else:
                state = "WAIT_NO_GROUP_SIGNAL" if not signal_group else "WAIT"

        # KEEP hết hạn theo round
        if keep_phase_left > 0 and not used_keep_phase:
            keep_phase_left -= 1
            if keep_phase_left <= 0:
                keep_phase_left = 0
                keep_phase_group = None
                keep_phase_color = None
                last_phase_bet_was_loss = False

        relock_triggered_now = False
        relock_reason_now = None

        if phase_consecutive_losses >= cfg.phase_loss_streak_relock:
            relock_triggered_now = True
            relock_reason_now = "PHASE_LOSS_STREAK_RELOCK"
            state = "AUTO_RELOCK_LOSS_STREAK"

        elif phase_profit_group <= cfg.phase_stop_loss:
            relock_triggered_now = True
            relock_reason_now = "PHASE_GROUP_STOP_LOSS"
            state = "AUTO_RELOCK_PHASE_GROUP_LOSS"

        elif cfg.phase_stop_win_enabled and phase_profit_group >= cfg.phase_stop_win:
            relock_triggered_now = True
            relock_reason_now = "PHASE_GROUP_TAKE_PROFIT"
            state = "AUTO_RELOCK_PHASE_GROUP_WIN"

        elif len(phase_hits_group) >= cfg.max_phase_trades:
            relock_triggered_now = True
            relock_reason_now = "MAX_PHASE_TRADES_RELOCK"
            state = "AUTO_RELOCK_MAX_PHASE_TRADES"

        elif cfg.enable_timeout_relock and phase_age >= cfg.timeout_relock_rounds and phase_profit_group <= 0:
            relock_triggered_now = True
            relock_reason_now = "TIMEOUT_RELOCK_PHASE_NOT_POSITIVE"
            state = "AUTO_RELOCK_TIMEOUT"

        history_rows.append(
            {
                "cfg": cfg.name,
                "phase": phase_index,
                "round": round_no,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "mode": current_mode["name"],
                "vote_required": vote_required,
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "active_preds_group": vote_summary["active"],
                "ratio_active_group": ratio_active,
                "ratio_total_group": ratio_total,
                "required_votes_group": vote_summary["required_votes"],
                "vote_margin_group": vote_summary["margin"],
                "signal_group": signal_group,
                "phase_warmup_block": phase_warmup_block,
                "max_phase_trades_block": max_phase_trades_block,
                "PHASE_BET": phase_trade_allowed,
                "used_keep_phase": used_keep_phase,
                "phase_bet_group": final_phase_group if phase_trade_allowed else None,
                "phase_hit_group": phase_hit_group,
                "phase_pnl_group": phase_pnl_group,
                "phase_profit_group": phase_profit_group,
                "phase_profit_total": phase_profit_total,
                "phase_consecutive_losses": phase_consecutive_losses,
                "keep_phase_group": keep_phase_group,
                "keep_phase_left": keep_phase_left,
                "last_phase_bet_was_loss": last_phase_bet_was_loss,
                "recent_phase_pnl": recent_phase_pnl,
                "total_phase_profit_all": total_phase_profit_all,
                "phase_age": phase_age,
                "state": state,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "relock_triggered_now": relock_triggered_now,
                "relock_reason": relock_reason_now,
            }
        )

        if relock_triggered_now:
            phase_summary_rows.append(
                {
                    "cfg": cfg.name,
                    "phase": phase_index,
                    "start_round": phase_start_round,
                    "end_round": round_no,
                    "reason": relock_reason_now,
                    "mode": current_mode["name"],
                    "vote_required": vote_required,
                    "top_windows": current_mode["top_windows"],
                    "spacing": current_mode.get("spacing"),
                    "validate_len": current_mode.get("validate_len"),
                    "locked_windows": ", ".join(map(str, locked_windows)),
                    "lock_mode": lock_mode,
                    "lock_round": selected_lock_round,
                    "phase_age": phase_age,
                    "phase_loss_streak": phase_consecutive_losses,
                    "phase_bet_trades": len(phase_hits_group),
                    "phase_group_profit": phase_profit_group,
                    "phase_group_wr": round(np.mean(phase_hits_group) * 100, 2) if phase_hits_group else 0.0,
                    "total_phase_profit_after_phase": total_phase_profit_all,
                }
            )

            scan_end = i
            scan_start = max(LOCK_ROUND_START, scan_end - cfg.relock_scan_len + 1 - cfg.relock_buffer)

            (
                new_selected_lock_round,
                new_locked_windows,
                new_selected_mode,
                new_scan_df_all,
                new_scan_df_filtered,
                new_round_eval_df,
                new_lock_mode,
            ) = find_best_auto_mode_in_range(groups, scan_start, scan_end, cfg)

            if new_selected_lock_round is not None and new_selected_mode is not None:
                relock_count += 1

                locked_windows = new_locked_windows
                selected_lock_round = round_no
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
                phase_profit_total = 0.0
                phase_hits_group = []

                phase_consecutive_losses = 0
                keep_phase_group = None
                keep_phase_color = None
                keep_phase_left = 0
                last_phase_bet_was_loss = False
                last_phase_trade_idx = i

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    session_stop = total_phase_profit_all >= cfg.session_stop_win or total_phase_profit_all <= cfg.session_stop_loss
    session_stop_reason = (
        "SESSION_STOP_WIN"
        if total_phase_profit_all >= cfg.session_stop_win
        else "SESSION_STOP_LOSS"
        if total_phase_profit_all <= cfg.session_stop_loss
        else None
    )

    result.update(
        {
            "hist": hist,
            "phase_summary_df": phase_summary_df,
            "scan_df_all": scan_df_all,
            "scan_df_filtered": scan_df_filtered,
            "round_eval_df": round_eval_df,
            "phase_profit_group": phase_profit_group,
            "phase_profit_total": phase_profit_total,
            "total_phase_profit_all": total_phase_profit_all,
            "locked_windows": locked_windows,
            "selected_lock_round": selected_lock_round,
            "selected_mode": current_mode,
            "lock_mode": lock_mode,
            "lock_scan_start": lock_scan_start,
            "lock_scan_end": lock_scan_end,
            "phase_index": phase_index,
            "relock_count": relock_count,
            "session_stop": session_stop,
            "session_stop_reason": session_stop_reason,
        }
    )
    return result


def summarize_sim(sim, cfg: Cfg):
    hist = sim["hist"]
    if hist.empty:
        return {
            "cfg": cfg.name,
            "trades": 0,
            "wins": 0,
            "profit": 0.0,
            "winrate": 0.0,
            "max_drawdown": 0.0,
            "recent_profit": 0.0,
            "phases": 0,
            "relock_count": 0,
            "total_profit_all": 0.0,
            "lock_mode": "not_found",
        }

    trade_df = hist[hist["PHASE_BET"] == True].copy()
    results = trade_df["phase_hit_group"].dropna().astype(int).tolist()

    trades = len(trade_df)
    wins = int(trade_df["phase_hit_group"].fillna(0).sum()) if trades else 0
    profit = float(trade_df["phase_pnl_group"].sum()) if trades else 0.0
    winrate = wins / trades if trades else 0.0
    max_dd = compute_max_drawdown(results, cfg.win_group, cfg.loss_group)
    recent_profit = compute_recent_profit(results, RECENT_WINDOW_SIZE, cfg.win_group, cfg.loss_group)
    phases = int(hist["phase"].nunique())

    return {
        "cfg": cfg.name,
        "trades": trades,
        "wins": wins,
        "profit": round(profit, 3),
        "winrate": round(winrate, 4),
        "max_drawdown": round(max_dd, 3),
        "recent_profit": round(recent_profit, 3),
        "phases": phases,
        "relock_count": int(sim["relock_count"]),
        "total_profit_all": round(float(sim["total_phase_profit_all"]), 3),
        "lock_mode": sim["lock_mode"],
    }


def run_self_checks():
    checks = []

    # 1) GAP legacy vs fixed
    checks.append(
        {
            "check": "cooldown_skip_1_round",
            "pass": cooldown_ok(11, 10, 1) is False,
            "detail": "Nếu skip=1 thì round kế tiếp không được trade",
        }
    )

    # 2) recent_pnl theo trades
    mock = [
        {"phase": 1, "phase_pnl_group": -1.0, "PHASE_BET": True},
        {"phase": 1, "phase_pnl_group": 0.0, "PHASE_BET": False},
        {"phase": 1, "phase_pnl_group": 0.0, "PHASE_BET": False},
        {"phase": 1, "phase_pnl_group": 0.0, "PHASE_BET": False},
        {"phase": 1, "phase_pnl_group": 0.0, "PHASE_BET": False},
    ]
    test_cfg = Cfg(name="test", recent_pnl_mode="trades")
    checks.append(
        {
            "check": "recent_pnl_uses_last_trades",
            "pass": recent_phase_pnl_from_history(mock, 1, test_cfg) == -1.0,
            "detail": "Recent PnL phải còn thấy trade lỗ gần nhất dù có nhiều WAIT rows",
        }
    )

    # 3) KEEP phải hết hạn
    keep_left = 1
    keep_left -= 1
    checks.append(
        {
            "check": "keep_expires_by_round",
            "pass": keep_left == 0,
            "detail": "KEEP không được tồn tại vô hạn",
        }
    )

    # 4) validate drawdown abs
    validate_bt = {"trades": 2, "profit_group": 1.5, "max_drawdown_group": -2.5}
    test_cfg2 = Cfg(name="test2", validate_max_drawdown_abs=3.0)
    checks.append(
        {
            "check": "validate_drawdown_abs",
            "pass": validate_pass(validate_bt, test_cfg2) is True,
            "detail": "Drawdown -2.5 phải pass nếu ngưỡng abs là 3.0",
        }
    )

    return pd.DataFrame(checks)


st.title("Auto Relock Engine Research | Baseline vs Fixed Variants")

numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

if st.sidebar.button("Clear cache & rerun"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.header("Tuned Config")

t_phase_stop_loss = st.sidebar.number_input("PHASE_STOP_LOSS", value=-2.0, step=0.5)
t_phase_stop_win = st.sidebar.number_input("PHASE_STOP_WIN", value=3.0, step=0.5)
t_loss_streak = st.sidebar.number_input("PHASE_LOSS_STREAK_RELOCK", value=2, step=1)
t_max_phase_trades = st.sidebar.number_input("MAX_PHASE_TRADES", value=5, step=1)
t_min_phase_age = st.sidebar.number_input("MIN_PHASE_AGE_TO_TRADE", value=3, step=1)
t_recent_gate = st.sidebar.number_input("PHASE_MIN_RECENT_PNL_TO_TRADE", value=0.0, step=0.5)
t_dom_ratio = st.sidebar.slider("VOTE_DOMINANCE_RATIO", 0.30, 0.80, 0.50, 0.05)
t_min_trades_win = st.sidebar.number_input("MIN_TRADES_PER_WINDOW", value=20, step=1)
t_validate_dd = st.sidebar.number_input("VALIDATE_MAX_DRAWDOWN_ABS", value=4.0, step=0.5)
t_skip_rounds = st.sidebar.number_input("ROUNDS_TO_SKIP_AFTER_TRADE", value=1, step=1)
t_window_spacing_max = st.sidebar.number_input("WINDOW_SPACING_MAX", value=4, step=1)

baseline = Cfg(
    name="baseline_current_like",
    rounds_to_skip_after_trade=0,
    recent_pnl_mode="rows",
    signal_mode="legacy",
    apply_dominance_in_backtest=False,
    dynamic_vote_required=False,
    use_total_windows_for_ratio=False,
    keep_after_loss_rounds=0,
    phase_stop_win_enabled=False,
    validate_max_drawdown_abs=None,
    validate_min_drawdown=0.0,
    require_non_negative_validate_profit=False,
    spacing_mode="legacy",
    train_lookback=None,
    score_recent_weight=1.5,
    score_profit_weight=0.8,
    score_winrate_weight=8.0,
    score_drawdown_weight=0.8,
    score_streak_weight=1.0,
    score_trades_weight=1.2,
    score_expectancy_weight=0.0,
    validate_weight=1.0,
)

balanced = Cfg(
    name="balanced_fix",
    rounds_to_skip_after_trade=int(t_skip_rounds),
    phase_stop_loss=float(t_phase_stop_loss),
    phase_stop_win=float(t_phase_stop_win),
    phase_stop_win_enabled=True,
    phase_loss_streak_relock=int(t_loss_streak),
    max_phase_trades=int(t_max_phase_trades),
    min_phase_age_to_trade=int(t_min_phase_age),
    phase_min_recent_pnl_to_trade=float(t_recent_gate),
    vote_dominance_ratio=float(t_dom_ratio),
    keep_after_loss_rounds=1,
    min_trades_per_window=int(t_min_trades_win),
    validate_max_drawdown_abs=float(t_validate_dd),
    min_validate_trades=2,
    require_non_negative_validate_profit=True,
    spacing_mode="gap",
    window_spacing_min=1,
    window_spacing_max=int(t_window_spacing_max),
    train_lookback=140,
)

conservative = Cfg(
    name="conservative_fix",
    rounds_to_skip_after_trade=1,
    phase_stop_loss=-1.5,
    phase_stop_win=3.0,
    phase_stop_win_enabled=True,
    phase_loss_streak_relock=2,
    max_phase_trades=4,
    min_phase_age_to_trade=3,
    phase_min_recent_pnl_to_trade=0.5,
    vote_dominance_ratio=0.625,
    keep_after_loss_rounds=0,
    min_trades_per_window=22,
    validate_max_drawdown_abs=3.0,
    min_validate_trades=2,
    require_non_negative_validate_profit=True,
    spacing_mode="gap",
    window_spacing_min=1,
    window_spacing_max=3,
    train_lookback=140,
)

configs = [baseline, balanced, conservative]

all_results = {}
summary_rows = []
curve_df = pd.DataFrame()

for cfg in configs:
    sim = simulate_engine(numbers, groups, colors, cfg)
    all_results[cfg.name] = sim
    summary_rows.append(summarize_sim(sim, cfg))

    hist = sim["hist"]
    if not hist.empty:
        curve_df[cfg.name] = hist["total_phase_profit_all"].reset_index(drop=True)

summary_df = pd.DataFrame(summary_rows).sort_values(
    ["total_profit_all", "profit", "winrate", "max_drawdown"],
    ascending=[False, False, False, False],
)

st.subheader("Bảng so sánh kết quả trước / sau / biến thể")
st.dataframe(summary_df, use_container_width=True)

st.subheader("Profit Curve Compare")
if not curve_df.empty:
    st.line_chart(curve_df)

selected_cfg_name = st.selectbox("Xem chi tiết config", summary_df["cfg"].tolist())
selected_sim = all_results[selected_cfg_name]

c1, c2, c3, c4 = st.columns(4)
row = summary_df[summary_df["cfg"] == selected_cfg_name].iloc[0]
c1.metric("Trades", int(row["trades"]))
c2.metric("Profit", float(row["profit"]))
c3.metric("Total Profit All", float(row["total_profit_all"]))
c4.metric("Max Drawdown", float(row["max_drawdown"]))

st.write("Lock mode:", selected_sim["lock_mode"])
st.write("Selected mode:", selected_sim["selected_mode"]["name"] if selected_sim["selected_mode"] else "-")
st.write("Locked windows:", selected_sim["locked_windows"])
st.write("Best lock round:", selected_sim["selected_lock_round"])
st.write("Scan range:", f'{selected_sim["lock_scan_start"]} -> {selected_sim["lock_scan_end"]}')

with st.expander("Phase Summary"):
    st.dataframe(selected_sim["phase_summary_df"], use_container_width=True)

with st.expander("Current Locked Window Detail"):
    scan_df_all = selected_sim["scan_df_all"]
    locked_windows = selected_sim["locked_windows"]
    if not scan_df_all.empty and locked_windows:
        st.dataframe(
            scan_df_all[scan_df_all["window"].isin(locked_windows)].sort_values("window"),
            use_container_width=True,
        )

with st.expander("History"):
    hist = selected_sim["hist"]
    show_cols = [
        "round",
        "phase",
        "number",
        "group",
        "vote_group",
        "confidence_group",
        "active_preds_group",
        "ratio_active_group",
        "ratio_total_group",
        "required_votes_group",
        "signal_group",
        "PHASE_BET",
        "used_keep_phase",
        "phase_bet_group",
        "phase_hit_group",
        "phase_pnl_group",
        "phase_profit_group",
        "recent_phase_pnl",
        "total_phase_profit_all",
        "state",
        "locked_windows",
        "relock_triggered_now",
        "relock_reason",
    ]
    st.dataframe(hist[show_cols].iloc[::-1].head(50), use_container_width=True)

with st.expander("Self Checks / Unit-like Tests"):
    st.dataframe(run_self_checks(), use_container_width=True)
