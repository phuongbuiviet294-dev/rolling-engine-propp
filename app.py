import time
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Group Pattern Engine FIX", layout="wide")
st_autorefresh(interval=3000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PATTERN_RULES = {
    "AAA": "A",
    "AAAB": "A",
    "AAAAB": "A",
    "BBAAB": "B",
    "AABBA": "A",
    "BBBAAAB": "B",
    "AAABBBA": "A",
    "ABABA": "B",
}

MIN_PATTERN_OCCURRENCES = 5
MIN_PATTERN_HIT_RATE = 0.30
MIN_PATTERN_PROFIT = 0.0

RECENT_CHECK_ROUNDS = 120
RECENT_MIN_PROFIT = -1.0

MIN_PATTERN_SCORE = 3.0

MAX_PATTERN_LOSS_STREAK = 2
BLACKLIST_AFTER_LOSS_STREAK = 3

SHOW_HISTORY_ROWS = 80


@st.cache_data(ttl=10, show_spinner=False)
def load_data():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&t={int(time.time())}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        st.error("Sheet phải có cột number")
        st.stop()

    nums = pd.to_numeric(df["number"], errors="coerce").dropna().astype(int).tolist()
    return [x for x in nums if 1 <= x <= 12]


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


def groups_to_ab_pattern(seq):
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


def calc_pattern_stats(groups, pattern, bet_label):
    L = len(pattern)
    rows = []
    results = []

    for i in range(L - 1, len(groups) - 1):
        tail = groups[i - L + 1:i + 1]
        ab, reverse = groups_to_ab_pattern(tail)

        if ab != pattern:
            continue
        if bet_label not in reverse:
            continue

        pred = reverse[bet_label]
        actual = groups[i + 1]
        hit = 1 if pred == actual else 0
        pnl = WIN_GROUP if hit else LOSS_GROUP

        results.append(hit)
        rows.append({
            "signal_round": i + 1,
            "target_round": i + 2,
            "pattern": pattern,
            "pred_group": pred,
            "actual_group": actual,
            "hit": hit,
            "pnl": pnl,
        })

    trades = len(results)
    wins = sum(results)
    profit = sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results)
    wr = wins / trades if trades else 0

    loss_streak = 0
    max_loss_streak = 0
    cur = 0

    for r in results:
        if r == 0:
            cur += 1
            max_loss_streak = max(max_loss_streak, cur)
        else:
            cur = 0

    if results:
        for r in reversed(results):
            if r == 0:
                loss_streak += 1
            else:
                break

    return {
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "profit": profit,
        "rows": rows,
        "loss_streak": loss_streak,
        "max_loss_streak": max_loss_streak,
    }


def calc_recent_stats(groups, pattern, bet_label):
    recent = groups[-RECENT_CHECK_ROUNDS:]
    return calc_pattern_stats(recent, pattern, bet_label)


def score_pattern(stat, recent_stat):
    return (
        stat["profit"] * 1.5
        + stat["wr"] * 10
        + recent_stat["profit"] * 2
        + stat["trades"] * 0.15
        - stat["loss_streak"] * 2.5
        - stat["max_loss_streak"] * 0.8
    )


def get_all_matched_patterns(groups):
    matches = []

    for pattern, bet_label in PATTERN_RULES.items():
        L = len(pattern)
        if len(groups) < L:
            continue

        tail = groups[-L:]
        ab, reverse = groups_to_ab_pattern(tail)

        if ab == pattern and bet_label in reverse:
            stat = calc_pattern_stats(groups, pattern, bet_label)
            recent_stat = calc_recent_stats(groups, pattern, bet_label)
            score = score_pattern(stat, recent_stat)

            matches.append({
                "pattern": pattern,
                "bet_label": bet_label,
                "bet_group": reverse[bet_label],
                "tail": tail,
                "trades": stat["trades"],
                "wins": stat["wins"],
                "wr": stat["wr"],
                "profit": stat["profit"],
                "recent_profit": recent_stat["profit"],
                "loss_streak": stat["loss_streak"],
                "max_loss_streak": stat["max_loss_streak"],
                "score": score,
            })

    matches = sorted(matches, key=lambda x: x["score"], reverse=True)
    return matches


