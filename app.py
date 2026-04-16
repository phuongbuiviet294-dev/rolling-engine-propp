import time
from collections import Counter, defaultdict

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= AUTO REFRESH =================
st_autorefresh(interval=1500, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# run-length pattern
MIN_RUN_LEN = 2          # bắt đầu xét từ chuỗi lặp 2 lần
MAX_RUN_LEN = 5          # xét tới chuỗi lặp 5 lần
MIN_PATTERN_COUNT = 8    # pattern phải xuất hiện ít nhất N lần
MIN_TOP1_PROB = 0.38     # xác suất next group top1 tối thiểu
MIN_EDGE = 0.08          # top1 - top2 tối thiểu
GAP = 1

# pnl
WIN = 2.5
LOSS = -1.0

# optional pause
PAUSE_AFTER_2_LOSSES = 4

# ================= LOAD DATA =================
@st.cache_data(ttl=10)
def load_numbers():
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export"
        f"?format=csv&cache={time.time()}"
    )
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

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

if len(groups) < 30:
    st.error("Chưa đủ dữ liệu để test pattern.")
    st.stop()

# ================= BUILD PATTERN TABLE =================
def build_run_pattern_stats(seq_groups, min_run_len=2, max_run_len=5):
    """
    Pattern key = (group_value, run_len)
    Ví dụ (4,2) nghĩa là vừa có chuỗi 4,4
    Ta thống kê next group sau pattern đó
    """
    stat_counter = defaultdict(Counter)
    sample_rows = []

    n = len(seq_groups)

    # tại mỗi vị trí i, xem đoạn kết thúc ở i-1 có phải là run không
    # rồi thống kê next = seq_groups[i]
    for i in range(1, n):
        current = seq_groups[i - 1]

        run_len = 1
        j = i - 2
        while j >= 0 and seq_groups[j] == current:
            run_len += 1
            j -= 1

        capped_run_len = min(run_len, max_run_len)

        # chỉ ghi nhận nếu đủ độ dài tối thiểu
        for rl in range(min_run_len, capped_run_len + 1):
            key = (current, rl)
            next_group = seq_groups[i]
            stat_counter[key][next_group] += 1

    rows = []
    for (g, rl), counter in stat_counter.items():
        total = sum(counter.values())
        ranked = counter.most_common()

        top1_group, top1_count = ranked[0]
        top1_prob = top1_count / total if total > 0 else 0.0

        if len(ranked) >= 2:
            top2_group, top2_count = ranked[1]
            top2_prob = top2_count / total
        else:
            top2_group, top2_count, top2_prob = None, 0, 0.0

        edge = top1_prob - top2_prob

        rows.append({
            "run_group": g,
            "run_len": rl,
            "samples": total,
            "next_top1": top1_group,
            "top1_count": top1_count,
            "top1_prob": round(top1_prob, 4),
            "next_top2": top2_group,
            "top2_count": top2_count,
            "top2_prob": round(top2_prob, 4),
            "edge": round(edge, 4),
            "dist_1": counter.get(1, 0),
            "dist_2": counter.get(2, 0),
            "dist_3": counter.get(3, 0),
            "dist_4": counter.get(4, 0),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, df

    df_all = df.sort_values(
        ["top1_prob", "edge", "samples", "run_len"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    df_good = df[
        (df["samples"] >= MIN_PATTERN_COUNT) &
        (df["top1_prob"] >= MIN_TOP1_PROB) &
        (df["edge"] >= MIN_EDGE)
    ].copy()

    df_good = df_good.sort_values(
        ["top1_prob", "edge", "samples", "run_len"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    return df_all, df_good

pattern_all_df, pattern_good_df = build_run_pattern_stats(
    groups,
    min_run_len=MIN_RUN_LEN,
    max_run_len=MAX_RUN_LEN
)

# ================= CURRENT RUN =================
def get_current_run(seq_groups):
    if not seq_groups:
        return None, 0
    g = seq_groups[-1]
    run_len = 1
    idx = len(seq_groups) - 2
    while idx >= 0 and seq_groups[idx] == g:
        run_len += 1
        idx -= 1
    return g, run_len

current_group, current_run_len = get_current_run(groups)
current_run_len_capped = min(current_run_len, MAX_RUN_LEN)

# ================= PICK NEXT BET FROM CURRENT RUN =================
def find_signal_for_current_run(current_group, current_run_len, pattern_good_df):
    if pattern_good_df.empty:
        return None

    # ưu tiên run dài hơn trước
    for rl in range(min(current_run_len, MAX_RUN_LEN), MIN_RUN_LEN - 1, -1):
        matched = pattern_good_df[
            (pattern_good_df["run_group"] == current_group) &
            (pattern_good_df["run_len"] == rl)
        ].copy()

        if not matched.empty:
            best = matched.iloc[0].to_dict()
            return best

    return None

signal_row = find_signal_for_current_run(
    current_group,
    current_run_len,
    pattern_good_df
)

# ================= BACKTEST LIVE SIMPLE =================
def backtest_run_pattern_live(seq_groups, pattern_good_df):
    profit = 0.0
    hits = []
    rows = []

    pause_left = 0
    consecutive_losses = 0
    last_trade = -999999

    for i in range(1, len(seq_groups)):
        current = seq_groups[i - 1]

        run_len = 1
        j = i - 2
        while j >= 0 and seq_groups[j] == current:
            run_len += 1
            j -= 1

        next_group_real = seq_groups[i]

        if pause_left > 0:
            pause_left -= 1
            rows.append({
                "round": i,
                "run_group": current,
                "run_len": run_len,
                "pred": None,
                "trade": False,
                "hit": None,
                "profit": profit,
                "state": "PAUSE",
                "pause_left": pause_left,
            })
            continue

        best_signal = None
        for rl in range(min(run_len, MAX_RUN_LEN), MIN_RUN_LEN - 1, -1):
            matched = pattern_good_df[
                (pattern_good_df["run_group"] == current) &
                (pattern_good_df["run_len"] == rl)
            ]
            if not matched.empty:
                best_signal = matched.iloc[0]
                break

        trade = False
        pred = None
        hit = None
        state = "WAIT"

        if best_signal is not None and (i - last_trade >= GAP):
            trade = True
            pred = int(best_signal["next_top1"])
            last_trade = i

            if next_group_real == pred:
                hit = 1
                profit += WIN
                hits.append(1)
                consecutive_losses = 0
                state = "TRADE_WIN"
            else:
                hit = 0
                profit += LOSS
                hits.append(0)
                consecutive_losses += 1
                state = "TRADE_LOSS"

                if consecutive_losses >= 2:
                    pause_left = PAUSE_AFTER_2_LOSSES
                    consecutive_losses = 0
                    state = "PAUSE_TRIGGER"

        rows.append({
            "round": i,
            "run_group": current,
            "run_len": run_len,
            "pred": pred,
            "real_next": next_group_real,
            "trade": trade,
            "hit": hit,
            "profit": profit,
            "state": state,
            "pause_left": pause_left,
        })

    hist = pd.DataFrame(rows)
    trades = len(hits)
    winrate = (sum(hits) / trades * 100) if trades > 0 else 0.0
    return hist, profit, trades, winrate

hist_df, live_profit, live_trades, live_winrate = backtest_run_pattern_live(groups, pattern_good_df)

# ================= NEXT BET =================
if signal_row is not None:
    next_group_pred = int(signal_row["next_top1"])
    next_prob = float(signal_row["top1_prob"])
    next_edge = float(signal_row["edge"])
    next_samples = int(signal_row["samples"])
else:
    next_group_pred = None
    next_prob = 0.0
    next_edge = 0.0
    next_samples = 0

# ================= UI =================
st.title("🔁 Run Pattern Engine: lặp group >= 2 lần")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Group", current_group)
c2.metric("Current Run Len", current_run_len)
c3.metric("Next Group", next_group_pred if next_group_pred is not None else "-")
c4.metric("Pattern Samples", next_samples)

st.write("Current run:", f"group {current_group} lặp {current_run_len} lần")
st.write("Top1 probability:", round(next_prob * 100, 2) if next_group_pred is not None else "-")
st.write("Edge over top2:", round(next_edge * 100, 2) if next_group_pred is not None else "-")

if next_group_pred is not None:
    st.markdown(
        f"""
        <div style="background:#ffd700;
        padding:18px;
        border-radius:10px;
        text-align:center;
        font-size:28px;
        font-weight:bold;">
        RUN SIGNAL → NEXT GROUP {next_group_pred}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("Chưa có pattern run đủ mạnh để bet.")

st.subheader("Session Statistics")
s1, s2, s3 = st.columns(3)
s1.metric("Profit", live_profit)
s2.metric("Trades", live_trades)
s3.metric("Winrate %", round(live_winrate, 2))

st.subheader("Pattern matched for current run")
if signal_row is not None:
    st.dataframe(pd.DataFrame([signal_row]), use_container_width=True)
else:
    st.write("Không có pattern đủ điều kiện.")

st.subheader("All run patterns")
st.dataframe(pattern_all_df, use_container_width=True)

st.subheader("Good run patterns")
st.dataframe(pattern_good_df, use_container_width=True)

st.subheader("Profit Curve")
if not hist_df.empty:
    st.line_chart(hist_df["profit"])

st.subheader("History")
def row_style(row):
    if row["state"] == "PAUSE":
        return ["background-color: #87ceeb; color:black"] * len(row)
    if row["state"] == "PAUSE_TRIGGER":
        return ["background-color: #9370db; color:white"] * len(row)
    if row["state"] == "TRADE_WIN":
        return ["background-color: #5cb85c; color:white"] * len(row)
    if row["state"] == "TRADE_LOSS":
        return ["background-color: #d9534f; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_df.iloc[::-1].style.apply(row_style, axis=1),
    use_container_width=True,
)
