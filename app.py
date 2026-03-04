import streamlit as st
import pandas as pd
import numpy as np
import math
from collections import Counter

GOOGLE_SHEET_CSV="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH=5
WIN_PROFIT=2.5
LOSE_LOSS=1

WINDOW_RANGE=range(4,31)

st.set_page_config(layout="wide")

# ================= CORE ================= #

def get_group(n):

    if 1<=n<=3:return 1
    if 4<=n<=6:return 2
    if 7<=n<=9:return 3
    if 10<=n<=12:return 4

    return None


@st.cache_data(ttl=AUTO_REFRESH)
def load():

    return pd.read_csv(GOOGLE_SHEET_CSV)


df=load()

numbers=df["number"].dropna().astype(int).tolist()

groups=[get_group(x) for x in numbers]

engine=[]

total_profit=0
last_trade_round=-999

next_signal=None
next_window=None
next_wr=None
next_ev=None

preview_signal=None
preview_window=None
preview_wr=None
preview_ev=None

signal_created_round=None

retry_mode=False

# ================= ENGINE ================= #

for i,n in enumerate(numbers):

    g=groups[i]

    predicted=None
    hit=None
    state="SCAN"

# ===== EXECUTE TRADE =====

    if next_signal is not None and signal_created_round<i:

        predicted=next_signal

        hit=1 if predicted==g else 0

        if hit:

            total_profit+=WIN_PROFIT
            retry_mode=False
            next_signal=None

        else:

            total_profit-=LOSE_LOSS

            if retry_mode==False:

                retry_mode=True

            else:

                next_signal=None
                retry_mode=False

        state="TRADE"
        last_trade_round=i


# ===== AI WINDOW SCAN =====

    if len(engine)>=60 and next_signal is None:

        best_score=-999
        best_window=None
        best_wr=0
        best_ev=0

        for w in WINDOW_RANGE:

            hits=[]

            for j in range(i-50,i):

                if j>=w:

                    if groups[j]==groups[j-w]:
                        hits.append(1)
                    else:
                        hits.append(0)

            if len(hits)<25:
                continue

            wr=np.mean(hits)

            ev=wr*WIN_PROFIT-(1-wr)*LOSE_LOSS

            stability=1-np.var(hits)

            score=ev*stability*math.log(len(hits))

            if score>best_score:

                best_score=score
                best_window=w
                best_wr=wr
                best_ev=ev


# ===== MARKOV TRANSITION =====

        transition=np.zeros((4,4))

        for j in range(i-40,i-1):

            a=groups[j]-1
            b=groups[j+1]-1

            transition[a][b]+=1

        for r in range(4):

            s=sum(transition[r])

            if s>0:
                transition[r]/=s


        current=groups[i-1]-1

        markov_pred=np.argmax(transition[current])+1


# ===== HOT GROUP =====

        recent=groups[i-20:i]

        freq=Counter(recent)

        hot_group=max(freq,key=freq.get)


# ===== COMBINE SIGNAL =====

        window_pred=groups[i-best_window] if best_window else None

        votes=[window_pred,markov_pred,hot_group]

        vote_count=Counter(votes)

        signal_group=vote_count.most_common(1)[0][0]


# ===== PREVIEW =====

        if best_window and best_wr>0.30:

            preview_signal=signal_group
            preview_window=best_window
            preview_wr=round(best_wr*100,2)
            preview_ev=round(best_ev,3)


# ===== REGIME STRENGTH =====

        regime_strength=best_wr


# ===== COOLDOWN =====

        cooldown=4

        if regime_strength>=0.42:
            cooldown=2

        elif regime_strength>=0.36:
            cooldown=3


# ===== CONFIRM SIGNAL =====

        if best_window and best_wr>0.33 and best_ev>0:

            if i-last_trade_round>cooldown:

                next_signal=signal_group
                next_window=best_window
                next_wr=round(best_wr*100,2)
                next_ev=round(best_ev,3)

                signal_created_round=i

                state="SIGNAL"


# ===== SAVE HISTORY =====

    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "window":next_window,
        "state":state

    })


# ================= DASHBOARD ================= #

st.title("⚡ QUANT AI ENGINE V3")

col1,col2,col3=st.columns(3)

col1.metric("Total Rounds",len(engine))
col2.metric("Total Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr=np.mean(hits)

    col3.metric("Winrate %",round(wr*100,2))


# ===== PREVIEW =====

if preview_signal:

    st.markdown(f"""
<div style='padding:15px;background:#444;color:white;border-radius:10px;text-align:center;font-size:20px'>

🔎 PREVIEW SIGNAL: {preview_signal}

Window: {preview_window}

WR: {preview_wr} %

EV: {preview_ev}

</div>
""",unsafe_allow_html=True)


# ===== NEXT GROUP =====

if next_signal:

    st.markdown(f"""
<div style='padding:20px;background:#c62828;color:white;border-radius:12px;text-align:center;font-size:28px;font-weight:bold'>

🚨 READY TO BET

NEXT GROUP: {next_signal}

Window: {next_window}

WR: {next_wr} %

EV: {next_ev}

</div>
""",unsafe_allow_html=True)

else:

    st.info("No valid signal yet")


# ===== HISTORY =====

st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)

st.caption("QUANT AI ENGINE V3 | WINDOW + MARKOV + HOT GROUP")
