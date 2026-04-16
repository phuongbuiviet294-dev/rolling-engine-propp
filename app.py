import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=2000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LIVE_START = 168   # 🔥 CHỈ TRADE TỪ ĐÂY

MIN_RUN_LEN = 2
MAX_RUN_LEN = 5

MIN_SAMPLES = 3
MIN_PROB = 0.34

BET_PROB = 0.55
BET_SMALL_PROB = 0.42

PAUSE_AFTER_2_LOSSES = 2
GROUP_PROFIT_STOP = 8.0
GROUP_MAX_LOSS_STREAK = 6

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

SHOW_HISTORY_ROWS = 120

# ================= LOAD DATA =================
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet cần cột 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    return [x for x in nums if 1 <= x <= 12]

numbers = load_numbers()

if len(numbers) < LIVE_START + 5:
    st.error(f"Cần ít nhất {LIVE_START + 5} dòng dữ liệu")
    st.stop()

# ================= MAP =================
def group_of(n):
    if n <= 3: return 1
    if n <= 6: return 2
    if n <= 9: return 3
    return 4

groups = [group_of(x) for x in numbers]

# ================= RUN DETECT =================
def get_current_run(seq):
    last = seq[-1]
    run_len = 1
    i = len(seq) - 2
    while i >= 0 and seq[i] == last:
        run_len += 1
        i -= 1
    return last, run_len

def build_run_stats(seq):
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
            for rl in range(MIN_RUN_LEN, min(run_len, MAX_RUN_LEN) + 1):
                stats[(g, rl)][next_g] += 1

        i = j

    return stats

def get_signal(seq):
    stats = build_run_stats(seq)
    g, run_len = get_current_run(seq)

    for rl in range(min(run_len, MAX_RUN_LEN), MIN_RUN_LEN - 1, -1):
        key = (g, rl)
        if key in stats:
            cnt = stats[key]
            total = sum(cnt.values())

            if total >= MIN_SAMPLES:
                pred, c = cnt.most_common(1)[0]
                prob = c / total

                if prob >= MIN_PROB:
                    return {
                        "next": pred,
                        "prob": prob,
                        "samples": total
                    }

    return None

# ================= STATE =================
def init_state():
    defaults = {
        "processed_until": LIVE_START,
        "profit": 0.0,
        "hits": [],
        "pause": 0,
        "loss_streak": 0,
        "group_pause": False,
        "history": []
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# reset
if st.button("RESET"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

# ================= LOAD STATE =================
p = st.session_state.profit
hits = st.session_state.hits
pause = st.session_state.pause
loss_streak = st.session_state.loss_streak
group_pause = st.session_state.group_pause
hist = st.session_state.history
processed = st.session_state.processed_until

# ================= LIVE LOOP =================
for i in range(processed, len(groups) - 1):

    if i < LIVE_START:
        continue

    seq = groups[:i + 1]
    real = groups[i + 1]

    g, run_len = get_current_run(seq)
    signal = get_signal(seq)

    action = "WAIT"
    pred = None
    trade = False
    hit = None

    # STOP PROFIT
    if p >= GROUP_PROFIT_STOP:
        group_pause = True

    if pause > 0:
        pause -= 1
        action = "PAUSE"

    elif group_pause:
        action = "STOP"

    elif signal:
        pred = signal["next"]
        prob = signal["prob"]

        if run_len >= 5:
            prob -= 0.05

        if prob >= BET_PROB:
            action = "BET"
        elif prob >= BET_SMALL_PROB:
            action = "SMALL"

        if action in ("BET", "SMALL"):
            trade = True

            if pred == real:
                hit = 1
                p += WIN_GROUP
                hits.append(1)
                loss_streak = 0
            else:
                hit = 0
                p += LOSS_GROUP
                hits.append(0)
                loss_streak += 1

                if loss_streak >= 2:
                    pause = PAUSE_AFTER_2_LOSSES
                    loss_streak = 0

                if len(hits) >= GROUP_MAX_LOSS_STREAK:
                    if sum(hits[-GROUP_MAX_LOSS_STREAK:]) == 0:
                        group_pause = True

    hist.append({
        "round": i,
        "group": groups[i],
        "next": real,
        "run": run_len,
        "pred": pred,
        "action": action,
        "hit": hit,
        "profit": round(p, 2)
    })

    processed = i + 1

# ================= SAVE =================
st.session_state.processed_until = processed
st.session_state.profit = p
st.session_state.hits = hits
st.session_state.pause = pause
st.session_state.loss_streak = loss_streak
st.session_state.group_pause = group_pause
st.session_state.history = hist

df = pd.DataFrame(hist)

# ================= NEXT =================
signal = get_signal(groups)
g, run_len = get_current_run(groups)

next_g = None
next_action = "WAIT"

if signal:
    next_g = signal["next"]
    prob = signal["prob"]

    if run_len >= 5:
        prob -= 0.05

    if pause > 0 or group_pause:
        next_action = "WAIT"
    elif prob >= BET_PROB:
        next_action = "BET"
    elif prob >= BET_SMALL_PROB:
        next_action = "SMALL"

# ================= UI =================
st.title("🔥 RUN GROUP LIVE (from 168)")

c1, c2, c3 = st.columns(3)
c1.metric("Current Group", g)
c2.metric("Run Length", run_len)
c3.metric("Next Action", next_action)

st.write("Next Group:", next_g)
st.write("Pause:", pause)
st.write("Profit:", round(p, 2))

if group_pause:
    st.error("STOP GROUP")
elif pause > 0:
    st.warning("PAUSE")
elif next_action == "BET":
    st.error(f"BET {next_g}")
elif next_action == "SMALL":
    st.warning(f"BET SMALL {next_g}")
else:
    st.info("WAIT")

# stats
st.subheader("Stats")
st.write("Trades:", len(hits))
st.write("Winrate:", round(sum(hits)/len(hits)*100,2) if hits else 0)

# chart
if not df.empty:
    st.line_chart(df["profit"])

# history
st.subheader("History")
st.dataframe(df.iloc[::-1].head(SHOW_HISTORY_ROWS))
