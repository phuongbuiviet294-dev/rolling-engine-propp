from collections import Counter, deque

WINDOWS = range(6, 23)
WIN_GROUP = 2.5
LOSS_GROUP = -1.0


def predict_next_group(groups, idx, w):
    if idx - w < 0:
        return None

    pred = groups[idx - w]

    if groups[idx - 1] == pred:
        return None

    return pred


window_state = {
    w: {
        "results": [],
        "profit20": 0.0,
        "profit50": 0.0,
        "loss_streak": 0,
        "score": 0.0,
        "next_group": None,
    }
    for w in WINDOWS
}

leader_history = deque(maxlen=20)


def update_window_state(groups, idx):

    for w in WINDOWS:

        pred = predict_next_group(groups, idx, w)

        if pred is None:
            continue

        hit = 1 if groups[idx] == pred else 0

        st = window_state[w]

        st["results"].append(hit)

        last20 = st["results"][-20:]
        last50 = st["results"][-50:]

        st["profit20"] = sum(WIN_GROUP if x else LOSS_GROUP for x in last20)
        st["profit50"] = sum(WIN_GROUP if x else LOSS_GROUP for x in last50)

        loss_streak = 0

        for x in reversed(st["results"]):
            if x == 0:
                loss_streak += 1
            else:
                break

        st["loss_streak"] = loss_streak

        st["score"] = (
            st["profit20"]
            + 0.3 * st["profit50"]
            - st["loss_streak"]
        )

        st["next_group"] = predict_next_group(groups, len(groups), w)


def get_top5():

    arr = sorted(
        window_state.items(),
        key=lambda x: x[1]["score"],
        reverse=True
    )

    return arr[:5]


def get_health():

    pos20 = 0
    pos50 = 0

    for w in WINDOWS:

        st = window_state[w]

        if st["profit20"] > 0:
            pos20 += 1

        if st["profit50"] > 0:
            pos50 += 1

    return pos20 / 17, pos50 / 17


def get_consensus():

    top5 = get_top5()

    preds = []

    for w, st in top5:
        if st["next_group"] is not None:
            preds.append(st["next_group"])

    if len(preds) == 0:
        return None, 0

    g, c = Counter(preds).most_common(1)[0]

    return g, c / len(preds)


def get_stability():

    if len(leader_history) == 0:
        return 0

    x, cnt = Counter(leader_history).most_common(1)[0]

    return cnt / len(leader_history)


def get_next_group_signal():

    top5 = get_top5()

    leader = top5[0][0]

    leader_history.append(leader)

    next_group, consensus = get_consensus()

    health20, health50 = get_health()

    stability = get_stability()

    ready = (
        health20 >= 0.7
        and health50 >= 0.6
        and consensus >= 0.8
        and stability >= 0.5
        and top5[0][1]["score"] > 0
    )

    state = "READY" if ready else "WAIT"

    return {
        "state": state,
        "next_group": next_group,
        "health20": round(health20, 3),
        "health50": round(health50, 3),
        "consensus": round(consensus, 3),
        "stability": round(stability, 3),
        "leader": leader
    }
