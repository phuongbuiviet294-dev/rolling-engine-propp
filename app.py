# ================== IMPORT ==================
import streamlit as st
import pandas as pd
import numpy as np

# ================== CONFIG ==================
GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW = 9
BASE_LOOKBACK = 26
BASE_GAP = 2

# ================== LOAD DATA ==================
@st.cache_data(ttl=10)
def load_data():
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

df = load_data()

st.title("⚡ TURBO ENGINE — AUTO LOOKBACK GAP PRO (FIXED)")

if df.empty:
    st.error("Không tải được dữ liệu Google Sheet")
    st.stop()

# ================== PREP ==================
if "group" not in df.columns:
    st.error("Thiếu cột: group")
    st.stop()

groups = df["group"].tolist()
n = len(groups)

history = []
total_profit = 0
last_trade_round = -999
loss_streak = 0

# ================== AUTO LOOKBACK GAP ==================
def auto_params(loss_streak):
    lookback = BASE_LOOKBACK + min(loss_streak * 2, 20)
    gap = max(1, BASE_GAP - min(loss_streak // 2, 1))
    return lookback, gap

# ================== ENGINE ==================
for i in range(n):
    state = "SCAN"
    pred = None
    hit = None
    pnl = 0

    LOOKBACK, GAP = auto_params(loss_streak)

    if i >= LOOKBACK and i - last_trade_round >= GAP:
        window_data = groups[i-LOOKBACK:i]
        freq = pd.Series(window_data).value_counts()

        if WINDOW in freq.index:
            pred = WINDOW
            state = "TRADE"
            last_trade_round = i

            if i+1 < n:
                actual = groups[i+1]
                hit = 1 if actual == pred else 0
                pnl = 2 if hit else -1
                total_profit += pnl
                loss_streak = 0 if hit else loss_streak + 1

    # ===== SAFE HISTORY RECORD =====
    history.append({
        "round": i+1,
        "group": groups[i],
        "predicted": pred,
        "hit": hit,
        "pnl": pnl,
        "lookback": LOOKBACK,
        "gap": GAP,
        "state": state,
        "total_profit": total_profit
    })

# ================== SAFE STATS ==================
df_hist = pd.DataFrame(history)

if "hit" in df_hist.columns:
    wins = df_hist["hit"].fillna(0).sum()
    trades = df_hist["hit"].notna().sum()
else:
    wins = 0
    trades = 0

winrate = (wins / trades * 100) if trades > 0 else 0

# ================== UI ==================
st.metric("Rounds", n)
st.metric("Total Profit", round(total_profit,2))
st.metric("Winrate %", round(winrate,2))

st.dataframe(df_hist.tail(50), use_container_width=True)
