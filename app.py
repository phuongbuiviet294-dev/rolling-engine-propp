import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=2000
RETRAIN=200

WIN=2.5
LOSS=1

WINDOW_RANGE=range(6,19)

LOOKBACK=26

# -------- group --------

def get_group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# -------- load --------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[get_group(n) for n in numbers]


# -------- train window --------

def train_window(data):

    best=None
    best_profit=-999

    for w in WINDOW_RANGE:

        p=0

        for i in range(w,len(data)):

            pred=data[i-w]
            actual=data[i]

            p += WIN if pred==actual else -LOSS

        if p>best_profit:

            best_profit=p
            best=w

    return best


window=train_window(groups[:TRAIN_SIZE])

profit=0
hits=[]
equity=[]
history=[]

pending_signal=None

last_retrain=TRAIN_SIZE


# -------- engine --------

for i in range(TRAIN_SIZE,len(groups)):

    g=groups[i]

    predicted=None
    hit=None

    # ---- execute trade ----

    if pending_signal is not None:

        predicted=pending_signal
        hit = 1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        hits.append(hit)

        pending_signal=None


    # ---- compute hits ----

    if i>=window:

        rec=[]

        for j in range(i-LOOKBACK,i):

            if j>=window:

                rec.append(
                    1 if groups[j]==groups[j-window] else 0
                )


        # ---- detect streak ----

        streak=0

        for x in reversed(rec):

            if x==0:
                streak+=1
            else:
                break


        # ---- trend pattern ----

        h1 = rec[-1] if len(rec)>1 else 0
        h2 = rec[-2] if len(rec)>2 else 0


        trend_signal=False
        reversion_signal=False


        if h1==1 and h2==1:
            trend_signal=True


        if streak>=4:
            reversion_signal=True


        if trend_signal or reversion_signal:

            pending_signal=groups[i-window]


    # ---- retrain ----

    if i-last_retrain>=RETRAIN:

        window=train_window(groups[:i])
        last_retrain=i


    equity.append(profit)


    history.append({

        "round":i+1,
        "number":numbers[i],
        "group":g,
        "pred":predicted,
        "hit":hit,
        "window":window,
        "profit":profit

    })


# -------- stats --------

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0


# -------- UI --------

st.title("🚀 V105 HYBRID ENGINE")

c1,c2,c3,c4=st.columns(4)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))
c4.metric("Active Window",window)

st.caption("Train=2000 | Retrain every 200 rounds")


st.subheader("Equity Curve")
st.line_chart(pd.DataFrame({"equity":equity}))


st.subheader("Next Signal")

if pending_signal:
    st.success(f"TRADE NEXT → Group {pending_signal}")
else:
    st.info("WAIT SIGNAL")


st.subheader("History")

hist_df=pd.DataFrame(history)
st.dataframe(hist_df.iloc[::-1],use_container_width=True)
