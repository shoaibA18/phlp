# SOL/USDT Spot - 4H Pivot High/Low Notifier
#
# Fetches recent 4H candles from Binance's public REST API (no API key
# needed for market data), finds confirmed swing pivot highs/lows, and
# sends a Telegram message for any pivot not already notified.
#
# State (the timestamp of the last pivot we notified about) is persisted
# to state.json so re-runs don't send duplicate alerts. When run inside
# the GitHub Actions workflow, that file gets committed back to the repo
# after each run.

import json
import os
import time
from pathlib import Path

import requests

# ---- Config -----------------------------------------------------------
SYMBOL = "SOLUSDT"      # spot market
INTERVAL = "4h"

# These mirror the Pine script's inputs exactly, unchanged:
#   lb = input(defval = 10, title="Left Bars")
#   rb = input(defval = 10, title="Right Bars")
LB = 10                 # Left Bars
RB = 10                 # Right Bars
# mb = lb + rb + 1 (from the Pine script) is implicit in the LB/RB window below

FETCH_LIMIT = 100        # how many recent candles to pull each run
STATE_FILE = Path(__file__).parent / "state.json"
# ------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def fetch_klines():
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": FETCH_LIMIT}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def find_pivots(klines):
    """
    Direct port of the Pine script's pivot logic:

        plotshape(iff(not na(high[mb]), iff(highestbars(mb) == -lb, high[lb], na), na), ...)  # pivot high
        plotshape(iff(not na(low[mb]),  iff(lowestbars(mb)  == -lb, low[lb],  na), na), ...)   # pivot low

    A bar `lb` bars back from the evaluation point is a pivot high if its
    high is the max over the mb-bar window (lb bars before it, itself, and
    rb bars after it) — same window, same condition, just expressed as an
    array slice instead of Pine's highestbars()/lowestbars(). Pivot low is
    the exact mirror using lows and min().

    Returns a list of (kind, open_time_ms, price) for confirmed pivots.
    """
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    times = [int(k[0]) for k in klines]

    pivots = []
    n = len(klines)
    for i in range(LB, n - RB):
        window_high = highs[i - LB : i + RB + 1]
        window_low = lows[i - LB : i + RB + 1]
        if highs[i] == max(window_high):
            pivots.append(("HIGH", times[i], highs[i]))
        if lows[i] == min(window_low):
            pivots.append(("LOW", times[i], lows[i]))
    return pivots


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_notified": 0}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set as environment variables"
        )
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15
    )
    resp.raise_for_status()


def main():
    klines = fetch_klines()
    pivots = find_pivots(klines)

    state = load_state()
    last_notified = state.get("last_notified", 0)

    new_pivots = sorted(
        (p for p in pivots if p[1] > last_notified), key=lambda p: p[1]
    )

    for kind, ts, price in new_pivots:
        readable = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts / 1000))
        msg = (
            f"SOL/USDT Spot - 4H Pivot {kind}\n"
            f"Price: {price:.3f}\n"
            f"Candle: {readable}"
        )
        send_telegram(msg)
        last_notified = ts
        print(f"Sent: {msg}")

    if new_pivots:
        state["last_notified"] = last_notified
        save_state(state)
    else:
        print("No new confirmed pivots this run.")


if __name__ == "__main__":
    main()
