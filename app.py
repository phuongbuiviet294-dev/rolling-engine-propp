import time
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# =========================================================
# APP CONFIG - MOBILE FAST VERSION
# =========================================================
st.set_page_config(page_title="Fast ABCD Pattern Live Engine", layout="wide")
st_autorefresh(interval=10000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

# =========================================================
# LIVE CONFIG
# =========================================================
LOCK_ROWS = 75
MAX_SOURCE_ROWS = 240

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

# =========================================================
# PATTERN CONFIG - FAST
# =========================================================
PATTERN_LEN_MIN = 3
PATTERN_LEN_MAX = 5

MIN_TRADES = 1
MIN_WR = 0.25
MIN_PROFIT = -1.0
MIN_SCORE = 0.5

RECENT_ROUNDS = 80
RECENT_MIN_PROFIT = -2.0

PATTERN_BREAK_STREAK_LIMIT = 2
ONLY_BET_IF_NOT_BROKEN = True

SHOW_HISTORY_ROWS = 30
SHOW_TOP_PATTERNS = 20


@st.cache_data(ttl=20, show_spinner=False)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={int(time.time() // 20)}"
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
        results.append(hit)

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

    last_result = results[-1] if results else None

    return {
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "profit": profit,
        "results": results,
        "current_loss_streak": current_loss_streak,
        "max_loss_streak": max_loss_streak,
        "last_result": last_result,
    }


def recent_stats(groups, pattern, bet_label):
    return calc_pattern_stats(groups[-RECENT_ROUNDS:], pattern, bet_label)


def score_pattern(stat, recent):
    trades = stat["trades"]
    wr = stat["wr"]
    profit = stat["profit"]
    recent_profit = recent["profit"]

    trade_confidence = min(trades, 6) / 6.0

    low_sample_penalty = 0.0
    if trades == 1 and wr >= 1.0:
        low_sample_penalty = 2.0
    elif trades == 1:
        low_sample_penalty = 1.0
    elif trades == 2:
        low_sample_penalty = 0.5

    broken_penalty = 4.0 if stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT else 0.0

    return (
        profit * 1.4
        + wr * 8.0
        + recent_profit * 1.2
        + trade_confidence * 2.0
        - stat["current_loss_streak"] * 1.8
        - stat["max_loss_streak"] * 0.3
        - low_sample_penalty
        - broken_penalty
    )


def pattern_is_broken(stat, recent):
    if stat["current_loss_streak"] >= PATTERN_BREAK_STREAK_LIMIT:
        if recent["profit"] <= 0:
            return True
    return False


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

            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)
            sc = score_pattern(stat, recent)
            broken = pattern_is_broken(stat, recent)

            rows.append({
                "pattern": pattern,
                "len": L,
                "bet_label": bet_label,
                "bet_group": reverse[bet_label],
                "tail": tail,
                "trades": stat["trades"],
                "wins": stat["wins"],
                "wr": stat["wr"],
                "profit": stat["profit"],
                "recent_profit": recent["profit"],
                "current_loss_streak": stat["current_loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "last_result": stat["last_result"],
                "broken": broken,
                "score": sc,
            })

    rows = sorted(rows, key=lambda x: x["score"], reverse=True)
    return rows


def choose_signal(groups):
    matches = current_tail_candidates(groups)

    if not matches:
        return None, "WAIT_NO_PATTERN", matches

    for m in matches:
        if m["trades"] < MIN_TRADES:
            continue

        if m["wr"] < MIN_WR:
            continue

        if m["profit"] < MIN_PROFIT:
            continue

        if m["recent_profit"] < RECENT_MIN_PROFIT:
            continue

        if ONLY_BET_IF_NOT_BROKEN and m["broken"]:
            continue

        if m["score"] < MIN_SCORE:
            continue

        return m, "READY", matches

    return None, "WAIT_PATTERN_WEAK_OR_BROKEN", matches


@st.cache_data(ttl=20, show_spinner=False)
def simulate_live_from_lock_cached(groups_tuple):
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
            "state": state,
            "score": round(sig["score"], 2) if sig else None,
            "wr": round(sig["wr"] * 100, 2) if sig else None,
            "pattern_profit": round(sig["profit"], 2) if sig else None,
            "recent_profit": round(sig["recent_profit"], 2) if sig else None,
            "current_loss_streak": sig["current_loss_streak"] if sig else None,
            "broken": sig["broken"] if sig else None,
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=30, show_spinner=False)
def discover_top_patterns_cached(groups_tuple):
    groups = list(groups_tuple)
    groups = groups[-200:]

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
            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent = recent_stats(groups, pattern, bet_label)
            sc = score_pattern(stat, recent)
            broken = pattern_is_broken(stat, recent)

            rows.append({
                "pattern": pattern,
                "len": len(pattern),
                "bet": bet_label,
                "trades": stat["trades"],
                "wins": stat["wins"],
                "wr": round(stat["wr"] * 100, 2),
                "profit": round(stat["profit"], 2),
                "recent_profit": round(recent["profit"], 2),
                "current_loss_streak": stat["current_loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "broken": broken,
                "score": round(sc, 2),
            })

    df = pd.DataFrame(rows)

    if not df.empty:
        df = df.sort_values(
            ["score", "profit", "wr", "trades"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)

    return df.head(SHOW_TOP_PATTERNS)


numbers = load_data()
groups = [group_of(n) for n in numbers]

if len(groups) < LOCK_ROWS + 5:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} ván, cần ít nhất {LOCK_ROWS + 5}.")
    st.stop()

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.rerun()

with st.spinner("Đang tính signal..."):
    signal, state, matches = choose_signal(groups)
    hist = simulate_live_from_lock_cached(tuple(groups))

live_profit = round(hist["live_profit"].iloc[-1], 2) if not hist.empty else 0.0
live_trades = int(hist["trade"].sum()) if not hist.empty else 0
live_wr = round(hist.loc[hist["trade"], "hit"].mean() * 100, 2) if live_trades > 0 else 0.0

st.title("FAST ABCD PATTERN LIVE ENGINE | LOCK 75")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Round", len(groups))
c2.metric("Current Number", numbers[-1])
c3.metric("Current Group", groups[-1])
c4.metric("Next Round", len(groups) + 1)

p1, p2, p3, p4 = st.columns(4)
p1.metric("Live Profit", live_profit)
p2.metric("Live Trades", live_trades)
p3.metric("Live WR %", live_wr)
p4.metric("State", state)

st.write("LOCK_ROWS:", LOCK_ROWS)
st.write("MAX_SOURCE_ROWS:", MAX_SOURCE_ROWS)
st.write("PATTERN_LEN_MIN:", PATTERN_LEN_MIN)
st.write("PATTERN_LEN_MAX:", PATTERN_LEN_MAX)
st.write("MIN_TRADES:", MIN_TRADES)
st.write("MIN_WR:", MIN_WR)
st.write("MIN_PROFIT:", MIN_PROFIT)
st.write("RECENT_MIN_PROFIT:", RECENT_MIN_PROFIT)
st.write("PATTERN_BREAK_STREAK_LIMIT:", PATTERN_BREAK_STREAK_LIMIT)
st.write("MIN_SCORE:", MIN_SCORE)

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
    st.write("Recent Profit:", round(signal["recent_profit"], 2))
    st.write("Current Loss Streak:", signal["current_loss_streak"])
    st.write("Max Loss Streak:", signal["max_loss_streak"])
    st.write("Broken:", signal["broken"])
else:
    st.warning(f"WAIT - {state}")

st.subheader("Matched Tail Patterns Ranking")

if matches:
    match_df = pd.DataFrame(matches)
    match_df["wr"] = (match_df["wr"] * 100).round(2)
    match_df["profit"] = match_df["profit"].round(2)
    match_df["recent_profit"] = match_df["recent_profit"].round(2)
    match_df["score"] = match_df["score"].round(2)
    st.dataframe(match_df, use_container_width=True)
else:
    st.info("Không có pattern nào match tail hiện tại.")

with st.expander("Discovered Top Patterns"):
    stats_df = discover_top_patterns_cached(tuple(groups))
    st.dataframe(stats_df, use_container_width=True)

st.subheader("Live Profit Curve From Round 76")

if not hist.empty:
    st.line_chart(hist[["live_profit"]].tail(150).reset_index(drop=True))

st.subheader("Live History")

if not hist.empty:
    st.dataframe(
        hist.iloc[::-1].head(SHOW_HISTORY_ROWS),
        use_container_width=True
    )
