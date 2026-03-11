import streamlit as st
import pandas as pd
import numpy as np
import requests
from collections import deque

# ===================== CONFIG =====================
st.set_page_config(layout="wide")

WIN_PROFIT = 1
LOSE_LOSS  = 1

WINDOWS = list(range(8,19))        # 8 → 18
LOOKBACKS = [12,16,20,24,28]
GAPS = [1,2,3,4]

MIN_SAMPLE = 15
RECENT_FLOW_N = 6

SOFT_FLOW_ALLOW = -2
HARD_STOP_LOSS_STREAK = 4
COOLDOWN_ROUNDS = 5

# ====== GOOGLE SHEET CSV ======
DATA_URL = st.secrets.get(
    "DATA_URL",
    "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv
)

# ===================== DATA LOAD =====================
@st.cache_data(ttl=3)
def load_data():
    df = pd.read_csv(DATA_URL)
    df = df.dropna()
    df["group"] = df["group"].astype(int)
    return df

df = load_data()

# ===================== ENGINE STATE =====================
if "history" not in st.session_state:
    st.session_state.history = []

history = st.session_state.history

# ===================== UTILS =====================
def calc_hits(seq, gap):
    hits=[]
    for i in range(gap,len(seq)):
        hits.append(1 if seq[i]==seq[i-gap] else 0)
    return hits

def pnl_from_hits(hits):
    return [WIN_PROFIT if h==1 else -LOSE_LOSS for h in hits]

def recent_profit_flow(pnls):
    return sum(pnls[-RECENT_FLOW_N:]) if pnls else 0

# ===================== ADAPTIVE PARAM SEARCH =====================
def find_best_params(groups):

    best=None
    best_score=-999

    for lb in LOOKBACKS:
        sub = groups[-lb:]
        if len(sub)<max(lb,MIN_SAMPLE):
            continue

        for gp in GAPS:
            hits = calc_hits(sub,gp)
            if len(hits)<MIN_SAMPLE:
                continue

            wr = np.mean(hits)
            ev = wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
            pnls = pnl_from_hits(hits)
            flow = recent_profit_flow(pnls)

            score = flow*2 + wr*1.5 + ev*10

            if score>best_score:
                best_score=score
                best=(lb,gp,wr,ev,flow)

    return best

# ===================== WINDOW SCORING =====================
def score_window(groups, window):
    if len(groups)<window:
        return None

    sub=groups[-window:]
    hits = calc_hits(sub,1)
    if len(hits)<MIN_SAMPLE:
        return None

    wr=np.mean(hits)
    ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS
    pnls=pnl_from_hits(hits)
    flow=recent_profit_flow(pnls)
    total=sum(pnls)

    score = flow*2 + wr*1.5 + ev*10 + total*0.5
    return score,wr,ev,flow,total

def pick_best_window(groups):
    best=None
    best_score=-999
    for w in WINDOWS:
        res=score_window(groups,w)
        if not res: continue
        score,wr,ev,flow,total=res
        if score>best_score:
            best_score=score
            best=(w,wr,ev,flow,total)
    return best

# ===================== MAIN ENGINE =====================
groups=df["group"].tolist()

param=find_best_params(groups)
window_pick=pick_best_window(groups)

state="SCAN"
next_group=None

loss_streak=0
cooldown=0

if history:
    loss_streak=history[-1]["loss_streak"]
    cooldown=history[-1]["cooldown"]

if param and window_pick:

    lb,gp,wr,ev,flow=param
    win_w,wr_w,ev_w,flow_w,total_w=window_pick

    # HARD STOP
    if loss_streak>=HARD_STOP_LOSS_STREAK:
        state="HARD_STOP"

    # COOLDOWN
    elif cooldown>0:
        state="COOLDOWN"
        cooldown-=1

    # ENTRY LOGIC
    else:
        if flow>=SOFT_FLOW_ALLOW and ev>0:
            state="TRADE"
            next_group=groups[-gp]
        else:
            state="SCAN"

# ===================== RESULT SIM =====================
hit=None
pnl=0

if state=="TRADE":
    real=groups[-1]
    hit = 1 if next_group==real else 0
    pnl = WIN_PROFIT if hit else -LOSE_LOSS

    if hit==0:
        loss_streak+=1
        cooldown=COOLDOWN_ROUNDS
    else:
        loss_streak=0

# ===================== SAVE HISTORY =====================
history.append({
    "round":len(groups),
    "state":state,
    "next":next_group,
    "hit":hit,
    "pnl":pnl,
    "loss_streak":loss_streak,
    "cooldown":cooldown
})

total_profit=sum(h["pnl"] for h in history)
winrate = np.mean([h["hit"] for h in history if h["hit"] is not None])*100 if history else 0

# ===================== UI =====================
st.title("🚀 TURBO FLOW HIT — ADAPTIVE PARAM PRO")

c1,c2,c3=st.columns(3)
c1.metric("Rounds",len(groups))
c2.metric("Total Profit",round(total_profit,2))
c3.metric("Winrate %",round(winrate,2))

if state=="TRADE":
    st.success(f"READY TO BET — NEXT GROUP: {next_group}")
elif state=="COOLDOWN":
    st.warning(f"COOLDOWN — {cooldown} rounds left")
elif state=="HARD_STOP":
    st.error("HARD STOP — Market bad")
else:
    st.info("Scanning market...")

st.subheader("Live History (No Repaint)")
st.dataframe(pd.DataFrame(history[::-1]),use_container_width=True)
