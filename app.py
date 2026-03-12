import streamlit as st
import pandas as pd
import numpy as np
import pickle

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOWS=range(8,13)
LOOKBACKS=range(18,29)
GAPS=[3,4]

TRAIN_SIZE=600

WIN=2.5
LOSS=1

TARGET_PROFIT=25
MAX_DRAWDOWN=12
LOSS_STREAK_LIMIT=4

STATE_FILE="engine_state.pkl"

st.set_page_config(layout="wide")

# ---------- GROUP ----------

def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- LOAD DATA ----------

@st.cache_data(ttl=5)
def load():

    df=pd.read_csv(DATA_URL)

    df.columns=[c.strip().lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()


# ---------- LOAD STATE ----------

def load_state():

    try:

        with open(STATE_FILE,"rb") as f:

            return pickle.load(f)

    except:

        return {

            "config":None,
            "profit":0,
            "cycle_profit":0,
            "peak":0,
            "loss_streak":0,
            "last_index":0,
            "history":[],
            "equity":[]
        }


def save_state(state):

    with open(STATE_FILE,"wb") as f:

        pickle.dump(state,f)


state=load_state()


# ---------- EDGE ----------

def calc_wr(nums,i,W,LB):

    rec=[]

    for j in range(max(W,i-LB),i):

        if j>=W:

            rec.append(
                1 if group(nums[j])==group(nums[j-W]) else 0
            )

    if len(rec)<10:

        return 0

    return np.mean(rec)


# ---------- SIM ----------

def simulate(nums,W,LB,G):

    profit=0
    next_signal=None
    last_trade=-999

    for i,n in enumerate(nums):

        g=group(n)

        if next_signal is not None:

            hit=1 if g==next_signal else 0

            profit+=WIN if hit else -LOSS

            next_signal=None
            last_trade=i

        if i-last_trade>=G and i>LB:

            wr=calc_wr(nums,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(nums[i-W])

                if group(nums[i-1])!=g1:

                    next_signal=g1

    return profit


# ---------- FIND CONFIG ----------

def find_config(train):

    best=None
    best_profit=-999

    for W in WINDOWS:
        for LB in LOOKBACKS:
            for G in GAPS:

                p=simulate(train,W,LB,G)

                if p>best_profit:

                    best_profit=p
                    best=(W,LB,G)

    return best


# ---------- TRAIN ----------

if state["config"] is None and len(numbers)>=TRAIN_SIZE:

    train=numbers[-TRAIN_SIZE:]

    state["config"]=find_config(train)

    st.success(f"CONFIG LOCKED {state['config']}")


config=state["config"]

profit=state["profit"]
cycle_profit=state["cycle_profit"]
peak=state["peak"]
loss_streak=state["loss_streak"]

history=state["history"]
equity=state["equity"]

last_index=state["last_index"]


next_signal=None
last_trade=-999

# ---------- PROCESS NEW DATA ----------

for i in range(last_index,len(numbers)):

    n=numbers[i]
    g=group(n)

    predicted=None
    hit=None

    if next_signal is not None:

        predicted=next_signal

        hit=1 if g==predicted else 0

        p=WIN if hit else -LOSS

        profit+=p
        cycle_profit+=p

        peak=max(peak,cycle_profit)

        if hit==0:
            loss_streak+=1
        else:
            loss_streak=0

        next_signal=None
        last_trade=i


    if config:

        W,LB,G=config

        if i-last_trade>=G and i>LB:

            wr=calc_wr(numbers,i,W,LB)

            ev=wr*WIN-(1-wr)*LOSS

            if ev>0:

                g1=group(numbers[i-W])

                if group(numbers[i-1])!=g1:

                    next_signal=g1


    # RESET

    if cycle_profit>=TARGET_PROFIT or peak-cycle_profit>=MAX_DRAWDOWN or loss_streak>=LOSS_STREAK_LIMIT:

        config=None
        cycle_profit=0
        peak=0
        loss_streak=0


    equity.append(profit)

    history.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "profit":profit

    })


state.update({

    "config":config,
    "profit":profit,
    "cycle_profit":cycle_profit,
    "peak":peak,
    "loss_streak":loss_streak,
    "last_index":len(numbers),
    "history":history[-200:],
    "equity":equity

})

save_state(state)


# ---------- UI ----------

st.title("🚀 QUANT PRO ENGINE")

st.metric("Total Profit",round(profit,2))

st.write("CONFIG",config)


st.subheader("Equity Curve")

st.line_chart(pd.DataFrame({"equity":equity}))


st.subheader("Next Group")

if next_signal:

    st.markdown(

        f"<h1 style='color:red;text-align:center'>NEXT GROUP → {next_signal}</h1>",

        unsafe_allow_html=True

    )

else:

    st.info("Scanning...")


st.subheader("History")

st.dataframe(pd.DataFrame(history[::-1]),use_container_width=True)
