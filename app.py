import time
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ---------------- AUTO REFRESH ----------------
st_autorefresh(interval=10000, key="refresh")

# ---------------- CONFIG ----------------
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROUND_START = 168
LOCK_ROUND_END = 204

WINDOW_MIN = 6
WINDOW_MAX = 20

TOP_WINDOWS = 5
GAP = 0

WIN = 2.5
LOSS = -1
PROFIT_TARGET = 3

MIN_WINDOW_PROFIT = -15
MIN_WINRATE = 0.28
MIN_EV = 0.0

MAX_NEGATIVE_WINDOWS = 2

# ranking weights
FREQ_WEIGHT = 12.0
AVG_PROFIT_WEIGHT = 5.0
AVG_EV_WEIGHT = 12.0
AVG_WINRATE_WEIGHT = 8.0
AVG_SCORE_WEIGHT = 0.3
AVG_STREAK_PENALTY = 1.5

# ---------------- LOAD DATA ----------------
@st.cache_data(ttl=10)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(f"Load Google Sheet failed: {e}")
        st.stop()

    df.columns = [c.lower().strip() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet thiếu cột 'number'")
        st.write("Columns found:", df.columns.tolist())
        st.stop()

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    numbers = df["number"].dropna().astype(int).tolist()

    if not numbers:
        st.error("Không đọc được dữ liệu number từ sheet")
        st.stop()

    return numbers


numbers = load_numbers()

# ---------------- GROUP ----------------
def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


groups = [group(n) for n in numbers]

# ---------------- GUARD ----------------
if len(groups) <= LOCK_ROUND_END:
    st.error(
        f"Chưa đủ dữ liệu để quét lock round đến {LOCK_ROUND_END}. Hiện có {len(groups)} rounds."
    )
    st.stop()

# ---------------- WINDOW EVAL ----------------
def evaluate_window(seq_groups, w):
    profit = 0
    trades = 0
    wins = 0
    profit_curve = []

    down_streak = 0
    max_down_streak = 0
    prev_profit = 0

    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]

        if seq_groups[i - 1] != pred:
            trades += 1

            if seq_groups[i] == pred:
                profit += WIN
                wins += 1
            else:
                profit += LOSS

            profit_curve.append(profit)

            if profit < prev_profit:
                down_streak += 1
            else:
                down_streak = 0

            max_down_streak = max(max_down_streak, down_streak)
            prev_profit = profit

    winrate = wins / trades if trades > 0 else 0
    score = profit * winrate * np.log(trades) if trades > 0 else -999999
    ev = winrate * WIN - (1 - winrate) * abs(LOSS) if trades > 0 else -999999

    hybrid_score = (
        profit * 5.0
        + winrate * 10.0
        + ev * 10.0
        - max_down_streak * 1.0
    )

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "ev": ev,
        "hybrid_score": hybrid_score,
        "max_down_streak": max_down_streak,
        "profit_curve": profit_curve,
    }


