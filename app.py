import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=2000, key="refresh")

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

SHOW_HISTORY_ROWS = 120

# ================= LOAD DATA =================
@st.cache_data(ttl=15)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={int(time.time() // 15)}"
    )
    df = pd.read_csv(url, usecols=["number"])
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]
    return nums

numbers = load_numbers()

if len(numbers) < 20:
    st.error("Chưa đủ dữ liệu.")
    st.stop()

# ================= MAP =================
def number_to_group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

def number_to_color(n: int) -> str:
    if n <= 4:
        return "red"
    if n <= 8:
        return "green"
    return "blue"

groups = [number_to_group(x) for x in numbers]
colors = [number_to_color(x) for x in numbers]

# ================= RUN HELPERS =================
def get_current_run(seq):
    cur = seq[-1]
    run_len = 1
    i = len(seq) - 2
    while i >= 0 and seq[i] == cur:
        run_len += 1
        i -= 1
    return cur, run_len

def build_run_stats_fast(seq, min_run_len=2, max_run_len=5):
    """
    Trả về:
    - all_rows: list[dict]
    - good_rows: list[dict]
    - index_all: dict[(run_value, run_len)] -> sorted list rows
    - index_good: dict[(run_value, run_len)] -> sorted list rows
    """
    stats = defaultdict(Counter)

    n = len(seq)
    for i in range(1, n):
        run_value = seq[i - 1]
        run_len = 1
        j = i - 2
        while j >= 0 and seq[j] == run_value and run_len < max_run_len:
            run_len += 1
            j -= 1

        if run_len >= min_run_len:
            next_value = seq[i]
            for rl in range(min_run_len, run_len + 1):
                stats[(run_value, rl)][next_value] += 1

    all_rows = []
    for (run_value, run_len), cnt in stats.items():
        samples = sum(cnt.values())
        ranked = cnt.most_common()

        top1, c1 = ranked[0]
        p1 = c1 / samples

        if len(ranked) > 1:
            top2, c2 = ranked[1]
            p2 = c2 / samples
        else:
            top2, c2, p2 = None, 0, 0.0

        edge = p1 - p2
        score = p1 * 0.5 + edge * 0.3 + min(samples / 20.0, 1.0) * 0.2

        all_rows.append({
            "run_value": run_value,
            "run_len": run_len,
            "samples": samples,
            "next_top1": top1,
            "top1_count": c1,
            "top1_prob": round(p1, 4),
            "next_top2": top2,
            "top2_count": c2,
            "top2_prob": round(p2, 4),
            "edge": round(edge, 4),
            "score": round(score, 4),
        })

    all_rows.sort(
        key=lambda x: (x["score"], x["top1_prob"], x["edge"], x["samples"], x["run_len"]),
        reverse=True
    )

    good_rows = [
        r for r in all_rows
        if r["samples"] >= MIN_SAMPLES and r["top1_prob"] >= MIN_PROB and r["edge"] >= MIN_EDGE
    ]

    index_all = defaultdict(list)
    index_good = defaultdict(list)

    for r in all_rows:
        index_all[(r["run_value"], r["run_len"])].append(r)
    for r in good_rows:
        index_good[(r["run_value"], r["run_len"])].append(r)

    return all_rows, good_rows, index_all, index_good

def find_best_signal(cur_value, cur_run_len, index_good, index_all, all_rows):
    cap_run = min(cur_run_len, MAX_RUN_LEN)

    for rl in range(cap_run, MIN_RUN_LEN - 1, -1):
        key = (cur_value, rl)
        if key in index_good and index_good[key]:
            return index_good[key][0], "good_exact"

    for rl in range(cap_run, MIN_RUN_LEN - 1, -1):
        key = (cur_value, rl)
        if key in index_all and index_all[key]:
            return index_all[key][0], "all_exact"

    candidates = [r for r in all_rows if r["run_value"] == cur_value]
    if candidates:
        return candidates[0], "all_fallback"

    if all_rows:
        return all_rows[0], "global_fallback"

    return None, "none"

# ================= BUILD MODEL ONCE =================
group_all_rows, group_good_rows, group_index_all, group_index_good = build_run_stats_fast(
    groups, MIN_RUN_LEN, MAX_RUN_LEN
)
color_all_rows, color_good_rows, color_index_all, color_index_good = build_run_stats_fast(
    colors, MIN_RUN_LEN, MAX_RUN_LEN
)

current_group, current_group_run = get_current_run(groups)
current_color, current_color_run = get_current_run(colors)

group_signal, group_mode = find_best_signal(
    current_group, current_group_run, group_index_good, group_index_all, group_all_rows
)
color_signal, color_mode = find_best_signal(
    current_color, current_color_run, color_index_good, color_index_all, color_all_rows
)

next_group = group_signal["next_top1"] if group_signal else None
next_color = color_signal["next_top1"] if color_signal else None

group_strength = group_signal["score"] if group_signal else 0
color_strength = color_signal["score"] if color_signal else 0

def group_to_color(g):
    if g == 1:
        return "red"
    if g == 2:
        return "green"
    if g in (3, 4):
        # group 3 = 7..9 => majority color split, nên không map cứng chuẩn tuyệt đối
        # dùng number mapping thì group 3 chứa green+blue, group 4 chỉ blue
        return None
    return None

