import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1500, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

MIN_RUN_LEN = 2
MAX_RUN_LEN = 5

MIN_SAMPLES = 6
MIN_PROB = 0.35
MIN_EDGE = 0.05

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

WIN_COLOR = 1.5
LOSS_COLOR = -1.0

# ================= LOAD DATA FROM GOOGLE SHEET =================
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Google Sheet phải có cột 'number'.")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

if len(numbers) < 20:
    st.error("Chưa đủ dữ liệu.")
    st.stop()

# ================= MAP NUMBER -> GROUP / COLOR =================
def number_to_group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

def number_to_color(n: int) -> str:
    if 1 <= n <= 4:
        return "red"
    if 5 <= n <= 8:
        return "green"
    return "blue"

groups = [number_to_group(x) for x in numbers]
colors = [number_to_color(x) for x in numbers]

# ================= BUILD RUN PATTERN STATS =================
def build_run_stats(seq):
    stats = defaultdict(Counter)

    for i in range(1, len(seq)):
        cur = seq[i - 1]

        run_len = 1
        j = i - 2
        while j >= 0 and seq[j] == cur:
            run_len += 1
            j -= 1

        capped = min(run_len, MAX_RUN_LEN)
        nxt = seq[i]

        for rl in range(MIN_RUN_LEN, capped + 1):
            stats[(cur, rl)][nxt] += 1

    rows = []
    for (run_value, run_len), counter in stats.items():
        total = sum(counter.values())
        ranked = counter.most_common()

        top1, c1 = ranked[0]
        p1 = c1 / total if total else 0.0

        if len(ranked) >= 2:
            top2, c2 = ranked[1]
            p2 = c2 / total
        else:
            top2, c2, p2 = None, 0, 0.0

        edge = p1 - p2

        score = (
            p1 * 0.5
            + edge * 0.3
            + min(total / 20, 1.0) * 0.2
        )

        rows.append({
            "run_value": run_value,
            "run_len": run_len,
            "samples": total,
            "next_top1": top1,
            "top1_count": c1,
            "top1_prob": round(p1, 4),
            "next_top2": top2,
            "top2_count": c2,
            "top2_prob": round(p2, 4),
            "edge": round(edge, 4),
            "score": round(score, 4),
            "dist": dict(counter),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df

    df_all = df.sort_values(
        ["score", "top1_prob", "edge", "samples", "run_len"],
        ascending=[False, False, False, False, False]
    ).reset_index(drop=True)

    df_good = df[
        (df["samples"] >= MIN_SAMPLES) &
        (df["top1_prob"] >= MIN_PROB) &
        (df["edge"] >= MIN_EDGE)
    ].copy()

    df_good = df_good.sort_values(
        ["score", "top1_prob", "edge", "samples", "run_len"],
        ascending=[False, False, False, False, False]
    ).reset_index(drop=True)

    return df_all, df_good

group_all_df, group_good_df = build_run_stats(groups)
color_all_df, color_good_df = build_run_stats(colors)

# ================= CURRENT RUN =================
def get_current_run(seq):
    cur = seq[-1]
    run_len = 1
    j = len(seq) - 2
    while j >= 0 and seq[j] == cur:
        run_len += 1
        j -= 1
    return cur, run_len

current_group, current_group_run_len = get_current_run(groups)
current_color, current_color_run_len = get_current_run(colors)

# ================= FIND BEST SIGNAL =================
def find_best_signal(current_value, current_run_len, good_df, all_df):
    # ưu tiên good pattern đúng run_len trước
    for rl in range(min(current_run_len, MAX_RUN_LEN), MIN_RUN_LEN - 1, -1):
        matched = good_df[
            (good_df["run_value"] == current_value) &
            (good_df["run_len"] == rl)
        ]
        if not matched.empty:
            return matched.iloc[0].to_dict(), "good_exact"

    # fallback good cùng value
    matched = good_df[good_df["run_value"] == current_value]
    if not matched.empty:
        return matched.iloc[0].to_dict(), "good_fallback"

    # fallback all cùng value
    for rl in range(min(current_run_len, MAX_RUN_LEN), MIN_RUN_LEN - 1, -1):
        matched = all_df[
            (all_df["run_value"] == current_value) &
            (all_df["run_len"] == rl)
        ]
        if not matched.empty:
            return matched.iloc[0].to_dict(), "all_exact"

    matched = all_df[all_df["run_value"] == current_value]
    if not matched.empty:
        return matched.iloc[0].to_dict(), "all_fallback"

    return None, "none"

group_signal, group_mode = find_best_signal(
    current_group, current_group_run_len, group_good_df, group_all_df
)
color_signal, color_mode = find_best_signal(
    current_color, current_color_run_len, color_good_df, color_all_df
)

next_group = group_signal["next_top1"] if group_signal else None
next_color = color_signal["next_top1"] if color_signal else None

group_score = group_signal["score"] if group_signal else 0
color_score = color_signal["score"] if color_signal else 0

group_color_match = (
    next_group is not None and next_color is not None and number_to_color(
        {1: 1, 2: 5, 3: 9, 4: 12}[int(next_group)]
    ) == next_color
)

# ================= LIVE BACKTEST =================
def backtest_live(numbers):
    profit_group = 0.0
    profit_color = 0.0
    hits_group = []
    hits_color = []
    rows = []

    live_groups = [number_to_group(x) for x in numbers]
    live_colors = [number_to_color(x) for x in numbers]

    for i in range(1, len(numbers)):
        hist_groups = live_groups[:i]
        hist_colors = live_colors[:i]

        if len(hist_groups) < 10:
            continue

        g_cur, g_run = get_current_run(hist_groups)
        c_cur, c_run = get_current_run(hist_colors)

        g_all, g_good = build_run_stats(hist_groups)
        c_all, c_good = build_run_stats(hist_colors)

        g_sig, _ = find_best_signal(g_cur, g_run, g_good, g_all)
        c_sig, _ = find_best_signal(c_cur, c_run, c_good, c_all)

        pred_group = g_sig["next_top1"] if g_sig else None
        pred_color = c_sig["next_top1"] if c_sig else None

        real_group = live_groups[i]
        real_color = live_colors[i]

        trade_group = pred_group is not None
        trade_color = pred_color is not None

        group_hit = None
        color_hit = None

        if trade_group:
            if pred_group == real_group:
                profit_group += WIN_GROUP
                group_hit = 1
                hits_group.append(1)
            else:
                profit_group += LOSS_GROUP
                group_hit = 0
                hits_group.append(0)

        if trade_color:
            if pred_color == real_color:
                profit_color += WIN_COLOR
                color_hit = 1
                hits_color.append(1)
            else:
                profit_color += LOSS_COLOR
                color_hit = 0
                hits_color.append(0)

        rows.append({
            "round": i,
            "number": numbers[i],
            "group": real_group,
            "color": real_color,
            "pred_group": pred_group,
            "pred_color": pred_color,
            "group_hit": group_hit,
            "color_hit": color_hit,
            "profit_group": profit_group,
            "profit_color": profit_color,
        })

    hist = pd.DataFrame(rows)
    return hist, profit_group, profit_color, hits_group, hits_color

hist_df, total_profit_group, total_profit_color, hits_group, hits_color = backtest_live(numbers)

# ================= UI =================
st.title("🔥 RUN PATTERN PRO LIVE - Google Sheet chỉ có number")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", current_group)
c3.metric("Current Color", current_color)
c4.metric("Rows", len(numbers))

st.subheader("Current Run")
r1, r2 = st.columns(2)
r1.write(f"Group hiện tại: {current_group}")
r1.write(f"Run group length: {current_group_run_len}")
r2.write(f"Color hiện tại: {current_color}")
r2.write(f"Run color length: {current_color_run_len}")

st.subheader("Next Prediction")
p1, p2 = st.columns(2)
p1.write(f"Next Group: {next_group}")
p1.write(f"Group signal mode: {group_mode}")
p1.write(f"Group score: {group_score}")
p2.write(f"Next Color: {next_color}")
p2.write(f"Color signal mode: {color_mode}")
p2.write(f"Color score: {color_score}")

st.write(f"Group/Color Match: {group_color_match}")

if next_group is not None or next_color is not None:
    st.markdown(
        f"""
        <div style="background:#ffd700;
        padding:18px;
        border-radius:10px;
        text-align:center;
        font-size:28px;
        font-weight:bold;">
        NEXT GROUP → {next_group if next_group is not None else "-"} |
        NEXT COLOR → {next_color if next_color is not None else "-"}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("Chưa có pattern đủ mạnh.")

st.subheader("Session Statistics (LIVE ONLY)")
s1, s2, s3 = st.columns(3)
s1.metric("Total Profit Group", round(total_profit_group, 2))
s2.metric("Trades Group", len(hits_group))
s3.metric("Winrate Group %", round(sum(hits_group) / len(hits_group) * 100, 2) if hits_group else 0)

s4, s5, s6 = st.columns(3)
s4.metric("Total Profit Color", round(total_profit_color, 2))
s5.metric("Trades Color", len(hits_color))
s6.metric("Winrate Color %", round(sum(hits_color) / len(hits_color) * 100, 2) if hits_color else 0)

st.subheader("All Group Run Patterns")
st.dataframe(group_all_df.drop(columns=["dist"]) if not group_all_df.empty else group_all_df, use_container_width=True)

st.subheader("Good Group Run Patterns")
st.dataframe(group_good_df.drop(columns=["dist"]) if not group_good_df.empty else group_good_df, use_container_width=True)

st.subheader("All Color Run Patterns")
st.dataframe(color_all_df.drop(columns=["dist"]) if not color_all_df.empty else color_all_df, use_container_width=True)

st.subheader("Good Color Run Patterns")
st.dataframe(color_good_df.drop(columns=["dist"]) if not color_good_df.empty else color_good_df, use_container_width=True)

st.subheader("Profit Curve - Total Group (LIVE ONLY)")
if not hist_df.empty:
    st.line_chart(hist_df["profit_group"])

st.subheader("Profit Curve - Total Color (LIVE ONLY)")
if not hist_df.empty:
    st.line_chart(hist_df["profit_color"])

st.subheader("History")
st.dataframe(hist_df.iloc[::-1], use_container_width=True)
