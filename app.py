import time
import math
import json
import os
from collections import Counter

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="LOCK75 FINAL LIVE ENGINE", layout="wide")
st_autorefresh(interval=5000, key="refresh")

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
STATE_FILE = "/tmp/lock75_final_live_engine.json"

LOCK_ROWS = 75
MAX_SOURCE_ROWS = 500

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PATTERN_LEN_MIN = 4
PATTERN_LEN_MAX = 6

# CORE
MIN_TRADES = 5
MIN_WR = 0.33
MIN_PROFIT = 1.0
MIN_SCORE = 5.0

# RECENT
RECENT_ROUNDS = 50
RECENT_MIN_PROFIT = 0.0
RECENT_WR_MIN = 0.25

# BREAK
PATTERN_BREAK_STREAK_LIMIT = 3
MAX_LOSS_STREAK_ALLOWED = 3

# DOMINANCE
DOMINANCE_MIN = 0.03
PROFIT_GAP_MIN = 0.5

# TRANSITION
ENABLE_TRANSITION_FILTER = True
TRANSITION_MIN_COUNT = 2
TRANSITION_DOMINANCE_MIN = 0.08

# LIGHT RUBBISH FILTER
PROFIT_PER_TRADE_MIN = -0.05
MAX_PATTERN_DRAWDOWN = 999.0

RECENT_CHECK_N = 3
RECENT_HIT_MIN = 1

# LIVE RISK
RISK_RECENT_N = 6
RISK_RECENT_STOP = -6.0
RISK_COOLDOWN_ROUNDS = 3

REAL_LIVE_LOSS_STREAK_STOP = 2
REAL_LIVE_COOLDOWN_ROUNDS = 10

SHOW_HISTORY_ROWS = 100
SHOW_TOP_PATTERNS = 60

BAD_PATTERN_SIDES = {
    ("AABB", "D"),
    ("ABBCC", "C"),
    ("ABCAD", "D"),
}


# =========================
# STATE
# =========================
def default_state():
    return {
        "real_live_profit": 0.0,
        "pending_bet": None,
        "settled_rounds": [],
        "real_live_history": [],
        "live_cooldown": 0,
    }


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            base = default_state()
            base.update(data)
            return base

        except Exception:
            return default_state()

    return default_state()


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# =========================
# LIVE LOSS STREAK
# =========================
def real_live_loss_streak(state):
    hist = state.get("real_live_history", [])

    streak = 0

    for x in reversed(hist):
        if x.get("pnl", 0) < 0:
            streak += 1
        else:
            break

    return streak


# =========================
# LOAD DATA
# =========================
@st.cache_data(ttl=5, show_spinner=False)
def load_data():

    url = (
        f"https://docs.google.com/spreadsheets/d/"
        f"{SHEET_ID}/export?format=csv&t={int(time.time() // 5)}"
    )

    df = pd.read_csv(url)

    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet phải có cột number")
        st.stop()

    nums_full = (
        pd.to_numeric(df["number"], errors="coerce")
        .dropna()
        .astype(int)
        .tolist()
    )

    nums_full = [x for x in nums_full if 1 <= x <= 12]

    total_round = len(nums_full)

    if len(nums_full) > MAX_SOURCE_ROWS:
        nums = nums_full[-MAX_SOURCE_ROWS:]
        start_round = total_round - len(nums) + 1
    else:
        nums = nums_full
        start_round = 1

    round_ids = list(range(start_round, start_round + len(nums)))

    return nums, round_ids, total_round


def group_of(n):

    if 1 <= n <= 3:
        return 1

    if 4 <= n <= 6:
        return 2

    if 7 <= n <= 9:
        return 3

    return 4


# =========================
# PATTERN NORMALIZE
# =========================
def groups_to_pattern(seq):

    mapping = {}
    reverse = {}

    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    out = []

    for g in seq:

        if g not in mapping:
            label = labels[len(mapping)]
            mapping[g] = label
            reverse[label] = g

        out.append(mapping[g])

    return "".join(out), reverse


def labels_in_pattern(pattern):
    return sorted(set(pattern))