def choose_best_signal(groups):
    matches = get_all_matched_patterns(groups)

    if not matches:
        return None, "WAIT_NO_PATTERN", []

    for m in matches:
        if m["trades"] < MIN_PATTERN_OCCURRENCES:
            continue

        if m["wr"] < MIN_PATTERN_HIT_RATE:
            continue

        if m["profit"] < MIN_PATTERN_PROFIT:
            continue

        if m["recent_profit"] < RECENT_MIN_PROFIT:
            continue

        if m["loss_streak"] >= BLACKLIST_AFTER_LOSS_STREAK:
            continue

        if m["max_loss_streak"] > MAX_PATTERN_LOSS_STREAK + 3:
            continue

        if m["score"] < MIN_PATTERN_SCORE:
            continue

        return m, "READY", matches

    return None, "WAIT_PATTERN_WEAK", matches


def simulate(groups):
    history = []
    total_profit = 0.0

    max_len = max(len(p) for p in PATTERN_RULES)

    for i in range(max_len, len(groups) - 1):
        sub = groups[:i]
        signal, state, matches = choose_best_signal(sub)

        trade = False
        pred = None
        hit = None
        pnl = 0.0

        if signal:
            pred = signal["bet_group"]
            actual = groups[i]
            trade = True

            if pred == actual:
                hit = 1
                pnl = WIN_GROUP
            else:
                hit = 0
                pnl = LOSS_GROUP

            total_profit += pnl
            state = "TRADE"
        else:
            actual = groups[i]

        history.append({
            "round": i + 1,
            "actual_group": actual,
            "pattern": signal["pattern"] if signal else None,
            "tail": str(signal["tail"]) if signal else None,
            "bet_group": pred,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "total_profit": total_profit,
            "state": state,
            "score": round(signal["score"], 2) if signal else None,
            "wr": round(signal["wr"] * 100, 2) if signal else None,
            "profit": signal["profit"] if signal else None,
            "recent_profit": signal["recent_profit"] if signal else None,
        })

    return pd.DataFrame(history)


numbers = load_data()
groups = [group_of(n) for n in numbers]

if len(groups) < 20:
    st.error("Chưa đủ dữ liệu")
    st.stop()

if st.sidebar.button("Clear cache"):
    st.cache_data.clear()
    st.rerun()

signal, state, matches = choose_best_signal(groups)
hist = simulate(groups)

st.title("GROUP PATTERN ENGINE FIX")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1])
c2.metric("Current Group", groups[-1])
c3.metric("State", state)
c4.metric("Total Profit", round(hist["total_profit"].iloc[-1], 2) if not hist.empty else 0)

if signal:
    st.success(
        f"READY BET GROUP {signal['bet_group']} | "
        f"Pattern {signal['pattern']} | "
        f"Score {round(signal['score'], 2)}"
    )
else:
    st.warning("WAIT - không có pattern đủ tin cậy")

st.subheader("Best Signal")

if signal:
    st.write("Pattern:", signal["pattern"])
    st.write("Tail:", signal["tail"])
    st.write("Bet Label:", signal["bet_label"])
    st.write("Bet Group:", signal["bet_group"])
    st.write("Trades:", signal["trades"])
    st.write("Wins:", signal["wins"])
    st.write("WR %:", round(signal["wr"] * 100, 2))
    st.write("Profit:", signal["profit"])
    st.write("Recent Profit:", signal["recent_profit"])
    st.write("Loss Streak:", signal["loss_streak"])
    st.write("Max Loss Streak:", signal["max_loss_streak"])
    st.write("Score:", round(signal["score"], 2))

st.subheader("Matched Patterns Ranking")

if matches:
    match_df = pd.DataFrame(matches)
    match_df["wr"] = (match_df["wr"] * 100).round(2)
    match_df["score"] = match_df["score"].round(2)
    st.dataframe(match_df, use_container_width=True)
else:
    st.info("Không có pattern nào match tail hiện tại.")

st.subheader("All Pattern Stats")

rows = []
for p, b in PATTERN_RULES.items():
    stat = calc_pattern_stats(groups, p, b)
    recent = calc_recent_stats(groups, p, b)
    rows.append({
        "pattern": p,
        "bet": b,
        "trades": stat["trades"],
        "wins": stat["wins"],
        "wr": round(stat["wr"] * 100, 2),
        "profit": stat["profit"],
        "recent_profit": recent["profit"],
        "loss_streak": stat["loss_streak"],
        "max_loss_streak": stat["max_loss_streak"],
        "score": round(score_pattern(stat, recent), 2),
    })

stats_df = pd.DataFrame(rows).sort_values(["score", "profit"], ascending=False)
st.dataframe(stats_df, use_container_width=True)

st.subheader("Profit Curve")
if not hist.empty:
    st.line_chart(hist[["total_profit"]])

st.subheader("History")
if not hist.empty:
    st.dataframe(hist.iloc[::-1].head(SHOW_HISTORY_ROWS), use_container_width=True)
