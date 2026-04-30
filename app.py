import time
import json
import os
import numpy as np
import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# ================= REFRESH =================
st_autorefresh(interval=5000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

REPLAY_FROM = 180
GAP = 1

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

PHASE_STOP_WIN = 3.5
PHASE_STOP_LOSS = -2.0

SESSION_STOP_WIN = 20.0
SESSION_STOP_LOSS = -20.0

SHOW_HISTORY_ROWS = 50
SHOW_STYLED_HISTORY = False

# ================= TELEGRAM =================
DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID

TELEGRAM_SEND_MODE = "READY_ONLY"
SENT_FILE = "/tmp/telegram_pattern_only_sent.json"


def telegram_enabled():
    return bool(BOT_TOKEN and CHAT_ID)


def send_telegram(msg):
    if not telegram_enabled():
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=5)
        return r.ok
    except Exception:
        return False


def send_signal_once(signal_name, current_round, msg):
    if TELEGRAM_SEND_MODE == "READY_ONLY" and signal_name != "READY":
        return False

    signal_key = f"{signal_name}|ROUND_{current_round}"

    if "sent_round_keys" not in st.session_state:
        st.session_state.sent_round_keys = set()

    if signal_key in st.session_state.sent_round_keys:
        return False

    try:
        if os.path.exists(SENT_FILE):
            with open(SENT_FILE, "r", encoding="utf-8") as f:
                sent_keys = set(json.load(f))
        else:
            sent_keys = set()
    except Exception:
        sent_keys = set()

    if signal_key in sent_keys:
        st.session_state.sent_round_keys.add(signal_key)
        return False

    ok = send_telegram(msg)

    if ok:
        st.session_state.sent_round_keys.add(signal_key)
        sent_keys.add(signal_key)
        try:
            with open(SENT_FILE, "w", encoding="utf-8") as f:
                json.dump(list(sent_keys)[-500:], f)
        except Exception:
            pass

    return ok


# ================= LOAD DATA =================
@st.cache_data(ttl=30, show_spinner=False)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet must contain column 'number'")

    df["number"] = pd.to_numeric(df["number"], errors="coerce")
    return df["number"].dropna().astype(int).tolist()


def group_of(n):
    if n <= 3:
        return 1
    if n <= 6:
        return 2
    if n <= 9:
        return 3
    return 4


# ================= PATTERN ENGINE =================
def detect_pattern_next_group(seq_numbers):
    n = len(seq_numbers)
    if n < 2:
        return None, "NO_PATTERN"

    tail2 = seq_numbers[-2:] if n >= 2 else []
    tail3 = seq_numbers[-3:] if n >= 3 else []
    tail4 = seq_numbers[-4:] if n >= 4 else []
    tail5 = seq_numbers[-5:] if n >= 5 else []
    tail6 = seq_numbers[-6:] if n >= 6 else []
    tail7 = seq_numbers[-7:] if n >= 7 else []

    # 1,2,3,4 -> bet group 1
    if n >= 4 and tail4 == [1, 2, 3, 4]:
        return 1, "NUMBER_SEQ_1234"

    # A,A,A,A,B -> bet group(A)
    if n >= 5:
        a, b, c, d, e = tail5
        if a == b == c == d and e != a:
            return group_of(a), "NUMBER_AAAAB"

    # A,A,A,B -> bet group(A)
    if n >= 4:
        a, b, c, d = tail4
        if a == b == c and d != a:
            return group_of(a), "NUMBER_AAAB"

    # A,A,A,A -> bet group(A)
    if n >= 4:
        a, b, c, d = tail4
        if a == b == c == d:
            return group_of(a), "NUMBER_REPEAT_4"

    # A,A,A -> bet group(A)
    if n >= 3:
        a, b, c = tail3
        if a == b == c:
            return group_of(a), "NUMBER_REPEAT_3"

    # A,A -> bet group(A)
    if n >= 2:
        a, b = tail2
        if a == b:
            return group_of(a), "NUMBER_REPEAT_2"

    # A,B,A,B -> bet group(A)
    if n >= 4:
        a, b, c, d = tail4
        if a == c and b == d and a != b:
            return group_of(a), "NUMBER_ABAB"

    # A,A,B,B -> bet group(A)
    if n >= 4:
        a, b, c, d = tail4
        if a == b and c == d and a != c:
            return group_of(a), "NUMBER_AABB"

    # A,A,A,B,B,B -> bet group(A)
    if n >= 6:
        a, b, c, d, e, f = tail6
        if a == b == c and d == e == f and a != d:
            return group_of(a), "NUMBER_AAABBB"

    # B,B,B,A,B,B,A -> bet group(B)
    if n >= 7:
        a, b, c, d, e, f, g = tail7
        if a == b == c and e == f and d == g and a == e and a != d:
            return group_of(a), "NUMBER_BBBABBA"

    return None, "NO_PATTERN"


