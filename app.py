import time 
import pandas as pd 
import streamlit as st 
from collections import Counter

================= CONFIG =================

SHEET_ID = "18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY"

WIN = 2.5 LOSS = -1.0 GAP = 1

================= LOAD =================

@st.cache_data(ttl=10) def load_numbers(): url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&cache={time.time()}" df = pd.read_csv(url) df.columns = [c.lower() for c in df.columns] return df["number"].dropna().astype(int).tolist()

numbers = load_numbers()

================= GROUP =================

def group_of(n): if n <= 3: return 1 elif n <= 6: return 2 elif n <= 9: return 3 return 4

groups = [group_of(n) for n in numbers]

================= ENGINE =================

history = [] last_trade_round = -999 last_trade_pnl = None profit_total = 0

for i in range(10, len(groups)): vote = groups[i-1]

can_signal = True

# RULE MOI
allow_trade = (last_trade_pnl is not None and last_trade_pnl > 0)

distance = i - last_trade_round

trade = can_signal and allow_trade and distance >= GAP

pnl = 0

if trade:
    last_trade_round = i
    if groups[i] == vote:
        pnl = WIN
    else:
        pnl = LOSS

    last_trade_pnl = pnl
    profit_total += pnl

history.append({
    "round": i,
    "group": groups[i],
    "vote": vote,
    "trade": trade,
    "pnl": pnl,
    "profit_total": profit_total,
    "last_trade_pnl": last_trade_pnl
})

hist = pd.DataFrame(history)

================= NEXT =================

next_round = len(groups) next_vote = groups[-1]

allow_trade_next = (last_trade_pnl is not None and last_trade_pnl > 0)

last_trade_idx = hist[hist.trade == True]["round"].max() if len(hist[hist.trade == True]) else -999

distance = next_round - last_trade_idx

can_bet = allow_trade_next and distance >= GAP

================= UI =================

st.title("🔥 SIMPLE ENGINE - LAST TRADE FILTER")

st.metric("Current Group", groups[-1]) st.metric("Next Bet Group", next_vote if can_bet else "-")

st.write("Last Trade PnL:", last_trade_pnl) st.write("Allow Trade Next:", allow_trade_next) st.write("Distance:", distance) st.write("Can Bet:", can_bet)

if can_bet: st.success(f"READY → BET GROUP {next_vote}") else: st.warning("WAIT")

st.subheader("History") st.dataframe(hist.tail(30))
