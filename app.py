import time
from collections import Counter

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1500, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# Bắt đầu scan từ đây, nếu đủ điều kiện thì lock luôn
LOCK_ROUND_START = 144
LOCK_SCAN_END = 180  # chỉ để tham chiếu, không bắt buộc phải đợi tới đây nữa

WINDOW_MIN = 6
WINDOW_MAX = 26

TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3
VOTE_REQUIRED = 3
GAP = 1

# Group PnL
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

# Color PnL
WIN_COLOR = 1.5
LOSS_COLOR = -1.0

KEEP_AFTER_LOSS_ROUNDS = 2
PAUSE_AFTER_2_LOSSES = 0
MIN_TRADES_PER_WINDOW = 30

# Pause group nếu:
GROUP_MAX_LOSS_STREAK = 3   # thua 3 lệnh group liên tiếp
GROUP_PROFIT_STOP = 6.0     # profit group >= 6

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


def color_of(n: int) -> str:
    if n <= 4:
        return "red"
    if n <= 8:
        return "green"
    return "blue"


groups = [group_of(n) for n in numbers]
colors = [color_of(n) for n in numbers]

# ================= GUARD =================
if len(groups) < LOCK_ROUND_START:
    st.error(
        f"Chưa đủ dữ liệu để bắt đầu scan lock. "
        f"Cần ít nhất {LOCK_ROUND_START} rounds, hiện có {len(groups)}."
    )
    st.stop()

