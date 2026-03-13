import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from math import gcd

st.set_page_config(page_title="V7000 RNG State Analyzer",layout="wide")

DATA_URL="https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv"

# --------------------
# LOAD DATA
# --------------------

@st.cache_data
def load():
    df=pd.read_csv(DATA_URL)
    df.columns=[c.lower().strip() for c in df.columns]
    nums=df["number"].dropna().astype(int)
    return nums

numbers=load().values
n=len(numbers)

st.title("🔬 V7000 RNG State Analyzer")

st.write("Total outputs:",n)

# --------------------
# LCG TEST
# --------------------

st.header("LCG Pattern Test")

if n>5:

    x0,x1,x2 = numbers[0],numbers[1],numbers[2]

    d1 = x1-x0
    d2 = x2-x1

    g = gcd(abs(d1),abs(d2))

    st.write("Difference GCD:",g)

    if g>1:
        st.warning("Possible modulus relation detected")
    else:
        st.success("No obvious LCG pattern")

# --------------------
# SEED PATTERN TEST
# --------------------

st.header("Seed Pattern Test")

diffs=np.diff(numbers)

diff_df=pd.DataFrame({
    
    "diff":diffs
    
})

fig=px.histogram(diff_df,x="diff",nbins=30)

st.plotly_chart(fig,use_container_width=True)

# --------------------
# SPECTRAL TEST
# --------------------

st.header("Spectral Test")

x=numbers[:-1]
y=numbers[1:]

spec_df=pd.DataFrame({
    
    "x":x,
    "y":y
    
})

fig2=px.scatter(spec_df,x="x",y="y")

st.plotly_chart(fig2,use_container_width=True)

# --------------------
# AUTOCORRELATION
# --------------------

st.header("Autocorrelation")

lags=20

corrs=[]

for lag in range(1,lags):

    corr=np.corrcoef(numbers[:-lag],numbers[lag:])[0,1]
    corrs.append(corr)

corr_df=pd.DataFrame({
    
    "lag":range(1,lags),
    "corr":corrs
    
})

fig3=px.line(corr_df,x="lag",y="corr")

st.plotly_chart(fig3,use_container_width=True)

# --------------------
# PREDICTABILITY SCORE
# --------------------

st.header("Predictability Score")

score=100

score-=abs(np.mean(corrs))*500

score=max(score,0)

st.metric("Predictability score",round(score,2))

if score>90:
    
    st.success("RNG appears strong")

elif score>70:
    
    st.warning("Possible weak RNG")

else:
    
    st.error("RNG may be predictable")