# rule match chặt: next_group phải suy ra được color trùng next_color
group_color_match = False
if next_group is not None and next_color is not None:
    if next_group == 1 and next_color == "red":
        group_color_match = True
    elif next_group == 2 and next_color == "green":
        group_color_match = True
    elif next_group == 4 and next_color == "blue":
        group_color_match = True
    elif next_group == 3 and next_color in ("green", "blue"):
        group_color_match = True

# ================= FAST LIVE BACKTEST =================
def backtest_live_fast(numbers, groups, colors):
    """
    Nhanh hơn bản cũ:
    - build model 1 lần trên full history
    - mô phỏng trade live từ MIN_RUN_LEN trở đi
    - không rebuild pattern mỗi round
    """
    profit_group = 0.0
    profit_color = 0.0
    hits_group = []
    hits_color = []
    rows = []

    for i in range(1, len(numbers)):
        hist_groups = groups[:i]
        hist_colors = colors[:i]

        if len(hist_groups) < 10:
            continue

        g_cur, g_run = get_current_run(hist_groups)
        c_cur, c_run = get_current_run(hist_colors)

        g_sig, _ = find_best_signal(g_cur, g_run, group_index_good, group_index_all, group_all_rows)
        c_sig, _ = find_best_signal(c_cur, c_run, color_index_good, color_index_all, color_all_rows)

        pred_group = g_sig["next_top1"] if g_sig else None
        pred_color = c_sig["next_top1"] if c_sig else None

        real_group = groups[i]
        real_color = colors[i]

        group_hit = None
        color_hit = None

        if pred_group is not None:
            if pred_group == real_group:
                profit_group += WIN_GROUP
                group_hit = 1
                hits_group.append(1)
            else:
                profit_group += LOSS_GROUP
                group_hit = 0
                hits_group.append(0)

        if pred_color is not None:
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
            "profit_group": round(profit_group, 2),
            "profit_color": round(profit_color, 2),
        })

    return rows, profit_group, profit_color, hits_group, hits_color

hist_rows, total_profit_group, total_profit_color, hits_group, hits_color = backtest_live_fast(
    numbers, groups, colors
)

# ================= UI =================
st.title("⚡ RUN PATTERN PRO LIVE - FAST")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", current_group)
c3.metric("Current Color", current_color)
c4.metric("Rows", len(numbers))

st.subheader("Current Run")
a1, a2 = st.columns(2)
a1.write(f"Group hiện tại: {current_group}")
a1.write(f"Run group length: {current_group_run}")
a2.write(f"Color hiện tại: {current_color}")
a2.write(f"Run color length: {current_color_run}")

st.subheader("Next Prediction")
b1, b2 = st.columns(2)
b1.write(f"Next Group: {next_group}")
b1.write(f"Group mode: {group_mode}")
b1.write(f"Group score: {round(group_strength, 4)}")
b2.write(f"Next Color: {next_color}")
b2.write(f"Color mode: {color_mode}")
b2.write(f"Color score: {round(color_strength, 4)}")

st.write(f"Group/Color Match: {group_color_match}")

if next_group is not None or next_color is not None:
    st.markdown(
        f"""
        <div style="background:#ffd700;
        padding:18px;
        border-radius:10px;
        text-align:center;
        font-size:26px;
        font-weight:bold;">
        NEXT GROUP → {next_group if next_group is not None else "-"} |
        NEXT COLOR → {next_color if next_color is not None else "-"}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("Chưa có pattern đủ mạnh.")

st.subheader("Session Statistics")
s1, s2, s3 = st.columns(3)
s1.metric("Total Profit Group", round(total_profit_group, 2))
s2.metric("Trades Group", len(hits_group))
s3.metric("Winrate Group %", round(sum(hits_group) / len(hits_group) * 100, 2) if hits_group else 0)

s4, s5, s6 = st.columns(3)
s4.metric("Total Profit Color", round(total_profit_color, 2))
s5.metric("Trades Color", len(hits_color))
s6.metric("Winrate Color %", round(sum(hits_color) / len(hits_color) * 100, 2) if hits_color else 0)

# Chỉ tạo DataFrame khi hiển thị
st.subheader("All Group Run Patterns")
if group_all_rows:
    st.dataframe(pd.DataFrame(group_all_rows), use_container_width=True)

st.subheader("Good Group Run Patterns")
if group_good_rows:
    st.dataframe(pd.DataFrame(group_good_rows), use_container_width=True)
else:
    st.write("Không có pattern group đủ điều kiện.")

st.subheader("All Color Run Patterns")
if color_all_rows:
    st.dataframe(pd.DataFrame(color_all_rows), use_container_width=True)

st.subheader("Good Color Run Patterns")
if color_good_rows:
    st.dataframe(pd.DataFrame(color_good_rows), use_container_width=True)
else:
    st.write("Không có pattern color đủ điều kiện.")

if hist_rows:
    hist_df = pd.DataFrame(hist_rows)

    st.subheader("Profit Curve - Total Group")
    st.line_chart(hist_df["profit_group"])

    st.subheader("Profit Curve - Total Color")
    st.line_chart(hist_df["profit_color"])

    st.subheader("History")
    st.dataframe(hist_df.iloc[-SHOW_HISTORY_ROWS:][::-1], use_container_width=True)
