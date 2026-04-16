import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# Run group config
MIN_RUN_LEN = 2
MAX_RUN_LEN = 5

# Điều kiện pattern
MIN_SAMPLES = 3
MIN_PROB = 0.34

# Tín hiệu thực chiến
BET_PROB = 0.6
BET_SMALL_PROB = 0.48

# Risk control
PAUSE_AFTER_2_LOSSES = 0
GROUP_PROFIT_STOP = 8.0
GROUP_MAX_LOSS_STREAK = 20

# PnL
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

SHOW_HISTORY_ROWS = 120

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
        raise ValueError("Google Sheet phải có cột 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]
    return nums

numbers = load_numbers()

if len(numbers) < 20:
    st.error("Chưa đủ dữ liệu.")
    st.stop()

# ================= MAP GROUP =================
def group_of(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

groups = [group_of(x) for x in numbers]

# ================= HELPERS =================
def get_current_run(seq):
    if not seq:
        return None, 0
    last = seq[-1]
    run_len = 1
    i = len(seq) - 2
    while i >= 0 and seq[i] == last:
        run_len += 1
        i -= 1
    return last, run_len

def build_run_pattern_stats(seq, min_run_len=2, max_run_len=5):
    """
    Ví dụ:
    4,4 -> sau đó group nào xuất hiện
    3,3,3 -> sau đó group nào xuất hiện
    """
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

def get_run_signal(seq, min_run_len=2, max_run_len=5, min_samples=3, min_prob=0.34):
    if len(seq) < 10:
        return None, None

    stats = build_run_pattern_stats(seq, min_run_len, max_run_len)
    current_group, current_run_len = get_current_run(seq)
    capped_run = min(current_run_len, max_run_len)

    # ưu tiên run đúng độ dài hiện tại
    for rl in range(capped_run, min_run_len - 1, -1):
        key = (current_group, rl)
        if key in stats:
            cnt = stats[key]
            total = sum(cnt.values())

            if total >= min_samples:
                pred, c = cnt.most_common(1)[0]
                prob = c / total

                if prob >= min_prob:
                    ranked = cnt.most_common(2)
                    edge = 0.0
                    if len(ranked) > 1:
                        edge = ranked[0][1] / total - ranked[1][1] / total

                    signal = {
                        "run_group": current_group,
                        "run_len": rl,
                        "next_group": pred,
                        "samples": total,
                        "prob": round(prob, 4),
                        "edge": round(edge, 4),
                        "dist": dict(cnt),
                    }
                    return signal, stats

    return None, stats

# ================= STATE INIT =================
def init_state():
    defaults = {
        "processed_until": 0,
        "profit_group": 0.0,
        "hits_group": [],
        "history_rows": [],
        "pause_left": 0,
        "consecutive_losses": 0,
        "group_pause": False,
        "base_data_len": len(groups),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# reset nếu dữ liệu bị ngắn lại
if st.session_state.base_data_len is not None and len(groups) < st.session_state.base_data_len:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

if st.button("🔄 Reset Session"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ================= LIVE LOOP =================
processed_until = st.session_state.processed_until
profit_group = st.session_state.profit_group
hits_group = st.session_state.hits_group
history_rows = st.session_state.history_rows
pause_left = st.session_state.pause_left
consecutive_losses = st.session_state.consecutive_losses
group_pause = st.session_state.group_pause

for i in range(processed_until, len(groups) - 1):
    hist_seq = groups[:i + 1]
    real_next_group = groups[i + 1]

    current_group, current_run_len = get_current_run(hist_seq)
    signal, _stats = get_run_signal(
        hist_seq,
        MIN_RUN_LEN,
        MAX_RUN_LEN,
        MIN_SAMPLES,
        MIN_PROB
    )

    action = "WAIT"
    pred_group = None
    hit_group = None
    trade = False
    state = "WAIT"

    # stop nếu profit đủ
    if profit_group >= GROUP_PROFIT_STOP:
        group_pause = True

    if pause_left > 0:
        pause_left -= 1
        state = "PAUSE"
    elif group_pause:
        state = "GROUP_PAUSED"
    elif signal is not None:
        pred_group = int(signal["next_group"])
        prob = float(signal["prob"])

        # anti đu trend quá dài
        if current_run_len >= 5:
            prob -= 0.05

        if prob >= BET_PROB:
            action = "BET"
        elif prob >= BET_SMALL_PROB:
            action = "BET_SMALL"
        else:
            action = "WAIT"

        if action in ("BET", "BET_SMALL"):
            trade = True

            if pred_group == real_next_group:
                hit_group = 1
                profit_group += WIN_GROUP
                hits_group.append(1)
                consecutive_losses = 0
                state = action
            else:
                hit_group = 0
                profit_group += LOSS_GROUP
                hits_group.append(0)
                consecutive_losses += 1
                state = action

                if consecutive_losses >= 2:
                    pause_left = PAUSE_AFTER_2_LOSSES
                    consecutive_losses = 0
                    state = "PAUSE_TRIGGER"

                if len(hits_group) >= GROUP_MAX_LOSS_STREAK:
                    last_hits = hits_group[-GROUP_MAX_LOSS_STREAK:]
                    if sum(last_hits) == 0:
                        group_pause = True
                        state = "GROUP_PAUSE_LOSS"

    history_rows.append({
        "round": i + 1,
        "number": numbers[i],
        "group": groups[i],
        "next_real_group": real_next_group,
        "current_run_group": current_group,
        "current_run_len": current_run_len,
        "pred_group": pred_group,
        "trade": trade,
        "action": action,
        "hit_group": hit_group,
        "state": state,
        "profit_group": round(profit_group, 2),
        "pause_left": pause_left,
    })

    processed_until = i + 1

# save
st.session_state.processed_until = processed_until
st.session_state.profit_group = profit_group
st.session_state.hits_group = hits_group
st.session_state.history_rows = history_rows
st.session_state.pause_left = pause_left
st.session_state.consecutive_losses = consecutive_losses
st.session_state.group_pause = group_pause
st.session_state.base_data_len = len(groups)

hist_df = pd.DataFrame(history_rows)

# ================= NEXT SIGNAL =================
current_group, current_run_len = get_current_run(groups)
next_signal, stats = get_run_signal(
    groups,
    MIN_RUN_LEN,
    MAX_RUN_LEN,
    MIN_SAMPLES,
    MIN_PROB
)

next_group = None
next_prob = None
next_samples = None
next_edge = None
next_action = "WAIT"

if next_signal is not None:
    next_group = int(next_signal["next_group"])
    next_prob = float(next_signal["prob"])
    next_samples = int(next_signal["samples"])
    next_edge = float(next_signal["edge"])

    adj_prob = next_prob
    if current_run_len >= 5:
        adj_prob -= 0.05

    if pause_left > 0 or group_pause:
        next_action = "WAIT"
    elif adj_prob >= BET_PROB:
        next_action = "BET"
    elif adj_prob >= BET_SMALL_PROB:
        next_action = "BET_SMALL"
    else:
        next_action = "WAIT"

# ================= UI =================
st.title("🎯 RUN GROUP THỰC CHIẾN")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", current_group)
c3.metric("Run Length", current_run_len)
c4.metric("Next Action", next_action)

st.subheader("Next Signal")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Next Group", next_group if next_group is not None else "-")
s2.metric("Prob", round(next_prob, 4) if next_prob is not None else "-")
s3.metric("Samples", next_samples if next_samples is not None else "-")
s4.metric("Edge", round(next_edge, 4) if next_edge is not None else "-")

if group_pause:
    st.warning("⛔ GROUP PAUSED")
elif pause_left > 0:
    st.warning(f"⏸ PAUSE - nghỉ {pause_left} vòng")
elif next_action == "BET":
    st.error(f"🔥 BET FULL → GROUP {next_group}")
elif next_action == "BET_SMALL":
    st.warning(f"⚠️ BET SMALL → GROUP {next_group}")
else:
    st.info("WAIT")

st.subheader("Session Statistics")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Profit Group", round(profit_group, 2))
m2.metric("Trades", len(hits_group))
m3.metric("Winrate %", round(sum(hits_group) / len(hits_group) * 100, 2) if hits_group else 0)
m4.metric("Pause Left", pause_left)

st.subheader("Profit Curve")
if not hist_df.empty:
    st.line_chart(hist_df["profit_group"])

with st.expander("Run Pattern Stats"):
    if stats:
        rows = []
        for (run_group, run_len), cnt in stats.items():
            total = sum(cnt.values())
            top = cnt.most_common(1)[0]
            rows.append({
                "run_group": run_group,
                "run_len": run_len,
                "samples": total,
                "next_top1": top[0],
                "top1_count": top[1],
                "top1_prob": round(top[1] / total, 4),
                "dist": dict(cnt),
            })
        stats_df = pd.DataFrame(rows).sort_values(
            ["top1_prob", "samples", "run_len"],
            ascending=[False, False, False]
        )
        st.dataframe(stats_df, use_container_width=True)

st.subheader("History")
if not hist_df.empty:
    def highlight_row(row):
        if row["state"] == "BET":
            return ["background-color: #ff4b4b; color:white"] * len(row)
        if row["state"] == "BET_SMALL":
            return ["background-color: #ffb347; color:black"] * len(row)
        if row["state"] == "PAUSE":
            return ["background-color: #87ceeb; color:black"] * len(row)
        if row["state"] == "PAUSE_TRIGGER":
            return ["background-color: #9370db; color:white"] * len(row)
        if row["state"] in ("GROUP_PAUSED", "GROUP_PAUSE_LOSS"):
            return ["background-color: #d9534f; color:white"] * len(row)
        return [""] * len(row)

    st.dataframe(
        hist_df.iloc[::-1].head(SHOW_HISTORY_ROWS).style.apply(highlight_row, axis=1),
        use_container_width=True,
    )
