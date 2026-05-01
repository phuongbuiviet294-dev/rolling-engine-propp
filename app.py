import time
import json
import os

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, key="refresh")

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

GAP = 1

TRAIN_LENS = [20, 30, 50, 80, 120]

MIN_PATTERN_TRADES = 5

MIN_PATTERN_WR = 0.5
MIN_PATTERN_EV = -0.02
MIN_PATTERN_PROFIT = -1.0
MAX_PATTERN_DD_LIMIT = -8.0

STRONG_WR = 0.58
STRONG_EV = 0.30
STRONG_PROFIT = 2.5

SESSION_STOP_WIN = 30.0
SESSION_STOP_LOSS = -10.0

REPLAY_FROM = 30
SHOW_HISTORY_ROWS = 100

DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID

SENT_FILE = "/tmp/telegram_sent_adaptive_ai_pattern_balanced.json"


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


def send_signal_once(current_round, msg):
    signal_key = f"READY|ROUND_{current_round}"

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


@st.cache_data(ttl=30, show_spinner=False)
def load_numbers():
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}"
    df = pd.read_csv(url)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "number" not in df.columns:
        raise ValueError("Sheet phải có column 'number'")

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


def color_of_number(n):
    if n <= 4:
        return 1
    if n <= 8:
        return 2
    return 3


def color_text(c):
    if c == 1:
        return "RED"
    if c == 2:
        return "GREEN"
    if c == 3:
        return "BLUE"
    return "-"


def color_icon(c):
    if c == 1:
        return "🔴 RED"
    if c == 2:
        return "🟢 GREEN"
    if c == 3:
        return "🔵 BLUE"
    return "-"


def detect_pattern_next_group(seq_groups):
    n = len(seq_groups)

    if n >= 8:
        a, b, c, d, e, f, g, h = seq_groups[-8:]
        if a == b == c and d == e == f and g == h == a and a != d:
            return a, "AAABBBAA"

    if n >= 7:
        a, b, c, d, e, f, g = seq_groups[-7:]
        if a == b == c and d == e == f and g == a and a != d:
            return a, "AAABBBA"

    if n >= 5:
        a, b, c, d, e = seq_groups[-5:]

        if a == b and c == d and e == a and a != c:
            return a, "AABBA"

        if a == c == e and b == d and a != b:
            return b, "ABABA_REVERSE"

    if n >= 4:
        a, b, c, d = seq_groups[-4:]

        if a == b == c and d != a:
            return a, "AAAB"

        if a == c and b == d and a != b:
            return a, "ABAB"

        if a == d and b == c and a != b:
            return a, "ABBA"

        if a == b and c == d and a != c:
            return a, "AABB"

        if a == b and a == d and c != a:
            return a, "AABA"

        if a == c == d and b != a:
            return a, "ABAA"

    if n >= 3:
        a, b, c = seq_groups[-3:]
        if a == b == c:
            return a, "AAA"

        if a == c and a != b:
            return a, "ABA"

    return None, "NO_PATTERN"


def calc_max_drawdown(results):
    peak = 0.0
    cur = 0.0
    max_dd = 0.0

    for r in results:
        cur += WIN_GROUP if r == 1 else LOSS_GROUP
        peak = max(peak, cur)
        max_dd = min(max_dd, cur - peak)

    return max_dd


def calc_pattern_stats(seq_groups, pattern_type, end_idx, train_len):
    start_idx = max(3, end_idx - train_len)

    results = []
    trades = 0
    wins = 0

    for i in range(start_idx, end_idx):
        pg, pt = detect_pattern_next_group(seq_groups[:i])

        if pg is None or pt != pattern_type:
            continue

        actual = seq_groups[i]
        hit = 1 if actual == pg else 0

        results.append(hit)
        trades += 1
        wins += hit

    profit = sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results)
    wr = wins / trades if trades else 0.0
    ev = wr * WIN_GROUP + (1 - wr) * LOSS_GROUP
    max_dd = calc_max_drawdown(results)

    return {
        "pattern_type": pattern_type,
        "train_len": train_len,
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "ev": ev,
        "profit": profit,
        "max_dd": max_dd,
    }


def pick_best_adaptive_stats(seq_groups, pattern_type, end_idx):
    best = None
    all_stats = []

    for train_len in TRAIN_LENS:
        stats = calc_pattern_stats(seq_groups, pattern_type, end_idx, train_len)

        score = (
            stats["ev"] * 10
            + stats["profit"] * 0.8
            + stats["wr"] * 5
            - abs(stats["max_dd"]) * 0.6
            + min(stats["trades"], 20) * 0.15
        )

        stats["score"] = score
        all_stats.append(stats)

        if best is None or score > best["score"]:
            best = stats

    return best, all_stats


