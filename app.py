import time
from collections import Counter
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================================================
# REFRESH
# =========================================================
st.set_page_config(page_title="Group Pattern Engine", layout="wide")
st_autorefresh(interval=3000, key="refresh")

# =========================================================
# GOOGLE SHEET
# =========================================================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# =========================================================
# PROFIT
# =========================================================
WIN_GROUP = 2.5
LOSS_GROUP = -1.0

# =========================================================
# PATTERN RULES
# =========================================================
PATTERN_RULES = {
    "AAA": "A",
    "AAAB": "A",
    "AAAAB": "A",
    "AABB": "A",
    "AABBA": "A",
    "AAABBB": "A",
    "AAABBBA": "A",
    "ABABA": "B",
}

# =========================================================
# FILTER
# =========================================================
MIN_PATTERN_OCCURRENCES = 2
MIN_PATTERN_HIT_RATE = 0.30
MIN_PATTERN_PROFIT = -1.0

RECENT_CHECK_ROUNDS = 120
MIN_RECENT_PATTERN_OCCURRENCES = 1

MAX_CONSECUTIVE_LOSSES = 3

SHOW_HISTORY_ROWS = 50

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=10)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={int(time.time())}"
    df = pd.read_csv(url)

    df.columns = [str(x).strip().lower() for x in df.columns]

    if "number" not in df.columns:
        st.error("Không tìm thấy cột number")
        st.stop()

    nums = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()

    nums = [x for x in nums if 1 <= x <= 12]

    return nums

# =========================================================
# GROUP
# =========================================================
def group_of(n):
    if n <= 3:
        return 1
    elif n <= 6:
        return 2
    elif n <= 9:
        return 3
    return 4

# =========================================================
# PATTERN CONVERT
# =========================================================
def groups_to_ab_pattern(group_seq):

    mapping = {}
    reverse_map = {}

    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    result = []

    for g in group_seq:

        if g not in mapping:
            idx = len(mapping)
            label = labels[idx]

            mapping[g] = label
            reverse_map[label] = g

        result.append(mapping[g])

    return "".join(result), reverse_map

# =========================================================
# FIND SIGNAL
# =========================================================
def get_signal(groups):

    best = None

    for pattern, bet_label in sorted(
        PATTERN_RULES.items(),
        key=lambda x: len(x[0]),
        reverse=True
    ):

        L = len(pattern)

        if len(groups) < L:
            continue

        tail = groups[-L:]

        ab_pattern, reverse_map = groups_to_ab_pattern(tail)

        if ab_pattern == pattern:

            if bet_label in reverse_map:

                best = {
                    "pattern": pattern,
                    "bet_label": bet_label,
                    "bet_group": reverse_map[bet_label],
                    "tail": tail
                }

                break

    return best

# =========================================================
# PATTERN STATS
# =========================================================
def calc_pattern_stats(groups, pattern, bet_label):

    L = len(pattern)

    trades = 0
    wins = 0
    profit = 0

    for i in range(L - 1, len(groups) - 1):

        tail = groups[i - L + 1:i + 1]

        ab_pattern, reverse_map = groups_to_ab_pattern(tail)

        if ab_pattern != pattern:
            continue

        if bet_label not in reverse_map:
            continue

        pred_group = reverse_map[bet_label]

        actual_group = groups[i + 1]

        trades += 1

        if pred_group == actual_group:
            wins += 1
            profit += WIN_GROUP
        else:
            profit += LOSS_GROUP

    hit_rate = wins / trades if trades > 0 else 0

    return {
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "hit_rate": hit_rate
    }

# =========================================================
# MAIN
# =========================================================
numbers = load_data()

groups = [group_of(x) for x in numbers]

if len(groups) < 10:
    st.warning("Chưa đủ dữ liệu")
    st.stop()

signal = get_signal(groups)

# =========================================================
# NEXT SIGNAL
# =========================================================
bet_ok = False
state = "WAIT"

pattern_stat = None

