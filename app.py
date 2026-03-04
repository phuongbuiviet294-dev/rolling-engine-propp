WINDOWS = [7,9,11,14]
LOOKBACK = 80

WR_THRESHOLD = 0.31
EV_THRESHOLD = 0.06
HIT_THRESHOLD = 12

if len(engine) >= LOOKBACK and i - last_trade_round > 4:

    best_window = None
    best_ev = -999
    best_wr = 0
    best_hits = 0

    for w in WINDOWS:

        recent_hits = []

        start = max(w, len(engine)-LOOKBACK)

        for j in range(start, len(engine)):

            if j >= w:

                hit_val = 1 if engine[j]["group"] == engine[j-w]["group"] else 0
                recent_hits.append(hit_val)

        if len(recent_hits) < 30:
            continue

        wr = np.mean(recent_hits)
        hits = sum(recent_hits)

        ev = wr * WIN_PROFIT - (1-wr)*LOSE_LOSS

        if wr > WR_THRESHOLD and hits >= HIT_THRESHOLD and ev > best_ev:

            best_ev = ev
            best_window = w
            best_wr = wr
            best_hits = hits


    # preview
    if best_window is not None:

        preview_signal = engine[-best_window]["group"]
        preview_window = best_window
        preview_wr = round(best_wr * 100,2)
        preview_ev = round(best_ev,3)


    # confirm entry with timing filter
    if best_window is not None and best_ev > EV_THRESHOLD:

        if engine[-1]["group"] != engine[-best_window]["group"]:

            next_signal = engine[-best_window]["group"]
            next_window = best_window
            next_wr = round(best_wr * 100,2)
            next_ev = round(best_ev,3)

            signal_created_at = i + 1

            state = "SIGNAL"
            reason = f"Adaptive window {best_window}"
