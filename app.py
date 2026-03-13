import streamlit as st
import pandas as pd
import numpy as np
from collections import Counter

# ================= CONFIG =================

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5

WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOW_POOL=range(8,18)

LOOKBACK=26

SIGNAL_THRESHOLD=0.45

LOCK_ROUND=3662
STOPLOSS_STREAK=5
PAUSE_AFTER_SL=3

st.set_page_config(layout="wide")

# ================= GROUP =================

def get_group(n):

    if 1<=n<=3: return 1
    if 4<=n<=6: return 2
    if 7<=n<=9: return 3
    if 10<=n<=12: return 4

    return None


# ================= LOAD =================

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    df=pd.read_csv(GOOGLE_SHEET_CSV)

    df.columns=[c.strip().lower() for c in df.columns]

    numbers=df["number"].dropna().astype(int).tolist()

    return numbers


numbers=load()

groups=[get_group(n) for n in numbers]

st.write("Total rounds:",len(groups))


# ================= WINDOW SCORE =================

def window_score(data,w):

    profit=0

    for i in range(w,len(data)-1):

        seq=data[i-w:i]

        pred=Counter(seq).most_common(1)[0][0]

        if pred==data[i]:

            profit+=WIN_PROFIT

        else:

            profit-=LOSE_LOSS

    return profit


# chọn window tốt nhất

scores={w:window_score(groups[-500:],w) for w in WINDOW_POOL}

best_window=max(scores,key=scores.get)


# ================= ENGINE =================

profit=0
equity=[]

hits=[]

trades=0
wins=0

loss_streak=0
pause=0

trade_log=[]

for i in range(best_window,len(groups)-1):

    seq=groups[i-best_window:i]

    pred=Counter(seq).most_common(1)[0][0]

    actual=groups[i]

    hit=1 if pred==actual else 0

    hits.append(hit)

    # -------- momentum --------

    momentum=0

    if len(hits)>=LOOKBACK:

        momentum=sum(hits[-LOOKBACK:])/LOOKBACK


    # -------- regime --------

    regime="break"

    if momentum>=0.48:

        regime="trend"

    elif momentum>=0.33:

        regime="random"


    # -------- pattern --------

    pattern=0

    if len(hits)>30:

        pattern=sum(hits[-30:])/30


    # -------- markov --------

    markov=0

    if len(hits)>5:

        last=hits[-1]

        trans=[hits[j+1] for j in range(len(hits)-1) if hits[j]==last]

        if trans:

            markov=sum(trans)/len(trans)


    stability=momentum


    strength=(

        0.35*pattern+
        0.25*momentum+
        0.20*markov+
        0.20*stability

    )


    trade=False

    if pause>0:

        pause-=1

    else:

        if strength>=SIGNAL_THRESHOLD and regime!="break":

            trade=True


    if trade:

        trades+=1

        if hit:

            wins+=1
            profit+=WIN_PROFIT
            loss_streak=0

        else:

            profit-=LOSE_LOSS
            loss_streak+=1


    if loss_streak>=STOPLOSS_STREAK:

        pause=PAUSE_AFTER_SL
        loss_streak=0


    equity.append(profit)


    trade_log.append({

        "round":i,
        "pred":pred,
        "actual":actual,
        "hit":hit,
        "strength":round(strength,3),
        "profit":profit
    })


wr=wins/trades if trades else 0


# ================= NEXT SIGNAL =================

next_seq=groups[-best_window:]

next_pred=Counter(next_seq).most_common(1)[0][0]


# ================= UI =================

st.title("⚡ V77 Stable Regime Engine")

c1,c2,c3=st.columns(3)

c1.metric("Best Window",best_window)
c2.metric("Trades",trades)
c3.metric("Winrate %",round(wr*100,2))

st.metric("Live Profit",round(profit,2))


st.subheader("Next Signal")

if strength>=SIGNAL_THRESHOLD:

    st.success(f"TRADE → Group {next_pred}")

else:

    st.info(f"WAIT → Group {next_pred}")


st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))


st.subheader("Recent Trades")

st.dataframe(pd.DataFrame(trade_log).iloc[::-1].head(50))
