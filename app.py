import streamlit as st
import pandas as pd
import numpy as np

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

AUTO_REFRESH = 5

WIN_PROFIT = 3
LOSE_LOSS = 1

PROB_THRESHOLD = 0.27

st.set_page_config(layout="wide")


def get_group(n):
    if 1 <= n <= 3: return 1
    if 4 <= n <= 6: return 2
    if 7 <= n <= 9: return 3
    if 10 <= n <= 12: return 4


@st.cache_data(ttl=AUTO_REFRESH)
def load():
    return pd.read_csv(GOOGLE_SHEET_CSV)


df = load()

numbers = df["number"].dropna().astype(int).tolist()

engine=[]
profit=0

next_group=None

for i,n in enumerate(numbers):

    g=get_group(n)

    predicted=None
    hit=None
    state="SCAN"


    # ===== TRADE =====

    if next_group is not None:

        predicted=next_group

        if g==predicted:

            hit=1
            profit+=WIN_PROFIT

        else:

            hit=0
            profit-=LOSE_LOSS

        state="TRADE"

        next_group=None


    # ===== SIGNAL =====

    if len(engine)>100:

        groups=[x["group"] for x in engine]

        # transition matrix
        trans={1:{},2:{},3:{},4:{}}

        for a,b in zip(groups[:-1],groups[1:]):

            trans[a][b]=trans[a].get(b,0)+1


        current=groups[-1]

        probs={}

        total=sum(trans[current].values())

        if total>0:

            for k,v in trans[current].items():

                probs[k]=v/total


        if probs:

            best=max(probs,key=probs.get)

            p=probs[best]

            # anti streak
            streak=1

            for j in range(len(groups)-2,-1,-1):

                if groups[j]==current:
                    streak+=1
                else:
                    break

            if streak>=2:
                probs[current]=0
                best=max(probs,key=probs.get)
                p=probs[best]


            if p>PROB_THRESHOLD:

                next_group=best
                state="SIGNAL"


    engine.append({
        "round":i+1,
        "number":n,
        "group":g,
        "predicted":predicted,
        "hit":hit,
        "state":state
    })


# ===== DASHBOARD =====

st.title("⚡ MARKOV QUANT ENGINE")

c1,c2,c3=st.columns(3)

c1.metric("Rounds",len(engine))
c2.metric("Profit",profit)

hits=[x["hit"] for x in engine if x["hit"] is not None]

if hits:
    wr=np.mean(hits)
    c3.metric("Winrate",round(wr*100,2))


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

    st.info("Scanning market...")


st.subheader("History")

hist=pd.DataFrame(engine).iloc[::-1]

st.dataframe(hist,use_container_width=True)
