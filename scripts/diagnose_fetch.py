#!/usr/bin/env python3
"""Throwaway probe: which Yahoo access path actually returns the newest bar?

The morning runs kept reporting the session before last while Yahoo's own
site already showed it, so this compares the ways of asking for the same
daily bars side by side.
"""

from __future__ import annotations

import datetime as dt
import json
import traceback

import pandas as pd
import requests
import yfinance as yf

TICKER = "PLTR"
pd.set_option("display.width", 200)

print(f"yfinance {yf.__version__} | pandas {pd.__version__}")
print(f"now UTC   {dt.datetime.now(dt.timezone.utc).isoformat()}")
print("=" * 72)


def show(label, fn):
    try:
        data = fn()
        if data is None or len(data) == 0:
            print(f"{label:38s} -> EMPTY")
            return
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        tail = data.tail(3)
        dates = [str(pd.Timestamp(i).date()) for i in tail.index]
        closes = [round(float(c), 2) for c in tail["Close"]]
        print(f"{label:38s} -> {list(zip(dates, closes))}")
    except Exception as exc:
        print(f"{label:38s} -> ERROR {type(exc).__name__}: {exc}")
        traceback.print_exc()


today = dt.date.today()
show("download period=1mo", lambda: yf.download(TICKER, period="1mo", interval="1d", progress=False, auto_adjust=False))
show("download period=5d", lambda: yf.download(TICKER, period="5d", interval="1d", progress=False, auto_adjust=False))
show("download start/end explicit", lambda: yf.download(TICKER, start=today - dt.timedelta(days=10), end=today + dt.timedelta(days=1), interval="1d", progress=False, auto_adjust=False))
show("Ticker.history period=5d", lambda: yf.Ticker(TICKER).history(period="5d", interval="1d", auto_adjust=False))
show("Ticker.history 5d prepost", lambda: yf.Ticker(TICKER).history(period="5d", interval="1d", auto_adjust=False, prepost=True))
show("Ticker.history 1mo", lambda: yf.Ticker(TICKER).history(period="1mo", interval="1d", auto_adjust=False))

print("=" * 72)
try:
    fi = yf.Ticker(TICKER).fast_info
    print("fast_info last_price :", fi.get("lastPrice"))
    print("fast_info prev_close :", fi.get("previousClose"))
except Exception as exc:
    print("fast_info ERROR:", exc)

print("=" * 72)
for host in ("query1", "query2"):
    url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{TICKER}?range=5d&interval=1d"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        print(f"{host} chart API status {r.status_code}")
        if r.ok:
            res = r.json()["chart"]["result"][0]
            stamps = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
            tz = res["meta"].get("exchangeTimezoneName")
            print(f"  meta tz={tz} regularMarketTime="
                  f"{dt.datetime.fromtimestamp(res['meta']['regularMarketTime'], dt.timezone.utc).isoformat()}")
            for ts, c in list(zip(stamps, closes))[-4:]:
                local = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
                print(f"  {local.isoformat()}  close={c}")
    except Exception as exc:
        print(f"{host} chart API ERROR: {exc}")
