import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 2.5
LOSE_LOSS = 1

EV_THRESHOLD = 0.07

WINDOWS = [8,9,10,12,14,16]

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None


@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)


df = load()

if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

# ================= ENGINE ================= #

engine = []

total_profit = 0

last_trade_round = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None

signal_created_at = None

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None


for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"

    window_used = None
    rolling_wr = None
    ev_value = None

    executed_from_round = None
    reason = None

    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev
        executed_from_round = signal_created_at

        hit = 1 if predicted == g else 0

        if hit == 1:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS
