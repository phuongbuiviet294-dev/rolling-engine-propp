
import streamlit as st

# ================= ENGINE CORE =================

class RollingEngine:
    def __init__(self):
        self.numbers = []
        self.groups = []
        self.lock_window = None
        self.lock_remaining = 0
        self.lookback = 26
        self.min_streak = 3
        self.min_hits = 6

    def get_group(self, n):
        return (n - 1) // 3 + 1

    def predicted(self, i, w):
        if i - w < 0:
            return None
        return self.groups[i - w]

    def compute_hits(self, w):
        hits = []
        for i in range(1, len(self.groups)):
            p = self.predicted(i - 1, w)
            hits.append(1 if p == self.groups[i] else 0 if p else 0)
        return hits

    def compute_stats(self, w):
        hits = self.compute_hits(w)

        streak = 0
        for h in reversed(hits):
            if h == 1:
                streak += 1
            else:
                break

        hits26 = sum(hits[-26:]) if len(hits) >= 26 else 0
        return streak, hits26

    def scan(self):
        best = None
        best_tuple = None

        for w in range(6, 20):
            streak, hits = self.compute_stats(w)
            if streak >= self.min_streak and hits >= self.min_hits:
                tup = (-streak, -hits, w)
                if best_tuple is None or tup < best_tuple:
                    best_tuple = tup
                    best = w
        return best

    def add(self, n):
        self.numbers.append(n)
        self.groups.append(self.get_group(n))

        if self.lock_remaining > 0:
            self.lock_remaining -= 1
            return "LOCKED", self.lock_window, self.lock_remaining

        if self.lock_remaining == 0 and self.lock_window is not None:
            self.lock_window = None

        if len(self.groups) < self.lookback:
            return "WAIT_26", None, 0

        best = self.scan()
        if best is not None:
            self.lock_window = best
            self.lock_remaining = 20
            return "NEW_LOCK", best, self.lock_remaining

        return "SCANNING", None, 0


# ================= STREAMLIT UI =================

st.set_page_config(page_title="Rolling Engine PRO++", layout="wide")

st.title("🚀 Rolling Engine PRO++")
st.caption("Window Lock Strategy – 20 Rounds Fixed")

if "engine" not in st.session_state:
    st.session_state.engine = RollingEngine()

engine = st.session_state.engine

col1, col2 = st.columns([1, 2])

with col1:
    number = st.number_input("Nhập số (1–12)", min_value=1, max_value=12, step=1)

    if st.button("ADD"):
        state, window, remaining = engine.add(number)
        st.session_state.last_state = state
        st.session_state.last_window = window
        st.session_state.last_remaining = remaining

    if st.button("RESET"):
        st.session_state.engine = RollingEngine()
        st.rerun()

with col2:
    st.subheader("📊 Engine Status")

    if "last_state" in st.session_state:
        st.write("State:", st.session_state.last_state)
        st.write("Active Window:", st.session_state.last_window)
        st.write("Lock Remaining:", st.session_state.last_remaining)

    st.write("Total Rounds:", len(engine.groups))

    if engine.lock_window:
        streak, hits26 = engine.compute_stats(engine.lock_window)
        st.write("Current Streak:", streak)
        st.write("Hits_26:", hits26)

st.divider()

st.subheader("📜 History")

if engine.groups:
    data = []
    for i in range(len(engine.groups)):
        data.append({
            "Round": i + 1,
            "Number": engine.numbers[i],
            "Group": engine.groups[i],
        })

    st.dataframe(data, use_container_width=True)
