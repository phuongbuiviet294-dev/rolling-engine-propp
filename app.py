# ================= PATTERN GROUP ONLY - FULL =================
def detect_pattern_next_group(seq_groups):
    n = len(seq_groups)
    if n < 2:
        return None, "NO_PATTERN"

    def tail(k):
        return seq_groups[-k:] if n >= k else []

    t2 = tail(2)
    t3 = tail(3)
    t4 = tail(4)
    t5 = tail(5)
    t6 = tail(6)
    t7 = tail(7)
    t8 = tail(8)

    if n >= 5 and len(set(t5)) == 1:
        return t5[-1], "REPEAT_5"

    if n >= 4 and len(set(t4)) == 1:
        return t4[-1], "REPEAT_4"

    if n >= 3 and len(set(t3)) == 1:
        return t3[-1], "REPEAT_3"

    if n >= 2 and t2[0] == t2[1]:
        return t2[-1], "REPEAT_2"

    if n >= 5:
        a, b, c, d, e = t5
        if a == b == c == d and e != a:
            return a, "AAAAB_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == b == c and d != a:
            return a, "AAAB_TO_A"

    if n >= 3:
        a, b, c = t3
        if a == b and c != a:
            return a, "AAB_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == b and a == d and c == e and a != c:
            return a, "AABAB_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == b and a == d and c != a:
            return a, "AABA_TO_A"

    if n >= 6:
        a, b, c, d, e, f = t6
        if a == c == e and b == d == f and a != b:
            return a, "ABABAB_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == c == e and b == d and a != b:
            return a, "ABABA_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == c and b == d and a != b:
            return a, "ABAB_TO_A"

    if n >= 3:
        a, b, c = t3
        if a == c and a != b:
            return a, "ABA_TO_A"

    if n >= 8:
        a, b, c, d, e, f, g, h = t8
        if a == b == c == d and e == f == g == h and a != e:
            return a, "AAAABBBB_TO_A"

    if n >= 6:
        a, b, c, d, e, f = t6
        if a == b == c and d == e == f and a != d:
            return a, "AAABBB_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == b == c and d == e and a != d:
            return a, "AAABB_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == b and c == d == e and a != c:
            return a, "AABBB_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == b and c == d and a != c:
            return a, "AABB_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == b and c == d and e == a and a != c:
            return a, "AABBA_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == e and b == d and a != b:
            return a, "ABCBA_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == e and b == c == d and a != b:
            return a, "ABBBA_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == d and b == c and a != b:
            return a, "ABBA_TO_A"

    if n >= 4:
        a, b, c, d = t4
        if a == d and len({a, b, c}) >= 3:
            return a, "ABCA_TO_A"

    if n >= 8:
        a, b, c, d, e, f, g, h = t8
        if a == e and b == f and c == g and d == h and len({a, b, c, d}) >= 4:
            return a, "ABCDABCD_TO_A"

    if n >= 6:
        a, b, c, d, e, f = t6
        if a == d and b == e and c == f and len({a, b, c}) >= 3:
            return a, "ABCABC_TO_A"

    if n >= 5:
        a, b, c, d, e = t5
        if a == e and len({a, b, c, d}) >= 4:
            return a, "ABCDA_TO_A"

    if n >= 4 and t4 == [1, 2, 3, 4]:
        return 1, "SEQ_1234_TO_1"

    if n >= 4 and t4 == [4, 3, 2, 1]:
        return 4, "SEQ_4321_TO_4"

    if n >= 4 and t4 == [1, 3, 2, 4]:
        return 1, "SEQ_1324_TO_1"

    if n >= 4 and t4 == [4, 2, 3, 1]:
        return 4, "SEQ_4231_TO_4"

    if n >= 7:
        a, b, c, d, e, f, g = t7
        if a == b == c and e == f and d == g and a == e and a != d:
            return a, "BBBABBA_TO_B"

    if n >= 6:
        a, b, c, d, e, f = t6
        if a == b == d == e and c == f and a != c:
            return a, "AABAAB_TO_A"

    if n >= 6:
        a, b, c, d, e, f = t6
        if a == d and b == c == e == f and a != b:
            return a, "ABBABB_TO_A"
			
			
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

    return None, "NO_PATTERN"


numbers = load_numbers()
groups = [group_of(n) for n in numbers]
colors = [color_of_number(n) for n in numbers]

if len(groups) < LOCK_ROUND_START:
    st.error(f"Chưa đủ dữ liệu. Hiện có {len(groups)} rounds, cần ít nhất {LOCK_ROUND_START}.")
    st.stop()

