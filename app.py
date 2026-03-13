import streamlit as st
import pandas as pd
import numpy as np

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

TRAIN_SIZE=2000
RETRAIN_OPTIONS=[50,100,150,200]

WINDOW_RANGE=range(6,19)

WIN=2.5
LOSS=1


# ---------------- group ----------------

def get_group(n):

    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


# ---------------- load ----------------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[get_group(n) for n in numbers]


# ---------------- window profit ----------------

def window_profit(data,window):

    p=0

    for i in range(window,len(data)):

        pred=data[i-window]
        actual=data[i]

        p += WIN if pred==actual else -LOSS

    return p


# ---------------- optimize retrain ----------------

def optimize_strategy(train_groups):

    best_profit=-999
    best_retrain=RETRAIN_OPTIONS[0]

    for retrain in RETRAIN_OPTIONS:

        profit=0
        window=max(WINDOW_RANGE)

        for i in range(len(train_groups)):

            if i < max(WINDOW_RANGE):
                continue

            # retrain window
            if i % retrain == 0:

                best_w=None
                best_p=-999

                for w in WINDOW_RANGE:

                    if i < w:
                        continue

                    p=window_profit(train_groups[:i],w)

                    if p>best_p:
                        best_p=p
                        best_w=w

                if best_w is not None:
                    window=best_w

            if i < window:
                continue

            pred=train_groups[i-window]
            actual=train_groups[i]

            profit += WIN if pred==actual else -LOSS


        if profit>best_profit:

            best_profit=profit
            best_retrain=retrain


    return best_retrain


# ---------------- TRAIN ----------------

train_groups=groups[:TRAIN_SIZE]

best_retrain=optimize_strategy(train_groups)

window=max(WINDOW_RANGE)

profit=0
hits=[]
equity=[]
history=[]

pending_signal=None

last_retrain=TRAIN_SIZE


# ---------------- FORWARD ENGINE ----------------

for i in range(TRAIN_SIZE,len(groups)):

    g=groups[i]

    predicted=None
    hit=None


    # execute trade
    if pending_signal is not None:

        predicted=pending_signal
        hit = 1 if predicted==g else 0

        profit += WIN if hit else -LOSS

        hits.append(hit)

        pending_signal=None


    # retrain window
    if i-last_retrain>=best_retrain:

        best_p=-999
        best_w=window

        for w in WINDOW_RANGE:

            if i < w:
                continue

            p=window_profit(groups[i-TRAIN_SIZE:i],w)

            if p>best_p:
                best_p=p
                best_w=w

        window=best_w
        last_retrain=i


    # signal detection
    if i>=window+2:

        h1 = 1 if groups[i-1]==groups[i-1-window] else 0
        h2 = 1 if groups[i-2]==groups[i-2-window] else 0

        if h1==1 and h2==1:

            pending_signal=groups[i-window]


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


# ---------------- stats ----------------

wr=np.mean(hits) if hits else 0

wins=hits.count(1)*WIN
loss=hits.count(0)*LOSS

pf=wins/loss if loss else 0


# ---------------- UI ----------------

st.title("🚀 V300 Walk-Forward Engine")

c1,c2,c3,c4=st.columns(4)

c1.metric("Profit",round(profit,2))
c2.metric("Winrate %",round(wr*100,2))
c3.metric("Profit Factor",round(pf,2))
c4.metric("Retrain Interval",best_retrain)

st.caption("Train 2000 → Optimize Retrain → Forward Test")


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
