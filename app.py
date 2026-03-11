# ======================================
# STICKY WINDOW PRO — SAFE MODE
# Google Sheet Live Data Version
# ======================================

import pandas as pd
import numpy as np

# ===== DATA CONFIG =====
DATA_SOURCE = "google_sheet"

GOOGLE_SHEET_CSV = "https://docs.google.com/spreadsheets/d/18gQsFPYPHB2EtkY_GLllBYKWcFPi_VP1vtGatflAuuY/export?format=csv
LOCAL_FILE = "data.csv"

# ===== SAFE CONFIG =====
WINDOW_RANGE = range(8, 19)
LOOKBACK = 26

MIN_REGIME_WR = 0.35
MIN_TREND_WR = 0.50
MIN_SHORT_PROFIT = 0

DEAD_WINDOW_LOOKBACK = 5
DEAD_WINDOW_MIN_HIT = 2

SCAN_FORCE_LIMIT = 20


# ===== LOAD DATA =====
def load_data():
    if DATA_SOURCE == "google_sheet":
        df = pd.read_csv(GOOGLE_SHEET_CSV)
    else:
        df = pd.read_csv(LOCAL_FILE)
    
    df = df.dropna()
    return df


# ===== METRICS =====
def winrate(series):
    if len(series) == 0:
        return 0
    return np.mean(series)


def calc_profit(hits, win=2.5, lose=-1):
    return sum([win if h==1 else lose for h in hits])


# ===== CHECKS =====
def market_ok(data):
    recent = data['hit'].tail(10)
    return winrate(recent) >= MIN_REGIME_WR


def trend_ok(data):
    recent = data['hit'].tail(5)
    return winrate(recent) >= MIN_TREND_WR


def short_profit_ok(data):
    recent = data['hit'].tail(10)
    return calc_profit(recent) >= MIN_SHORT_PROFIT


def window_alive(data):
    recent = data['hit'].tail(DEAD_WINDOW_LOOKBACK)
    return sum(recent) >= DEAD_WINDOW_MIN_HIT


# ===== WINDOW PICK =====
def evaluate_window(data, w):
    hits = data['hit'].tail(w)
    wr = winrate(hits)
    profit = calc_profit(hits)
    return {'window': w, 'wr': wr, 'profit': profit}


def pick_best_window(data):
    results = []
    for w in WINDOW_RANGE:
        if len(data) >= w:
            results.append(evaluate_window(data, w))
    if not results:
        return None
    return max(results, key=lambda x: x['profit'])


# ===== ENGINE =====
class SafeEngine:
    def __init__(self):
        self.current_window = None
        self.scan_count = 0
    
    def decide(self, data):
        if len(data) < LOOKBACK:
            return "SCAN", None
        
        if not market_ok(data):
            return "PAUSE_MARKET", None
        
        if not trend_ok(data):
            self.scan_count += 1
            if self.scan_count >= SCAN_FORCE_LIMIT:
                best = pick_best_window(data)
                self.scan_count = 0
                if best:
                    return "FORCE_TRADE", best['window']
            return "SCAN", None
        
        if not short_profit_ok(data):
            return "WAIT_PROFIT", None
        
        if not self.current_window or not window_alive(data):
            best = pick_best_window(data)
            if not best:
                return "SCAN", None
            self.current_window = best['window']
        
        self.scan_count = 0
        return "TRADE", self.current_window


# ===== RUN =====
if __name__ == "__main__":
    df = load_data()
    
    engine = SafeEngine()
    state, window = engine.decide(df)
    
    print("STATE:", state)
    print("WINDOW:", window)
