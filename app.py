import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter
import time
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=1000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

SCAN = 168
WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 4
VOTE_REQUIRED = 3
GAP = 1

WIN = 2.5
LOSS = -1

SCAN_LIST = [120, 130, 140, 150, 160, 168, 174, 180, 190, 200]

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

groups = [group(n) for n in numbers]

# ---------------- WINDOW SCAN ----------------
def scan_windows(scan_groups):
    results = []

    for w in range(WINDOW_MIN, WINDOW_MAX + 1):
        profit = 0
        trades = 0
        wins = 0

        for i in range(w, len(scan_groups)):
            pred = scan_groups[i - w]

            if scan_groups[i - 1] != pred:
                trades += 1
                if scan_groups[i] == pred:
                    profit += WIN
                    wins += 1
                else:
                    profit += LOSS

        if trades > 0:
            wr = wins / trades
            score = profit * wr * np.log(trades)

            results.append({
                "window": w,
                "trades": trades,
                "wins": wins,
                "profit": profit,
                "winrate": wr,
                "score": score
            })

    if not results:
        return pd.DataFrame(columns=["window", "trades", "wins", "profit", "winrate", "score"])

    return pd.DataFrame(results).sort_values("score", ascending=False).reset_index(drop=True)

# ---------------- WINDOW SELECTORS ----------------
def select_windows_simple(groups):
    scan_groups = groups[:SCAN]
    scan_df = scan_windows(scan_groups)

    positive_df = scan_df[scan_df["profit"] > 0].copy()

    if len(positive_df) >= TOP_WINDOWS:
        selected = positive_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    else:
        selected = scan_df.head(TOP_WINDOWS)["window"].astype(int).tolist()

    debug_df = scan_df.copy()
    debug_df["mode"] = "SIMPLE"

    return selected, scan_df, debug_df

def select_windows_auto(groups):
    window_counter = Counter()
    window_scores = {}

    for scan in SCAN_LIST:
        if len(groups) < scan:
            continue

        scan_groups = groups[:scan]
        scan_df = scan_windows(scan_groups)

        if scan_df.empty:
            continue

        top_ws = scan_df.head(TOP_WINDOWS)

        for _, row in top_ws.iterrows():
            w = int(row["window"])
            score = float(row["score"])

            window_counter[w] += 1
            window_scores.setdefault(w, []).append(score)

    final_rows = []
    for w in window_counter:
        scores = window_scores[w]
        avg_score = float(np.mean(scores))
        count = int(window_counter[w])

        if avg_score <= 0:
            continue

        stability_score = avg_score * count
        final_rows.append({
            "window": w,
            "stability_score": stability_score,
            "count": count,
            "avg_score": avg_score
        })

    debug_df = pd.DataFrame(final_rows).sort_values(
        ["stability_score", "avg_score", "count"],
        ascending=False
    ).reset_index(drop=True) if final_rows else pd.DataFrame(
        columns=["window", "stability_score", "count", "avg_score"]
    )

    if len(debug_df) >= TOP_WINDOWS:
        selected = debug_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    else:
        simple_selected, scan_df_simple, _ = select_windows_simple(groups)
        selected = simple_selected
        scan_df = scan_df_simple
        return selected, scan_df, debug_df

    scan_df = scan_windows(groups[:SCAN])
    return selected, scan_df, debug_df

# ---------------- MODE SELECT ----------------
mode = st.radio(
    "Chọn mode",
    ["SIMPLE", "AUTO"],
    horizontal=True
)

# ---------------- LOCK WINDOWS ----------------
if "window_mode" not in st.session_state:
    st.session_state.window_mode = mode

if "top_windows" not in st.session_state or st.session_state.window_mode != mode:
    if mode == "SIMPLE":
        selected, scan_df, debug_df = select_windows_simple(groups)
    else:
        selected, scan_df, debug_df = select_windows_auto(groups)

    st.session_state.top_windows = selected
    st.session_state.scan_df = scan_df
    st.session_state.window_debug_df = debug_df
    st.session_state.window_mode = mode

top_windows = st.session_state.top_windows
scan_df = st.session_state.scan_df
debug_df = st.session_state.window_debug_df

if st.button("🔄 Re-optimize Windows"):
    if mode == "SIMPLE":
        selected, scan_df, debug_df = select_windows_simple(groups)
    else:
        selected, scan_df, debug_df = select_windows_auto(groups)

    st.session_state.top_windows = selected
    st.session_state.scan_df = scan_df
    st.session_state.window_debug_df = debug_df
    st.session_state.window_mode = mode
    st.rerun()

# ---------------- TRADE ENGINE ----------------
profit = 0
last_trade = -999
history = []
hits = []

start_index = SCAN

for i in range(start_index, len(groups)):
    preds = [groups[i - w] for w in top_windows if i - w >= 0]

    if not preds:
        continue

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= VOTE_REQUIRED
    distance = i - last_trade
    trade = signal and distance >= GAP

    bet_group = vote if trade else None
    hit = None
    state = "WAIT"

    if signal:
        state = "SIGNAL"

    if trade:
        state = "TRADE"
        last_trade = i

        if groups[i] == vote:
            hit = 1
            profit += WIN
            hits.append(1)
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

    history.append({
        "round": i,
        "number": numbers[i],
        "group": groups[i],
        "vote": vote,
        "confidence": confidence,
        "signal": signal,
        "trade": trade,
        "bet_group": bet_group,
        "hit": hit,
        "state": state,
        "profit": profit
    })

hist = pd.DataFrame(history)

# ---------------- NEXT BET ----------------
i = len(groups)
preds = [groups[i - w] for w in top_windows if i - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = i - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

signal = confidence >= VOTE_REQUIRED if vote is not None else False

next_row = {
    "round": i,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": False,
    "bet_group": vote if signal else None,
    "hit": None,
    "state": "NEXT",
    "profit": profit
}

hist = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Engine Compare Mode")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.write("Mode:", mode)
st.write("Vote Strength:", confidence)
st.write("Distance:", distance)

st.markdown(
    f"""
    <div style="background:#ffd700;padding:20px;border-radius:10px;text-align:center;font-size:28px;font-weight:bold;">
    NEXT GROUP → {vote if vote is not None else "-"}
    </div>
    """,
    unsafe_allow_html=True
)

if signal and distance >= GAP and vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:25px;border-radius:10px;text-align:center;font-size:32px;color:white;font-weight:bold;">
        BET GROUP → {vote}
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.info("WAIT")

# ---------------- STATS ----------------
st.subheader("Stats")
col1, col2, col3 = st.columns(3)
col1.metric("Profit", profit)
col2.metric("Trades", len(hits))
col3.metric("Winrate", round(np.mean(hits) * 100, 2) if hits else 0)

# ---------------- CHART ----------------
st.subheader("Profit Curve")
if not hist.empty:
    st.line_chart(hist["profit"])

# ---------------- WINDOW TABLES ----------------
st.subheader("Window Scan (168 đầu)")
st.dataframe(scan_df, use_container_width=True)

st.subheader("Window Debug")
st.dataframe(debug_df, use_container_width=True)

st.write("Final Windows:", top_windows)

# ---------------- HISTORY ----------------
def highlight(row):
    if row["state"] == "NEXT":
        return ['background-color: #ffd700'] * len(row)
    elif row["trade"]:
        return ['background-color: #ff4b4b; color:white'] * len(row)
    return [''] * len(row)

st.subheader("History")
st.dataframe(
    hist.iloc[::-1].style.apply(highlight, axis=1),
    use_container_width=True
)
