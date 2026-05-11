import time
import math
import json
import os
from collections import Counter

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="LOCK75 REAL LIVE ENGINE FINAL", layout="wide")
st_autorefresh(interval=5000, key="refresh")

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
STATE_FILE = "/tmp/real_live_lock75_state.json"

LOCK_ROWS = 75
MAX_SOURCE_ROWS = 500

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PATTERN_LEN_MIN = 4
PATTERN_LEN_MAX = 6

# Core filter - tối ưu theo dữ liệu hiện tại
MIN_TRADES = 5
MIN_WR = 0.34
MIN_PROFIT = 1.5
MIN_SCORE = 6.0

RECENT_ROUNDS = 100
RECENT_MIN_PROFIT = 1.0
RECENT_WR_MIN = 0.31

PATTERN_BREAK_STREAK_LIMIT = 1
MAX_LOSS_STREAK_ALLOWED = 2

DOMINANCE_MIN = 0.05
PROFIT_GAP_MIN = 1.0

ENABLE_TRANSITION_FILTER = True
TRANSITION_MIN_COUNT = 3
TRANSITION_DOMINANCE_MIN = 0.06

LIVE_RECENT_N = 6
LIVE_RECENT_STOP = -3.0

SHOW_HISTORY_ROWS = 80
SHOW_TOP_PATTERNS = 50

BAD_PATTERN_SIDES = {
    ("AABB", "B"),
    ("AABB", "D"),
    ("ABAACC", "A"),
    ("ABAACC", "B"),
    ("ABBCC", "A"),
    ("ABBCC", "C"),
    ("ABBAA", "B"),
    ("ABBC", "A"),
    ("ABCCDD", "C"),
    ("ABCCDD", "D"),
}


