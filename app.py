import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 10

WIN_PROFIT = 3
LOSE_LOSS = 1

LAG_RANGE = range(2,40)

TOP_LAGS = 5

st.set_page_config(layout="wide")


def get_group(n):

    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4


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

engine=[]

total_profit=0

next_group=None

best_lags=[]


for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"


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


    if len(engine)>120:

        lag_scores=[]

        for lag in LAG_RANGE:

            wins=0
            total=0

            for j in range(lag,len(engine)):

                if engine[j]["group"]==engine[j-lag]["group"]:
                    wins+=1

                total+=1

            if total>50:

                wr=wins/total

                lag_scores.append((lag,wr))


        lag_scores.sort(key=lambda x:x[1],reverse=True)

        best_lags=lag_scores[:TOP_LAGS]

        votes={1:0,2:0,3:0,4:0}

        for lag,wr in best_lags:

            grp=engine[-lag]["group"]

            votes[grp]+=wr


        next_group=max(votes,key=votes.get)

        state="SIGNAL"


    engine.append({

        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state,
        "lag":best_lags

    })


st.title("🚀 ADAPTIVE QUANT ENGINE")

col1,col2,col3=st.columns(3)

col1.metric("Rounds",len(engine))
col2.metric("Profit",round(total_profit,2))

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:

    wr=np.mean(hits)

    col3.metric("Winrate",round(wr*100,2))


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


st.subheader("History")

hist_df=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist_df,use_container_width=True)