def adaptive_ai_accept(seq_groups, pattern_group, pattern_type, end_idx):
    if pattern_group is None or pattern_type == "NO_PATTERN":
        return False, "NO_PATTERN", {}, []

    best, all_stats = pick_best_adaptive_stats(seq_groups, pattern_type, end_idx)

    if best["trades"] < MIN_PATTERN_TRADES:
        return False, f"LOW_SAMPLE {best['trades']}/{MIN_PATTERN_TRADES}", best, all_stats

    if (
        best["wr"] >= STRONG_WR
        and best["ev"] >= STRONG_EV
        and best["profit"] >= STRONG_PROFIT
        and best["max_dd"] >= MAX_PATTERN_DD_LIMIT
    ):
        return True, "READY_STRONG", best, all_stats

    if (
        best["wr"] >= MIN_PATTERN_WR
        and best["ev"] >= MIN_PATTERN_EV
        and best["profit"] >= MIN_PATTERN_PROFIT
        and best["max_dd"] >= MAX_PATTERN_DD_LIMIT
    ):
        return True, "READY_SOFT", best, all_stats

    return False, (
        f"AI_REJECT WR={round(best['wr'] * 100, 2)}% "
        f"EV={round(best['ev'], 3)} "
        f"PROFIT={round(best['profit'], 2)} "
        f"DD={round(best['max_dd'], 2)}"
    ), best, all_stats


numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < 30:
    st.error("Chưa đủ dữ liệu để chạy adaptive AI.")
    st.stop()


def simulate_adaptive_ai(numbers, groups, colors):
    rows = []

    total_profit = 0.0
    total_hits = []
    last_trade = -999
    consecutive_losses = 0
    session_stop = False
    session_stop_reason = None

    start_idx = max(REPLAY_FROM, 10)

    for i in range(start_idx, len(groups)):
        if total_profit >= SESSION_STOP_WIN:
            session_stop = True
            session_stop_reason = "SESSION_STOP_WIN"
            break

        if total_profit <= SESSION_STOP_LOSS:
            session_stop = True
            session_stop_reason = "SESSION_STOP_LOSS"
            break

        pattern_group, pattern_type = detect_pattern_next_group(groups[:i])
        ai_ok, ai_reason, best, _ = adaptive_ai_accept(groups, pattern_group, pattern_type, i)

        distance = i - last_trade
        trade = ai_ok and distance >= GAP

        bet_group = pattern_group if trade else None
        hit = None
        pnl = 0.0
        state = "WAIT"

        if trade:
            actual_group = groups[i]
            last_trade = i

            hit = 1 if actual_group == bet_group else 0
            pnl = WIN_GROUP if hit == 1 else LOSS_GROUP

            total_profit += pnl
            total_hits.append(hit)

            if hit == 1:
                consecutive_losses = 0
            else:
                consecutive_losses += 1

            state = "TRADE_ADAPTIVE_AI"

        elif pattern_group is not None and not ai_ok:
            state = "AI_FILTERED"
        elif ai_ok:
            state = "SIGNAL_WAIT_GAP"

        rows.append(
            {
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "pattern_group": pattern_group,
                "pattern_type": pattern_type,
                "ai_ok": ai_ok,
                "ai_reason": ai_reason,
                "best_train_len": best.get("train_len", 0),
                "ai_trades": best.get("trades", 0),
                "ai_wr": round(best.get("wr", 0) * 100, 2),
                "ai_ev": round(best.get("ev", 0), 3),
                "ai_profit": round(best.get("profit", 0), 2),
                "ai_max_dd": round(best.get("max_dd", 0), 2),
                "ai_score": round(best.get("score", 0), 3),
                "trade": trade,
                "bet_group": bet_group,
                "hit": hit,
                "pnl": pnl,
                "total_profit": total_profit,
                "consecutive_losses": consecutive_losses,
                "distance": distance,
                "state": state,
            }
        )

    return {
        "hist": pd.DataFrame(rows),
        "total_profit": total_profit,
        "total_hits": total_hits,
        "last_trade": last_trade,
        "consecutive_losses": consecutive_losses,
        "session_stop": session_stop,
        "session_stop_reason": session_stop_reason,
    }


@st.cache_data(ttl=20, show_spinner=False)
def cached_simulate_adaptive_ai(numbers_tuple):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    cols = [color_of_number(n) for n in nums]
    return simulate_adaptive_ai(nums, grps, cols)


sim = cached_simulate_adaptive_ai(tuple(numbers))

hist = sim["hist"]
total_profit = sim["total_profit"]
total_hits = sim["total_hits"]
last_trade = sim["last_trade"]
consecutive_losses = sim["consecutive_losses"]
session_stop = sim["session_stop"]
session_stop_reason = sim["session_stop_reason"]

next_round = len(groups)
current_round = len(numbers)

current_number = numbers[-1]
current_group = groups[-1]
current_color = colors[-1]

pattern_group, pattern_type = detect_pattern_next_group(groups)
ai_ok, ai_reason, best, all_stats = adaptive_ai_accept(groups, pattern_group, pattern_type, len(groups))

