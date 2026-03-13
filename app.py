import streamlit as st
import pandas as pd

DATA_URL = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

WINDOW_RANGE = range(6,20)

WIN = 2.5
LOSS = 1


def get_group(n):
    if n<=3: return 1
    if n<=6: return 2
    if n<=9: return 3
    return 4


df = pd.read_csv(DATA_URL)

numbers = df["number"].dropna().astype(int).tolist()

groups = [get_group(n) for n in numbers]


patterns = {
"1-1":[1,1],
"1-1-1":[1,1,1],
"0-0":[0,0],
"0-0-0":[0,0,0],
"0-1-0":[0,1,0],
"1-0-1":[1,0,1]
}


rows = []

for window in WINDOW_RANGE:

    hits = []

    for i in range(window,len(groups)):
        hits.append(1 if groups[i]==groups[i-window] else 0)

    for name,p in patterns.items():

        L = len(p)

        trades = 0
        win_hit = 0
        win_miss = 0

        for i in range(len(hits)-L):

            if hits[i:i+L]==p:

                trades += 1

                if hits[i+L]==1:
                    win_hit += 1
                else:
                    win_miss += 1


        if trades>0:

            wr_hit = win_hit/trades
            wr_miss = win_miss/trades

            ev_hit = wr_hit*WIN - (1-wr_hit)*LOSS
            ev_miss = wr_miss*WIN - (1-wr_miss)*LOSS

            rows.append({
                "window":window,
                "pattern":name,
                "direction":"HIT",
                "trades":trades,
                "wins":win_hit,
                "winrate":round(wr_hit*100,2),
                "EV":round(ev_hit,3)
            })

            rows.append({
                "window":window,
                "pattern":name,
                "direction":"MISS",
                "trades":trades,
                "wins":win_miss,
                "winrate":round(wr_miss*100,2),
                "EV":round(ev_miss,3)
            })


result = pd.DataFrame(rows)

result = result.sort_values("EV",ascending=False)

st.title("V440 Dual Edge Engine")

st.dataframe(result,use_container_width=True)
