import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=2000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# Live starts here
LIVE_START = 168

# Run config
MIN_RUN_LEN = 2
MAX_RUN_LEN = 5

# Pattern quality
MIN_SAMPLES = 5
MIN_PROB = 0.38
MIN_EDGE = 0.08

# Trading thresholds
BET_PROB = 0.62
BET_SMALL_PROB = 0.50

# Risk / execution
GAP = 2
PAUSE_AFTER_2_LOSSES = 3
GROUP_PROFIT_STOP = 8.0
GROUP_MAX_LOSS_STREAK = 5

# Regime filter
REGIME_LOOKBACK = 12
REGIME_MIN_TRADES = 4
REGIME_MIN_WR = 0.34

# PnL
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

SHOW_HISTORY_ROWS = 150

# ================= LOAD DATA =================
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Google Sheet phải có cột 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    return [x for x in nums if 1 <= x <= 12]

numbers = load_numbers()

if len(numbers) < LIVE_START + 5:
    st.error(f"Cần ít nhất {LIVE_START + 5} dòng dữ liệu.")
    st.stop()

# ================= MAP =================
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

def build_run_stats(seq, min_run_len=2, max_run_len=5):
    stats = defaultdict(Counter)
    i = 0
    n = len(seq)

    while i < n:
        g = seq[i]
        j = i
        while j < n and seq[j] == g:
            j += 1

        run_len = j - i

        if j < n:
            next_g = seq[j]
            for rl in range(min_run_len, min(run_len, max_run_len) + 1):
                stats[(g, rl)][next_g] += 1

        i = j

    return stats

def get_signal(seq):
    """
    Trả về tín hiệu tốt nhất cho current run:
    (group hiện tại, run_len hiện tại) -> next group
    """
    if len(seq) < 20:
        return None, None

    stats = build_run_stats(seq, MIN_RUN_LEN, MAX_RUN_LEN)
    g, run_len = get_current_run(seq)

    capped_len = min(run_len, MAX_RUN_LEN)

    for rl in range(capped_len, MIN_RUN_LEN - 1, -1):
        key = (g, rl)
        if key in stats:
            cnt = stats[key]
            total = sum(cnt.values())

            if total < MIN_SAMPLES:
                continue

            ranked = cnt.most_common()
            pred, top1 = ranked[0]
            prob = top1 / total

            edge = 0.0
            if len(ranked) > 1:
                edge = top1 / total - ranked[1][1] / total
            else:
                edge = top1 / total

            if prob >= MIN_PROB and edge >= MIN_EDGE:
                return {
                    "run_group": g,
                    "run_len": rl,
                    "next_group": pred,
                    "samples": total,
                    "prob": prob,
                    "edge": edge,
                    "dist": dict(cnt),
                }, stats

    return None, stats

def calc_recent_regime_from_hits(hits, lookback=12):
    if not hits:
        return {
            "recent_trades": 0,
            "recent_wr": 0.0,
            "regime_ok": False,
        }

    tail = hits[-lookback:]
    trades = len(tail)
    wr = sum(tail) / trades if trades > 0 else 0.0

    regime_ok = trades >= REGIME_MIN_TRADES and wr >= REGIME_MIN_WR

    return {
        "recent_trades": trades,
        "recent_wr": wr,
        "regime_ok": regime_ok,
    }