if not hist.empty:
    trade_rows = hist[hist["trade"] == True]
    distance = next_round - trade_rows["round"].max() if len(trade_rows) else 999
else:
    distance = 999

can_bet = ai_ok and distance >= GAP and not session_stop
final_bet_group = pattern_group if can_bet else None

if session_stop:
    ready_reason = session_stop_reason
elif pattern_group is None:
    ready_reason = "NO_PATTERN"
elif not ai_ok:
    ready_reason = ai_reason
elif distance < GAP:
    ready_reason = f"GAP_NOT_ENOUGH {distance}"
else:
    ready_reason = "OK_ADAPTIVE_READY"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "color": color_text(current_color),
    "pattern_group": pattern_group,
    "pattern_type": pattern_type,
    "ai_ok": ai_ok,
    "ai_reason": ai_reason,
    "best_train_len": best.get("train_len", 0),
    "ai_trades": best.get("trades", 0),
    "ai_wr": round(best.get("wr", 0) * 100, 2),
    "ai_ev": round(best.get("ev", 0), 3),
    "ai_profit": round(best.get("profit", 0), 2),
    "ai_max_dd": round(best.get("max_dd", 0), 2),
    "ai_score": round(best.get("score", 0), 3),
    "trade": False,
    "bet_group": final_bet_group,
    "hit": None,
    "pnl": 0.0,
    "total_profit": total_profit,
    "consecutive_losses": consecutive_losses,
    "distance": distance,
    "state": "READY" if can_bet else "WAIT",
    "ready_reason": ready_reason,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

if telegram_enabled() and can_bet and final_bet_group is not None:
    msg = (
        f"READY ADAPTIVE AI BET\n"
        f"Round: {current_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Current Color: {color_icon(current_color)}\n"
        f"Bet Group: {final_bet_group}\n"
        f"Pattern: {pattern_type}\n"
        f"Best Train Len: {best.get('train_len', 0)}\n"
        f"AI Trades: {best.get('trades', 0)}\n"
        f"AI WR: {round(best.get('wr', 0) * 100, 2)}%\n"
        f"AI EV: {round(best.get('ev', 0), 3)}\n"
        f"AI Profit: {round(best.get('profit', 0), 2)}\n"
        f"AI DD: {round(best.get('max_dd', 0), 2)}\n"
        f"Total Profit: {total_profit}\n"
        f"Reason: {ready_reason}"
    )
    send_signal_once(current_round, msg)


st.title("🤖 Adaptive AI Pattern Live Engine")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number)
c2.metric("Current Group", current_group)
c3.metric("Current Color", color_icon(current_color))
c4.metric("Next Bet Group", final_bet_group if final_bet_group is not None else "-")

st.write("Pattern Type:", pattern_type)
st.write("Pattern Group:", pattern_group)
st.write("AI OK:", ai_ok)
st.write("AI Reason:", ai_reason)
st.write("Best Train Len:", best.get("train_len", 0))
st.write("AI Trades:", best.get("trades", 0))
st.write("AI WR %:", round(best.get("wr", 0) * 100, 2))
st.write("AI EV:", round(best.get("ev", 0), 3))
st.write("AI Profit:", round(best.get("profit", 0), 2))
st.write("AI Max DD:", round(best.get("max_dd", 0), 2))
st.write("AI Score:", round(best.get("score", 0), 3))
st.write("Distance:", distance)
st.write("Ready Reason:", ready_reason)

st.write("Total Profit:", total_profit)
st.write("Total Trades:", len(total_hits))
st.write("Total WR %:", round(sum(total_hits) / len(total_hits) * 100, 2) if total_hits else 0)
st.write("Consecutive Losses:", consecutive_losses)
st.write("Session Stop:", session_stop)
st.write("Session Stop Reason:", session_stop_reason)
st.write("Telegram Enabled:", telegram_enabled())

if session_stop:
    st.error(f"⛔ {session_stop_reason}")
elif can_bet:
    st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:22px;border-radius:10px;text-align:center;font-size:28px;color:white;font-weight:bold;">
        READY ADAPTIVE AI BET<br>
        BET GROUP {final_bet_group}<br>
        PATTERN → {pattern_type}<br>
        TRAIN LEN → {best.get("train_len", 0)}<br>
        WR → {round(best.get("wr", 0) * 100, 2)}% | EV → {round(best.get("ev", 0), 3)}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info(f"WAIT | {ready_reason}")

st.subheader("Adaptive Train Len Comparison")
if all_stats:
    st.dataframe(pd.DataFrame(all_stats), use_container_width=True)

st.subheader("Total Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"].reset_index(drop=True))

st.subheader("History")
history_view = hist_display.iloc[::-1].head(SHOW_HISTORY_ROWS).copy()
st.dataframe(history_view, use_container_width=True)
