import math
from collections import Counter
USE_EV_FILTER = True   # hoặc False nếu muốn tắt EV filter
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Rolling Engine Fast", layout="centered")
st_autorefresh(interval=15000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

LOCK_LOOKBACK_MIN = 144
LOCK_LOOKBACK_MAX = 180

WINDOW_MIN = 6
WINDOW_MAX = 26
TOP_WINDOWS = 4
MIN_POSITIVE_WINDOWS = 3

MIN_TRADES_PER_WINDOW = 20
MIN_WINRATE_PER_WINDOW = 0.25

GAP = 0
WIN = 2.5
LOSS = -1.0

CYCLE_PROFIT_TARGET = 4.0
CYCLE_STOP_LOSS = -8.0

RECENT_HITS_WINDOW = 20
RECENT_WINRATE_FLOOR = 0.24

KEEP_AFTER_LOSS_ROUNDS = 4
EV_MIN_THRESHOLD = -0.05

MAX_HISTORY_ROWS = 30

@st.cache_data(ttl=60)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    df = pd.read_csv(url)
    df.columns = [c.lower() for c in df.columns]
    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()

def group(n: int) -> int:
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4

def recent_winrate(hit_list, n):
    if not hit_list:
        return 0.0
    arr = hit_list[-n:] if len(hit_list) >= n else hit_list
    return float(np.mean(arr)) if arr else 0.0

def calc_ev(winrate: float):
    return winrate * WIN - (1.0 - winrate) * abs(LOSS)

def dynamic_vote_required(lock_count: int) -> int:
    if lock_count >= 4:
        return 3
    if lock_count == 3:
        return 2
    return 1

def get_dynamic_lock_range(current_round: int):
    start = max(WINDOW_MAX + 1, current_round - LOCK_LOOKBACK_MAX)
    end = max(start, current_round - LOCK_LOOKBACK_MIN)
    return start, end

def evaluate_window(seq_groups, w):
    profit = 0.0
    trades = 0
    wins = 0

    for i in range(w, len(seq_groups)):
        pred = seq_groups[i - w]
        if seq_groups[i - 1] != pred:
            trades += 1
            if seq_groups[i] == pred:
                wins += 1
                profit += WIN
            else:
                profit += LOSS

    winrate = wins / trades if trades > 0 else 0.0
    score = profit * winrate * math.log(trades) if trades > 0 else -999999.0
    ev = calc_ev(winrate) if trades > 0 else -999999.0

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "profit": profit,
        "winrate": winrate,
        "score": score,
        "ev": ev,
    }

def build_window_tables(train_groups):
    rows = [evaluate_window(train_groups, w) for w in range(WINDOW_MIN, WINDOW_MAX + 1)]
    df = pd.DataFrame(rows)

    positive_df = df[
        (df["profit"] > 0) &
        (df["trades"] >= MIN_TRADES_PER_WINDOW) &
        (df["winrate"] >= MIN_WINRATE_PER_WINDOW)
    ].copy()

    positive_df = positive_df.sort_values(
        ["score", "profit", "winrate", "trades"],
        ascending=[False, False, False, False]
    ).reset_index(drop=True)

    selected_df = positive_df.head(TOP_WINDOWS).copy()
    selected = selected_df["window"].astype(int).tolist() if not selected_df.empty else []

    return selected, positive_df, selected_df

