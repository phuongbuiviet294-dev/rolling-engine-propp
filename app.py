# =========================================================
# AUTO RELOCK ENGINE | FULL FIX VERSION
# =========================================================

import time
import json
import os
from collections import Counter

import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================================================
# PAGE
# =========================================================
st.set_page_config(
    page_title="AUTO RELOCK ENGINE FIX",
    layout="wide"
)

st_autorefresh(interval=5000, key="refresh")

# =========================================================
# DATA
# =========================================================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# =========================================================
# LOCK
# =========================================================
LOCK_ROUND_START = 168
LOCK_ROUND_END = 180
REPLAY_FROM = 180

# =========================================================
# MODES
# =========================================================
MODES = [
    {
        "name": "8v4",
        "top_windows": 8,
        "vote_required": 4,
        "window_min": 6,
        "window_max": 22,
    },
]

# =========================================================
# CORE
# =========================================================
GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

ENABLE_COLOR_BET = False

WIN_COLOR = 1.5
LOSS_COLOR = -1.0

COLOR_VOTE_OFFSET = 0

# =========================================================
# PHASE SETTINGS
# =========================================================
PHASE_BET_UNIT = 1.0
COLOR_BET_UNIT = 1.0

PHASE_STOP_WIN = 44
PHASE_STOP_LOSS = -2.0

# thua liên tiếp
PHASE_LOSS_STREAK_RELOCK = 2

# pause phase khi thua chuỗi
ENABLE_PHASE_PAUSE = True

# chỉ mở lại nếu profit hồi
PHASE_RECOVER_PROFIT = 0.0

# phase âm => không trade
PHASE_MIN_TOTAL_PNL_TO_TRADE = 0.0

MIN_PHASE_AGE_TO_TRADE = 4

MAX_PHASE_TRADES = 8

RECENT_PHASE_CHECK = 5

PHASE_MIN_RECENT_PNL_TO_TRADE = 0.0

VOTE_DOMINANCE_RATIO = 0.60

KEEP_AFTER_LOSS_ROUNDS = 0

SESSION_STOP_WIN = 15.0
SESSION_STOP_LOSS = -10.0

# =========================================================
# WINDOW FILTER
# =========================================================
MIN_FALLBACK_SCORE = 1

MIN_TRADES_PER_WINDOW = 26

RECENT_WINDOW_SIZE = 33

MIN_WINDOW_SPACING = 1

AUTO_SCAN_WINDOW_SPACING = True

WINDOW_SPACING_MIN = 1
WINDOW_SPACING_MAX = 5

MAX_CANDIDATE_WINDOWS = 8

VALIDATE_LEN = 16

AUTO_SCAN_VALIDATE_LEN = True

VALIDATE_LEN_LIST = [12, 16, 20]

MIN_TRAIN_LEN = 100

MIN_VALIDATE_TRADES = 2

VALIDATE_MIN_DRAWDOWN = -6

# =========================================================
# DISPLAY
# =========================================================
SHOW_HISTORY_ROWS = 12

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=10, show_spinner=False)
def load_numbers():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&cache={time.time()}"
    )

    df = pd.read_csv(url)

    df.columns = [str(c).strip().lower() for c in df.columns]

    df["number"] = pd.to_numeric(
        df["number"],
        errors="coerce"
    )

    nums = (
        df["number"]
        .dropna()
        .astype(int)
        .tolist()
    )

    return [x for x in nums if 1 <= x <= 12]

# =========================================================
# GROUP / COLOR
# =========================================================
def group_of(n):

    if n <= 3:
        return 1

    if n <= 6:
        return 2

    if n <= 9:
        return 3

    return 4


def color_of_number(n):

    if n <= 4:
        return 1

    if n <= 8:
        return 2

    return 3


def color_text(c):

    if c == 1:
        return "RED"

    if c == 2:
        return "GREEN"

    if c == 3:
        return "BLUE"

    return "-"

# =========================================================
# HELPERS
# =========================================================
def compute_max_drawdown(results):

    if not results:
        return 0.0

    profit = 0.0
    peak = 0.0
    max_dd = 0.0

    for r in results:

        if r == 1:
            profit += WIN_GROUP
        else:
            profit += LOSS_GROUP

        peak = max(peak, profit)

        max_dd = min(max_dd, profit - peak)

    return max_dd


def get_valid_group_preds(seq_groups, i, windows):

    preds = []

    for w in windows:

        if i - w >= 0:

            pred = seq_groups[i - w]

            if seq_groups[i - 1] != pred:
                preds.append(pred)

    return preds


def vote_dominance_ok(preds, confidence):

    if not preds:
        return False, 0.0

    ratio = confidence / len(preds)

    return ratio >= VOTE_DOMINANCE_RATIO, ratio

