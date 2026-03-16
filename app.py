import streamlit as st
from collections import Counter
import pandas as pd

st.title("🎯 NEXT BET")

# group mapping
def get_group(n):
    if n in [1,2,3]:
        return 1
    elif n in [4,5,6]:
        return 2
    elif n in [7,8]:
        return 3
    else:
        return 4

# session state
if "numbers" not in st.session_state:
    st.session_state.numbers=[]

if "profit" not in st.session_state:
    st.session_state.profit=0

# input number
n=st.number_input("Input Number (1-10)",1,10,step=1)

if st.button("ADD"):
    st.session_state.numbers.append(n)

numbers=st.session_state.numbers
groups=[get_group(x) for x in numbers]

# vote engine
def predict_next(groups):

    windows=[3,5,8,12,20]

    preds=[]

    for w in windows:
        if len(groups)>=w:
            last=groups[-w:]
            c=Counter(last)

            pred=min(c,key=c.get)
            preds.append(pred)

    if len(preds)==0:
        return None,0

    c=Counter(preds)
    vote,confidence=c.most_common(1)[0]

    return vote,confidence


# history table
rows=[]

profit=0

for i in range(len(numbers)):

    sub_groups=groups[:i+1]

    vote,conf=predict_next(sub_groups[:-1])

    state="WAIT"
    signal=False
    trade=False

    if vote!=None:

        if conf>=2 and sub_groups[-1]!=vote:
            state="TRADE"
            signal=True
            trade=True

            if sub_groups[-1]==vote:
                profit+=1
            else:
                profit-=1

    rows.append({
        "number":numbers[i],
        "group":groups[i],
        "vote":vote,
        "confidence":conf,
        "state":state,
        "signal":signal,
        "trade":trade
    })


df=pd.DataFrame(rows)

st.subheader("History")
st.dataframe(df)

# next prediction
vote,conf=predict_next(groups)

st.divider()

if len(numbers)>0:

    current_number=numbers[-1]
    current_group=groups[-1]

    st.write("Current Number:",current_number)
    st.write("Current Group:",current_group)

    if vote!=None and conf>=2 and current_group!=vote:

        st.markdown(
        f"""
        <div style="background:#ff4b4b;padding:20px;border-radius:10px;text-align:center;font-size:28px;color:white">
        BET GROUP → {vote}
        </div>
        """,unsafe_allow_html=True)

    else:

        st.markdown(
        """
        <div style="background:#999;padding:20px;border-radius:10px;text-align:center;font-size:28px;color:white">
        WAIT
        </div>
        """,unsafe_allow_html=True)

st.subheader("Session Statistics")

st.write("Profit:",profit)
st.write("Trades:",len(df[df.trade==True]))