# ================= WINDOW EVAL =================
def evaluate_window_group(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0

    n = len(seq_groups)
    for i in range(w, n):
        pred = seq_groups[i - w]

        # Giữ nguyên logic gốc
        if seq_groups[i - 1] != pred:
            trades += 1
            if seq_groups[i] == pred:
                profit += WIN_GROUP
                wins += 1
            else:
                profit += LOSS_GROUP

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
    rows = [evaluate_window_group(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
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

    selected_df = positive_df.head(TOP_WINDOWS).copy()

    if len(positive_df) >= MIN_POSITIVE_WINDOWS and len(selected_df) < TOP_WINDOWS:
        selected_windows = set(selected_df["window"].tolist()) if not selected_df.empty else set()

        remain_df = df[~df["window"].isin(selected_windows)].copy()
        remain_df = remain_df.sort_values(
            ["score", "profit", "winrate", "trades"],
            ascending=[False, False, False, False]
        ).reset_index(drop=True)

        need = TOP_WINDOWS - len(selected_df)
        if need > 0 and len(remain_df) > 0:
            selected_df = pd.concat([selected_df, remain_df.head(need)], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected_df = selected_df.sort_values(
        ["score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    selected = selected_df["window"].astype(int).tolist() if not selected_df.empty else []

    return selected, df_all, positive_df, selected_df


def find_first_lock_round(all_groups):
    """
    Scan từ round 168 trở đi.
    Hễ có ít nhất 3 window profit dương là lock luôn tại round đó.
    Không đợi tới 180.
    """
    best_round = None
    best_windows = []
    best_scan_all = pd.DataFrame()
    best_positive = pd.DataFrame()
    best_selected = pd.DataFrame()
    round_eval_rows = []

    scan_end = len(all_groups)

    for r in range(LOCK_ROUND_START, scan_end + 1):
        train_groups = all_groups[:r]
        tmp_windows, tmp_all, tmp_positive, tmp_selected = build_window_tables(train_groups)

        pos_count = len(tmp_positive)

        round_eval_rows.append(
            {
                "lock_round": r,
                "positive_windows": pos_count,
                "selected_count": len(tmp_selected),
                "selected_windows": ", ".join(map(str, tmp_windows)),
                "lock_now": pos_count >= MIN_POSITIVE_WINDOWS,
            }
        )

        if pos_count >= MIN_POSITIVE_WINDOWS and not tmp_selected.empty:
            best_round = r
            best_windows = tmp_windows
            best_scan_all = tmp_all
            best_positive = tmp_positive
            best_selected = tmp_selected
            break

    round_eval_df = pd.DataFrame(round_eval_rows)

    return (
        best_round,
        best_windows,
        best_scan_all,
        best_positive,
        best_selected,
        round_eval_df,
    )

# ================= STATE INIT =================
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,

        # Group
        "total_profit_group": 0.0,
        "last_trade": -999,
        "hits_group": [],

        # Color
        "total_profit_color": 0.0,
        "hits_color": [],

        # History
        "history_rows": [],

        # Lock fixed
        "locked_windows": [],
        "scan_df_all": pd.DataFrame(),
        "scan_df_positive": pd.DataFrame(),
        "scan_df_selected": pd.DataFrame(),
        "round_eval_df": pd.DataFrame(),
        "lock_round_used": None,

        "base_data_len": None,

        # Keep / pause
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "consecutive_losses": 0,
        "pause_rounds_left": 0,

        # Pause group riêng
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

if (
    st.session_state.base_data_len is not None
    and len(groups) < st.session_state.base_data_len
):
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
        round_eval_df,
    ) = find_first_lock_round(groups)

    if lock_round_used is None:
        st.error(
            f"Chưa tìm được round lock từ {LOCK_ROUND_START} trở đi "
            f"có ít nhất {MIN_POSITIVE_WINDOWS} window profit dương."
        )
        st.stop()

    st.session_state.locked_windows = locked_windows
    st.session_state.scan_df_all = scan_df_all
    st.session_state.scan_df_positive = scan_df_positive
    st.session_state.scan_df_selected = scan_df_selected
    st.session_state.round_eval_df = round_eval_df
    st.session_state.lock_round_used = lock_round_used
    st.session_state.processed_until = lock_round_used - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ================= LOAD LOCAL STATE =================
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
round_eval_df = st.session_state.round_eval_df
lock_round_used = st.session_state.lock_round_used
processed_until = st.session_state.processed_until

keep_bet_group = st.session_state.keep_bet_group
keep_rounds_left = st.session_state.keep_rounds_left
last_trade_was_loss = st.session_state.last_trade_was_loss
consecutive_losses = st.session_state.consecutive_losses
pause_rounds_left = st.session_state.pause_rounds_left

group_consecutive_losses = st.session_state.group_consecutive_losses
group_pause = st.session_state.group_pause

# ================= MAIN LOOP =================
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

    new_signal = confidence_group >= VOTE_REQUIRED
    distance = i - last_trade

    final_vote_group = vote_group
    used_keep = False
    trade = False
    can_bet = False
    hit_group = None
    hit_color = None
    state = "WAIT"

    # profit group >= +6 thì dừng bet group vĩnh viễn trong session
    if total_profit_group >= GROUP_PROFIT_STOP:
        group_pause = True

    # pause do thua 2 lệnh liên tiếp
    if pause_rounds_left > 0:
        pause_rounds_left -= 1
        state = "PAUSE"

        history_rows.append(
            {
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "color": colors[i],
                "vote_group": vote_group,
                "vote_color": vote_color,
                "confidence_group": confidence_group,
                "confidence_color": confidence_color,
                "new_signal": new_signal,
                "used_keep": False,
                "keep_group": None,
                "keep_left": 0,
                "final_vote_group": final_vote_group,
                "final_vote_color": vote_color,
                "signal": False,
                "trade": False,
                "bet_group": None,
                "bet_color": None,
                "hit_group": None,
                "hit_color": None,
                "state": state,
                "total_profit_group": total_profit_group,
                "total_profit_color": total_profit_color,
                "locked_windows": ", ".join(map(str, locked_windows)),
                "consecutive_losses": consecutive_losses,
                "pause_left": pause_rounds_left,
                "group_consecutive_losses": group_consecutive_losses,
                "group_pause": group_pause,
            }
        )
        processed_until = i
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

    # block group trade nếu group_pause
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
    bet_color = vote_color if can_bet else None

    if used_keep:
        keep_rounds_left -= 1
        if keep_rounds_left < 0:
            keep_rounds_left = 0

    if trade:
        last_trade = i

        # ===== GROUP =====
        if groups[i] == final_vote_group:
            hit_group = 1
            total_profit_group += WIN_GROUP
            hits_group.append(1)

            last_trade_was_loss = False
            keep_rounds_left = 0
            keep_bet_group = None
            consecutive_losses = 0
            group_consecutive_losses = 0

            if total_profit_group >= GROUP_PROFIT_STOP:
                group_pause = True
                state = "GROUP_PAUSE_PROFIT"

        else:
            hit_group = 0
            total_profit_group += LOSS_GROUP
            hits_group.append(0)

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

            # thua 2 lệnh liên tiếp => nghỉ 4 vòng
            if consecutive_losses >= 2:
                pause_rounds_left = PAUSE_AFTER_2_LOSSES
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False
                consecutive_losses = 0
                state = "PAUSE_TRIGGER"

            # group thua 3 lệnh liên tiếp => dừng bet group
            if group_consecutive_losses >= GROUP_MAX_LOSS_STREAK:
                group_pause = True
                keep_rounds_left = 0
                keep_bet_group = None
                last_trade_was_loss = False
                state = "GROUP_PAUSE_LOSS"

        # ===== COLOR =====
        if colors[i] == vote_color:
            hit_color = 1
            total_profit_color += WIN_COLOR
            hits_color.append(1)
        else:
            hit_color = 0
            total_profit_color += LOSS_COLOR
            hits_color.append(0)

    else:
        if used_keep and keep_rounds_left <= 0:
            keep_rounds_left = 0
            keep_bet_group = None
            last_trade_was_loss = False

    history_rows.append(
        {
            "round": i,
            "number": numbers[i],
            "group": groups[i],
            "color": colors[i],
            "vote_group": vote_group,
            "vote_color": vote_color,
            "confidence_group": confidence_group,
            "confidence_color": confidence_color,
            "new_signal": new_signal,
            "used_keep": used_keep,
            "keep_group": keep_bet_group,
            "keep_left": keep_rounds_left,
            "final_vote_group": final_vote_group,
            "final_vote_color": vote_color,
            "signal": final_signal,
            "trade": trade,
            "bet_group": bet_group,
            "bet_color": bet_color,
            "hit_group": hit_group,
            "hit_color": hit_color,
            "state": state,
            "total_profit_group": total_profit_group,
            "total_profit_color": total_profit_color,
            "locked_windows": ", ".join(map(str, locked_windows)),
            "consecutive_losses": consecutive_losses,
            "pause_left": pause_rounds_left,
            "group_consecutive_losses": group_consecutive_losses,
            "group_pause": group_pause,
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
st.session_state.round_eval_df = round_eval_df
st.session_state.lock_round_used = lock_round_used
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)

st.session_state.keep_bet_group = keep_bet_group
st.session_state.keep_rounds_left = keep_rounds_left
st.session_state.last_trade_was_loss = last_trade_was_loss
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

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None
current_color = colors[-1] if colors else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

new_signal = confidence_group >= VOTE_REQUIRED if vote_group is not None else False
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
    can_bet = (not group_pause) and signal and distance >= GAP

    if group_pause:
        next_state = "GROUP_PAUSED"
    else:
        next_state = "NEXT_KEEP" if (used_keep_next and can_bet) else "NEXT"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "color": current_color,
    "vote_group": vote_group,
    "vote_color": vote_color,
    "confidence_group": confidence_group,
    "confidence_color": confidence_color,
    "new_signal": new_signal,
    "used_keep": used_keep_next,
    "keep_group": next_keep_bet_group,
    "keep_left": next_keep_rounds_left,
    "final_vote_group": final_vote_group,
    "final_vote_color": vote_color,
    "signal": signal,
    "trade": False,
    "bet_group": final_vote_group if can_bet else None,
    "bet_color": vote_color if can_bet else None,
    "hit_group": None,
    "hit_color": None,
    "state": next_state,
    "total_profit_group": total_profit_group,
    "total_profit_color": total_profit_color,
    "locked_windows": ", ".join(map(str, locked_windows)),
    "consecutive_losses": consecutive_losses,
    "pause_left": pause_rounds_left,
    "group_consecutive_losses": group_consecutive_losses,
    "group_pause": group_pause,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= UI =================
st.title("🎯 Rolling Engine - lock ngay khi đủ 3 window profit dương")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Current Color", current_color if current_color is not None else "-")
col4.metric("Lock Round Used", lock_round_used if lock_round_used is not None else "-")

st.divider()
st.write("Vote Strength Group:", confidence_group)
st.write("Vote Strength Color:", confidence_color)
st.write("Next Group:", final_vote_group)
st.write("Next Color:", vote_color)
st.write("Locked Windows:", locked_windows)
st.write("Locked Window Count:", len(locked_windows))
st.write("Scan Start Round:", LOCK_ROUND_START)
st.write("Reference End Round:", LOCK_SCAN_END)
st.write("Need Positive Windows >=", MIN_POSITIVE_WINDOWS)
st.write("Min Trades / Window:", MIN_TRADES_PER_WINDOW)
st.write("Group Profit Stop:", GROUP_PROFIT_STOP)
st.write("Group Loss Streak Stop:", GROUP_MAX_LOSS_STREAK)
st.write("Keep Bet Group:", keep_bet_group)
st.write("Keep Rounds Left:", keep_rounds_left)
st.write("Consecutive Losses:", consecutive_losses)
st.write("Pause Rounds Left:", pause_rounds_left)
st.write("Group Consecutive Losses:", group_consecutive_losses)
st.write("Group Pause:", group_pause)
st.write("Processed Until:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT GROUP → {final_vote_group if final_vote_group is not None else "-"} | NEXT COLOR → {vote_color if vote_color is not None else "-"}
    </div>
    """,
    unsafe_allow_html=True,
)

if group_pause:
    st.warning("⛔ GROUP PAUSED (thua 3 liên tiếp hoặc profit group >= +6)")
elif pause_rounds_left > 0:
    st.warning(f"⏸ PAUSE - Đang nghỉ {pause_rounds_left} vòng do thua 2 lệnh liên tiếp")
elif can_bet and final_vote_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:25px;border-radius:10px;text-align:center;font-size:32px;color:white;font-weight:bold;">
        BET GROUP → {final_vote_group} | BET COLOR → {vote_color}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT (conditions not met)")

# ================= SESSION STATS =================
st.subheader("Session Statistics")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit Group", total_profit_group)
s2.metric("Trades Group", len(hits_group))
s3.metric("Winrate Group %", round(np.mean(hits_group) * 100, 2) if hits_group else 0)
s4.metric("Pause Left", pause_rounds_left)

s5, s6, s7 = st.columns(3)
s5.metric("Total Profit Color", total_profit_color)
s6.metric("Trades Color", len(hits_color))
s7.metric("Winrate Color %", round(np.mean(hits_color) * 100, 2) if hits_color else 0)

# ================= CHARTS =================
st.subheader("Profit Curve - Total Group")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_group"])

st.subheader("Profit Curve - Total Color")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit_color"])

# ================= DEBUG TABLES =================
st.subheader("Round Evaluation")
st.dataframe(round_eval_df, use_container_width=True)

st.subheader("Window Scan All")
st.dataframe(scan_df_all, use_container_width=True)

st.subheader("All Positive Windows")
st.dataframe(scan_df_positive, use_container_width=True)

st.subheader("Locked Windows")
st.dataframe(scan_df_selected, use_container_width=True)

# ================= HISTORY =================
st.subheader("History")

def highlight_trade(row):
    if row["state"] in ("NEXT", "NEXT_KEEP"):
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "TRADE_KEEP":
        return ["background-color: #ffb347; color:black"] * len(row)
    if row["state"] == "PAUSE":
        return ["background-color: #87ceeb; color:black"] * len(row)
    if row["state"] == "PAUSE_TRIGGER":
        return ["background-color: #9370db; color:white"] * len(row)
    if row["state"] in ("GROUP_PAUSED", "GROUP_PAUSE_PROFIT", "GROUP_PAUSE_LOSS"):
        return ["background-color: #696969; color:white"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

st.write("Total Rows:", len(numbers))