# =========================
# STATE FILE
# =========================
def default_state():
    return {
        "real_live_profit": 0.0,
        "pending_bet": None,
        "settled_rounds": [],
        "real_live_history": [],
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
# LOAD DATA
# =========================
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
# PATTERN CORE
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

    return {
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "profit": profit,
        "current_loss_streak": current_loss_streak,
        "max_loss_streak": max_loss,
        "min_equity": min(equity) if equity else 0.0,
        "max_equity": max(equity) if equity else 0.0,
        "last_result": results[-1] if results else None,
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

    return {
        "transition_count": total,
        "transition_top_group": top_group,
        "transition_dominance": dominance,
        "transition_ok": (
            total >= TRANSITION_MIN_COUNT
            and pred_group == top_group
            and dominance >= TRANSITION_DOMINANCE_MIN
        ),
    }


def pattern_is_broken(stat, recent):
    return (
        stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT
        and recent["profit"] <= 0
    )


def score_pattern(stat, recent, trans):
    trades = stat["trades"]
    wr = stat["wr"]
    profit = stat["profit"]
    recent_wr = recent["wr"]
    recent_profit = recent["profit"]

    score = 0.0

    score += profit * 1.5
    score += recent_profit * 4.0

    score += wr * 5.0
    score += recent_wr * 10.0

    score += math.log1p(trades) * 3.0

    score -= stat["max_loss_streak"] * 2.0
    score -= stat["current_loss_streak"] * 4.0
    score -= abs(min(stat["min_equity"], 0)) * 0.8

    if trans["transition_ok"]:
        score += trans["transition_dominance"] * 12.0

    if stat["min_equity"] >= 0:
        score += 3.0

    if trades <= 7 and wr >= 0.80:
        score -= 8.0

    if trades < MIN_TRADES:
        score -= (MIN_TRADES - trades) * 6.0

    return score


def add_dominance_fields(rows):
    grouped = {}

    for r in rows:
        grouped.setdefault((r["pattern"], r["len"]), []).append(r)

    for _, items in grouped.items():
        by_profit = sorted(items, key=lambda x: x["profit"], reverse=True)
        by_wr = sorted(items, key=lambda x: x["wr"], reverse=True)

        best_profit = by_profit[0]["profit"]
        second_profit = by_profit[1]["profit"] if len(by_profit) > 1 else 0.0

        best_wr = by_wr[0]["wr"]
        second_wr = by_wr[1]["wr"] if len(by_wr) > 1 else 0.0

        for r in items:
            r["is_best_side"] = r["profit"] == best_profit
            r["profit_gap"] = best_profit - second_profit if r["is_best_side"] else 0.0
            r["dominance"] = best_wr - second_wr if r["wr"] == best_wr else 0.0

    return rows


def current_tail_candidates(groups):
    rows = []

    for L in range(PATTERN_LEN_MIN, PATTERN_LEN_MAX + 1):
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

            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)
            trans = transition_stats(groups, tail, bet_group)
            broken = pattern_is_broken(stat, recent)
            score = score_pattern(stat, recent, trans)

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
                "score": score,
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


# =========================
# BACKTEST LOCK75 - KHÔNG STOP CHART
# =========================
@st.cache_data(ttl=5, show_spinner=False)
def simulate_lock75_backtest(groups_tuple):
    groups = list(groups_tuple)
    rows = []

    profit = 0.0
    peak = 0.0

    for target_idx in range(LOCK_ROWS, len(groups)):
        train = groups[:target_idx]
        actual = groups[target_idx]

        sig, state, _ = choose_signal(train)

        trade = sig is not None
        bet_group = None
        hit = None
        pnl = 0.0

        if trade:
            bet_group = sig["bet_group"]
            hit = 1 if bet_group == actual else 0
            pnl = WIN_GROUP if hit else LOSS_GROUP
            profit += pnl
            peak = max(peak, profit)
            state = "LIVE_TRADE"

        rows.append({
            "row": target_idx + 1,
            "train_until_row": target_idx,
            "actual_group": actual,
            "pattern": sig["pattern"] if sig else None,
            "bet_label": sig["bet_label"] if sig else None,
            "bet_group": bet_group,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "live_profit": profit,
            "peak_profit": peak,
            "drawdown": peak - profit,
            "state": state,
            "score": round(sig["score"], 2) if sig else None,
            "wr": round(sig["wr"] * 100, 2) if sig else None,
            "recent_wr": round(sig["recent_wr"] * 100, 2) if sig else None,
            "pattern_profit": round(sig["profit"], 2) if sig else None,
            "recent_profit": round(sig["recent_profit"], 2) if sig else None,
        })

    return pd.DataFrame(rows)


# =========================
# REAL LIVE LEDGER
# =========================
def settle_pending(state, groups, round_ids, current_round):
    pending = state.get("pending_bet")

    if pending is None:
        return state

    target = pending["target_round"]
    settled = set(state.get("settled_rounds", []))

    if current_round >= target and target not in settled:
        if target in round_ids:
            idx = round_ids.index(target)
            actual_group = groups[idx]
            bet_group = pending["bet_group"]

            hit = 1 if actual_group == bet_group else 0
            pnl = WIN_GROUP if hit else LOSS_GROUP

            state["real_live_profit"] = float(state.get("real_live_profit", 0.0)) + pnl
            settled.add(target)
            state["settled_rounds"] = sorted(list(settled))

            state["real_live_history"].append({
                "created_round": pending["created_round"],
                "target_round": target,
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


def create_pending(state, signal, current_round):
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


def discover_top_patterns(groups):
    pattern_set = set()

    for L in range(PATTERN_LEN_MIN, PATTERN_LEN_MAX + 1):
        for i in range(L - 1, len(groups)):
            tail = groups[i - L + 1:i + 1]
            pattern, _ = groups_to_pattern(tail)
            pattern_set.add(pattern)

    rows = []

    for pattern in pattern_set:
        for bet_label in labels_in_pattern(pattern):
            if (pattern, bet_label) in BAD_PATTERN_SIDES:
                continue

            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)

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
            })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = df[df["trades"] >= MIN_TRADES]
    df = df.sort_values(
        ["profit", "recent_profit", "wr", "trades"],
        ascending=[False, False, False, False],
    ).head(SHOW_TOP_PATTERNS)

    return df


# =========================
# MAIN
# =========================
numbers, round_ids, total_round = load_data()
groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROWS + 5:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} ván, cần tối thiểu {LOCK_ROWS + 5}.")
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

state_data = settle_pending(state_data, groups, round_ids, current_round)

hist = simulate_lock75_backtest(tuple(groups))

live_profit = round(hist["live_profit"].iloc[-1], 2) if not hist.empty else 0.0
live_trades = int(hist["trade"].sum()) if not hist.empty else 0
live_wr = round(hist.loc[hist["trade"], "hit"].mean() * 100, 2) if live_trades else 0.0
peak_profit = round(hist["peak_profit"].max(), 2) if not hist.empty else 0.0
drawdown_now = round(hist["drawdown"].iloc[-1], 2) if not hist.empty else 0.0

signal, state, matches = choose_signal(groups)

# recent live protection dựa trên trade gần nhất, không lấy cả WAIT
recent_live_profit = 0.0
if not hist.empty:
    trade_hist = hist[hist["trade"] == True]
    if len(trade_hist) >= LIVE_RECENT_N:
        recent_live_profit = float(trade_hist.tail(LIVE_RECENT_N)["pnl"].sum())
        if recent_live_profit <= LIVE_RECENT_STOP:
            signal = None
            state = "WAIT_LIVE_RECENT_WEAK"