@st.cache_data(ttl=60)
def find_best_lock_round_cached(groups_tuple, current_round: int):
    groups = list(groups_tuple)
    lock_start, lock_end = get_dynamic_lock_range(current_round)

    best_round = None
    best_score = -999999.0
    best_selected = pd.DataFrame()

    for r in range(lock_start, lock_end + 1):
        train_groups = groups[:r]
        _, positive_df, selected_df = build_window_tables(train_groups)

        if len(positive_df) < MIN_POSITIVE_WINDOWS or selected_df.empty:
            continue

        total_profit = float(selected_df["profit"].sum())
        avg_winrate = float(selected_df["winrate"].mean())
        total_trades = float(selected_df["trades"].sum())
        avg_score = float(selected_df["score"].mean())
        avg_ev = float(selected_df["ev"].mean())

        round_score = (
            total_profit
            + avg_winrate * 10.0
            + math.log(max(total_trades, 1.0))
            + avg_score * 0.2
            + avg_ev * 8.0
        )

        if (round_score > best_score) or (round_score == best_score and (best_round is None or r > best_round)):
            best_score = round_score
            best_round = r
            best_selected = selected_df.copy()

    return best_round, best_selected, lock_start, lock_end

def weighted_vote(pred_rows):
    group_weights = {}
    group_counts = {}

    for row in pred_rows:
        g = row["pred_group"]
        w = row["weight"]
        group_weights[g] = group_weights.get(g, 0.0) + w
        group_counts[g] = group_counts.get(g, 0) + 1

    best_group = max(group_weights.items(), key=lambda x: (x[1], group_counts[x[0]]))[0]
    best_count = group_counts[best_group]
    return best_group, best_count

