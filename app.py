import time
import json
import os
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="FIXED RULE GROUP ENGINE", layout="wide")
st_autorefresh(interval=5000, key="refresh")

# =========================
# CONFIG
# =========================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"
STATE_FILE = "/tmp/fixed_rule_group_engine.json"

LOCK_ROWS = 75
MAX_SOURCE_ROWS = 500

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PATTERN_LEN_MIN = 3
PATTERN_LEN_MAX = 7

SHOW_HISTORY_ROWS = 100

# Chặn live nếu thua liên tiếp
REAL_LIVE_LOSS_STREAK_STOP = 22

# =========================
# FIXED RULES
# =========================
FIXED_RULES = {
    # 1 GROUP - chỉ dừng tới 4
    "AAA": "A",
    "AAAA": "A",

    # 2 GROUP - quay về A
    "AAAB": "A",
    "AAAAB": "A",
    "AABB": "A",
    "AABBA": "A",
    "AAABB": "A",
    "AAABBA": "A",

    # 2 GROUP - xen kẽ
    "ABABA": "B",
    "BABAB": "A",

    # 3 GROUP - chỉ chơi chuỗi xen kẽ lặp có A
    "ABCAB": "A",
    "ABACAB": "A",
    "ABACABA": "A",
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


# =========================
# FIXED RULE SIGNAL
# =========================
def choose_signal(groups):
    matches = []

    for L in range(PATTERN_LEN_MAX, PATTERN_LEN_MIN - 1, -1):
        if len(groups) < L:
            continue

        tail = groups[-L:]
        pattern, reverse = groups_to_pattern(tail)

        # bỏ pattern 4 group trở lên
        if len(set(pattern)) >= 4:
            continue

        if pattern not in FIXED_RULES:
            continue

        bet_label = FIXED_RULES[pattern]

        if bet_label not in reverse:
            continue

        bet_group = reverse[bet_label]

        sig = {
            "pattern": pattern,
            "len": L,
            "tail": tail,
            "bet_label": bet_label,
            "bet_group": bet_group,
            "unique_count": len(set(pattern)),
            "rule": f"{pattern} -> {bet_label}",
        }

        matches.append(sig)
        return sig, "READY_FIXED_RULE", matches

    return None, "WAIT_NO_FIXED_RULE", matches


# =========================
# BACKTEST LOCK
# =========================
@st.cache_data(ttl=5, show_spinner=False)
def simulate_backtest(groups_tuple):
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
            "rule": sig["rule"] if sig else None,
            "tail": str(sig["tail"]) if sig else None,
            "bet_label": sig["bet_label"] if sig else None,
            "bet_group": bet_group,
            "trade": trade,
            "hit": hit,
            "pnl": pnl,
            "live_profit": profit,
            "peak_profit": peak,
            "drawdown": peak - profit,
            "state": state,
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
                "rule": pending["rule"],
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
        "rule": signal["rule"],
        "bet_label": signal["bet_label"],
    }

    return state


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

hist = simulate_backtest(tuple(groups))

bt_profit = round(hist["live_profit"].iloc[-1], 2) if not hist.empty else 0.0
bt_trades = int(hist["trade"].sum()) if not hist.empty else 0
bt_wr = round(hist.loc[hist["trade"], "hit"].mean() * 100, 2) if bt_trades else 0.0
peak_profit = round(hist["peak_profit"].max(), 2) if not hist.empty else 0.0
drawdown_now = round(hist["drawdown"].iloc[-1], 2) if not hist.empty else 0.0

signal, state, matches = choose_signal(groups)

live_loss_streak = real_live_loss_streak(state_data)

if live_loss_streak >= REAL_LIVE_LOSS_STREAK_STOP:
    signal = None
    state = "WAIT_REAL_LIVE_LOSS_STREAK"

if current_round >= LOCK_ROWS and signal is not None:
    state_data = create_pending(state_data, signal, current_round)

save_state(state_data)

# =========================
# UI
# =========================
st.title("FIXED RULE GROUP ENGINE")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Round", current_round)
c2.metric("Current Number", current_number)
c3.metric("Current Group", current_group)
c4.metric("Next Round", current_round + 1)

p1, p2, p3, p4 = st.columns(4)
p1.metric("REAL LIVE PROFIT", round(state_data["real_live_profit"], 2))
p2.metric("Backtest Profit", bt_profit)
p3.metric("Backtest Trades", bt_trades)
p4.metric("Backtest WR %", bt_wr)

q1, q2, q3 = st.columns(3)
q1.metric("Peak Profit", peak_profit)
q2.metric("Drawdown", drawdown_now)
q3.metric("Live Loss Streak", live_loss_streak)

st.metric("State", state)

st.subheader("NEXT BET")

if signal:
    st.success(
        f"READY BET NEXT GROUP {signal['bet_group']} | "
        f"Rule {signal['rule']} | Tail {signal['tail']}"
    )

    a, b, c, d = st.columns(4)
    a.metric("NEXT GROUP", signal["bet_group"])
    b.metric("Pattern", signal["pattern"])
    c.metric("Bet Label", signal["bet_label"])
    d.metric("Unique Groups", signal["unique_count"])
else:
    st.warning(f"WAIT - {state}")

st.subheader("REAL LIVE LEDGER")
st.write("Pending Bet:", state_data.get("pending_bet"))
st.write("Settled Rounds:", state_data.get("settled_rounds", [])[-20:])

if state_data.get("real_live_history"):
    st.dataframe(
        pd.DataFrame(state_data["real_live_history"]).iloc[::-1].head(50),
        use_container_width=True,
    )

st.subheader("Backtest Profit Curve")
if not hist.empty:
    st.line_chart(hist[["live_profit"]].reset_index(drop=True))

st.subheader("Backtest History")
if not hist.empty:
    st.dataframe(hist.iloc[::-1].head(SHOW_HISTORY_ROWS), use_container_width=True)

st.subheader("Fixed Rules")
st.dataframe(
    pd.DataFrame(
        [{"pattern": k, "bet_label": v} for k, v in FIXED_RULES.items()]
    ),
    use_container_width=True,
)