# =========================================================
# WINDOW EVAL
# =========================================================
def evaluate_window_group(seq_groups, w):

    profit = 0.0

    trades = 0

    wins = 0

    results = []

    for i in range(w, len(seq_groups)):

        pred = seq_groups[i - w]

        if seq_groups[i - 1] != pred:

            trades += 1

            if seq_groups[i] == pred:

                profit += WIN_GROUP

                wins += 1

                results.append(1)

            else:

                profit += LOSS_GROUP

                results.append(0)

    if trades == 0:

        return {
            "window": w,
            "score": -999999,
            "profit": 0,
            "trades": 0,
            "winrate": 0,
            "drawdown": 0,
        }

    winrate = wins / trades

    drawdown = compute_max_drawdown(results)

    score = (
        profit * 1.2
        + winrate * 10
        - abs(drawdown) * 0.7
    )

    return {
        "window": w,
        "score": score,
        "profit": profit,
        "trades": trades,
        "winrate": winrate,
        "drawdown": drawdown,
    }

# =========================================================
# BUILD WINDOWS
# =========================================================
def build_best_windows(groups):

    rows = []

    for w in range(6, 23):

        rows.append(
            evaluate_window_group(groups, w)
        )

    df = pd.DataFrame(rows)

    df = df[df["trades"] >= MIN_TRADES_PER_WINDOW]

    df = df.sort_values(
        ["score", "profit", "winrate"],
        ascending=False
    )

    windows = []

    for _, row in df.iterrows():

        w = int(row["window"])

        ok = True

        for x in windows:

            if abs(w - x) < MIN_WINDOW_SPACING:
                ok = False
                break

        if ok:
            windows.append(w)

        if len(windows) >= 8:
            break

    return windows, df

# =========================================================
# ENGINE
# =========================================================
def simulate_engine(numbers, groups):

    locked_windows, scan_df = build_best_windows(groups)

    if not locked_windows:

        return {
            "hist": pd.DataFrame(),
            "scan_df": pd.DataFrame(),
        }

    history_rows = []

    phase_profit_group = 0.0

    total_phase_profit_all = 0.0

    phase_consecutive_losses = 0

    phase_paused = False

    phase_index = 1

    phase_trade_count = 0

    for i in range(REPLAY_FROM, len(groups)):

        round_no = i + 1

        preds = get_valid_group_preds(
            groups,
            i,
            locked_windows
        )

        if preds:

            vote_group, confidence = (
                Counter(preds)
                .most_common(1)[0]
            )

            dominance_ok, ratio = vote_dominance_ok(
                preds,
                confidence
            )

            signal = (
                confidence >= 4
                and dominance_ok
            )

        else:

            vote_group = None
            confidence = 0
            ratio = 0
            signal = False

        recent_rows = history_rows[-RECENT_PHASE_CHECK:]

        recent_pnl = sum(
            x["phase_pnl_group"]
            for x in recent_rows
            if x["phase"] == phase_index
        )

        phase_trade_allowed = signal

        # =================================================
        # FIX 1
        # phase âm => wait
        # =================================================
        if phase_profit_group < PHASE_MIN_TOTAL_PNL_TO_TRADE:
            phase_trade_allowed = False

        # =================================================
        # FIX 2
        # pause phase sau chuỗi thua
        # =================================================
        if phase_paused:

            phase_trade_allowed = False

            if phase_profit_group >= PHASE_RECOVER_PROFIT:
                phase_paused = False

        # =================================================
        # FIX 3
        # warmup
        # =================================================
        if phase_trade_count < MIN_PHASE_AGE_TO_TRADE:
            phase_trade_allowed = False

        # =================================================
        # FIX 4
        # recent pnl âm => wait
        # =================================================
        if recent_pnl < PHASE_MIN_RECENT_PNL_TO_TRADE:
            phase_trade_allowed = False

        # =================================================
        # BET
        # =================================================
        if phase_trade_allowed:

            phase_trade_count += 1

            if groups[i] == vote_group:

                hit = 1

                pnl = WIN_GROUP

            else:

                hit = 0

                pnl = LOSS_GROUP

            # FIX PROFIT DOUBLE
            phase_profit_group += pnl

            total_phase_profit_all += pnl

            # =================================================
            # WIN
            # =================================================
            if hit == 1:

                phase_consecutive_losses = 0

                if phase_profit_group >= PHASE_RECOVER_PROFIT:
                    phase_paused = False

            # =================================================
            # LOSS
            # =================================================
            else:

                phase_consecutive_losses += 1

                if (
                    ENABLE_PHASE_PAUSE
                    and phase_consecutive_losses >= PHASE_LOSS_STREAK_RELOCK
                ):
                    phase_paused = True

            state = "BET"

        else:

            hit = None

            pnl = 0.0

            if phase_paused:
                state = "WAIT_PHASE_RECOVER"

            elif not signal:
                state = "WAIT_NO_SIGNAL"

            elif phase_profit_group < 0:
                state = "WAIT_NEGATIVE_PHASE"

            else:
                state = "WAIT"

        # =================================================
        # RELOCK
        # =================================================
        relock = False

        if (
            phase_profit_group <= PHASE_STOP_LOSS
            and not phase_paused
        ):

            relock = True

        if phase_profit_group >= PHASE_STOP_WIN:

            relock = True

        if phase_trade_count >= MAX_PHASE_TRADES:

            relock = True

        # =================================================
        # SAVE
        # =================================================
        history_rows.append({

            "round": round_no,

            "phase": phase_index,

            "number": numbers[i],

            "group": groups[i],

            "vote_group": vote_group,

            "confidence": confidence,

            "dominance_ratio": round(ratio, 2),

            "signal": signal,

            "PHASE_BET": phase_trade_allowed,

            "phase_hit_group": hit,

            "phase_pnl_group": pnl,

            "phase_profit_group": phase_profit_group,

            "total_phase_profit_all": total_phase_profit_all,

            "phase_consecutive_losses": phase_consecutive_losses,

            "phase_paused": phase_paused,

            "state": state,

            "locked_windows": ",".join(map(str, locked_windows)),
        })

        # =================================================
        # RESET PHASE
        # =================================================
        if relock:

            phase_index += 1

            phase_profit_group = 0.0

            phase_trade_count = 0

            phase_consecutive_losses = 0

            phase_paused = False

    hist = pd.DataFrame(history_rows)

    return {
        "hist": hist,
        "scan_df": scan_df,
        "locked_windows": locked_windows,
    }

