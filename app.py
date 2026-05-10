import time
import math
import json
import os
from collections import Counter

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="REAL LIVE LOCK 75 ENGINE", layout="wide")
st_autorefresh(interval=5000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
STATE_FILE = "/tmp/real_live_state_lock75.json"

LOCK_ROWS = 75
MAX_SOURCE_ROWS = 500

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

SHOW_HISTORY_ROWS = 50

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


def default_state():
    return {
        "real_live_profit": 0.0,
        "pending_bet": None,
        "settled_rounds": [],
        "real_live_history": [],
    }


def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            base = default_state()
            base.update(data)
            return base
    except Exception:
        pass
    return default_state()


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@st.cache_data(ttl=5, show_spinner=False)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={int(time.time() // 5)}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet phải có cột number")
        st.stop()

    nums_full = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()
    nums_full = [x for x in nums_full if 1 <= x <= 12]

    total_round_full = len(nums_full)

    if len(nums_full) > MAX_SOURCE_ROWS:
        nums = nums_full[-MAX_SOURCE_ROWS:]
        start_round = total_round_full - len(nums) + 1
    else:
        nums = nums_full
        start_round = 1

    round_ids = list(range(start_round, start_round + len(nums)))
    return nums, round_ids, total_round_full


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
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

    wr = wins / trades if trades else 0.0

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
        "current_loss_streak": current_loss_streak,
        "max_loss_streak": max_loss_streak,
        "last_result": results[-1] if results else None,
        "min_equity": min(equity) if equity else 0.0,
        "max_equity": max(equity) if equity else 0.0,
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
            "transition_dominance": 0.0,
            "transition_ok": False,
        }

    ranked = counts.most_common()
    top_group, top_count = ranked[0]
    second_count = ranked[1][1] if len(ranked) > 1 else 0

    top_rate = top_count / total
    second_rate = second_count / total
    dominance = top_rate - second_rate

    ok = (
        total >= TRANSITION_MIN_COUNT
        and pred_group == top_group
        and dominance >= TRANSITION_DOMINANCE_MIN
    )

    return {
        "transition_count": total,
        "transition_top_group": top_group,
        "transition_dominance": dominance,
        "transition_ok": ok,
    }


def pattern_is_broken(stat, recent):
    return stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT and recent["profit"] <= 0


def score_pattern(stat, recent, transition):
    trades = stat["trades"]
    wr = stat["wr"]
    profit = stat["profit"]
    recent_wr = recent["wr"]
    recent_profit = recent["profit"]

    trade_factor = math.log1p(max(trades, 0))
    low_sample_penalty = (MIN_TRADES - trades) * 5.0 if trades < MIN_TRADES else 0.0
    fake_wr_penalty = 6.0 if trades <= 7 and wr >= 0.80 else 0.0
    broken_penalty = 8.0 if stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT else 0.0
    transition_bonus = transition["transition_dominance"] * 10.0 if transition["transition_ok"] else 0.0
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
                "min_equity": stat["min_equity"],
                "broken": broken,
                "transition_count": trans["transition_count"],
                "transition_top_group": trans["transition_top_group"],
                "transition_dominance": trans["transition_dominance"],
                "transition_ok": trans["transition_ok"],
                "score": sc,
            })

    rows = add_dominance_fields(rows)
    return sorted(rows, key=lambda x: x["score"], reverse=True)


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
def simulate_lock75_backtest(groups_tuple):
    groups = list(groups_tuple)
    rows = []
    live_profit = 0.0

    start_idx = max(LOCK_ROWS, PATTERN_LEN_MAX)

    for target_idx in range(start_idx, len(groups)):
        train_groups = groups[:target_idx]
        actual_group = groups[target_idx]

        sig, state, _ = choose_signal(train_groups)

        trade = sig is not None
        pred_group = None
        hit = None
        pnl = 0.0

        if trade:
            pred_group = sig["bet_group"]
            hit = 1 if pred_group == actual_group else 0
            pnl = WIN_GROUP if hit else LOSS_GROUP
            live_profit += pnl
            state = "LIVE_TRADE"

        rows.append({
            "row": target_idx + 1,
            "actual_group": actual_group,
            "pattern": sig["pattern"] if sig else None,
            "bet_group": pred_group,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "live_profit": live_profit,
            "state": state,
        })

    return pd.DataFrame(rows)