numbers = load_numbers()
groups = [group_of(n) for n in numbers]

if len(numbers) < REPLAY_FROM:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(numbers)} rounds, cần ít nhất {REPLAY_FROM}.")
    st.stop()


# ================= SIMULATION =================
def simulate_pattern_only(numbers):
    groups = [group_of(n) for n in numbers]

    phase_profit = 0.0
    total_profit = 0.0

    phase_hits = []
    total_hits = []

    phase_index = 1
    phase_loss_streak = 0
    consecutive_losses = 0

    last_trade = -999
    phase_summary_rows = []
    history_rows = []

    session_stop = False
    session_stop_reason = None

    for i in range(REPLAY_FROM, len(numbers)):
        if total_profit >= SESSION_STOP_WIN:
            session_stop = True
            session_stop_reason = "SESSION_STOP_WIN"
            break

        if total_profit <= SESSION_STOP_LOSS:
            session_stop = True
            session_stop_reason = "SESSION_STOP_LOSS"
            break

        pattern_group, pattern_type = detect_pattern_next_group(numbers[:i])

        signal = pattern_group is not None
        distance = i - last_trade
        trade = signal and distance >= GAP

        bet_group = pattern_group if trade else None
        hit_group = None
        pnl = 0.0
        state = "WAIT"

        if signal:
            state = "SIGNAL_PATTERN"

        if trade:
            state = "TRADE_PATTERN"
            last_trade = i

            actual_group = groups[i]

            if actual_group == pattern_group:
                hit_group = 1
                pnl = WIN_GROUP
                consecutive_losses = 0
                phase_loss_streak = 0
            else:
                hit_group = 0
                pnl = LOSS_GROUP
                consecutive_losses += 1
                phase_loss_streak += 1

            phase_profit += pnl
            total_profit += pnl

            phase_hits.append(hit_group)
            total_hits.append(hit_group)

            relock_triggered_now = False
            relock_reason_now = None

            if phase_profit >= PHASE_STOP_WIN:
                relock_triggered_now = True
                relock_reason_now = "PHASE_TAKE_PROFIT"
                state = "PHASE_TAKE_PROFIT"
            elif phase_profit <= PHASE_STOP_LOSS:
                relock_triggered_now = True
                relock_reason_now = "PHASE_STOP_LOSS"
                state = "PHASE_STOP_LOSS"

            if relock_triggered_now:
                phase_summary_rows.append(
                    {
                        "phase": phase_index,
                        "end_round": i,
                        "reason": relock_reason_now,
                        "phase_trades": len(phase_hits),
                        "phase_profit": phase_profit,
                        "phase_winrate": round(np.mean(phase_hits) * 100, 2) if phase_hits else 0.0,
                        "total_profit_after_phase": total_profit,
                    }
                )

                phase_index += 1
                phase_profit = 0.0
                phase_hits = []
                phase_loss_streak = 0
                consecutive_losses = 0

        else:
            relock_triggered_now = False

        history_rows.append(
            {
                "phase": phase_index,
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "pattern_group": pattern_group,
                "pattern_type": pattern_type,
                "signal": signal,
                "trade": trade,
                "bet_group": bet_group,
                "hit_group": hit_group,
                "pnl": pnl,
                "state": state,
                "phase_profit": phase_profit,
                "total_profit": total_profit,
                "phase_loss_streak": phase_loss_streak,
                "consecutive_losses": consecutive_losses,
                "distance_from_last_trade": distance,
            }
        )

    hist = pd.DataFrame(history_rows)
    phase_summary_df = pd.DataFrame(phase_summary_rows)

    if total_profit >= SESSION_STOP_WIN:
        session_stop = True
        session_stop_reason = "SESSION_STOP_WIN"
    elif total_profit <= SESSION_STOP_LOSS:
        session_stop = True
        session_stop_reason = "SESSION_STOP_LOSS"

    return {
        "hist": hist,
        "phase_profit": phase_profit,
        "total_profit": total_profit,
        "phase_hits": phase_hits,
        "total_hits": total_hits,
        "phase_index": phase_index,
        "phase_loss_streak": phase_loss_streak,
        "consecutive_losses": consecutive_losses,
        "last_trade": last_trade,
        "session_stop": session_stop,
        "session_stop_reason": session_stop_reason,
        "phase_summary_df": phase_summary_df,
    }


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_pattern_only(numbers_tuple):
    return simulate_pattern_only(list(numbers_tuple))


sim = cached_simulate_pattern_only(tuple(numbers))

hist = sim["hist"]
phase_profit = sim["phase_profit"]
total_profit = sim["total_profit"]
phase_hits = sim["phase_hits"]
total_hits = sim["total_hits"]
phase_index = sim["phase_index"]
phase_loss_streak = sim["phase_loss_streak"]
consecutive_losses = sim["consecutive_losses"]
last_trade = sim["last_trade"]
session_stop = sim["session_stop"]
session_stop_reason = sim["session_stop_reason"]
phase_summary_df = sim["phase_summary_df"]

