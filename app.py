import time
import math
from collections import Counter

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="ABCD Pattern Live Engine Optimized Real Live", layout="wide")
st_autorefresh(interval=10000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_ROWS = 75
MAX_SOURCE_ROWS = 300

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PATTERN_LEN_MIN = 4
PATTERN_LEN_MAX = 6

MIN_TRADES = 5
MIN_WR = 0.34
MIN_PROFIT = 1.5
MIN_SCORE = 10.0

RECENT_ROUNDS = 80
RECENT_MIN_PROFIT = 0.5
RECENT_WR_MIN = 0.30

PATTERN_BREAK_STREAK_LIMIT = 2
MAX_LOSS_STREAK_ALLOWED = 3

DOMINANCE_MIN = 0.05
PROFIT_GAP_MIN = 1.0

ENABLE_TRANSITION_FILTER = True
TRANSITION_MIN_COUNT = 3
TRANSITION_DOMINANCE_MIN = 0.08

LIVE_RECENT_N = 6
LIVE_RECENT_STOP = -3.0

SESSION_PROFIT_TARGET = 10.0
SESSION_STOP_LOSS = -6.0
SESSION_MAX_DRAWDOWN_FROM_PEAK = 5.0

SHOW_HISTORY_ROWS = 40
SHOW_TOP_PATTERNS = 30

BAD_PATTERN_SIDES = {
    ("AABB", "B"),
    ("AABB", "D"),
    ("ABAACC", "A"),
    ("ABAACC", "B"),
    ("ABBCC", "A"),
    ("ABBCC", "C"),
    ("ABBAA", "B"),
    ("ABBC", "A"),
}


@st.cache_data(ttl=5, show_spinner=False)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={int(time.time() // 5)}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet phải có cột number")
        st.stop()

    nums = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()
    nums = [x for x in nums if 1 <= x <= 12]

    if len(nums) > MAX_SOURCE_ROWS:
        nums = nums[-MAX_SOURCE_ROWS:]

    return nums


def group_of(n):
    if 1 <= n <= 3:
        return 1
    if 4 <= n <= 6:
        return 2
    if 7 <= n <= 9:
        return 3
    return 4


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


def calc_pattern_stats(groups, pattern, bet_label):
    L = len(pattern)
    trades = 0
    wins = 0
    profit = 0.0
    results = []
    equity = []
    running = 0.0

    for i in range(L - 1, len(groups) - 1):
        tail = groups[i - L + 1:i + 1]
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

    wr = wins / trades if trades > 0 else 0.0

    current_loss_streak = 0
    max_loss_streak = 0
    cur_loss = 0

    for r in results:
        if r == 0:
            cur_loss += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_loss = 0

    for r in reversed(results):
        if r == 0:
            current_loss_streak += 1
        else:
            break

    return {
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "profit": profit,
        "results": results,
        "current_loss_streak": current_loss_streak,
        "max_loss_streak": max_loss_streak,
        "last_result": results[-1] if results else None,
        "min_equity": min(equity) if equity else 0.0,
        "max_equity": max(equity) if equity else 0.0,
        "end_equity": equity[-1] if equity else 0.0,
    }


def recent_stats(groups, pattern, bet_label):
    return calc_pattern_stats(groups[-RECENT_ROUNDS:], pattern, bet_label)


def transition_stats(groups, tail, pred_group):
    L = len(tail)
    counts = Counter()

    for i in range(L - 1, len(groups) - 1):
        if groups[i - L + 1:i + 1] == tail:
            counts[groups[i + 1]] += 1

    total = sum(counts.values())

    if total == 0:
        return {
            "transition_count": 0,
            "transition_top_group": None,
            "transition_top_rate": 0.0,
            "transition_second_rate": 0.0,
            "transition_dominance": 0.0,
            "transition_pred_rate": 0.0,
            "transition_ok": False,
        }

    ranked = counts.most_common()
    top_group, top_count = ranked[0]
    second_count = ranked[1][1] if len(ranked) > 1 else 0

    top_rate = top_count / total
    second_rate = second_count / total
    dominance = top_rate - second_rate
    pred_rate = counts.get(pred_group, 0) / total

    ok = (
        total >= TRANSITION_MIN_COUNT
        and pred_group == top_group
        and dominance >= TRANSITION_DOMINANCE_MIN
    )

    return {
        "transition_count": total,
        "transition_top_group": top_group,
        "transition_top_rate": top_rate,
        "transition_second_rate": second_rate,
        "transition_dominance": dominance,
        "transition_pred_rate": pred_rate,
        "transition_ok": ok,
    }


def pattern_is_broken(stat, recent):
    if stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT:
        if recent["profit"] <= 0:
            return True
    return False


def score_pattern(stat, recent, transition):
    trades = stat["trades"]
    wr = stat["wr"]
    profit = stat["profit"]
    recent_wr = recent["wr"]
    recent_profit = recent["profit"]

    trade_factor = math.log1p(max(trades, 0))

    low_sample_penalty = 0.0
    if trades < MIN_TRADES:
        low_sample_penalty = (MIN_TRADES - trades) * 5.0

    fake_wr_penalty = 0.0
    if trades <= 7 and wr >= 0.80:
        fake_wr_penalty = 6.0

    broken_penalty = 8.0 if stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT else 0.0

    transition_bonus = 0.0
    if transition["transition_ok"]:
        transition_bonus = transition["transition_dominance"] * 10.0

    stability_bonus = 2.0 if stat["min_equity"] >= 0 else 0.0

    return (
        recent_profit * 4.0
        + profit * 1.3
        + recent_wr * 8.0
        + wr * 4.0
        + trade_factor * 3.0
        + transition_bonus
        + stability_bonus
        - stat["max_loss_streak"] * 1.5
        - stat["current_loss_streak"] * 3.0
        - abs(min(stat["min_equity"], 0)) * 0.8
        - low_sample_penalty
        - fake_wr_penalty
        - broken_penalty
    )


def add_dominance_fields(rows):
    grouped = {}

    for r in rows:
        key = (r["pattern"], r["len"])
        grouped.setdefault(key, []).append(r)

    for _, items in grouped.items():
        sorted_by_profit = sorted(items, key=lambda x: x["profit"], reverse=True)
        sorted_by_wr = sorted(items, key=lambda x: x["wr"], reverse=True)

        best_profit = sorted_by_profit[0]["profit"] if sorted_by_profit else 0.0
        second_profit = sorted_by_profit[1]["profit"] if len(sorted_by_profit) > 1 else 0.0

        best_wr = sorted_by_wr[0]["wr"] if sorted_by_wr else 0.0
        second_wr = sorted_by_wr[1]["wr"] if len(sorted_by_wr) > 1 else 0.0

        for r in items:
            r["profit_gap"] = best_profit - second_profit if r["profit"] == best_profit else 0.0
            r["dominance"] = best_wr - second_wr if r["wr"] == best_wr else 0.0
            r["is_best_side"] = r["profit"] == best_profit

    return rows


def current_tail_candidates(groups):
    rows = []

    for L in range(PATTERN_LEN_MIN, PATTERN_LEN_MAX + 1):
        if len(groups) < L:
            continue

        tail = groups[-L:]
        pattern, reverse = groups_to_pattern(tail)

        if len(set(pattern)) > 4:
            continue

        for bet_label in labels_in_pattern(pattern):
            if bet_label not in reverse:
                continue

            if (pattern, bet_label) in BAD_PATTERN_SIDES:
                continue

            bet_group = reverse[bet_label]
            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)
            trans = transition_stats(groups, tail, bet_group)
            broken = pattern_is_broken(stat, recent)
            sc = score_pattern(stat, recent, trans)

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
                "recent_wr": recent["wr"],
                "recent_profit": recent["profit"],
                "current_loss_streak": stat["current_loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "last_result": stat["last_result"],
                "min_equity": stat["min_equity"],
                "max_equity": stat["max_equity"],
                "broken": broken,
                "transition_count": trans["transition_count"],
                "transition_top_group": trans["transition_top_group"],
                "transition_top_rate": trans["transition_top_rate"],
                "transition_dominance": trans["transition_dominance"],
                "transition_pred_rate": trans["transition_pred_rate"],
                "transition_ok": trans["transition_ok"],
                "score": sc,
            })

    rows = add_dominance_fields(rows)
    rows = sorted(rows, key=lambda x: x["score"], reverse=True)
    return rows


def choose_signal(groups):
    matches = current_tail_candidates(groups)

    if not matches:
        return None, "WAIT_NO_PATTERN", matches

    for m in matches:
        if not m["is_best_side"]:
            continue
        if m["trades"] < MIN_TRADES:
            continue
        if m["wr"] < MIN_WR:
            continue
        if m["profit"] < MIN_PROFIT:
            continue
        if m["recent_profit"] < RECENT_MIN_PROFIT:
            continue
        if m["recent_wr"] < RECENT_WR_MIN:
            continue
        if m["dominance"] < DOMINANCE_MIN:
            continue
        if m["profit_gap"] < PROFIT_GAP_MIN:
            continue
        if m["broken"]:
            continue
        if m["max_loss_streak"] > MAX_LOSS_STREAK_ALLOWED:
            continue
        if m["profit"] <= 0:
            continue
        if m["recent_profit"] < 0:
            continue
        if m["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT:
            continue
        if m["min_equity"] <= -5:
            continue

        if ENABLE_TRANSITION_FILTER:
            if m["transition_count"] >= TRANSITION_MIN_COUNT and not m["transition_ok"]:
                continue

        if m["score"] < MIN_SCORE:
            continue

        return m, "READY", matches

    return None, "WAIT_PATTERN_WEAK_OR_BROKEN", matches


@st.cache_data(ttl=5, show_spinner=False)
def simulate_live_from_lock_cached(groups_tuple):
    groups = list(groups_tuple)
    rows = []

    live_profit = 0.0
    peak_profit = 0.0
    session_stopped = False
    stop_reason = None

    start_idx = max(LOCK_ROWS, PATTERN_LEN_MAX)

    for target_idx in range(start_idx, len(groups)):
        train_groups = groups[:target_idx]
        actual_group = groups[target_idx]

        sig = None
        state = "WAIT"
        trade = False
        pred_group = None
        hit = None
        pnl = 0.0

        if session_stopped:
            state = stop_reason
        else:
            sig, state, _ = choose_signal(train_groups)

            if sig is not None:
                trade = True
                pred_group = sig["bet_group"]
                hit = 1 if pred_group == actual_group else 0
                pnl = WIN_GROUP if hit else LOSS_GROUP
                live_profit += pnl
                peak_profit = max(peak_profit, live_profit)
                state = "LIVE_TRADE"

                drawdown = peak_profit - live_profit

                if live_profit >= SESSION_PROFIT_TARGET:
                    session_stopped = True
                    stop_reason = "STOP_PROFIT_TARGET"
                elif live_profit <= SESSION_STOP_LOSS:
                    session_stopped = True
                    stop_reason = "STOP_SESSION_LOSS"
                elif drawdown >= SESSION_MAX_DRAWDOWN_FROM_PEAK:
                    session_stopped = True
                    stop_reason = "STOP_DRAWDOWN_FROM_PEAK"

        rows.append({
            "round": target_idx + 1,
            "train_until_round": target_idx,
            "actual_group": actual_group,
            "pattern": sig["pattern"] if sig else None,
            "pattern_len": sig["len"] if sig else None,
            "tail": str(sig["tail"]) if sig else None,
            "bet_label": sig["bet_label"] if sig else None,
            "bet_group": pred_group,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "live_profit": live_profit,
            "peak_profit": peak_profit,
            "drawdown_from_peak": peak_profit - live_profit,
            "state": state,
            "score": round(sig["score"], 2) if sig else None,
            "wr": round(sig["wr"] * 100, 2) if sig else None,
            "recent_wr": round(sig["recent_wr"] * 100, 2) if sig else None,
            "pattern_profit": round(sig["profit"], 2) if sig else None,
            "recent_profit": round(sig["recent_profit"], 2) if sig else None,
            "dominance": round(sig["dominance"], 3) if sig else None,
            "profit_gap": round(sig["profit_gap"], 2) if sig else None,
            "min_equity": round(sig["min_equity"], 2) if sig else None,
            "current_loss_streak": sig["current_loss_streak"] if sig else None,
            "max_loss_streak": sig["max_loss_streak"] if sig else None,
            "transition_count": sig["transition_count"] if sig else None,
            "transition_top_group": sig["transition_top_group"] if sig else None,
            "transition_dominance": round(sig["transition_dominance"], 3) if sig else None,
            "broken": sig["broken"] if sig else None,
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=30, show_spinner=False)
def discover_top_patterns_cached(groups_tuple):
    groups = list(groups_tuple)
    groups = groups[-220:]
    pattern_set = set()

    for L in range(PATTERN_LEN_MIN, PATTERN_LEN_MAX + 1):
        for i in range(L - 1, len(groups)):
            tail = groups[i - L + 1:i + 1]
            pattern, _ = groups_to_pattern(tail)
            if len(set(pattern)) <= 4:
                pattern_set.add(pattern)

    rows = []

    for pattern in sorted(pattern_set):
        for bet_label in labels_in_pattern(pattern):
            if (pattern, bet_label) in BAD_PATTERN_SIDES:
                continue

            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)
            dummy_trans = {"transition_ok": False, "transition_dominance": 0.0}
            sc = score_pattern(stat, recent, dummy_trans)
            broken = pattern_is_broken(stat, recent)

            rows.append({
                "pattern": pattern,
                "len": len(pattern),
                "bet": bet_label,
                "trades": stat["trades"],
                "wins": stat["wins"],
                "wr": round(stat["wr"] * 100, 2),
                "profit": round(stat["profit"], 2),
                "recent_wr": round(recent["wr"] * 100, 2),
                "recent_profit": round(recent["profit"], 2),
                "current_loss_streak": stat["current_loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "min_equity": round(stat["min_equity"], 2),
                "broken": broken,
                "score": round(sc, 2),
            })

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df[df["trades"] >= MIN_TRADES]
        df = df.sort_values(
            ["score", "profit", "wr", "trades"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)

    return df.head(SHOW_TOP_PATTERNS)


# =========================================================
# MAIN
# =========================================================
numbers = load_data()
groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROWS + 5:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} ván, cần ít nhất {LOCK_ROWS + 5}.")
    st.stop()

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("Reset REAL LIVE"):
    st.session_state.real_live_profit = 0.0
    st.session_state.pending_bet = None
    st.session_state.settled_rounds = set()
    st.session_state.real_live_history = []
    st.rerun()

# Init real live state
if "real_live_profit" not in st.session_state:
    st.session_state.real_live_profit = 0.0
if "pending_bet" not in st.session_state:
    st.session_state.pending_bet = None
if "settled_rounds" not in st.session_state:
    st.session_state.settled_rounds = set()
if "real_live_history" not in st.session_state:
    st.session_state.real_live_history = []

current_round = len(groups)
current_group = groups[-1]

# Settle pending bet from previous READY
pending = st.session_state.pending_bet

if pending is not None:
    target_round = pending["target_round"]

    if current_round >= target_round and target_round not in st.session_state.settled_rounds:
        actual_group = groups[target_round - 1]
        bet_group = pending["bet_group"]
        hit = 1 if actual_group == bet_group else 0
        pnl = WIN_GROUP if hit else LOSS_GROUP

        st.session_state.real_live_profit += pnl
        st.session_state.settled_rounds.add(target_round)

        st.session_state.real_live_history.append({
            "created_round": pending["created_round"],
            "target_round": target_round,
            "pattern": pending["pattern"],
            "bet_label": pending["bet_label"],
            "bet_group": bet_group,
            "actual_group": actual_group,
            "hit": hit,
            "pnl": pnl,
            "real_live_profit": st.session_state.real_live_profit,
        })

        st.session_state.pending_bet = None

signal, state, matches = choose_signal(groups)
hist = simulate_live_from_lock_cached(tuple(groups))

recent_live_profit = 0.0
if not hist.empty and int(hist["trade"].sum()) >= LIVE_RECENT_N:
    recent_live_profit = hist[hist["trade"] == True].tail(LIVE_RECENT_N)["pnl"].sum()

if recent_live_profit <= LIVE_RECENT_STOP:
    signal = None
    state = "WAIT_LIVE_RECENT_WEAK"

# Create pending bet for next round
if signal is not None:
    pending = st.session_state.pending_bet

    if pending is None or pending.get("created_round") != current_round:
        st.session_state.pending_bet = {
            "created_round": current_round,
            "target_round": current_round + 1,
            "bet_group": signal["bet_group"],
            "pattern": signal["pattern"],
            "bet_label": signal["bet_label"],
            "score": round(signal["score"], 2),
        }

live_profit = round(hist["live_profit"].iloc[-1], 2) if not hist.empty else 0.0
live_trades = int(hist["trade"].sum()) if not hist.empty else 0
live_wr = round(hist.loc[hist["trade"], "hit"].mean() * 100, 2) if live_trades > 0 else 0.0
peak_profit = round(hist["peak_profit"].max(), 2) if not hist.empty else 0.0
drawdown_now = round(hist["drawdown_from_peak"].iloc[-1], 2) if not hist.empty else 0.0

# =========================================================
# UI
# =========================================================
st.title("ABCD PATTERN LIVE ENGINE | OPTIMIZED REAL LIVE")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Round", current_round)
c2.metric("Current Number", numbers[-1])
c3.metric("Current Group", current_group)
c4.metric("Next Round", current_round + 1)

p1, p2, p3, p4 = st.columns(4)
p1.metric("Backtest Profit", live_profit)
p2.metric("Backtest Trades", live_trades)
p3.metric("Backtest WR %", live_wr)
p4.metric("State", state)

r1, r2, r3 = st.columns(3)
r1.metric("REAL LIVE PROFIT", round(st.session_state.real_live_profit, 2))
r2.metric("Peak Profit", peak_profit)
r3.metric("Recent Backtest Profit", round(recent_live_profit, 2))

st.subheader("REAL LIVE TRACKING")
st.write("Pending Bet:", st.session_state.pending_bet)
st.write("Settled Rounds:", sorted(list(st.session_state.settled_rounds))[-10:])

if st.session_state.real_live_history:
    st.dataframe(
        pd.DataFrame(st.session_state.real_live_history).iloc[::-1].head(20),
        use_container_width=True,
    )

with st.expander("CONFIG"):
    st.write("LOCK_ROWS:", LOCK_ROWS)
    st.write("MAX_SOURCE_ROWS:", MAX_SOURCE_ROWS)
    st.write("PATTERN_LEN:", f"{PATTERN_LEN_MIN} → {PATTERN_LEN_MAX}")
    st.write("MIN_TRADES:", MIN_TRADES)
    st.write("MIN_WR:", MIN_WR)
    st.write("MIN_PROFIT:", MIN_PROFIT)
    st.write("RECENT_MIN_PROFIT:", RECENT_MIN_PROFIT)
    st.write("RECENT_WR_MIN:", RECENT_WR_MIN)
    st.write("DOMINANCE_MIN:", DOMINANCE_MIN)
    st.write("PROFIT_GAP_MIN:", PROFIT_GAP_MIN)
    st.write("MAX_LOSS_STREAK_ALLOWED:", MAX_LOSS_STREAK_ALLOWED)
    st.write("MIN_SCORE:", MIN_SCORE)
    st.write("LIVE_RECENT_N:", LIVE_RECENT_N)
    st.write("LIVE_RECENT_STOP:", LIVE_RECENT_STOP)

st.subheader("NEXT BET")

if signal:
    st.success(
        f"READY BET NEXT GROUP {signal['bet_group']} | "
        f"Pattern {signal['pattern']} | "
        f"Tail {signal['tail']} | "
        f"Bet {signal['bet_label']} | "
        f"Score {round(signal['score'], 2)}"
    )

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("NEXT BET GROUP", signal["bet_group"])
    n2.metric("Pattern", signal["pattern"])
    n3.metric("WR %", round(signal["wr"] * 100, 2))
    n4.metric("Score", round(signal["score"], 2))

    st.write("Tail Groups:", signal["tail"])
    st.write("Bet Label:", signal["bet_label"])
    st.write("Trades:", signal["trades"])
    st.write("Wins:", signal["wins"])
    st.write("Profit:", round(signal["profit"], 2))
    st.write("Recent WR %:", round(signal["recent_wr"] * 100, 2))
    st.write("Recent Profit:", round(signal["recent_profit"], 2))
    st.write("Dominance:", round(signal["dominance"], 3))
    st.write("Profit Gap:", round(signal["profit_gap"], 2))
    st.write("Min Equity:", round(signal["min_equity"], 2))
    st.write("Current Loss Streak:", signal["current_loss_streak"])
    st.write("Max Loss Streak:", signal["max_loss_streak"])
    st.write("Transition Count:", signal["transition_count"])
    st.write("Transition Top Group:", signal["transition_top_group"])
    st.write("Transition Dominance:", round(signal["transition_dominance"], 3))
    st.write("Broken:", signal["broken"])
else:
    st.warning(f"WAIT - {state}")

st.subheader("Matched Tail Patterns Ranking")

if matches:
    match_df = pd.DataFrame(matches)
    match_df["wr"] = (match_df["wr"] * 100).round(2)
    match_df["recent_wr"] = (match_df["recent_wr"] * 100).round(2)
    match_df["profit"] = match_df["profit"].round(2)
    match_df["recent_profit"] = match_df["recent_profit"].round(2)
    match_df["score"] = match_df["score"].round(2)
    match_df["dominance"] = match_df["dominance"].round(3)
    match_df["profit_gap"] = match_df["profit_gap"].round(2)
    match_df["transition_dominance"] = match_df["transition_dominance"].round(3)
    match_df["min_equity"] = match_df["min_equity"].round(2)
    st.dataframe(match_df, use_container_width=True)
else:
    st.info("Không có pattern nào match tail hiện tại.")

with st.expander("Discovered Top Patterns"):
    stats_df = discover_top_patterns_cached(tuple(groups))
    st.dataframe(stats_df, use_container_width=True)

st.subheader("Backtest Profit Curve")

if not hist.empty:
    st.line_chart(hist[["live_profit"]].tail(150).reset_index(drop=True))

st.subheader("Backtest History")

if not hist.empty:
    st.dataframe(
        hist.iloc[::-1].head(SHOW_HISTORY_ROWS),
        use_container_width=True,
    )
