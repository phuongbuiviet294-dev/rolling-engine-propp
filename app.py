import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5
ALLOWED_WINDOWS = [9,14]
WIN_PROFIT = 2.5
LOSE_LOSS = 1

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None

def recent_winrate(engine, w, lookback=50):
    df = pd.DataFrame(engine)
    df_w = df[(df["window"]==w) & (df["hit"].notna())]
    if len(df_w)==0:
        return 0
    return df_w.tail(lookback)["hit"].mean()

# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)

df = load()
if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()

engine=[]
total_profit=0
equity_curve=[0]
last_trade_round=-999

# ================= ENGINE LOOP ================= #

for i,n in enumerate(numbers):

    g=get_group(n)
    predicted=None
    hit=None
    state="SCAN"
    window_display=None

    if len(engine)>=26:

        best_window=None
        best_ev=-999

        for w in ALLOWED_WINDOWS:
            wr=recent_winrate(engine,w)
            ev=wr*WIN_PROFIT - (1-wr)*LOSE_LOSS
            if ev>best_ev:
                best_ev=ev
                best_window=w

        if best_window and best_ev>0:

            # Chỉ trade nếu chưa trade ở vòng trước
            if i-last_trade_round>1:

                predicted=engine[-best_window]["group"]
                hit=1 if predicted==g else 0
                window_display=best_window

                if hit==1:
                    total_profit+=WIN_PROFIT
                else:
                    total_profit-=LOSE_LOSS

                equity_curve.append(total_profit)
                last_trade_round=i
                state="ONE_SHOT"

    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":window_display,
        "state":state
    })

# ================= DASHBOARD ================= #

st.title("🎯 ONE-SHOT PRO ENGINE")

col1,col2,col3,col4 = st.columns(4)

col1.metric("Total Rounds",len(engine))
col2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:
    wr=sum(hits)/len(hits)
    col3.metric("Winrate %",round(wr*100,2))

    p=wr
    kelly=p-(1-p)/WIN_PROFIT
    col4.metric("Kelly %",round(max(0,kelly)*100,2))

# Max DD
if len(equity_curve)>1:
    peak=np.maximum.accumulate(equity_curve)
    dd=peak-equity_curve
    st.metric("Max Drawdown",round(max(dd),2))

# NEXT GROUP (Preview only)
if len(engine)>=1 and engine[-1]["window"]:
    next_group=engine[-1]["predicted"]
    st.markdown(f"""
    <div style='padding:15px;
                background:#1f4e79;
                color:white;
                border-radius:10px;
                text-align:center;
                font-size:26px;
                font-weight:bold'>
        🎯 NEXT GROUP: {next_group}
    </div>
    """,unsafe_allow_html=True)

st.subheader("History")
st.dataframe(pd.DataFrame(engine).iloc[::-1],use_container_width=True)

st.caption("ONE SHOT MODE | TRADE ONCE PER SIGNAL | NO LOCK | PURE EV FILTER")
