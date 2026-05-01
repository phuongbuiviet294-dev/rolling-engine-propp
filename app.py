import time
import json
import os
from collections import Counter

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st_autorefresh(interval=5000, key="refresh")

# ================= CONFIG =================
SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN_GROUP = 2.5
LOSS_GROUP = -1.0

GAP = 2
REPLAY_FROM = 80
SHOW_HISTORY_ROWS = 100

TRAIN_LENS = [50, 80, 120, 160]
WINDOW_MIN = 6
WINDOW_MAX = 22

MODES = [
    {"name": "4v3", "top_windows": 4, "vote_required": 3},
    {"name": "6v4", "top_windows": 6, "vote_required": 4},
    {"name": "8v5", "top_windows": 8, "vote_required": 5},
]

MIN_AI_TRADES = 4
MIN_AI_WR = 0.52
MIN_AI_EV = 0.05
MIN_AI_PROFIT = 0.0
MAX_AI_DD = -8.0

SESSION_STOP_WIN = 30.0
SESSION_STOP_LOSS = -12.0

ALLOW_WINDOW_ONLY = True
ALLOW_PATTERN_ONLY = False
REJECT_WINDOW_PATTERN_CONFLICT = True

# ================= TELEGRAM =================
DEFAULT_BOT_TOKEN = ""
DEFAULT_CHAT_ID = "6655585286"

BOT_TOKEN = st.secrets["BOT_TOKEN"] if "BOT_TOKEN" in st.secrets else DEFAULT_BOT_TOKEN
CHAT_ID = st.secrets["CHAT_ID"] if "CHAT_ID" in st.secrets else DEFAULT_CHAT_ID

SENT_FILE = "/tmp/telegram_sent_hybrid_ai_pro.json"


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


# ================= DATA =================
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
    return {1: "RED", 2: "GREEN", 3: "BLUE"}.get(c, "-")


def color_icon(c):
    return {1: "🔴 RED", 2: "🟢 GREEN", 3: "🔵 BLUE"}.get(c, "-")


# ================= PATTERN =================
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


# ================= WINDOW =================
def calc_max_drawdown(results):
    cur = 0.0
    peak = 0.0
    max_dd = 0.0

    for r in results:
        cur += WIN_GROUP if r == 1 else LOSS_GROUP
        peak = max(peak, cur)
        max_dd = min(max_dd, cur - peak)

    return max_dd


def evaluate_window(seq_groups, w, start_idx, end_idx):
    results = []
    trades = 0
    wins = 0

    for i in range(max(start_idx, w), end_idx):
        pred = seq_groups[i - w]
        hit = 1 if seq_groups[i] == pred else 0
        results.append(hit)
        trades += 1
        wins += hit

    profit = sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results)
    wr = wins / trades if trades else 0.0
    ev = wr * WIN_GROUP + (1 - wr) * LOSS_GROUP
    dd = calc_max_drawdown(results)

    score = profit + ev * 10 + wr * 5 - abs(dd) * 0.7

    return {
        "window": w,
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "ev": ev,
        "profit": profit,
        "dd": dd,
        "score": score,
    }


def select_windows(seq_groups, end_idx, train_len, top_n):
    start_idx = max(1, end_idx - train_len)

    rows = [
        evaluate_window(seq_groups, w, start_idx, end_idx)
        for w in range(WINDOW_MIN, WINDOW_MAX + 1)
        if end_idx > w
    ]

    if not rows:
        return []

    df = pd.DataFrame(rows)
    df = df.sort_values(
        ["score", "profit", "ev", "wr", "trades"],
        ascending=[False, False, False, False, False],
    )

    return df["window"].astype(int).head(top_n).tolist()


def get_window_vote(seq_groups, idx, windows, vote_required):
    preds = [seq_groups[idx - w] for w in windows if idx - w >= 0]

    if not preds:
        return None, 0, False

    vote_group, confidence = Counter(preds).most_common(1)[0]
    vote_signal = confidence >= vote_required

    return vote_group, confidence, vote_signal


