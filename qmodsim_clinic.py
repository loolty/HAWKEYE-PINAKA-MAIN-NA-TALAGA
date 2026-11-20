"""HawkEye Optical Clinic - queue model + Monte Carlo simulation (QMODSIM).

Part 1  Analytic M/M/c (Erlang C) model     -> formulas for the report
Part 2  Discrete-event simulation (Monte Carlo over many clinic days) -> compare with Part 1
Part 3  No-show / overbooking model         -> how many bookings to accept

Run:  python qmodsim_clinic.py        (standard library only; charts if matplotlib is installed)
Replace the INPUTS with numbers from your own appointments data (see the SQL in the notes).
"""
import heapq, math, random, statistics

# ---------------- INPUTS (edit these) ----------------
ARRIVALS_PER_HOUR = 2.0    # average patients arriving per hour
MEAN_SERVICE_MIN = 20.0    # average consultation length (minutes)
OPEN_HOURS = 8             # clinic hours per day
DOCTORS = [1, 2]     # staffing levels to compare
TARGET_WAIT_MIN = 15       # service target: wait under this many minutes
NO_SHOW_RATE = 0.15        # share of booked patients who do not come
BOOKED_PER_DAY = 10        # appointments booked per day (no-show model)
RUNS = 1000                # simulated days per scenario
SEED = 42
# ------------------------------------------------------

LAM = ARRIVALS_PER_HOUR / 60.0          # arrivals per minute
MU = 1.0 / MEAN_SERVICE_MIN             # services per minute, per doctor
OPEN_MIN = OPEN_HOURS * 60


def erlang_c(c):
    """Analytic M/M/c results: utilisation, P(wait), mean wait Wq (min). None if unstable."""
    a = LAM / MU                         # offered load
    rho = a / c
    if rho >= 1:
        return None
    top = a ** c / math.factorial(c) / (1 - rho)
    p_wait = top / (sum(a ** k / math.factorial(k) for k in range(c)) + top)
    wq = p_wait / (c * MU - LAM)
    return rho, p_wait, wq


def simulate_day(c):
    """One clinic day, first-come-first-served, c doctors. Returns (waits, busy_minutes, finish_time)."""
    t, arrivals = 0.0, []
    while True:
        t += random.expovariate(LAM)     # Poisson arrivals
        if t > OPEN_MIN:
            break
        arrivals.append(t)
    free = [0.0] * c                     # time each doctor becomes free
    waits, busy, finish = [], 0.0, 0.0
    for a in arrivals:
        f = heapq.heappop(free)
        start = max(a, f)
        s = random.expovariate(MU)       # exponential consultation time
        waits.append(start - a)
        heapq.heappush(free, start + s)
        busy += s
        finish = max(finish, start + s)
    return waits, busy, finish


def run_scenario(c):
    all_waits, util, overtime = [], [], []
    for _ in range(RUNS):
        w, busy, finish = simulate_day(c)
        all_waits += w
        util.append(busy / (c * OPEN_MIN))
        overtime.append(max(0.0, finish - OPEN_MIN))
    all_waits.sort()
    return {
        "mean": statistics.mean(all_waits),
        "p90": all_waits[int(0.9 * len(all_waits))],
        "over_target": sum(w > TARGET_WAIT_MIN for w in all_waits) / len(all_waits),
        "util": statistics.mean(util),
        "overtime": statistics.mean(overtime),
    }


def overbooking(c):
    """How many bookings can be accepted given no-shows? Compares expected visits to capacity."""
    capacity = int(c * OPEN_MIN / MEAN_SERVICE_MIN)
    rows = []
    for booked in range(capacity, int(capacity * 1.5) + 1, max(1, capacity // 8)):
        visits = [sum(random.random() > NO_SHOW_RATE for _ in range(booked)) for _ in range(RUNS)]
        rows.append((booked, statistics.mean(visits), sum(v > capacity for v in visits) / RUNS))
    return capacity, rows


def main():
    random.seed(SEED)
    print(f"Inputs: {ARRIVALS_PER_HOUR}/h arrivals, {MEAN_SERVICE_MIN} min service, "
          f"{OPEN_HOURS} h day, target wait < {TARGET_WAIT_MIN} min, {RUNS} simulated days\n")
    print("PART 1+2: queue model (analytic) vs simulation")
    print(f"{'Doctors':>7} {'Util%':>6} {'Wq theory':>10} {'Wq sim':>8} {'P90 wait':>9} "
          f"{'>target%':>9} {'Overtime':>9}")
    results = {}
    for c in DOCTORS:
        theory = erlang_c(c)
        if theory is None:
            print(f"{c:>7}  unstable: arrivals exceed capacity (utilisation >= 100%)")
            continue
        r = run_scenario(c)
        results[c] = (theory, r)
        print(f"{c:>7} {theory[0]*100:>6.1f} {theory[2]:>9.1f}m {r['mean']:>7.1f}m "
              f"{r['p90']:>8.1f}m {r['over_target']*100:>8.1f}% {r['overtime']:>7.1f}m")
    ok = [c for c, (_, r) in results.items() if r["over_target"] <= 0.10]
    if ok:
        print(f"\nSmallest team where at most 10% of patients wait over {TARGET_WAIT_MIN} min: {min(ok)} doctor(s)")

    print(f"\nPART 3: no-shows ({NO_SHOW_RATE*100:.0f}% of bookings), per day")
    for c in DOCTORS[:3]:
        cap, rows = overbooking(c)
        print(f"\n{c} doctor(s): capacity {cap} patients/day")
        print(f"{'Booked':>7} {'Avg visits':>11} {'P(over capacity)':>17}")
        for booked, avg, p_over in rows:
            print(f"{booked:>7} {avg:>11.1f} {p_over*100:>16.1f}%")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        cs = list(results)
        plt.figure(figsize=(7, 4))
        plt.plot(cs, [results[c][1]["mean"] for c in cs], "o-", label="Simulated mean wait")
        plt.plot(cs, [results[c][0][2] for c in cs], "s--", label="Erlang C (theory)")
        plt.axhline(TARGET_WAIT_MIN, color="red", ls=":", label="Target")
        plt.xlabel("Number of doctors"); plt.ylabel("Wait (minutes)"); plt.legend()
        plt.title("Patient waiting time vs staffing"); plt.tight_layout()
        plt.savefig("wait_vs_doctors.png", dpi=150)
        print("\nChart saved: wait_vs_doctors.png")
    except ImportError:
        print("\n(Install matplotlib to also get a chart: pip install matplotlib)")


if __name__ == "__main__":
    main()
