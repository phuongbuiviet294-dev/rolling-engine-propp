import streamlit as st
import pandas as pd
import numpy as np

# ================= CONFIG =================
WINDOW_FIXED = 9

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

BET_SIZE = 1
WIN_RETURN = 2
LOSS_RETURN = -1

# ================ LOAD DATA ================
@st.cache_data(ttl=5)
def load_data():
    df = pd.read_csv(GOOGLE_SHEET_CSV)
    df = df.dropna()
    df = df.reset_index(drop=True)
    return df

df = load_data()

# ================ UI =================
st.title("⚡ AUTO LOOKBACK GAP PRO")

rounds = len(df)
st.metric("Rounds", rounds)

# ================ ENGINE =================
history = []
total_profit = 0
loss_streak = 0
cooldown = 0

def calc_hit(pred, actual):
    return 1 if pred == actual else 0

def choose_group(window_slice):
    counts = window_slice.value_counts()
    return counts.idxmax()

def auto_mode(hit_hist, pnl_hist):
    if len(hit_hist) < 12:
        return 26, 2

    hit_rate = sum(hit_hist[-12:]) / 12
    profit_flow = sum(pnl_hist[-12:])

    if hit_rate >= 0.45 and profit_flow > 0:
        return 18, 1   # Trend mạnh
    elif hit_rate >= 0.30:
        return 26, 2   # Trung tính
    else:
        return 36, 4   # Nhiễu

hit_hist = []
pnl_hist = []

for i in range(rounds):

    actual = df.iloc[i]["group"]

    LOOKBACK, GAP = auto_mode(hit_hist, pnl_hist)

    if i < LOOKBACK:
        history.append({
            "round": i+1,
            "predicted": None,
            "hit": None,
            "pnl": 0,
            "lookback": LOOKBACK,
            "gap": GAP,
            "state": "SCAN",
            "total_profit": total_profit
        })
        continue

    if cooldown > 0:
        cooldown -= 1
        history.append({
            "round": i+1,
            "predicted": None,
            "hit": None,
            "pnl": 0,
            "lookback": LOOKBACK,
            "gap": GAP,
            "state": "COOLDOWN",
            "total_profit": total_profit
        })
        continue

    window_data = df.iloc[i-LOOKBACK:i]["group"]

    if i % GAP != 0:
        history.append({
            "round": i+1,
            "predicted": None,
            "hit": None,
            "pnl": 0,
            "lookback": LOOKBACK,
            "gap": GAP,
            "state": "WAIT",
            "total_profit": total_profit
        })
        continue

    pred = choose_group(window_data)
    hit = calc_hit(pred, actual)

    pnl = WIN_RETURN if hit else LOSS_RETURN
    total_profit += pnl

    hit_hist.append(hit)
    pnl_hist.append(pnl)

    if hit == 0:
        loss_streak += 1
    else:
        loss_streak = 0

    if loss_streak >= 4:
        cooldown = 5
        loss_streak = 0

    history.append({
        "round": i+1,
        "predicted": pred,
        "hit": hit,
        "pnl": pnl,
        "lookback": LOOKBACK,
        "gap": GAP,
        "state": "TRADE",
        "total_profit": total_profit
    })

# ================ STATS =================
df_hist = pd.DataFrame(history)

wins = df_hist["hit"].fillna(0).sum()
trades = df_hist["hit"].notna().sum()
winrate = (wins / trades * 100) if trades > 0 else 0

st.metric("Total Profit", round(total_profit,2))
st.metric("Winrate %", round(winrate,2))

# ================ STATUS =================
last = df_hist.iloc[-1]
if last["state"] == "TRADE":
    st.success(f"🎯 READY — Next bet FOLLOW window {WINDOW_FIXED}")
elif last["state"] == "COOLDOWN":
    st.warning("🧊 Cooling down...")
else:
    st.info("⏳ Waiting signal...")

# ================ TABLE =================
st.subheader("Live History")
st.dataframe(df_hist.tail(50), use_container_width=True)