# =========================
# PATTERN STATS
# =========================
def calc_pattern_stats(groups, pattern, bet_label):

    L = len(pattern)

    trades = 0
    wins = 0
    profit = 0.0

    results = []
    equity = []

    running = 0.0

    for i in range(L - 1, len(groups) - 1):

        tail = groups[i - L + 1 : i + 1]

        p, reverse = groups_to_pattern(tail)

        if p != pattern:
            continue

        if bet_label not in reverse:
            continue

        pred_group = reverse[bet_label]
        actual_group = groups[i + 1]

        hit = 1 if pred_group == actual_group else 0

        pnl = WIN_GROUP if hit else LOSS_GROUP

        trades += 1
        wins += hit
        profit += pnl

        running += pnl

        results.append(hit)
        equity.append(running)

    wr = wins / trades if trades else 0.0

    cur_loss = 0
    max_loss = 0

    for r in results:

        if r == 0:
            cur_loss += 1
            max_loss = max(max_loss, cur_loss)
        else:
            cur_loss = 0

    current_loss_streak = 0

    for r in reversed(results):

        if r == 0:
            current_loss_streak += 1
        else:
            break

    recent_results = results[-RECENT_CHECK_N:]
    recent_hits = sum(recent_results)

    max_drawdown = 0.0
    peak = 0.0

    for v in equity:

        peak = max(peak, v)
        max_drawdown = max(max_drawdown, peak - v)

    profit_per_trade = profit / trades if trades else 0.0

    return {
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "profit": profit,
        "profit_per_trade": profit_per_trade,
        "current_loss_streak": current_loss_streak,
        "max_loss_streak": max_loss,
        "recent_hits": recent_hits,
        "recent_check_count": len(recent_results),
        "min_equity": min(equity) if equity else 0.0,
        "max_equity": max(equity) if equity else 0.0,
        "max_drawdown": max_drawdown,
    }


def recent_stats(groups, pattern, bet_label):

    return calc_pattern_stats(
        groups[-RECENT_ROUNDS:],
        pattern,
        bet_label,
    )


# =========================
# TRANSITION
# =========================
def transition_stats(groups, tail, pred_group):

    L = len(tail)

    counts = Counter()

    for i in range(L - 1, len(groups) - 1):

        if groups[i - L + 1 : i + 1] == tail:
            counts[groups[i + 1]] += 1

    total = sum(counts.values())

    if total == 0:
        return {
            "transition_count": 0,
            "transition_top_group": None,
            "transition_top_ratio": 0.0,
            "transition_dominance": 0.0,
            "transition_ok": False,
        }

    ranked = counts.most_common()

    top_group, top_count = ranked[0]

    second_count = ranked[1][1] if len(ranked) > 1 else 0

    top_ratio = top_count / total
    second_ratio = second_count / total

    dominance = top_ratio - second_ratio

    return {
        "transition_count": total,
        "transition_top_group": top_group,
        "transition_top_ratio": top_ratio,
        "transition_dominance": dominance,
        "transition_ok": (
            total >= TRANSITION_MIN_COUNT
            and pred_group == top_group
            and dominance >= TRANSITION_DOMINANCE_MIN
        ),
    }


# =========================
# BROKEN
# =========================
def pattern_is_broken(stat, recent):

    return (
        stat["current_loss_streak"]
        >= PATTERN_BREAK_STREAK_LIMIT
        and recent["profit"] <= 0
    )


# =========================
# SCORE
# =========================
def score_pattern(stat, recent, trans):

    trades = stat["trades"]

    wr = stat["wr"]
    profit = stat["profit"]

    recent_wr = recent["wr"]
    recent_profit = recent["profit"]

    score = 0.0

    score += profit * 1.3
    score += recent_profit * 3.8

    score += stat["profit_per_trade"] * 5.0

    score += wr * 4.0
    score += recent_wr * 8.0

    score += math.log1p(trades) * 2.5

    score -= stat["max_loss_streak"] * 1.5
    score -= stat["current_loss_streak"] * 2.5

    score -= abs(min(stat["min_equity"], 0)) * 0.5

    score -= stat["max_drawdown"] * 0.25

    if trans["transition_ok"]:

        score += trans["transition_dominance"] * 10.0

        score += trans["transition_top_ratio"] * 3.0

    if stat["min_equity"] >= 0:
        score += 2.0

    if stat["recent_hits"] >= RECENT_HIT_MIN:
        score += 1.5

    if trades <= 6 and wr >= 0.90:
        score -= 5.0

    if trades < MIN_TRADES:
        score -= (MIN_TRADES - trades) * 5.0

    return score


