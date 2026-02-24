import streamlit as st
import requests
import json
from datetime import datetime

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxjblHz-kQ_4Bzb-VtO-Ux7_siTTA2-cQ-DGK8apuSxHz3_mDskP0OReynSunKJOmKL/exec"

WINDOW = 26

st.set_page_config(page_title="Rolling Engine PRO++", layout="wide")

st.title("🚀 Rolling Engine PRO++")
st.write("Window Lock Strategy – 20 Rounds Fixed")

# --- Input chuỗi ---
input_str = st.text_input("Nhập chuỗi số (vd: 1,4,8,7,2):")

if st.button("RUN") and input_str:

    numbers = [int(x.strip()) for x in input_str.split(",") if x.strip().isdigit()]

    results = []
    groups = []

    def get_group(n):
        if 1 <= n <= 3:
            return 1
        elif 4 <= n <= 6:
            return 2
        elif 7 <= n <= 9:
            return 3
        elif 10 <= n <= 12:
            return 4
        return None

    for i, n in enumerate(numbers):
        group = get_group(n)
        groups.append(group)

        predicted = None
        hit = None

        if i >= WINDOW:
            predicted = groups[i - WINDOW]
            hit = 1 if predicted == group else 0

        results.append({
            "round": i + 1,
            "number": n,
            "group": group,
            "predicted": predicted,
            "hit": hit
        })

        # Gửi sang Google Sheet
        payload = {
            "round": i + 1,
            "number": n,
            "group": group,
            "predicted": predicted,
            "hit": hit,
            "window": WINDOW,
            "state": "RUN"
        }

        requests.post(WEBHOOK_URL, data=json.dumps(payload))

    st.success("Đã lưu dữ liệu vào Google Sheet")

    st.dataframe(results)