if current_round >= LOCK_ROWS and signal is not None:
    state_data = create_pending(state_data, signal, current_round)

save_state(state_data)

# =========================
# UI
# =========================
st.title("LOCK75 GROUP PATTERN ENGINE | FINAL OPTIMIZED")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Round", current_round)
c2.metric("Current Number", current_number)
c3.metric("Current Group", current_group)
c4.metric("Next Round", current_round + 1)

p1, p2, p3, p4 = st.columns(4)
p1.metric("REAL LIVE PROFIT", round(state_data["real_live_profit"], 2))
p2.metric("Backtest Profit From 76", live_profit)
p3.metric("Backtest Trades", live_trades)
p4.metric("Backtest WR %", live_wr)

q1, q2, q3, q4 = st.columns(4)
q1.metric("Peak Profit", peak_profit)
q2.metric("Drawdown Now", drawdown_now)
q3.metric("Recent Live Profit", round(recent_live_profit, 2))
q4.metric("State", state)

with st.expander("CONFIG"):
    st.write("LOCK_ROWS:", LOCK_ROWS)
    st.write("MAX_SOURCE_ROWS:", MAX_SOURCE_ROWS)
    st.write("PATTERN_LEN:", f"{PATTERN_LEN_MIN} → {PATTERN_LEN_MAX}")
    st.write("MIN_TRADES:", MIN_TRADES)
    st.write("MIN_WR:", MIN_WR)
    st.write("MIN_PROFIT:", MIN_PROFIT)
    st.write("MIN_SCORE:", MIN_SCORE)
    st.write("RECENT_ROUNDS:", RECENT_ROUNDS)
    st.write("RECENT_MIN_PROFIT:", RECENT_MIN_PROFIT)
    st.write("RECENT_WR_MIN:", RECENT_WR_MIN)
    st.write("LIVE_RECENT_N:", LIVE_RECENT_N)
    st.write("LIVE_RECENT_STOP:", LIVE_RECENT_STOP)
    st.write("BAD_PATTERN_SIDES:", sorted(list(BAD_PATTERN_SIDES)))

st.subheader("REAL LIVE LEDGER")
st.write("Pending Bet:", state_data.get("pending_bet"))
st.write("Settled Rounds:", state_data.get("settled_rounds", [])[-20:])

if state_data.get("real_live_history"):
    st.dataframe(
        pd.DataFrame(state_data["real_live_history"]).iloc[::-1].head(40),
        use_container_width=True,
    )

st.subheader("NEXT BET")

if signal:
    st.success(
        f"READY BET NEXT GROUP {signal['bet_group']} | "
        f"Pattern {signal['pattern']} | Tail {signal['tail']} | "
        f"Bet {signal['bet_label']} | Score {round(signal['score'], 2)}"
    )

    a, b, c, d = st.columns(4)
    a.metric("NEXT BET GROUP", signal["bet_group"])
    b.metric("Pattern", signal["pattern"])
    c.metric("WR %", round(signal["wr"] * 100, 2))
    d.metric("Score", round(signal["score"], 2))

    st.write("Tail Groups:", signal["tail"])
    st.write("Trades:", signal["trades"])
    st.write("Wins:", signal["wins"])
    st.write("Profit:", round(signal["profit"], 2))
    st.write("Recent Profit:", round(signal["recent_profit"], 2))
    st.write("Recent WR %:", round(signal["recent_wr"] * 100, 2))
else:
    st.warning(f"WAIT - {state}")

st.subheader("Matched Tail Patterns Ranking")

if matches:
    dfm = pd.DataFrame(matches)
    dfm["wr"] = (dfm["wr"] * 100).round(2)
    dfm["recent_wr"] = (dfm["recent_wr"] * 100).round(2)

    for col in ["profit", "recent_profit", "score", "profit_gap", "min_equity"]:
        dfm[col] = dfm[col].round(2)

    dfm["dominance"] = dfm["dominance"].round(3)
    dfm["transition_dominance"] = dfm["transition_dominance"].round(3)

    st.dataframe(dfm, use_container_width=True)

with st.expander("Discovered Top Patterns"):
    st.dataframe(discover_top_patterns(groups), use_container_width=True)

st.subheader("Backtest Profit Curve From Row 76")
if not hist.empty:
    st.line_chart(hist[["live_profit"]].reset_index(drop=True))

st.subheader("Backtest History")
if not hist.empty:
    st.dataframe(hist.iloc[::-1].head(SHOW_HISTORY_ROWS), use_container_width=True)
