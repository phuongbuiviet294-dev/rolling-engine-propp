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

MIN_SAMPLES = 8
MIN_PROB = 0.40
MIN_EDGE = 0.08

# chỉ bet khi group và color khớp
REQUIRE_GROUP_COLOR_MATCH = True

# dùng strict mode: chỉ nhận good_exact/good_fallback
STRICT_LIVE_MODE = True

# ================= LOAD DATA =================
@st.cache_data(ttl=15)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={int(time.time() // 15)}"
    )
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Google Sheet phải có cột 'number'.")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    nums = df["number"].dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]
    return nums

numbers = load_numbers()

if len(numbers) < 30:
    st.error("Chưa đủ dữ liệu để chạy LIVE ONLY.")
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

# ================= HELPERS =================
def get_current_run(seq):
    cur = seq[-1]
    run_len = 1
    i = len(seq) - 2
    while i >= 0 and seq[i] == cur:
        run_len += 1
        i -= 1
    return cur, run_len

def build_run_stats_fast(seq, min_run_len=2, max_run_len=5):
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

    candidates_good = [r for r in all_rows if r["run_value"] == cur_value and r in sum(index_good.values(), [])]
    if candidates_good:
        candidates_good.sort(
            key=lambda x: (x["score"], x["top1_prob"], x["edge"], x["samples"], x["run_len"]),
            reverse=True
        )
        return candidates_good[0], "good_fallback"

    for rl in range(cap_run, MIN_RUN_LEN - 1, -1):
        key = (cur_value, rl)
        if key in index_all and index_all[key]:
            return index_all[key][0], "all_exact"

    candidates_all = [r for r in all_rows if r["run_value"] == cur_value]
    if candidates_all:
        candidates_all.sort(
            key=lambda x: (x["score"], x["top1_prob"], x["edge"], x["samples"], x["run_len"]),
            reverse=True
        )
        return candidates_all[0], "all_fallback"

    return None, "none"

def group_matches_color(next_group, next_color):
    if next_group is None or next_color is None:
        return False
    if next_group == 1 and next_color == "red":
        return True
    if next_group == 2 and next_color == "green":
        return True
    if next_group == 4 and next_color == "blue":
        return True
    if next_group == 3 and next_color in ("green", "blue"):
        return True
    return False

# ================= BUILD MODEL =================
group_all_rows, group_good_rows, group_index_all, group_index_good = build_run_stats_fast(
    groups, MIN_RUN_LEN, MAX_RUN_LEN
)
color_all_rows, color_good_rows, color_index_all, color_index_good = build_run_stats_fast(
    colors, MIN_RUN_LEN, MAX_RUN_LEN
)

current_number = numbers[-1]
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

group_score = group_signal["score"] if group_signal else 0.0
color_score = color_signal["score"] if color_signal else 0.0

group_prob = group_signal["top1_prob"] if group_signal else 0.0
color_prob = color_signal["top1_prob"] if color_signal else 0.0

match_ok = group_matches_color(next_group, next_color)

# ================= LIVE FILTER =================
bet_allowed = True
bet_reason = "OK"

if STRICT_LIVE_MODE:
    if group_mode not in ("good_exact", "good_fallback"):
        bet_allowed = False
        bet_reason = f"Group mode yếu: {group_mode}"
    elif color_mode not in ("good_exact", "good_fallback"):
        bet_allowed = False
        bet_reason = f"Color mode yếu: {color_mode}"

if bet_allowed and REQUIRE_GROUP_COLOR_MATCH and not match_ok:
    bet_allowed = False
    bet_reason = "Group / Color không khớp"

if bet_allowed and current_group_run < MIN_RUN_LEN and current_color_run < MIN_RUN_LEN:
    bet_allowed = False
    bet_reason = "Run hiện tại còn ngắn"

signal_strength = round((group_score + color_score) / 2, 4)

# ================= UI =================
st.title("⚡ LIVE ONLY SIGNAL")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number)
c2.metric("Current Group", current_group)
c3.metric("Current Color", current_color)
c4.metric("Rows", len(numbers))

st.subheader("Current Run")
r1, r2 = st.columns(2)
r1.write(f"Group hiện tại: {current_group}")
r1.write(f"Run group length: {current_group_run}")
r2.write(f"Color hiện tại: {current_color}")
r2.write(f"Run color length: {current_color_run}")

st.subheader("Next Prediction")
p1, p2 = st.columns(2)

with p1:
    st.write(f"Next Group: {next_group}")
    st.write(f"Group mode: {group_mode}")
    st.write(f"Group score: {group_score}")
    st.write(f"Group prob: {group_prob}")

with p2:
    st.write(f"Next Color: {next_color}")
    st.write(f"Color mode: {color_mode}")
    st.write(f"Color score: {color_score}")
    st.write(f"Color prob: {color_prob}")

st.write(f"Group/Color Match: {match_ok}")
st.write(f"Signal strength: {signal_strength}")

if bet_allowed and next_group is not None and next_color is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;
        padding:22px;
        border-radius:12px;
        text-align:center;
        font-size:30px;
        color:white;
        font-weight:bold;">
        BET NOW → GROUP {next_group} | COLOR {next_color}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info(f"WAIT → {bet_reason}")

# ================= OPTIONAL DEBUG =================
with st.expander("Debug patterns"):
    st.write("Top Group Patterns")
    if group_all_rows:
        st.dataframe(pd.DataFrame(group_all_rows[:20]), use_container_width=True)

    st.write("Top Color Patterns")
    if color_all_rows:
        st.dataframe(pd.DataFrame(color_all_rows[:20]), use_container_width=True)

    st.write("Good Group Patterns")
    if group_good_rows:
        st.dataframe(pd.DataFrame(group_good_rows[:20]), use_container_width=True)
    else:
        st.write("Không có good group pattern.")

    st.write("Good Color Patterns")
    if color_good_rows:
        st.dataframe(pd.DataFrame(color_good_rows[:20]), use_container_width=True)
    else:
        st.write("Không có good color pattern.")