# =========================
# BEST SIDE
# =========================
def add_side_strength_fields(rows):

    grouped = {}

    for r in rows:
        grouped.setdefault(
            (r["pattern"], r["len"], tuple(r["tail"])),
            [],
        ).append(r)

    clean_rows = []

    for _, items in grouped.items():

        by_profit = sorted(
            items,
            key=lambda x: x["profit"],
            reverse=True,
        )

        by_score = sorted(
            items,
            key=lambda x: x["score"],
            reverse=True,
        )

        best_profit = by_profit[0]["profit"]

        second_profit = (
            by_profit[1]["profit"]
            if len(by_profit) > 1
            else 0.0
        )

        for r in items:

            r["profit_gap"] = (
                best_profit - second_profit
                if r["profit"] == best_profit
                else 0.0
            )

            r["is_best_side"] = r is by_score[0]

        clean_rows.append(by_score[0])

    return clean_rows


# =========================
# TAIL MATCH
# =========================
def current_tail_candidates(groups):

    rows = []

    for L in range(
        PATTERN_LEN_MIN,
        PATTERN_LEN_MAX + 1,
    ):

        if len(groups) < L:
            continue

        tail = groups[-L:]

        pattern, reverse = groups_to_pattern(tail)

        for bet_label in labels_in_pattern(pattern):

            if bet_label not in reverse:
                continue

            if (pattern, bet_label) in BAD_PATTERN_SIDES:
                continue

            bet_group = reverse[bet_label]

            stat = calc_pattern_stats(
                groups,
                pattern,
                bet_label,
            )

            recent = recent_stats(
                groups,
                pattern,
                bet_label,
            )

            trans = transition_stats(
                groups,
                tail,
                bet_group,
            )

            broken = pattern_is_broken(stat, recent)

            score = score_pattern(
                stat,
                recent,
                trans,
            )

            rows.append({
                "pattern": pattern,
                "len": L,
                "bet_label": bet_label,
                "bet_group": bet_group,
                "tail": tail,
                "trades": stat["trades"],
                "wins": stat["wins"],
                "wr": stat["wr"],
                "profit": stat["profit"],
                "profit_per_trade": stat["profit_per_trade"],
                "recent_wr": recent["wr"],
                "recent_profit": recent["profit"],
                "recent_hits": stat["recent_hits"],
                "recent_check_count": stat["recent_check_count"],
                "current_loss_streak": stat["current_loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "min_equity": stat["min_equity"],
                "max_drawdown": stat["max_drawdown"],
                "broken": broken,
                "transition_count": trans["transition_count"],
                "transition_top_group": trans["transition_top_group"],
                "transition_top_ratio": trans["transition_top_ratio"],
                "transition_dominance": trans["transition_dominance"],
                "transition_ok": trans["transition_ok"],
                "score": score,
            })

    rows = add_side_strength_fields(rows)

    return sorted(
        rows,
        key=lambda x: x["score"],
        reverse=True,
    )


# =========================
# CHOOSE SIGNAL
# =========================
def choose_signal(groups):

    matches = current_tail_candidates(groups)

    if not matches:
        return None, "WAIT_NO_PATTERN", matches

    for m in matches:

        if m["len"] >= 6 and m["trades"] < 8:
            continue

        if m["trades"] < MIN_TRADES:
            continue

        if m["wr"] < MIN_WR:
            continue

        if m["profit"] < MIN_PROFIT:
            continue

        if (
            m["profit_per_trade"]
            < PROFIT_PER_TRADE_MIN
        ):
            continue

        if (
            m["recent_profit"]
            < RECENT_MIN_PROFIT
        ):
            continue

        if (
            m["recent_wr"]
            < RECENT_WR_MIN
        ):
            continue

        if (
            m["profit_gap"]
            < PROFIT_GAP_MIN
        ):
            continue

        if (
            m["max_drawdown"]
            > MAX_PATTERN_DRAWDOWN
        ):
            continue

        if m["broken"]:
            continue

        if (
            m["max_loss_streak"]
            > MAX_LOSS_STREAK_ALLOWED
        ):
            continue

        if (
            m["current_loss_streak"]
            >= PATTERN_BREAK_STREAK_LIMIT
        ):
            continue

        if m["min_equity"] <= -6:
            continue

        if ENABLE_TRANSITION_FILTER:

            if (
                m["transition_count"]
                >= TRANSITION_MIN_COUNT
                and not m["transition_ok"]
            ):
                continue

        if m["score"] < MIN_SCORE:
            continue

        return m, "READY", matches

    return None, "WAIT_PATTERN_FILTERED", matches


# =========================
# BACKTEST
# =========================
@st.cache_data(ttl=5, show_spinner=False)
def simulate_lock75_backtest(groups_tuple):

    groups = list(groups_tuple)

    rows = []

    profit = 0.0
    peak = 0.0

    cooldown = 0

    for target_idx in range(
        LOCK_ROWS,
        len(groups),
    ):

        train = groups[:target_idx]

        actual = groups[target_idx]

        sig = None

        state = "WAIT"

        trade = False

        bet_group = None
        hit = None

        pnl = 0.0

        if cooldown > 0:

            state = "WAIT_RISK_COOLDOWN"

            cooldown -= 1

        else:

            sig, state, _ = choose_signal(train)

            if sig is not None:

                trade = True

                bet_group = sig["bet_group"]

                hit = (
                    1
                    if bet_group == actual
                    else 0
                )

                pnl = (
                    WIN_GROUP
                    if hit
                    else LOSS_GROUP
                )

                profit += pnl

                peak = max(peak, profit)

                state = "LIVE_TRADE"

        rows.append({
            "row": target_idx + 1,
            "train_until_row": target_idx,
            "actual_group": actual,
            "pattern": (
                sig["pattern"]
                if sig else None
            ),
            "bet_label": (
                sig["bet_label"]
                if sig else None
            ),
            "bet_group": bet_group,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "live_profit": profit,
            "peak_profit": peak,
            "drawdown": peak - profit,
            "state": state,
        })

        trade_hist = [
            r for r in rows
            if r["trade"]
        ]

        if len(trade_hist) >= RISK_RECENT_N:

            recent_sum = sum(
                r["pnl"]
                for r in trade_hist[-RISK_RECENT_N:]
            )

            if recent_sum <= RISK_RECENT_STOP:
                cooldown = RISK_COOLDOWN_ROUNDS

    return pd.DataFrame(rows)


# =========================
# LIVE LEDGER
# =========================
def settle_pending(
    state,
    groups,
    round_ids,
    current_round,
):

    pending = state.get("pending_bet")

    if pending is None:
        return state

    target = pending["target_round"]

    settled = set(
        state.get("settled_rounds", [])
    )

    if (
        current_round >= target
        and target not in settled
    ):

        if target in round_ids:

            idx = round_ids.index(target)

            actual_group = groups[idx]

            bet_group = pending["bet_group"]

            hit = (
                1
                if actual_group == bet_group
                else 0
            )

            pnl = (
                WIN_GROUP
                if hit
                else LOSS_GROUP
            )

            state["real_live_profit"] = (
                float(
                    state.get(
                        "real_live_profit",
                        0.0,
                    )
                )
                + pnl
            )

            settled.add(target)

            state["settled_rounds"] = sorted(
                list(settled)
            )

            state["real_live_history"].append({
                "created_round":
                    pending["created_round"],
                "target_round":
                    target,
                "pattern":
                    pending["pattern"],
                "bet_label":
                    pending["bet_label"],
                "bet_group":
                    bet_group,
                "actual_group":
                    actual_group,
                "hit":
                    hit,
                "pnl":
                    pnl,
                "real_live_profit":
                    state["real_live_profit"],
            })

            state["pending_bet"] = None

    return state


def create_pending(
    state,
    signal,
    current_round,
):

    if signal is None:
        return state

    if state.get("pending_bet") is not None:
        return state

    state["pending_bet"] = {
        "created_round": current_round,
        "target_round": current_round + 1,
        "bet_group": signal["bet_group"],
        "pattern": signal["pattern"],
        "bet_label": signal["bet_label"],
        "score": round(signal["score"], 2),
    }

    return state


# =========================
# MAIN
# =========================
numbers, round_ids, total_round = load_data()

groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROWS + 5:

    st.error(
        f"Chưa đủ dữ liệu. "
        f"Hiện có {len(groups)} ván."
    )

    st.stop()

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("Reset REAL LIVE"):
    save_state(default_state())
    st.rerun()

state_data = load_state()

current_round = total_round

current_number = numbers[-1]
current_group = groups[-1]

state_data = settle_pending(
    state_data,
    groups,
    round_ids,
    current_round,
)

hist = simulate_lock75_backtest(tuple(groups))

bt_profit = (
    round(
        hist["live_profit"].iloc[-1],
        2,
    )
    if not hist.empty
    else 0.0
)

bt_trades = (
    int(hist["trade"].sum())
    if not hist.empty
    else 0
)

bt_wr = (
    round(
        hist.loc[
            hist["trade"],
            "hit",
        ].mean() * 100,
        2,
    )
    if bt_trades
    else 0.0
)

peak_profit = (
    round(
        hist["peak_profit"].max(),
        2,
    )
    if not hist.empty
    else 0.0
)

drawdown_now = (
    round(
        hist["drawdown"].iloc[-1],
        2,
    )
    if not hist.empty
    else 0.0
)

signal, state, matches = choose_signal(groups)

recent_live_profit = 0.0

if not hist.empty:

    trade_hist = hist[
        hist["trade"] == True
    ]

    if len(trade_hist) >= RISK_RECENT_N:

        recent_live_profit = float(
            trade_hist
            .tail(RISK_RECENT_N)["pnl"]
            .sum()
        )

        if (
            recent_live_profit
            <= RISK_RECENT_STOP
        ):

            signal = None

            state = "WAIT_LIVE_RECENT_WEAK"

# =========================
# LIVE TOTAL LOSS STOP
# =========================
live_loss_streak = real_live_loss_streak(
    state_data
)

if (
    live_loss_streak
    >= REAL_LIVE_LOSS_STREAK_STOP
):

    signal = None

    state = "WAIT_REAL_LIVE_COOLDOWN"

    state_data["live_cooldown"] = (
        REAL_LIVE_COOLDOWN_ROUNDS
    )

if state_data["live_cooldown"] > 0:

    signal = None

    state = (
        f"WAIT_COOLDOWN_"
        f"{state_data['live_cooldown']}"
    )

    state_data["live_cooldown"] -= 1

if (
    current_round >= LOCK_ROWS
    and signal is not None
):

    state_data = create_pending(
        state_data,
        signal,
        current_round,
    )

save_state(state_data)

# =========================
# UI
# =========================
st.title(
    "LOCK75 FINAL LIVE ENGINE"
)

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Current Round",
    current_round,
)

