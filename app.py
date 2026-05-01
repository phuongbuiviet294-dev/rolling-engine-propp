# A,A,B,A -> A
if n >= 4:
    a, b, c, d = t4
    if a == b and a == d and c != a:
        return a, "AABA_TO_A"

# A,B,A,A -> A
if n >= 4:
    a, b, c, d = t4
    if a == c == d and b != a:
        return a, "ABAA_TO_A"

# A,B,B,A -> A
if n >= 4:
    a, b, c, d = t4
    if a == d and b == c and a != b:
        return a, "ABBA_TO_A"

# A,B,A,C -> A
if n >= 4:
    a, b, c, d = t4
    if a == c and a != b and d != a:
        return a, "ABAC_TO_A"

# A,B,C,A -> A
if n >= 4:
    a, b, c, d = t4
    if a == d and len({a, b, c}) >= 3:
        return a, "ABCA_TO_A"

# A,A,B,C -> A
if n >= 4:
    a, b, c, d = t4
    if a == b and c != a and d != a:
        return a, "AABC_TO_A"

# A,B,B,C -> B
if n >= 4:
    a, b, c, d = t4
    if b == c and a != b and d != b:
        return b, "ABBC_TO_B"

# A,B,C,B -> B
if n >= 4:
    a, b, c, d = t4
    if b == d and a != b and c != b:
        return b, "ABCB_TO_B"

# A,B,C,D -> A nếu đủ 4 group khác nhau
if n >= 4:
    a, b, c, d = t4
    if len({a, b, c, d}) == 4:
        return a, "ABCD_TO_A"
