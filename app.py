import time
from collections import Counter

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= REFRESH =================
st_autorefresh(interval=8000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 180

MODES = [
    {"name": "5v4", "top_windows": 5, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "6v4", "top_windows": 6, "vote_required": 4, "window_min": 6, "window_max": 22},
    {"name": "8v5", "top_windows": 8, "vote_required": 5, "window_min": 6, "window_max": 22},
]

GAP = 1
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PHASE_STOP_WIN = 3.5
PHASE_STOP_LOSS = -2.0
SESSION_STOP_WIN = 40.0
SESSION_STOP_LOSS = -10.0

KEEP_AFTER_LOSS_ROUNDS = 2

MIN_TRADES_PER_WINDOW = 12
RECENT_WINDOW_SIZE = 20
MIN_WINDOW_SPACING = 2
MAX_CANDIDATE_WINDOWS = 8

VALIDATE_LEN = 20
MIN_TRAIN_LEN = 120
MIN_VALIDATE_TRADES = 2
VALIDATE_MIN_DRAWDOWN = -6.0

RELOCK_SCAN_LEN = 8
RELOCK_BUFFER = 0

REPLAY_FROM = 180
SHOW_HISTORY_ROWS = 40

# ================= TELEGRAM =================
DEFAULT_BOT_TOKEN = "PASTE_NEW_TOKEN_HERE"
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = DEFAULT_BOT_TOKEN
CHAT_ID = DEFAULT_CHAT_ID


def telegram_enabled() -> bool:
    return bool(BOT_TOKEN and CHAT_ID and BOT_TOKEN != "PASTE_NEW_TOKEN_HERE")


def send_telegram(msg: str) -> bool:
    if not telegram_enabled():
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=5,
        )
        return resp.ok
    except Exception:
        return False


def init_notification_state():
    if "last_status_sent_key" not in st.session_state:
        st.session_state.last_status_sent_key = ""


def send_status_once(status_key: str, msg: str):
    if st.session_state.last_status_sent_key != status_key:
        ok = send_telegram(msg)
        if ok:
            st.session_state.last_status_sent_key = status_key


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
        raise ValueError("Sheet must contain column 'number'")
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    df = df.dropna(subset=["number"]).copy()
    df["number"] = df["number"].astype(int)
    df["round"] = np.arange(1, len(df) + 1)
    return df


sheet_df = load_numbers()
numbers = sheet_df["number"].tolist()


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


def backtest_bundle_vote_range(seq_groups, windows, vote_required, start_idx, end_idx):
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
        "streak_score": streak_metrics["streak_score"],
    }


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

    score = -999999.0
    if trades > 0:
        score = (
            profit
            + winrate * 8.0
            + np.log(trades + 1) * 1.2
            + recent_profit * 0.8
            - abs(max_drawdown) * 0.7
            + streak_metrics["streak_score"] * 1.2
        )

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

        for mode in MODES:
            top_windows = mode["top_windows"]
            vote_required = mode["vote_required"]

            candidate_windows, df_all, filtered_df = build_window_tables(
                train_groups, mode["window_min"], mode["window_max"]
            )
            if len(candidate_windows) < top_windows:
                continue

            selected_windows = candidate_windows[:top_windows]

            train_bt = backtest_bundle_vote_range(train_groups, selected_windows, vote_required, 0, len(train_groups))
            validate_bt = backtest_bundle_vote_range(validate_groups, selected_windows, vote_required, validate_start, validate_end)

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

    round_eval_df = pd.DataFrame(round_eval_rows)
    return best_round, best_windows, best_mode, best_scan_df, best_filtered_df, round_eval_df, best_lock_mode