c2.metric(
    "Current Number",
    current_number,
)

c3.metric(
    "Current Group",
    current_group,
)

c4.metric(
    "Next Round",
    current_round + 1,
)

p1, p2, p3, p4 = st.columns(4)

p1.metric(
    "REAL LIVE PROFIT",
    round(
        state_data["real_live_profit"],
        2,
    ),
)

p2.metric(
    "Backtest Profit",
    bt_profit,
)

p3.metric(
    "Backtest Trades",
    bt_trades,
)

p4.metric(
    "Backtest WR %",
    bt_wr,
)

q1, q2, q3, q4 = st.columns(4)

q1.metric(
    "Peak Profit",
    peak_profit,
)

q2.metric(
    "Drawdown",
    drawdown_now,
)

q3.metric(
    "Recent Live Profit",
    round(
        recent_live_profit,
        2,
    ),
)

q4.metric(
    "Live Loss Streak",
    live_loss_streak,
)

st.metric("State", state)

st.subheader("NEXT BET")

if signal:

    st.success(
        f"READY BET NEXT GROUP "
        f"{signal['bet_group']} | "
        f"Pattern {signal['pattern']} | "
        f"Score {round(signal['score'], 2)}"
    )

    a, b, c, d = st.columns(4)

    a.metric(
        "NEXT GROUP",
        signal["bet_group"],
    )

    b.metric(
        "Pattern",
        signal["pattern"],
    )

    c.metric(
        "WR %",
        round(
            signal["wr"] * 100,
            2,
        ),
    )

    d.metric(
        "Score",
        round(
            signal["score"],
            2,
        ),
    )

else:

    st.warning(f"WAIT - {state}")

st.subheader(
    "Backtest Profit Curve"
)

if not hist.empty:

    st.line_chart(
        hist[["live_profit"]]
        .reset_index(drop=True)
    )

st.subheader(
    "Backtest History"
)

if not hist.empty:

    st.dataframe(
        hist.iloc[::-1]
        .head(SHOW_HISTORY_ROWS),
        use_container_width=True,
    )

st.subheader(
    "Matched Tail Patterns"
)

if matches:

    dfm = pd.DataFrame(matches)

    dfm["wr"] = (
        dfm["wr"] * 100
    ).round(2)

    dfm["recent_wr"] = (
        dfm["recent_wr"] * 100
    ).round(2)

    st.dataframe(
        dfm,
        use_container_width=True,
    )
