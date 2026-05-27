# =========================================================
# FINAL WINDOW-CENTRIC ENGINE
# FULL STABLE VERSION
# =========================================================

import pandas as pd
import numpy as np
import streamlit as st

from streamlit_autorefresh import st_autorefresh

# =========================================================
# CONFIG
# =========================================================

PHASE_STOP_LOSS = -8.0

PHASE_TRAILING_STOP = 6.0

MIN_PHASE_TRADES_BEFORE_RELOCK = 12

RELOCK_SCAN_LEN = 35

VALIDATE_LEN = 24

MAX_CANDIDATE_WINDOWS = 8

CACHE_TTL = 60

AUTO_REFRESH_MS = 15000

# =========================================================
# WINDOW SCORE
# =========================================================

def calc_window_score(pnl_list):

    if not pnl_list:
        return -999999

    total_profit = sum(pnl_list)

    running = 0
    peak = 0
    max_drawdown = 0

    for p in pnl_list:

        running += p

        peak = max(
            peak,
            running
        )

        dd = peak - running

        max_drawdown = max(
            max_drawdown,
            dd
        )

    win_rate = (
        sum(
            1
            for x in pnl_list
            if x > 0
        )
        / len(pnl_list)
    )

    stability_bonus = (
        win_rate * 3.0
    )

    score = (
        total_profit
        - (max_drawdown * 1.5)
        + stability_bonus
    )

    return score

# =========================================================
# VALIDATE WINDOW
# =========================================================

def validate_window(
    numbers,
    start_idx,
    size
):

    pnl_hist = []

    running = 0

    end_idx = min(
        len(numbers),
        start_idx + VALIDATE_LEN
    )

    for i in range(
        start_idx,
        end_idx
    ):

        n = numbers[i]

        # SIMPLE DEMO LOGIC
        # replace with your real signal

        pnl = 1 if n % 2 == 0 else -1

        running += pnl

        pnl_hist.append(
            pnl
        )

    return {
        "pnl_history": pnl_hist,
        "profit": running,
    }

# =========================================================
# BUILD WINDOWS
# =========================================================

def build_candidate_windows(
    numbers
):

    candidates = []

    start_base = max(
        0,
        len(numbers)
        - RELOCK_SCAN_LEN
    )

    for size in range(4, 18):

        val = validate_window(
            numbers,
            start_base,
            size
        )

        score = calc_window_score(
            val["pnl_history"]
        )

        candidates.append(
            {
                "size": size,
                "score": score,
                "profit": val["profit"],
                "validate_pnl_history":
                    val["pnl_history"]
            }
        )

    candidates = sorted(
        candidates,
        key=lambda x: x["score"],
        reverse=True
    )

    return candidates[
        :MAX_CANDIDATE_WINDOWS
    ]

# =========================================================
# FIND BEST WINDOW
# =========================================================

def relock_best_window(
    candidates
):

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda x: x["score"],
        reverse=True
    )[0]

# =========================================================
# SIGNAL
# =========================================================

def get_signal(number):

    # replace with your real logic

    return (
        number % 2 == 0
    )

# =========================================================
# ENGINE
# =========================================================