def simulate_engine(numbers, groups):
    result = {
        "hist": pd.DataFrame(),
        "phase_profit_group": 0.0,
        "phase_hits_group": [],
        "total_profit_all_phase": 0.0,
        "total_hits_all_phase": [],
        "locked_windows": [],
        "selected_lock_round": None,
        "selected_mode": None,
        "lock_mode": "",
        "round_eval_df": pd.DataFrame(),
        "lock_scan_start": None,
        "lock_scan_end": None,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "phase_loss_streak": 0,
        "last_trade": -999,
        "phase_index": 1,
    }

    selected_lock_round, locked_windows, selected_mode, _, _, round_eval_df, lock_mode = find_best_auto_mode_in_range(
        groups, LOCK_ROUND_START, LOCK_ROUND_END
    )

    if selected_lock_round is None or selected_mode is None:
        return result

    phase_profit_group = 0.0
    phase_hits_group = []
    total_profit_all_phase = 0.0
    total_hits_all_phase = []
    last_trade = -999
    keep_bet_group = None
    keep_rounds_left = 0
    last_trade_was_loss = False
    phase_loss_streak = 0
    phase_index = 1
    history_rows = []

    start_replay = max(LOCK_ROUND_END + 1, REPLAY_FROM + 1)
    current_mode = selected_mode

    for i in range(start_replay, len(groups)):
        if total_profit_all_phase >= SESSION_STOP_WIN or total_profit_all_phase <= SESSION_STOP_LOSS:
            break

        preds_group = [groups[i - w] for w in locked_windows if i - w >= 0]
        if not preds_group:
            continue

        vote_required = current_mode["vote_required"]
        vote_group, confidence_group = Counter(preds_group).most_common(1)[0]
        new_signal = confidence_group >= vote_required
        distance = i - last_trade

        final_vote_group = vote_group
        used_keep = False
        trade = False
        hit_group = None
        state = "WAIT"

        if new_signal:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False
        elif last_trade_was_loss and keep_rounds_left > 0 and keep_bet_group is not None:
            final_vote_group = keep_bet_group
            used_keep = True

        final_signal = new_signal or used_keep
        trade = final_signal and distance >= GAP

        if trade:
            last_trade = i
            if groups[i] == final_vote_group:
                hit_group = 1
                phase_profit_group += WIN_GROUP
                total_profit_all_phase += WIN_GROUP
                phase_hits_group.append(1)
                total_hits_all_phase.append(1)
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False
                phase_loss_streak = 0
                state = "TRADE"
            else:
                hit_group = 0
                phase_profit_group += LOSS_GROUP
                total_profit_all_phase += LOSS_GROUP
                phase_hits_group.append(0)
                total_hits_all_phase.append(0)
                keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                keep_bet_group = final_vote_group
                last_trade_was_loss = True
                phase_loss_streak += 1
                state = "TRADE"
        else:
            if used_keep:
                keep_rounds_left = max(0, keep_rounds_left - 1)
                state = "KEEP_WAIT"

        history_rows.append(
            {
                "phase": phase_index,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "mode": current_mode["name"],
                "vote_required": current_mode["vote_required"],
                "top_windows": current_mode["top_windows"],
                "vote_group": vote_group,
                "confidence_group": confidence_group,
                "signal": final_signal,
                "trade": trade,
                "state": state,
                "phase_profit_group": phase_profit_group,
                "total_profit_all_phase": total_profit_all_phase,
            }
        )

    result.update(
        {
            "hist": pd.DataFrame(history_rows),
            "phase_profit_group": phase_profit_group,
            "phase_hits_group": phase_hits_group,
            "total_profit_all_phase": total_profit_all_phase,
            "total_hits_all_phase": total_hits_all_phase,
            "locked_windows": locked_windows,
            "selected_lock_round": selected_lock_round,
            "selected_mode": selected_mode,
            "lock_mode": lock_mode,
            "round_eval_df": round_eval_df,
            "lock_scan_start": LOCK_ROUND_START,
            "lock_scan_end": LOCK_ROUND_END,
            "keep_bet_group": keep_bet_group,
            "keep_rounds_left": keep_rounds_left,
            "last_trade_was_loss": last_trade_was_loss,
            "phase_loss_streak": phase_loss_streak,
            "last_trade": last_trade,
            "phase_index": phase_index,
        }
    )
    return result


# ================= RUN =================
sim = simulate_engine(numbers, groups)

hist = sim["hist"]
phase_profit_group = sim["phase_profit_group"]
total_profit_all_phase = sim["total_profit_all_phase"]
locked_windows = sim["locked_windows"]
selected_lock_round = sim["selected_lock_round"]
selected_mode = sim["selected_mode"]
lock_mode = sim["lock_mode"]

# ================= CURRENT STATUS =================
current_round = int(sheet_df["round"].iloc[-1])
current_number = int(sheet_df["number"].iloc[-1])
current_group = group_of(current_number)

next_round = len(groups)
preds_group = [groups[next_round - w] for w in locked_windows if i - w >= 0] if locked_windows else []

if preds_group and selected_mode is not None:
    predicted_group, confidence_group = Counter(preds_group).most_common(1)[0]
    vote_required = selected_mode["vote_required"]
    ready = confidence_group >= vote_required
else:
    predicted_group, confidence_group = None, 0
    vote_required = 0
    ready = False

status_text = "READY" if ready else "WAIT"

# ================= TELEGRAM: READY / WAIT ONLY =================
init_notification_state()

if telegram_enabled():
    status_key = (
        f"{status_text}|round={current_round}|number={current_number}|group={current_group}|"
        f"pred={predicted_group}|mode={selected_mode['name'] if selected_mode else '-'}|"
        f"strength={confidence_group}|phase={phase_profit_group}|total={total_profit_all_phase}"
    )

    msg = (
        f"STATUS: {status_text}\n"
        f"Current Round: {current_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Predicted Group: {predicted_group if predicted_group is not None else '-'}\n"
        f"Mode: {selected_mode['name'] if selected_mode else '-'}\n"
        f"Vote Strength: {confidence_group}\n"
        f"Phase Profit: {phase_profit_group}\n"
        f"Total Profit: {total_profit_all_phase}\n"
        f"Lock Round: {selected_lock_round}\n"
        f"Lock Mode: {lock_mode}"
    )
    send_status_once(status_key, msg)

# ================= UI =================
st.title("📡 Status Engine | Google Sheet + Telegram")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Round", current_round)
c2.metric("Current Number", current_number)
c3.metric("Current Group", current_group)
c4.metric("Status", status_text)

st.write("Predicted Group:", predicted_group if predicted_group is not None else "-")
st.write("Selected Mode:", selected_mode["name"] if selected_mode else "-")
st.write("Vote Strength:", confidence_group)
st.write("Vote Required:", vote_required)
st.write("Lock Round:", selected_lock_round)
st.write("Lock Mode:", lock_mode)
st.write("Locked Windows:", locked_windows)
st.write("Telegram Enabled:", telegram_enabled())

if status_text == "READY":
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:22px;border-radius:10px;text-align:center;font-size:30px;color:white;font-weight:bold;">
        READY → {predicted_group} | MODE → {selected_mode["name"] if selected_mode else "-"}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT")

s1, s2, s3 = st.columns(3)
s1.metric("Phase Profit", phase_profit_group)
s2.metric("Total Profit", total_profit_all_phase)
s3.metric("Trades", len(sim["total_hits_all_phase"]))

st.subheader("History")
history_view = hist.iloc[::-1].head(SHOW_HISTORY_ROWS).copy() if not hist.empty else pd.DataFrame()
st.dataframe(history_view, use_container_width=True)