def settle_pending_if_ready(state, groups, round_ids, current_round):
    pending = state.get("pending_bet")

    if pending is None:
        return state

    target_round = pending["target_round"]
    settled = set(state.get("settled_rounds", []))

    if current_round >= target_round and target_round not in settled:
        if target_round in round_ids:
            idx = round_ids.index(target_round)
            actual_group = groups[idx]

            bet_group = pending["bet_group"]
            hit = 1 if actual_group == bet_group else 0
            pnl = WIN_GROUP if hit else LOSS_GROUP

            state["real_live_profit"] = float(state.get("real_live_profit", 0.0)) + pnl
            settled.add(target_round)
            state["settled_rounds"] = sorted(list(settled))

            state["real_live_history"].append({
                "created_round": pending["created_round"],
                "target_round": target_round,
                "pattern": pending["pattern"],
                "bet_label": pending["bet_label"],
                "bet_group": bet_group,
                "actual_group": actual_group,
                "hit": hit,
                "pnl": pnl,
                "real_live_profit": state["real_live_profit"],
            })

            state["pending_bet"] = None

    return state


def create_pending_if_signal(state, signal, current_round):
    if signal is None:
        return state

    pending = state.get("pending_bet")

    if pending is None:
        state["pending_bet"] = {
            "created_round": current_round,
            "target_round": current_round + 1,
            "bet_group": signal["bet_group"],
            "pattern": signal["pattern"],
            "bet_label": signal["bet_label"],
            "score": round(signal["score"], 2),
        }

    return state


# =========================================================
# MAIN
# =========================================================
numbers, round_ids, total_round_full = load_data()
groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROWS + 5:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} ván, cần ít nhất {LOCK_ROWS + 5}.")
    st.stop()

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("Reset REAL LIVE"):
    save_state(default_state())
    st.rerun()

state_data = load_state()

current_round = total_round_full
current_group = groups[-1]

state_data = settle_pending_if_ready(state_data, groups, round_ids, current_round)

signal, state, matches = choose_signal(groups)

# Chỉ tạo pending nếu đã qua LOCK_ROWS
if current_round >= LOCK_ROWS and signal is not None:
    state_data = create_pending_if_signal(state_data, signal, current_round)

save_state(state_data)

hist = simulate_lock75_backtest(tuple(groups))
backtest_profit = round(hist["live_profit"].iloc[-1], 2) if not hist.empty else 0.0
backtest_trades = int(hist["trade"].sum()) if not hist.empty else 0
backtest_wr = round(hist.loc[hist["trade"], "hit"].mean() * 100, 2) if backtest_trades > 0 else 0.0

# =========================================================
# UI
# =========================================================
st.title("REAL LIVE LOCK 75 GROUP PATTERN ENGINE")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Real Round", current_round)
c2.metric("Current Number", numbers[-1])
c3.metric("Current Group", current_group)
c4.metric("Next Round", current_round + 1)

p1, p2, p3, p4 = st.columns(4)
p1.metric("REAL LIVE PROFIT", round(state_data["real_live_profit"], 2))
p2.metric("Backtest Profit From 76", backtest_profit)
p3.metric("Backtest Trades", backtest_trades)
p4.metric("State", state)

st.subheader("REAL LIVE LEDGER")
st.write("Pending Bet:", state_data.get("pending_bet"))
st.write("Settled Rounds:", state_data.get("settled_rounds", [])[-20:])

if state_data.get("real_live_history"):
    st.dataframe(
        pd.DataFrame(state_data["real_live_history"]).iloc[::-1].head(30),
        use_container_width=True,
    )

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

st.subheader("Backtest Profit Curve From Row 76")

if not hist.empty:
    st.line_chart(hist[["live_profit"]].tail(150).reset_index(drop=True))

st.subheader("Backtest History")

if not hist.empty:
    st.dataframe(hist.iloc[::-1].head(SHOW_HISTORY_ROWS), use_container_width=True)