def init_state():
    defaults = {
        "initialized": False,
        "processed_until": None,
        "total_profit": 0.0,
        "cycle_profit": 0.0,
        "hits": [],
        "last_trade": -999,
        "locked_windows": [],
        "vote_required": 1,
        "selected_df": pd.DataFrame(),
        "lock_round_used": None,
        "lock_start": None,
        "lock_end": None,
        "cycle_start_round": None,
        "cycle_id": 1,
        "keep_bet_group": None,
        "keep_rounds_left": 0,
        "last_trade_was_loss": False,
        "history": [],
        "base_len": None,
        "last_relock_reason": "INIT",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

if st.button("Reset Session"):
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

numbers = load_numbers()
groups = [group(n) for n in numbers]

if len(groups) < max(WINDOW_MAX + 1, LOCK_LOOKBACK_MAX + 1):
    st.error("Chưa đủ dữ liệu để chạy.")
    st.stop()

if st.session_state.base_len is not None and len(groups) < st.session_state.base_len:
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()

def relock(current_round: int, reason: str):
    best_round, selected_df, lock_start, lock_end = find_best_lock_round_cached(tuple(groups), current_round)
    if best_round is None or selected_df.empty:
        return False

    st.session_state.locked_windows = selected_df["window"].astype(int).tolist()
    st.session_state.vote_required = dynamic_vote_required(len(st.session_state.locked_windows))
    st.session_state.selected_df = selected_df
    st.session_state.lock_round_used = best_round
    st.session_state.lock_start = lock_start
    st.session_state.lock_end = lock_end
    st.session_state.cycle_profit = 0.0
    st.session_state.cycle_start_round = current_round
    st.session_state.cycle_id += 1
    st.session_state.keep_bet_group = None
    st.session_state.keep_rounds_left = 0
    st.session_state.last_trade_was_loss = False
    st.session_state.last_relock_reason = reason
    return True

if not st.session_state.initialized:
    ok = relock(len(groups), "INIT")
    if not ok:
        st.error("Không tìm được bộ lock phù hợp.")
        st.stop()
    st.session_state.processed_until = st.session_state.lock_round_used - 1
    st.session_state.initialized = True
    st.session_state.base_len = len(groups)

selected_df = st.session_state.selected_df
selected_meta = {}
if not selected_df.empty:
    for _, row in selected_df.iterrows():
        selected_meta[int(row["window"])] = {
            "score": float(row["score"]),
            "profit": float(row["profit"]),
            "winrate": float(row["winrate"]),
            "trades": int(row["trades"]),
            "ev": float(row["ev"]),
        }

for i in range(st.session_state.processed_until + 1, len(groups)):
    recent_wr = recent_winrate(st.session_state.hits, RECENT_HITS_WINDOW)

    if st.session_state.cycle_profit >= CYCLE_PROFIT_TARGET:
        if relock(i, "TARGET_REACHED"):
            st.session_state.processed_until = i - 1
            break

    if st.session_state.cycle_profit <= CYCLE_STOP_LOSS:
        if relock(i, "LOSS_REACHED"):
            st.session_state.processed_until = i - 1
            break

    if len(st.session_state.hits) >= RECENT_HITS_WINDOW and recent_wr < RECENT_WINRATE_FLOOR:
        if relock(i, "RECENT_WR_LOW"):
            st.session_state.processed_until = i - 1
            break

    if i < st.session_state.lock_round_used:
        continue

    pred_rows = []
    for w in st.session_state.locked_windows:
        if i - w >= 0:
            meta = selected_meta.get(w, {"score": 0.0, "profit": 0.0, "winrate": 0.0, "trades": 0, "ev": 0.0})
            weight = max(meta["score"], 0.01) * 0.6 + max(meta["profit"], 0.0) * 0.25 + max(meta["winrate"], 0.0) * 10.0 * 0.15
            pred_rows.append({
                "window": w,
                "pred_group": groups[i - w],
                "ev": meta["ev"],
                "weight": weight,
            })

    if not pred_rows:
        st.session_state.processed_until = i
        continue

    vote, confidence = weighted_vote(pred_rows)
    winning_rows = [x for x in pred_rows if x["pred_group"] == vote]
    avg_ev = float(np.mean([x["ev"] for x in winning_rows])) if winning_rows else -999999.0

    new_signal = confidence >= st.session_state.vote_required
    final_vote = vote
    used_keep = False

    if new_signal:
        st.session_state.keep_bet_group = None
        st.session_state.keep_rounds_left = 0
        st.session_state.last_trade_was_loss = False
    elif st.session_state.last_trade_was_loss and st.session_state.keep_rounds_left > 0 and st.session_state.keep_bet_group is not None:
        final_vote = st.session_state.keep_bet_group
        used_keep = True

    final_signal = new_signal or used_keep
    distance = i - st.session_state.last_trade
    can_bet = final_signal and distance >= GAP

    if new_signal and USE_EV_FILTER:
        can_bet = can_bet and (avg_ev >= EV_MIN_THRESHOLD)

    trade = can_bet
    hit = None

    if used_keep:
        st.session_state.keep_rounds_left -= 1
        if st.session_state.keep_rounds_left < 0:
            st.session_state.keep_rounds_left = 0

    if trade:
        st.session_state.last_trade = i
        if groups[i] == final_vote:
            hit = 1
            st.session_state.total_profit += WIN
            st.session_state.cycle_profit += WIN
            st.session_state.hits.append(1)
            st.session_state.keep_bet_group = None
            st.session_state.keep_rounds_left = 0
            st.session_state.last_trade_was_loss = False
        else:
            hit = 0
            st.session_state.total_profit += LOSS
            st.session_state.cycle_profit += LOSS
            st.session_state.hits.append(0)

            if used_keep:
                if st.session_state.keep_rounds_left <= 0:
                    st.session_state.keep_bet_group = None
                    st.session_state.last_trade_was_loss = False
                else:
                    st.session_state.last_trade_was_loss = True
            else:
                st.session_state.keep_bet_group = final_vote
                st.session_state.keep_rounds_left = max(KEEP_AFTER_LOSS_ROUNDS - 1, 0)
                st.session_state.last_trade_was_loss = True

    st.session_state.history.append({
        "cycle_id": st.session_state.cycle_id,
        "round": i,
        "number": numbers[i],
        "group": groups[i],
        "vote": vote,
        "confidence": confidence,
        "vote_required": st.session_state.vote_required,
        "final_vote": final_vote,
        "trade": trade,
        "hit": hit,
        "avg_ev": avg_ev,
        "cycle_profit": st.session_state.cycle_profit,
        "total_profit": st.session_state.total_profit,
    })

    st.session_state.processed_until = i

hist = pd.DataFrame(st.session_state.history)

next_round = len(groups)
pred_rows_next = []
for w in st.session_state.locked_windows:
    if next_round - w >= 0:
        meta = selected_meta.get(w, {"score": 0.0, "profit": 0.0, "winrate": 0.0, "trades": 0, "ev": 0.0})
        weight = max(meta["score"], 0.01) * 0.6 + max(meta["profit"], 0.0) * 0.25 + max(meta["winrate"], 0.0) * 10.0 * 0.15
        pred_rows_next.append({
            "window": w,
            "pred_group": groups[next_round - w],
            "ev": meta["ev"],
            "weight": weight,
        })

if pred_rows_next:
    vote, confidence = weighted_vote(pred_rows_next)
    winning_rows_next = [x for x in pred_rows_next if x["pred_group"] == vote]
    avg_ev_next = float(np.mean([x["ev"] for x in winning_rows_next])) if winning_rows_next else -999999.0
else:
    vote, confidence, avg_ev_next = None, 0, -999999.0

new_signal_next = vote is not None and confidence >= st.session_state.vote_required
final_vote_next = vote

if not new_signal_next and st.session_state.last_trade_was_loss and st.session_state.keep_rounds_left > 0 and st.session_state.keep_bet_group is not None:
    final_vote_next = st.session_state.keep_bet_group

distance_next = next_round - st.session_state.last_trade if st.session_state.last_trade > -999 else 999
can_bet_next = (new_signal_next or final_vote_next != vote) and distance_next >= GAP

if new_signal_next and USE_EV_FILTER:
    can_bet_next = can_bet_next and (avg_ev_next >= EV_MIN_THRESHOLD)

st.title("🎯 Rolling Engine Fast Balanced")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", numbers[-1] if numbers else "-")
c2.metric("Current Group", groups[-1] if groups else "-")
c3.metric("Next Group", final_vote_next if final_vote_next is not None else "-")
c4.metric("Cycle ID", st.session_state.cycle_id)

st.write("Vote Strength:", confidence)
st.write("Vote Required:", st.session_state.vote_required)
st.write("Locked Windows:", st.session_state.locked_windows)
st.write("Lock Range:", f"{st.session_state.lock_start} -> {st.session_state.lock_end}")
st.write("Lock Round Used:", st.session_state.lock_round_used)
st.write("Cycle Start Round:", st.session_state.cycle_start_round)
st.write("Last Relock Reason:", st.session_state.last_relock_reason)
st.write("Next EV:", round(avg_ev_next, 4) if avg_ev_next > -999 else "-")

if st.session_state.cycle_profit >= CYCLE_PROFIT_TARGET:
    st.success("RELOCK ready - target reached")
elif st.session_state.cycle_profit <= CYCLE_STOP_LOSS:
    st.warning("RELOCK ready - loss reached")
elif len(st.session_state.hits) >= RECENT_HITS_WINDOW and recent_winrate(st.session_state.hits, RECENT_HITS_WINDOW) < RECENT_WINRATE_FLOOR:
    st.warning("RELOCK ready - recent WR low")
elif can_bet_next and final_vote_next is not None:
    st.error(f"BET GROUP -> {final_vote_next}")
else:
    st.info("WAIT")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Total Profit", st.session_state.total_profit)
s2.metric("Cycle Profit", st.session_state.cycle_profit)
s3.metric("Trades", len(st.session_state.hits))
s4.metric("Winrate %", round(np.mean(st.session_state.hits) * 100, 2) if st.session_state.hits else 0)

if not hist.empty:
    st.subheader("Profit Curve")
    st.line_chart(hist["total_profit"].tail(120))

    st.subheader("History")
    st.dataframe(hist.iloc[::-1].head(MAX_HISTORY_ROWS), use_container_width=True)
