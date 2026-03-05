import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 10

WIN_PROFIT = 3
LOSE_LOSS = 1

# lag scan range
LAG_RANGE = range(2,40)

st.set_page_config(layout="wide")

# ================= GROUP ================= #

def get_group(n):

    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4
    return None


# ================= LOAD ================= #

@st.cache_data(ttl=AUTO_REFRESH)
def load():

    try:
        return pd.read_csv(GOOGLE_SHEET_CSV)
    except:
        return pd.DataFrame()

df = load()

if df.empty:
    st.stop()

numbers = df["number"].dropna().astype(int).tolist()


# ================= ENGINE ================= #

engine=[]

total_profit=0

best_lag=None

next_group=None


for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"


    # execute trade

    if next_group is not None:

        predicted=next_group

        if g==predicted:

            hit=1
            total_profit+=WIN_PROFIT

        else:

            hit=0
            total_profit-=LOSE_LOSS

        state="TRADE"

        next_group=None


    # find best lag

    if len(engine)>80:

        best_wr=0

        for lag in LAG_RANGE:

            wins=0
            total=0

            for j in range(lag,len(engine)):

                if engine[j]["group"]==engine[j-lag]["group"]:
                    wins+=1

                total+=1

            if total>30:

                wr=wins/total

                if wr>best_wr:

                    best_wr=wr
                    best_lag=lag


        if best_lag is not None and len(engine)>best_lag:

            next_group=engine[-best_lag]["group"]
            state="SIGNAL"


    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state,
        "lag":best_lag

    })


# ================= DASHBOARD ================= #

st.title("ADAPTIVE LAG ENGINE")

col1,col2,col3=st.columns(3)

col1.metric("Rounds",len(engine))
col2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr=np.mean(hits)

    col3.metric("Winrate",round(wr*100,2))


# ================= NEXT GROUP ================= #

if next_group:

    st.markdown(f"""
    <div style='padding:25px;
                background:#c62828;
                color:white;
                border-radius:12px;
                text-align:center;
                font-size:28px;
                font-weight:bold'>

        NEXT GROUP

        <br><br>{next_group}

    </div>
    """,unsafe_allow_html=True)

else:

    st.info("Scanning...")


# ================= HISTORY ================= #

st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)