# ================= STATE =================
def init_state():
    defaults = {
        "processed_until": LIVE_START,
        "profit": 0.0,
        "hits": [],
        "pause": 0,
        "loss_streak": 0,
        "group_pause": False,
        "history": [],
        "last_trade_round": -999999,
        "base_data_len": len(groups),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# reset khi data ngắn lại
if st.session_state.base_data_len is not None and len(groups) < st.session_state.base_data_len:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

if st.button("🔄 RESET"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ================= LOAD STATE =================
profit = st.session_state.profit
hits = st.session_state.hits
pause = st.session_state.pause
loss_streak = st.session_state.loss_streak
group_pause = st.session_state.group_pause
hist = st.session_state.history
processed = st.session_state.processed_until
last_trade_round = st.session_state.last_trade_round

# ================= LIVE LOOP =================
for i in range(processed, len(groups) - 1):
    if i < LIVE_START:
        continue

    seq = groups[:i + 1]
    real_next_group = groups[i + 1]

    current_group, current_run_len = get_current_run(seq)
    signal, _stats = get_signal(seq)

    regime = calc_recent_regime_from_hits(hits, REGIME_LOOKBACK)

    action = "WAIT"
    pred_group = None
    hit = None
    trade = False
    state = "WAIT"
    signal_prob = None
    signal_samples = None
    signal_edge = None

    # hard stop
    if profit >= GROUP_PROFIT_STOP:
        group_pause = True

    if pause > 0:
        pause -= 1
        state = "PAUSE"

    elif group_pause:
        state = "STOP"

    elif signal is not None:
        pred_group = int(signal["next_group"])
        signal_prob = float(signal["prob"])
        signal_samples = int(signal["samples"])
        signal_edge = float(signal["edge"])

        adj_prob = signal_prob

        # penalty nếu run quá dài, tránh đu trend muộn
        if current_run_len >= 5:
            adj_prob -= 0.05
        elif current_run_len >= 4:
            adj_prob -= 0.02

        # regime yếu thì giảm xác suất hiệu lực
        if not regime["regime_ok"]:
            adj_prob -= 0.06

        # rules vào lệnh
        if (
            current_run_len >= MIN_RUN_LEN
            and signal_samples >= MIN_SAMPLES
            and (i - last_trade_round) >= GAP
        ):
            if adj_prob >= BET_PROB:
                action = "BET"
            elif adj_prob >= BET_SMALL_PROB and regime["regime_ok"]:
                action = "BET_SMALL"

        if action in ("BET", "BET_SMALL"):
            trade = True
            last_trade_round = i

            if pred_group == real_next_group:
                hit = 1
                profit += WIN_GROUP
                hits.append(1)
                loss_streak = 0
                state = action
            else:
                hit = 0
                profit += LOSS_GROUP
                hits.append(0)
                loss_streak += 1
                state = action

                if loss_streak >= 2:
                    pause = PAUSE_AFTER_2_LOSSES
                    loss_streak = 0
                    state = "PAUSE_TRIGGER"

                # nếu 5 lệnh gần nhất toàn thua thì stop
                if len(hits) >= GROUP_MAX_LOSS_STREAK:
                    last_hits = hits[-GROUP_MAX_LOSS_STREAK:]
                    if sum(last_hits) == 0:
                        group_pause = True
                        state = "STOP_BAD_STREAK"

    hist.append({
        "round": i,
        "group": groups[i],
        "next_real_group": real_next_group,
        "current_run_group": current_group,
        "current_run_len": current_run_len,
        "pred_group": pred_group,
        "signal_prob": round(signal_prob, 4) if signal_prob is not None else None,
        "signal_samples": signal_samples,
        "signal_edge": round(signal_edge, 4) if signal_edge is not None else None,
        "recent_wr": round(regime["recent_wr"], 4),
        "recent_trades": regime["recent_trades"],
        "regime_ok": regime["regime_ok"],
        "trade": trade,
        "action": action,
        "hit": hit,
        "state": state,
        "profit": round(profit, 2),
        "pause": pause,
    })

    processed = i + 1

# ================= SAVE =================
st.session_state.processed_until = processed
st.session_state.profit = profit
st.session_state.hits = hits
st.session_state.pause = pause
st.session_state.loss_streak = loss_streak
st.session_state.group_pause = group_pause
st.session_state.history = hist
st.session_state.last_trade_round = last_trade_round
st.session_state.base_data_len = len(groups)

df = pd.DataFrame(hist)

# ================= NEXT SIGNAL =================
current_group, current_run_len = get_current_run(groups)
next_signal, stats = get_signal(groups)
regime = calc_recent_regime_from_hits(hits, REGIME_LOOKBACK)

next_group = None
next_prob = None
next_samples = None
next_edge = None
next_action = "WAIT"

if next_signal:
    next_group = int(next_signal["next_group"])
    next_prob = float(next_signal["prob"])
    next_samples = int(next_signal["samples"])
    next_edge = float(next_signal["edge"])

    adj_prob = next_prob

    if current_run_len >= 5:
        adj_prob -= 0.05
    elif current_run_len >= 4:
        adj_prob -= 0.02

    if not regime["regime_ok"]:
        adj_prob -= 0.06

    if pause > 0 or group_pause:
        next_action = "WAIT"
    elif (len(groups) - 1 - last_trade_round) < GAP:
        next_action = "WAIT"
    elif adj_prob >= BET_PROB:
        next_action = "BET"
    elif adj_prob >= BET_SMALL_PROB and regime["regime_ok"]:
        next_action = "BET_SMALL"
    else:
        next_action = "WAIT"

# ================= UI =================
st.title("🎯 RUN GROUP LIVE CHUẨN")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Group", current_group)
c2.metric("Run Length", current_run_len)
c3.metric("Next Group", next_group if next_group is not None else "-")
c4.metric("Next Action", next_action)

st.write("Live trading from round:", LIVE_START)
st.write("Pause:", pause)
st.write("Last trade round:", last_trade_round)
st.write("Recent regime WR:", round(regime["recent_wr"] * 100, 2))
st.write("Recent regime trades:", regime["recent_trades"])
st.write("Regime OK:", regime["regime_ok"])
st.write("Signal Prob:", round(next_prob, 4) if next_prob is not None else "-")
st.write("Signal Samples:", next_samples if next_samples is not None else "-")
st.write("Signal Edge:", round(next_edge, 4) if next_edge is not None else "-")

if group_pause:
    st.error("STOP GROUP")
elif pause > 0:
    st.warning("PAUSE")
elif next_action == "BET":
    st.error(f"BET {next_group}")
elif next_action == "BET_SMALL":
    st.warning(f"BET SMALL {next_group}")
else:
    st.info("WAIT")

st.subheader("Stats")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Profit", round(profit, 2))
s2.metric("Trades", len(hits))
s3.metric("Winrate %", round(sum(hits) / len(hits) * 100, 2) if hits else 0)
s4.metric("Loss Streak", loss_streak)

st.subheader("Profit Curve (Live only)")
if not df.empty:
    st.line_chart(df["profit"])

with st.expander("Run Pattern Stats"):
    if stats:
        rows = []
        for (run_group, run_len), cnt in stats.items():
            total = sum(cnt.values())
            top = cnt.most_common(1)[0]
            ranked = cnt.most_common(2)
            edge = 0.0
            if len(ranked) > 1:
                edge = ranked[0][1] / total - ranked[1][1] / total
            else:
                edge = ranked[0][1] / total
            rows.append({
                "run_group": run_group,
                "run_len": run_len,
                "samples": total,
                "next_top1": top[0],
                "top1_count": top[1],
                "top1_prob": round(top[1] / total, 4),
                "edge": round(edge, 4),
                "dist": dict(cnt),
            })
        stats_df = pd.DataFrame(rows).sort_values(
            ["top1_prob", "edge", "samples", "run_len"],
            ascending=[False, False, False, False]
        )
        st.dataframe(stats_df, use_container_width=True)

st.subheader("History")
if not df.empty:
    def highlight_row(row):
        if row["state"] == "BET":
            return ["background-color: #ff4b4b; color:white"] * len(row)
        if row["state"] == "BET_SMALL":
            return ["background-color: #ffb347; color:black"] * len(row)
        if row["state"] == "PAUSE":
            return ["background-color: #87ceeb; color:black"] * len(row)
        if row["state"] == "PAUSE_TRIGGER":
            return ["background-color: #9370db; color:white"] * len(row)
        if row["state"] in ("STOP", "STOP_BAD_STREAK"):
            return ["background-color: #d9534f; color:white"] * len(row)
        return [""] * len(row)

    st.dataframe(
        df.iloc[::-1].head(SHOW_HISTORY_ROWS).style.apply(highlight_row, axis=1),
        use_container_width=True,
    )