# ================= HYBRID SIGNAL =================
def build_hybrid_signal(seq_groups, idx, windows, mode):
    pattern_group, pattern_type = detect_pattern_next_group(seq_groups[:idx])
    vote_group, confidence, vote_signal = get_window_vote(
        seq_groups, idx, windows, mode["vote_required"]
    )

    has_pattern = pattern_group is not None
    source = "NO_SIGNAL"
    bet_group = None

    if vote_signal and has_pattern:
        if pattern_group == vote_group:
            source = "HYBRID_MATCH"
            bet_group = vote_group
        else:
            source = "CONFLICT"
            if not REJECT_WINDOW_PATTERN_CONFLICT:
                bet_group = vote_group

    elif vote_signal and not has_pattern:
        if ALLOW_WINDOW_ONLY:
            source = "WINDOW_ONLY"
            bet_group = vote_group

    elif has_pattern and not vote_signal:
        if ALLOW_PATTERN_ONLY:
            source = "PATTERN_ONLY"
            bet_group = pattern_group

    return {
        "bet_group": bet_group,
        "source": source,
        "pattern_group": pattern_group,
        "pattern_type": pattern_type,
        "vote_group": vote_group,
        "confidence": confidence,
        "vote_signal": vote_signal,
        "has_pattern": has_pattern,
    }


# ================= AI BACKTEST =================
def calc_signal_stats(seq_groups, end_idx, train_len, mode, windows, source_filter):
    start_idx = max(max(WINDOW_MAX + 1, 10), end_idx - train_len)

    results = []
    trades = 0
    wins = 0

    for i in range(start_idx, end_idx):
        sig = build_hybrid_signal(seq_groups, i, windows, mode)

        if sig["bet_group"] is None:
            continue

        if sig["source"] != source_filter:
            continue

        actual = seq_groups[i]
        hit = 1 if actual == sig["bet_group"] else 0

        results.append(hit)
        trades += 1
        wins += hit

    profit = sum(WIN_GROUP if r == 1 else LOSS_GROUP for r in results)
    wr = wins / trades if trades else 0.0
    ev = wr * WIN_GROUP + (1 - wr) * LOSS_GROUP
    dd = calc_max_drawdown(results)

    score = profit + ev * 12 + wr * 6 - abs(dd) * 0.8 + min(trades, 20) * 0.2

    return {
        "train_len": train_len,
        "mode": mode["name"],
        "windows": ",".join(map(str, windows)),
        "source": source_filter,
        "trades": trades,
        "wins": wins,
        "wr": wr,
        "ev": ev,
        "profit": profit,
        "max_dd": dd,
        "score": score,
    }


def ai_pick_signal(seq_groups, idx):
    best = None
    all_rows = []

    for train_len in TRAIN_LENS:
        for mode in MODES:
            windows = select_windows(seq_groups, idx, train_len, mode["top_windows"])
            if len(windows) < mode["top_windows"]:
                continue

            current_sig = build_hybrid_signal(seq_groups, idx, windows, mode)

            if current_sig["bet_group"] is None:
                continue

            if current_sig["source"] == "CONFLICT":
                continue

            stats = calc_signal_stats(
                seq_groups,
                idx,
                train_len,
                mode,
                windows,
                current_sig["source"],
            )

            row = {**current_sig, **stats}
            all_rows.append(row)

            pass_ai = (
                stats["trades"] >= MIN_AI_TRADES
                and stats["wr"] >= MIN_AI_WR
                and stats["ev"] >= MIN_AI_EV
                and stats["profit"] >= MIN_AI_PROFIT
                and stats["max_dd"] >= MAX_AI_DD
            )

            row["ai_ok"] = pass_ai

            if pass_ai:
                if best is None or stats["score"] > best["score"]:
                    best = row

    if best is None:
        return {
            "ai_ok": False,
            "ai_reason": "NO_AI_PASS",
            "all_rows": all_rows,
            "bet_group": None,
            "source": "NO_SIGNAL",
            "pattern_group": None,
            "pattern_type": "NO_PATTERN",
            "vote_group": None,
            "confidence": 0,
            "vote_signal": False,
            "has_pattern": False,
            "train_len": 0,
            "mode": "-",
            "windows": "",
            "trades": 0,
            "wr": 0.0,
            "ev": 0.0,
            "profit": 0.0,
            "max_dd": 0.0,
            "score": 0.0,
        }

    best["ai_ok"] = True
    best["ai_reason"] = "AI_ACCEPT"
    best["all_rows"] = all_rows
    return best