# ================= NEXT STATUS =================
next_round = len(numbers)
current_number = numbers[-1]
current_group = groups[-1]

pattern_group, pattern_type = detect_pattern_next_group(numbers)

if not hist.empty:
    trade_rows = hist[hist["trade"] == True]
    distance = next_round - trade_rows["round"].max() if len(trade_rows) > 0 else 999
else:
    distance = 999

signal = pattern_group is not None
can_bet = signal and distance >= GAP and not session_stop
next_state = "READY" if can_bet else "WAIT"

next_row = {
    "phase": phase_index,
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "pattern_group": pattern_group,
    "pattern_type": pattern_type,
    "signal": signal,
    "trade": False,
    "bet_group": pattern_group if can_bet else None,
    "hit_group": None,
    "pnl": 0.0,
    "state": next_state,
    "phase_profit": phase_profit,
    "total_profit": total_profit,
    "phase_loss_streak": phase_loss_streak,
    "consecutive_losses": consecutive_losses,
    "distance_from_last_trade": distance,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

# ================= TELEGRAM =================
if telegram_enabled() and can_bet and pattern_group is not None:
    ready_msg = (
        f"READY PATTERN BET\n"
        f"Round: {next_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Bet Group: {pattern_group}\n"
        f"Pattern: {pattern_type}\n"
        f"Phase Profit: {phase_profit}\n"
        f"Total Profit: {total_profit}\n"
        f"Distance: {distance}"
    )

    send_signal_once("READY", next_round, ready_msg)


# ================= UI =================
st.title("🎯 Pattern Only Engine | No Window | Group Bet")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number)
c2.metric("Current Group", current_group)
c3.metric("Phase", phase_index)
c4.metric("Next Bet Group", pattern_group if pattern_group is not None else "-")

st.write("Pattern Type:", pattern_type)
st.write("Pattern Bet Group:", pattern_group)
st.write("Signal:", signal)
st.write("Can Bet:", can_bet)
st.write("Distance From Last Trade:", distance)
st.write("Session Stop:", session_stop)
st.write("Session Stop Reason:", session_stop_reason)
st.write("Telegram Enabled:", telegram_enabled())

if session_stop:
    if session_stop_reason == "SESSION_STOP_WIN":
        st.success("✅ SESSION STOP WIN")
    elif session_stop_reason == "SESSION_STOP_LOSS":
        st.error("⛔ SESSION STOP LOSS")
elif can_bet and pattern_group is not None:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:28px;border-radius:12px;text-align:center;font-size:34px;color:white;font-weight:bold;">
        READY PATTERN BET<br>
        GROUP {pattern_group}<br>
        PATTERN → {pattern_type}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info(f"WAIT | Pattern={pattern_type}")

st.subheader("Current Phase Stats")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Phase Profit", phase_profit)
s2.metric("Phase Trades", len(phase_hits))
s3.metric("Phase Winrate %", round(np.mean(phase_hits) * 100, 2) if phase_hits else 0)
s4.metric("Phase Loss Streak", phase_loss_streak)

st.subheader("Session Stats")
t1, t2, t3, t4 = st.columns(4)
t1.metric("Total Profit", total_profit)
t2.metric("Total Trades", len(total_hits))
t3.metric("Total Winrate %", round(np.mean(total_hits) * 100, 2) if total_hits else 0)
t4.metric("Last Trade Round", last_trade)

st.subheader("Phase Profit Curve")
if not hist_display.empty:
    current_phase_df = hist_display[hist_display["phase"] == phase_index].copy()
    if not current_phase_df.empty:
        st.line_chart(current_phase_df["phase_profit"].reset_index(drop=True))

st.subheader("Total Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"].reset_index(drop=True))

with st.expander("Phase Summary"):
    st.dataframe(phase_summary_df, use_container_width=True)

st.subheader("History")
history_view = hist_display.iloc[::-1].head(SHOW_HISTORY_ROWS).copy()

if SHOW_STYLED_HISTORY:
    def highlight_trade(row):
        if row["state"] == "READY":
            return ["background-color: #ffd700; color:black"] * len(row)
        if row["state"] == "TRADE_PATTERN":
            return ["background-color: #ff4b4b; color:white"] * len(row)
        if row["state"] in ("PHASE_TAKE_PROFIT",):
            return ["background-color: #2e8b57; color:white"] * len(row)
        if row["state"] in ("PHASE_STOP_LOSS",):
            return ["background-color: #d9534f; color:white"] * len(row)
        return [""] * len(row)

    st.dataframe(history_view.style.apply(highlight_trade, axis=1), use_container_width=True)
else:
    st.dataframe(history_view, use_container_width=True)
