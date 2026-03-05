# ================= ENGINE ================= #

engine = []

total_profit = 0
last_trade_round = -999

next_signal = None
next_window = None
next_wr = None
next_ev = None

signal_created_at = None

preview_signal = None
preview_window = None
preview_wr = None
preview_ev = None

prev_best_window = None


for i, n in enumerate(numbers):

    g = get_group(n)

    predicted = None
    hit = None
    state = "SCAN"
    window_used = None
    rolling_wr = None
    ev_value = None
    reason = None


    # ===== EXECUTE TRADE =====

    if next_signal is not None:

        predicted = next_signal
        window_used = next_window
        rolling_wr = next_wr
        ev_value = next_ev

        hit = 1 if predicted == g else 0

        if hit == 1:
            total_profit += WIN_PROFIT
        else:
            total_profit -= LOSE_LOSS

        state = "TRADE"
        reason = f"Executed signal from round {signal_created_at}"

        last_trade_round = i
        next_signal = None


    # ===== SIGNAL SEARCH =====

    if len(engine) >= 50 and i - last_trade_round > 4:

        best_window = None
        best_ev = -999
        best_wr = 0

        for w in WINDOWS:

            recent_hits = []

            for j in range(len(engine)-40, len(engine)):

                if j >= w:

                    recent_hits.append(
                        1 if engine[j]["group"] == engine[j-w]["group"] else 0
                    )

            if len(recent_hits) >= 25:

                wr = np.mean(recent_hits)

                ev = wr * WIN_PROFIT - (1-wr)*LOSE_LOSS

                if ev > best_ev:

                    best_ev = ev
                    best_window = w
                    best_wr = wr


        # ===== PREVIEW =====

        if best_window is not None and best_wr > 0.28:

            preview_signal = engine[-best_window]["group"]
            preview_window = best_window
            preview_wr = round(best_wr*100,2)
            preview_ev = round(best_ev,3)


        # ===== CONFIRM TRADE =====

        if best_window is not None:

            if best_wr > 0.30 and best_ev > 0.03:

                # stability check
                if prev_best_window == best_window:

                    g1 = engine[-best_window]["group"]
                    g2 = engine[-2*best_window]["group"] if len(engine) >= 2*best_window else g1

                    # double confirm
                    if g1 == g2:

                        next_signal = g1
                        next_window = best_window
                        next_wr = round(best_wr*100,2)
                        next_ev = round(best_ev,3)

                        signal_created_at = i + 1

                        state = "SIGNAL"
                        reason = f"Stable window {best_window}"

                prev_best_window = best_window


    engine.append({

        "round": i+1,
        "number": n,
        "group": g,
        "predicted": predicted,
        "hit": hit,
        "window": window_used,
        "rolling_wr_%": rolling_wr,
        "ev": ev_value,
        "state": state,
        "reason": reason

    })