# ================= RUN =================
numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < 40:
    st.error("Chưa đủ dữ liệu.")
    st.stop()


def simulate(numbers, groups, colors):
    rows = []

    total_profit = 0.0
    total_hits = []
    last_trade = -999
    consecutive_losses = 0
    session_stop = False
    session_stop_reason = None

    start_idx = max(REPLAY_FROM, WINDOW_MAX + 5)

    for i in range(start_idx, len(groups)):
        if total_profit >= SESSION_STOP_WIN:
            session_stop = True
            session_stop_reason = "SESSION_STOP_WIN"
            break

        if total_profit <= SESSION_STOP_LOSS:
            session_stop = True
            session_stop_reason = "SESSION_STOP_LOSS"
            break

        sig = ai_pick_signal(groups, i)
        distance = i - last_trade

        trade = sig["ai_ok"] and sig["bet_group"] is not None and distance >= GAP

        hit = None
        pnl = 0.0
        state = "WAIT"

        if trade:
            actual = groups[i]
            hit = 1 if actual == sig["bet_group"] else 0
            pnl = WIN_GROUP if hit == 1 else LOSS_GROUP

            total_profit += pnl
            total_hits.append(hit)
            last_trade = i

            if hit == 1:
                consecutive_losses = 0
            else:
                consecutive_losses += 1

            state = f"TRADE_{sig['source']}"
        elif sig["ai_ok"]:
            state = "SIGNAL_WAIT_GAP"
        else:
            state = "AI_FILTERED"

        rows.append(
            {
                "round": i,
                "number": numbers[i],
                "group": groups[i],
                "color": color_text(colors[i]),
                "state": state,
                "source": sig["source"],
                "bet_group": sig["bet_group"] if trade else None,
                "hit": hit,
                "pnl": pnl,
                "total_profit": total_profit,
                "pattern_type": sig["pattern_type"],
                "pattern_group": sig["pattern_group"],
                "vote_group": sig["vote_group"],
                "confidence": sig["confidence"],
                "mode": sig["mode"],
                "train_len": sig["train_len"],
                "windows": sig["windows"],
                "ai_trades": sig["trades"],
                "ai_wr": round(sig["wr"] * 100, 2),
                "ai_ev": round(sig["ev"], 3),
                "ai_profit": round(sig["profit"], 2),
                "ai_max_dd": round(sig["max_dd"], 2),
                "ai_score": round(sig["score"], 3),
                "ai_reason": sig["ai_reason"],
                "distance": distance,
                "consecutive_losses": consecutive_losses,
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
def cached_simulate(numbers_tuple):
    nums = list(numbers_tuple)
    grps = [group_of(n) for n in nums]
    cols = [color_of_number(n) for n in nums]
    return simulate(nums, grps, cols)


sim = cached_simulate(tuple(numbers))

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

sig = ai_pick_signal(groups, next_round)

if not hist.empty:
    trade_rows = hist[hist["hit"].notna()]
    distance = next_round - trade_rows["round"].max() if len(trade_rows) else 999
else:
    distance = 999

can_bet = (
    sig["ai_ok"]
    and sig["bet_group"] is not None
    and distance >= GAP
    and not session_stop
)

final_bet_group = sig["bet_group"] if can_bet else None

if session_stop:
    ready_reason = session_stop_reason
elif not sig["ai_ok"]:
    ready_reason = sig["ai_reason"]
elif distance < GAP:
    ready_reason = f"GAP_NOT_ENOUGH {distance}"
else:
    ready_reason = "OK_HYBRID_AI_READY"

next_row = {
    "round": next_round,
    "number": current_number,
    "group": current_group,
    "color": color_text(current_color),
    "state": "READY" if can_bet else "WAIT",
    "source": sig["source"],
    "bet_group": final_bet_group,
    "hit": None,
    "pnl": 0.0,
    "total_profit": total_profit,
    "pattern_type": sig["pattern_type"],
    "pattern_group": sig["pattern_group"],
    "vote_group": sig["vote_group"],
    "confidence": sig["confidence"],
    "mode": sig["mode"],
    "train_len": sig["train_len"],
    "windows": sig["windows"],
    "ai_trades": sig["trades"],
    "ai_wr": round(sig["wr"] * 100, 2),
    "ai_ev": round(sig["ev"], 3),
    "ai_profit": round(sig["profit"], 2),
    "ai_max_dd": round(sig["max_dd"], 2),
    "ai_score": round(sig["score"], 3),
    "ai_reason": ready_reason,
    "distance": distance,
    "consecutive_losses": consecutive_losses,
}

hist_display = pd.concat([hist, pd.DataFrame([next_row])], ignore_index=True)

if telegram_enabled() and can_bet:
    msg = (
        f"READY HYBRID AI BET\n"
        f"Round: {current_round}\n"
        f"Current Number: {current_number}\n"
        f"Current Group: {current_group}\n"
        f"Current Color: {color_icon(current_color)}\n"
        f"Bet Group: {final_bet_group}\n"
        f"Source: {sig['source']}\n"
        f"Pattern: {sig['pattern_type']} -> {sig['pattern_group']}\n"
        f"Vote: {sig['vote_group']} strength={sig['confidence']}\n"
        f"Mode: {sig['mode']}\n"
        f"Train Len: {sig['train_len']}\n"
        f"Windows: {sig['windows']}\n"
        f"AI WR: {round(sig['wr'] * 100, 2)}%\n"
        f"AI EV: {round(sig['ev'], 3)}\n"
        f"AI Profit: {round(sig['profit'], 2)}\n"
        f"Total Profit: {total_profit}\n"
        f"Reason: {ready_reason}"
    )
    send_signal_once(current_round, msg)

# ================= UI =================
st.title("🤖 Hybrid AI PRO | Pattern + Window")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Number", current_number)
c2.metric("Current Group", current_group)
c3.metric("Current Color", color_icon(current_color))
c4.metric("Next Bet Group", final_bet_group if final_bet_group is not None else "-")

st.write("Can Bet:", can_bet)
st.write("Ready Reason:", ready_reason)
st.write("Source:", sig["source"])
st.write("Pattern:", f"{sig['pattern_type']} -> {sig['pattern_group']}")
st.write("Window Vote:", sig["vote_group"])
st.write("Vote Strength:", sig["confidence"])
st.write("Mode:", sig["mode"])
st.write("Train Len:", sig["train_len"])
st.write("Windows:", sig["windows"])
st.write("AI Trades:", sig["trades"])
st.write("AI WR %:", round(sig["wr"] * 100, 2))
st.write("AI EV:", round(sig["ev"], 3))
st.write("AI Profit:", round(sig["profit"], 2))
st.write("AI Max DD:", round(sig["max_dd"], 2))
st.write("AI Score:", round(sig["score"], 3))
st.write("Distance:", distance)

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
        READY HYBRID AI BET<br>
        BET GROUP {final_bet_group}<br>
        SOURCE → {sig["source"]}<br>
        MODE → {sig["mode"]} | TRAIN → {sig["train_len"]}<br>
        WR → {round(sig["wr"] * 100, 2)}% | EV → {round(sig["ev"], 3)}
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.info(f"WAIT | {ready_reason}")

st.subheader("Candidate Comparison")
if sig.get("all_rows"):
    st.dataframe(pd.DataFrame(sig["all_rows"]), use_container_width=True)

st.subheader("Total Profit Curve")
if not hist_display.empty:
    st.line_chart(hist_display["total_profit"].reset_index(drop=True))

st.subheader("History")
history_view = hist_display.iloc[::-1].head(SHOW_HISTORY_ROWS).copy()
st.dataframe(history_view, use_container_width=True)