def simulate_engine(numbers):

    history = []

    phase_profit_group = 0.0

    phase_peak_profit = 0.0

    phase_trade_count = 0

    total_phase_profit_all = 0.0

    locked_window = None

    candidates = build_candidate_windows(
        numbers
    )

    locked_window = relock_best_window(
        candidates
    )

    for idx, n in enumerate(numbers):

        signal_group = get_signal(n)

        phase_trade_allowed = (
            signal_group
        )

        pnl = 1 if signal_group else -1

        if phase_trade_allowed:

            phase_profit_group += pnl

            total_phase_profit_all += pnl

            phase_peak_profit = max(
                phase_peak_profit,
                phase_profit_group
            )

            phase_trade_count += 1

        relock_now = False

        relock_reason = None

        # =================================================
        # HARD STOP
        # =================================================

        if (
            phase_trade_count
            >= MIN_PHASE_TRADES_BEFORE_RELOCK
        ):

            if (
                phase_profit_group
                <= PHASE_STOP_LOSS
            ):

                relock_now = True

                relock_reason = (
                    "PHASE_STOP_LOSS"
                )

        # =================================================
        # TRAILING STOP
        # =================================================

        if (
            phase_trade_count
            >= MIN_PHASE_TRADES_BEFORE_RELOCK
        ):

            trailing_dd = (
                phase_peak_profit
                - phase_profit_group
            )

            if (
                trailing_dd
                >= PHASE_TRAILING_STOP
            ):

                relock_now = True

                relock_reason = (
                    "PHASE_TRAILING_STOP"
                )

        # =================================================
        # EXECUTE RELOCK
        # =================================================

        if relock_now:

            candidates = (
                build_candidate_windows(
                    numbers[
                        max(
                            0,
                            idx - RELOCK_SCAN_LEN
                        ):idx
                    ]
                )
            )

            locked_window = (
                relock_best_window(
                    candidates
                )
            )

            phase_profit_group = 0.0

            phase_peak_profit = 0.0

            phase_trade_count = 0

        history.append(
            {
                "round": idx,
                "number": n,
                "phase_profit_group":
                    phase_profit_group,
                "total_phase_profit_all":
                    total_phase_profit_all,
                "relock_reason":
                    relock_reason,
            }
        )

    return pd.DataFrame(history)

# =========================================================
# CACHE
# =========================================================

@st.cache_data(
    ttl=CACHE_TTL
)

def cached_simulate_engine(
    numbers_tuple
):

    return simulate_engine(
        list(numbers_tuple)
    )

# =========================================================
# STREAMLIT UI
# =========================================================

st.set_page_config(
    layout="wide"
)

st.title(
    "FINAL WINDOW ENGINE"
)

st_autorefresh(
    interval=AUTO_REFRESH_MS
)

# =========================================================
# INPUT
# =========================================================

default_numbers = list(
    np.random.randint(
        0,
        37,
        200
    )
)

numbers_text = st.text_area(
    "Numbers",
    ",".join(
        map(
            str,
            default_numbers
        )
    ),
    height=120
)

numbers = [
    int(x.strip())
    for x in numbers_text.split(",")
    if x.strip()
]

# =========================================================
# RUN ENGINE
# =========================================================

hist = cached_simulate_engine(
    tuple(numbers)
)

# =========================================================
# METRICS
# =========================================================

col1, col2, col3 = st.columns(3)

with col1:

    st.metric(
        "Phase Group Profit",
        round(
            hist[
                "phase_profit_group"
            ].iloc[-1],
            2
        )
    )

with col2:

    st.metric(
        "Total Phase Profit",
        round(
            hist[
                "total_phase_profit_all"
            ].iloc[-1],
            2
        )
    )

with col3:

    relock_count = (
        hist[
            "relock_reason"
        ]
        .notna()
        .sum()
    )

    st.metric(
        "Relock Count",
        int(relock_count)
    )

# =========================================================
# CHART
# =========================================================

chart_df = (
    hist.tail(120)
    .reset_index(drop=True)
)

st.subheader(
    "Profit Curve"
)

st.line_chart(
    chart_df[
        [
            "phase_profit_group",
            "total_phase_profit_all"
        ]
    ]
)

# =========================================================
# TABLE
# =========================================================

st.subheader(
    "History"
)

st.dataframe(
    hist.tail(50),
    use_container_width=True
)

# =========================================================
# DOWNLOAD
# =========================================================

csv = hist.to_csv(
    index=False
)

st.download_button(
    "Download History CSV",
    csv,
    file_name="history.csv",
    mime="text/csv"
)

# =========================================================
# END
# =========================================================