def select_top_windows_for_round(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    full_rank_df = df.sort_values(
        ["profit", "ev", "hybrid_score", "score", "winrate", "max_down_streak"],
        ascending=[False, False, False, False, False, True]
    ).reset_index(drop=True)

    # 1) window dương có edge
    positive_df = df[
        (df["profit"] > 0) &
        (df["winrate"] >= MIN_WINRATE) &
        (df["ev"] >= MIN_EV)
    ].copy()

    positive_df = positive_df.sort_values(
        ["profit", "ev", "max_down_streak", "score", "winrate"],
        ascending=[False, False, True, False, False]
    ).reset_index(drop=True)

    selected_parts = []

    if len(positive_df) >= TOP_WINDOWS:
        selected_df = positive_df.head(TOP_WINDOWS).copy()
        selected_df["pick_source"] = "positive_edge"
    else:
        if len(positive_df) > 0:
            tmp = positive_df.copy()
            tmp["pick_source"] = "positive_edge"
            selected_parts.append(tmp)

        need_more = TOP_WINDOWS - len(positive_df)

        # 2) âm nhẹ nhưng phải có edge thật sự
        negative_df = df[
            (df["profit"] <= 0) &
            (df["profit"] > MIN_WINDOW_PROFIT) &
            (df["winrate"] >= MIN_WINRATE) &
            (df["ev"] >= MIN_EV)
        ].copy()

        negative_df = negative_df.sort_values(
            ["max_down_streak", "ev", "profit", "score", "winrate"],
            ascending=[True, False, False, False, False]
        ).reset_index(drop=True)

        take_neg = min(need_more, MAX_NEGATIVE_WINDOWS, len(negative_df))
        if take_neg > 0:
            neg_take = negative_df.head(take_neg).copy()
            neg_take["pick_source"] = "negative_edge_low_noise"
            selected_parts.append(neg_take)

        selected_df = pd.concat(selected_parts, ignore_index=True) if selected_parts else pd.DataFrame()

        # 3) nếu vẫn thiếu, lấy phần còn lại có EV tốt hơn trước
        if len(selected_df) < TOP_WINDOWS:
            already = set(selected_df["window"].tolist()) if not selected_df.empty else set()

            fallback_df = df[~df["window"].isin(already)].copy()
            fallback_df = fallback_df.sort_values(
                ["ev", "max_down_streak", "profit", "score", "winrate"],
                ascending=[False, True, False, False, False]
            ).reset_index(drop=True)

            need_last = TOP_WINDOWS - len(selected_df)
            if need_last > 0 and len(fallback_df) > 0:
                fb_take = fallback_df.head(need_last).copy()
                fb_take["pick_source"] = "fallback_by_ev"
                selected_df = pd.concat([selected_df, fb_take], ignore_index=True)

    selected_df = selected_df.head(TOP_WINDOWS).copy()
    selected = selected_df["window"].astype(int).tolist()

    return selected, full_rank_df, selected_df


# ---------------- AGGREGATE WINDOWS ACROSS LOCK RANGE ----------------
def aggregate_best_windows(groups, lock_start, lock_end):
    per_round_rows = []
    agg = defaultdict(lambda: {
        "appear_count": 0,
        "profit_sum": 0.0,
        "score_sum": 0.0,
        "hybrid_sum": 0.0,
        "winrate_sum": 0.0,
        "ev_sum": 0.0,
        "streak_sum": 0.0,
        "positive_count": 0,
        "edge_count": 0,
        "rounds": [],
    })

    for r in range(lock_start, lock_end + 1):
        train_groups = groups[:r]
        selected, _, selected_df = select_top_windows_for_round(train_groups)

        rank_map = {w: idx + 1 for idx, w in enumerate(selected)}

        for _, row in selected_df.iterrows():
            w = int(row["window"])
            agg[w]["appear_count"] += 1
            agg[w]["profit_sum"] += float(row["profit"])
            agg[w]["score_sum"] += float(row["score"])
            agg[w]["hybrid_sum"] += float(row["hybrid_score"])
            agg[w]["winrate_sum"] += float(row["winrate"])
            agg[w]["ev_sum"] += float(row["ev"])
            agg[w]["streak_sum"] += float(row["max_down_streak"])
            agg[w]["rounds"].append(r)

            if float(row["profit"]) > 0:
                agg[w]["positive_count"] += 1
            if float(row["ev"]) >= MIN_EV and float(row["winrate"]) >= MIN_WINRATE:
                agg[w]["edge_count"] += 1

            per_round_rows.append({
                "lock_round": r,
                "window": w,
                "rank_in_round": rank_map[w],
                "profit": float(row["profit"]),
                "score": float(row["score"]),
                "hybrid_score": float(row["hybrid_score"]),
                "winrate": float(row["winrate"]),
                "ev": float(row["ev"]),
                "max_down_streak": float(row["max_down_streak"]),
                "pick_source": row.get("pick_source", ""),
            })

    summary_rows = []
    for w, v in agg.items():
        appear = v["appear_count"]
        avg_profit = v["profit_sum"] / appear
        avg_score = v["score_sum"] / appear
        avg_hybrid = v["hybrid_sum"] / appear
        avg_winrate = v["winrate_sum"] / appear
        avg_ev = v["ev_sum"] / appear
        avg_streak = v["streak_sum"] / appear
        positive_ratio = v["positive_count"] / appear
        edge_ratio = v["edge_count"] / appear

        aggregate_score = (
            appear * FREQ_WEIGHT
            + avg_profit * AVG_PROFIT_WEIGHT
            + avg_ev * AVG_EV_WEIGHT
            + avg_winrate * AVG_WINRATE_WEIGHT
            + avg_score * AVG_SCORE_WEIGHT
            - avg_streak * AVG_STREAK_PENALTY
            + positive_ratio * 10
            + edge_ratio * 12
        )

        summary_rows.append({
            "window": w,
            "appear_count": appear,
            "avg_profit": avg_profit,
            "avg_score": avg_score,
            "avg_hybrid_score": avg_hybrid,
            "avg_winrate": avg_winrate,
            "avg_ev": avg_ev,
            "avg_max_down_streak": avg_streak,
            "positive_ratio": positive_ratio,
            "edge_ratio": edge_ratio,
            "aggregate_score": aggregate_score,
            "rounds_seen": ", ".join(map(str, v["rounds"][:15])) + ("..." if len(v["rounds"]) > 15 else ""),
        })

    summary_df = pd.DataFrame(summary_rows).sort_values(
        ["aggregate_score", "edge_ratio", "appear_count", "avg_profit", "avg_ev"],
        ascending=[False, False, False, False, False]
    ).reset_index(drop=True)

    locked_windows = summary_df.head(TOP_WINDOWS)["window"].astype(int).tolist()
    per_round_df = pd.DataFrame(per_round_rows).sort_values(
        ["lock_round", "rank_in_round"],
        ascending=[True, True]
    ).reset_index(drop=True)

    return locked_windows, summary_df, per_round_df


# ---------------- DYNAMIC VOTE ----------------
def get_effective_vote_required(window_count: int) -> int:
    if window_count >= 6:
        return 4
    return 3


# ---------------- STATE INIT ----------------
def init_state():
    defaults = {
        "live_initialized": False,
        "processed_until": None,
        "profit": 0.0,
        "last_trade": -999,
        "hits": [],
        "history_rows": [],
        "locked_windows": [],
        "window_summary_df": pd.DataFrame(),
        "window_per_round_df": pd.DataFrame(),
        "base_data_len": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()

# ---------------- RESET ----------------
if st.button("🔄 Reset Session"):
    keys_to_clear = [
        "live_initialized",
        "processed_until",
        "profit",
        "last_trade",
        "hits",
        "history_rows",
        "locked_windows",
        "window_summary_df",
        "window_per_round_df",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

if (
    st.session_state.base_data_len is not None
    and len(groups) < st.session_state.base_data_len
):
    keys_to_clear = [
        "live_initialized",
        "processed_until",
        "profit",
        "last_trade",
        "hits",
        "history_rows",
        "locked_windows",
        "window_summary_df",
        "window_per_round_df",
        "base_data_len",
    ]
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

# ---------------- INITIAL LOCK ONLY ONCE ----------------
start_index = LOCK_ROUND_END

if not st.session_state.live_initialized:
    locked_windows, window_summary_df, window_per_round_df = aggregate_best_windows(
        groups, LOCK_ROUND_START, LOCK_ROUND_END
    )

    st.session_state.locked_windows = locked_windows
    st.session_state.window_summary_df = window_summary_df
    st.session_state.window_per_round_df = window_per_round_df
    st.session_state.processed_until = LOCK_ROUND_END - 1
    st.session_state.base_data_len = len(groups)
    st.session_state.live_initialized = True

# ---------------- PROCESS ONLY NEW ROUNDS ----------------
profit = st.session_state.profit
last_trade = st.session_state.last_trade
hits = st.session_state.hits
history_rows = st.session_state.history_rows
locked_windows = st.session_state.locked_windows
window_summary_df = st.session_state.window_summary_df
window_per_round_df = st.session_state.window_per_round_df
processed_until = st.session_state.processed_until

effective_vote_required = get_effective_vote_required(len(locked_windows))

for i in range(processed_until + 1, len(groups)):
    if i < start_index:
        continue

    preds = [groups[i - w] for w in locked_windows if i - w >= 0]
    if not preds:
        processed_until = i
        continue

    vote, confidence = Counter(preds).most_common(1)[0]

    signal = confidence >= effective_vote_required
    distance = i - last_trade

    if profit >= PROFIT_TARGET:
        signal = False
        trade = False
        can_bet = False
        state = "STOP"
    else:
        trade = signal and distance >= GAP
        can_bet = trade
        state = "TRADE" if trade else ("SIGNAL" if signal else "WAIT")

    bet_group = vote if can_bet else None
    hit = None

    if trade:
        last_trade = i

        if groups[i] == vote:
            hit = 1
            profit += WIN
            hits.append(1)
        else:
            hit = 0
            profit += LOSS
            hits.append(0)

    history_rows.append(
        {
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
            "profit": profit,
            "locked_windows": ", ".join(map(str, locked_windows)),
        }
    )

    processed_until = i

st.session_state.profit = profit
st.session_state.last_trade = last_trade
st.session_state.hits = hits
st.session_state.history_rows = history_rows
st.session_state.locked_windows = locked_windows
st.session_state.window_summary_df = window_summary_df
st.session_state.window_per_round_df = window_per_round_df
st.session_state.processed_until = processed_until
st.session_state.base_data_len = len(groups)

hist = pd.DataFrame(history_rows)

# ---------------- NEXT BET ----------------
next_round = len(groups)
preds = [groups[next_round - w] for w in locked_windows if next_round - w >= 0]

if preds:
    vote, confidence = Counter(preds).most_common(1)[0]
else:
    vote, confidence = None, 0

current_number = numbers[-1] if numbers else None
current_group = groups[-1] if groups else None

if not hist.empty:
    last_trade_rows = hist[hist["trade"] == True]
    distance = next_round - last_trade_rows["round"].max() if len(last_trade_rows) > 0 else 999
else:
    distance = 999

raw_signal = confidence >= effective_vote_required if vote is not None else False

if profit >= PROFIT_TARGET:
    signal = False
    can_bet = False
    next_state = "STOP"
else:
    signal = raw_signal
    can_bet = signal and distance >= GAP
    next_state = "NEXT"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "vote": vote,
    "confidence": confidence,
    "signal": signal,
    "trade": False,
    "bet_group": vote if can_bet else None,
    "hit": None,
    "state": next_state,
    "profit": profit,
    "locked_windows": ", ".join(map(str, locked_windows)),
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ---------------- UI ----------------
st.title("🎯 Rolling Prediction Engine - Range Lock + EV Filter")

col1, col2, col3 = st.columns(3)
col1.metric("Current Number", current_number if current_number is not None else "-")
col2.metric("Current Group", current_group if current_group is not None else "-")
col3.metric("Next Group", vote if vote is not None else "-")

st.divider()
st.write("Vote Strength:", confidence)
st.write("Distance From Last Trade:", distance)
st.write("Locked Windows:", locked_windows)
st.write("Lock Round Range:", f"{LOCK_ROUND_START} → {LOCK_ROUND_END}")
st.write("Profit Target:", PROFIT_TARGET)
st.write("Vote Required (effective):", effective_vote_required)
st.write("Min Window Profit:", MIN_WINDOW_PROFIT)
st.write("Min Winrate:", MIN_WINRATE)
st.write("Min EV:", MIN_EV)
st.write("Processed Until Round:", processed_until)

st.markdown(
    f"""
    <div style="background:#ffd700;
    padding:20px;
    border-radius:10px;
    text-align:center;
    font-size:28px;
    font-weight:bold;">
    NEXT GROUP → {vote if vote is not None else "-"} (Vote Strength: {confidence})
    </div>
    """,
    unsafe_allow_html=True,
)

if profit >= PROFIT_TARGET:
    st.error(f"🛑 STOP - Reached Profit Target {PROFIT_TARGET}")
elif can_bet and vote is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;
        padding:25px;
        border-radius:10px;
        text-align:center;
        font-size:32px;
        color:white;
        font-weight:bold;">
        BET GROUP → {vote}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info("WAIT (conditions not met)")

# ---------------- SESSION STATS ----------------
st.subheader("Session Statistics")
s1, s2, s3 = st.columns(3)
s1.metric("Profit", profit)
s2.metric("Trades", len(hits))
s3.metric("Winrate %", round(np.mean(hits) * 100, 2) if hits else 0)

# ---------------- PROFIT CURVE ----------------
st.subheader("Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["profit"])

# ---------------- WINDOW SUMMARY ----------------
st.subheader("Window Summary Across Lock Rounds")
st.dataframe(window_summary_df, use_container_width=True)

st.subheader("Per-Round Top Windows (168→204)")
st.dataframe(window_per_round_df, use_container_width=True)

# ---------------- HISTORY ----------------
st.subheader("History")

def highlight_trade(row):
    if row["state"] == "NEXT":
        return ["background-color: #ffd700"] * len(row)
    if row["state"] == "STOP":
        return ["background-color: #d9534f; color:white"] * len(row)
    if row["trade"]:
        return ["background-color: #ff4b4b; color:white"] * len(row)
    return [""] * len(row)

st.dataframe(
    hist_display.iloc[::-1].style.apply(highlight_trade, axis=1),
    use_container_width=True,
)

# ---------------- DEBUG ----------------
st.write("Locked Windows (final from range):", locked_windows)
st.write("Total Rows:", len(numbers))