if signal is not None:

    pattern_stat = calc_pattern_stats(
        groups,
        signal["pattern"],
        signal["bet_label"]
    )

    if pattern_stat["trades"] >= MIN_PATTERN_OCCURRENCES:

        if pattern_stat["hit_rate"] >= MIN_PATTERN_HIT_RATE:

            if pattern_stat["profit"] >= MIN_PATTERN_PROFIT:

                bet_ok = True
                state = "READY"

# =========================================================
# BACKTEST
# =========================================================
history = []

total_profit = 0
consecutive_losses = 0

max_pattern_len = max(len(x) for x in PATTERN_RULES.keys())

for i in range(max_pattern_len, len(groups) - 1):

    sub_groups = groups[:i]

    sig = get_signal(sub_groups)

    trade = False

    pred_group = None

    hit = None
    pnl = 0

    state_row = "WAIT"

    if sig is not None:

        stat = calc_pattern_stats(
            sub_groups,
            sig["pattern"],
            sig["bet_label"]
        )

        if (
            stat["trades"] >= MIN_PATTERN_OCCURRENCES
            and stat["hit_rate"] >= MIN_PATTERN_HIT_RATE
            and stat["profit"] >= MIN_PATTERN_PROFIT
        ):

            trade = True
            state_row = "TRADE"

            pred_group = sig["bet_group"]

            actual_group = groups[i]

            if pred_group == actual_group:

                hit = 1
                pnl = WIN_GROUP
                consecutive_losses = 0

            else:

                hit = 0
                pnl = LOSS_GROUP
                consecutive_losses += 1

            total_profit += pnl

    history.append({
        "round": i + 1,
        "pattern": sig["pattern"] if sig else None,
        "tail": str(sig["tail"]) if sig else None,
        "bet_group": pred_group,
        "actual_group": groups[i],
        "trade": trade,
        "hit": hit,
        "pnl": pnl,
        "total_profit": total_profit,
        "state": state_row
    })

# =========================================================
# UI
# =========================================================
st.title("GROUP PATTERN ENGINE")

c1, c2, c3, c4 = st.columns(4)

c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", groups[-1])
c3.metric("Total Profit", round(total_profit, 2))
c4.metric("State", state)

if bet_ok and signal:

    st.success(
        f"READY BET GROUP {signal['bet_group']} | "
        f"PATTERN {signal['pattern']} | "
        f"TAIL {signal['tail']}"
    )

else:

    st.warning("WAIT")

# =========================================================
# SIGNAL INFO
# =========================================================
st.subheader("Signal")

if signal:

    st.write("Pattern:", signal["pattern"])
    st.write("Tail:", signal["tail"])
    st.write("Bet Label:", signal["bet_label"])
    st.write("Bet Group:", signal["bet_group"])

if pattern_stat:

    st.write("Trades:", pattern_stat["trades"])
    st.write("Wins:", pattern_stat["wins"])
    st.write("Hit Rate:", round(pattern_stat["hit_rate"] * 100, 2))
    st.write("Profit:", round(pattern_stat["profit"], 2))

# =========================================================
# PATTERN TABLE
# =========================================================
rows = []

for p, b in PATTERN_RULES.items():

    stat = calc_pattern_stats(groups, p, b)

    rows.append({
        "pattern": p,
        "bet": b,
        "trades": stat["trades"],
        "wins": stat["wins"],
        "wr": round(stat["hit_rate"] * 100, 2),
        "profit": stat["profit"]
    })

stats_df = pd.DataFrame(rows)

stats_df = stats_df.sort_values(
    ["profit", "wr"],
    ascending=False
)

st.subheader("Pattern Stats")

st.dataframe(stats_df, use_container_width=True)

# =========================================================
# CHART
# =========================================================
hist_df = pd.DataFrame(history)

if not hist_df.empty:

    st.subheader("Profit Curve")

    st.line_chart(
        hist_df[["total_profit"]]
    )

# =========================================================
# HISTORY
# =========================================================
st.subheader("History")

if not hist_df.empty:

    st.dataframe(
        hist_df.iloc[::-1].head(SHOW_HISTORY_ROWS),
        use_container_width=True
    )