# =========================================================
# RUN
# =========================================================
numbers = load_numbers()

groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:

    st.error("NOT ENOUGH DATA")

    st.stop()

sim = simulate_engine(
    numbers,
    groups
)

hist = sim["hist"]

if hist.empty:

    st.error("NO RESULT")

    st.stop()

# =========================================================
# UI
# =========================================================
st.title("AUTO RELOCK ENGINE FIX")

last = hist.iloc[-1]

# =========================================================
# METRICS
# =========================================================
c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "TOTAL PROFIT",
    round(float(last["total_phase_profit_all"]), 2)
)

c2.metric(
    "PHASE PROFIT",
    round(float(last["phase_profit_group"]), 2)
)

c3.metric(
    "LOSS STREAK",
    int(last["phase_consecutive_losses"])
)

c4.metric(
    "STATE",
    str(last["state"])
)

# =========================================================
# NEXT
# =========================================================
st.subheader("NEXT ROUND")

next_idx = len(groups)

preds = get_valid_group_preds(
    groups,
    next_idx,
    sim["locked_windows"]
)

if preds:

    vote_group, confidence = (
        Counter(preds)
        .most_common(1)[0]
    )

    dominance_ok, ratio = vote_dominance_ok(
        preds,
        confidence
    )

    next_signal = (
        confidence >= 4
        and dominance_ok
    )

else:

    vote_group = None

    confidence = 0

    ratio = 0

    next_signal = False

phase_paused = bool(last["phase_paused"])

phase_profit = float(last["phase_profit_group"])

next_allowed = next_signal

if phase_profit < 0:
    next_allowed = False

if phase_paused:
    next_allowed = False

# =========================================================
# READY PANEL
# =========================================================
if next_allowed:

    st.markdown(
        f"""
        <div style="
        background:#ff3333;
        padding:25px;
        border-radius:12px;
        text-align:center;
        color:white;
        font-size:34px;
        font-weight:bold;
        ">
        READY BET<br>
        GROUP {vote_group}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.markdown(
        f"""
        <div style="
        background:#333;
        padding:25px;
        border-radius:12px;
        text-align:center;
        color:white;
        font-size:28px;
        font-weight:bold;
        ">
        WAIT
        </div>
        """,
        unsafe_allow_html=True
    )

# =========================================================
# CHART
# =========================================================
st.subheader("PROFIT CURVE")

st.line_chart(
    hist[
        [
            "phase_profit_group",
            "total_phase_profit_all"
        ]
    ]
)

# =========================================================
# WINDOWS
# =========================================================
with st.expander("WINDOW DETAIL"):

    st.dataframe(
        sim["scan_df"],
        use_container_width=True
    )

# =========================================================
# HISTORY
# =========================================================
st.subheader("HISTORY")

show_cols = [

    "round",
    "phase",
    "number",
    "group",
    "vote_group",
    "confidence",
    "dominance_ratio",
    "signal",
    "PHASE_BET",
    "phase_hit_group",
    "phase_pnl_group",
    "phase_profit_group",
    "total_phase_profit_all",
    "phase_consecutive_losses",
    "phase_paused",
    "state",
]

st.dataframe(
    hist[show_cols]
    .iloc[::-1]
    .head(SHOW_HISTORY_ROWS),
    use_container_width=True
)
