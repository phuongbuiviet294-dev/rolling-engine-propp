import streamlit as st
import pandas as pd

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WIN=2.5
LOSS=1

BACKTEST_SPLIT=2000


# ---------- GROUP ----------
def group(n):

    if n<=3:return 1
    if n<=6:return 2
    if n<=9:return 3
    return 4


# ---------- LOAD ----------
@st.cache_data(ttl=10)
def load():

    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower() for c in df.columns]

    return df["number"].dropna().astype(int).tolist()


numbers=load()
groups=[group(n) for n in numbers]


# ---------- ENGINE ----------

hits=[]
profit=0
equity=[]
history=[]
trades=0
wins=0

for i in range(9,len(groups)):

    # 1 detect signal from past hits
    signal=False

    if len(hits)>=2 and hits[-2:]==[1,1]:
        signal=True

    if len(hits)>=3 and hits[-3:]==[0,1,1]:
        signal=True


    # 2 prediction
    pred=groups[i-9]

    # 3 actual result
    actual=groups[i]

    hit=1 if pred==actual else 0


    # 4 trade only if signal
    if signal:

        trades+=1

        if hit:
            profit+=WIN
            wins+=1
        else:
            profit-=LOSS


    hits.append(hit)

    equity.append(profit)

    history.append({
        "round":i,
        "number":numbers[i],
        "predicted":pred,
        "actual":actual,
        "hit":hit,
        "trade":signal,
        "profit":profit
    })


df_hist=pd.DataFrame(history)


# ---------- METRICS ----------

winrate=(wins/trades*100) if trades>0 else 0

backtest=df_hist[df_hist["round"]<=BACKTEST_SPLIT]
live=df_hist[df_hist["round"]>BACKTEST_SPLIT]

profit_backtest=backtest["profit"].iloc[-1] if len(backtest)>0 else 0
profit_live=live["profit"].iloc[-1]-profit_backtest if len(live)>0 else 0


# ---------- NEXT SIGNAL ----------

next_signal=False

if len(hits)>=2 and hits[-2:]==[1,1]:
    next_signal=True

if len(hits)>=3 and hits[-3:]==[0,1,1]:
    next_signal=True

next_group=groups[-9]


# ---------- UI ----------

st.title("Pattern Engine Walk-Forward")

c1,c2,c3,c4=st.columns(4)

c1.metric("Backtest Profit",round(profit_backtest,2))
c2.metric("Live Profit",round(profit_live,2))
c3.metric("Total Profit",round(profit,2))
c4.metric("Winrate %",round(winrate,2))


st.subheader("Next Signal")

if next_signal:
    st.success(f"BET GROUP {next_group}")
else:
    st.info("WAIT")


st.subheader("Equity Curve")

st.line_chart(equity)


st.subheader("Trade Stats")

st.write("Trades:",trades)
st.write("Wins:",wins)


st.subheader("History")

st.dataframe(df_hist.iloc[::-1],use_container_width=True)
