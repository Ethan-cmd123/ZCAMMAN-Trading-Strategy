import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta, timezone
import alpaca_trade_api as tradeapi

API_KEY = "PK7FCMSPZHW7ONUT894V"
API_SECRET = "AtJxadxXnTfPcwqnGOirnu6xM251smYXc06X7JPx"
BASE_URL = "https://paper-api.alpaca.markets"

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version="v2")

TICKER = "AAPL"
INTERVAL = "1Min"  
LOOKBACK = 20
Z_ENTRY = 2.0
Z_EXIT = 0.5
SL_PCT = 0.003
TP_PCT = 0.02
RISK_PERC = 0.25  

cash = float(api.get_account().cash)
positions = {}
prices_window = []

kalman_est = []
P = 1.0
R = 0.01
Q = 0.0001

trades = []


def kalman_update(price):
    global P, kalman_est
    if not kalman_est:
        kalman_est.append(price)
    x_pred = kalman_est[-1]
    P_pred = P + Q
    K = P_pred / (P_pred + R)
    x_new = x_pred + K * (price - x_pred)
    P = (1 - K) * P_pred
    kalman_est.append(x_new)
    return x_new


def zscore(series):
    mean = np.mean(series)
    std = np.std(series)
    return (series[-1] - mean) / std if std != 0 else 0


def get_latest_price(ticker):
    barset = api.get_bars(ticker, tradeapi.TimeFrame.Minute, limit=1, adjustment='raw')
    if barset:
        bar = barset[0]
        return bar.c
    return None


def calc_size(price):
    global cash
    risk_capital = cash * RISK_PERC
    size = int(risk_capital / (price * SL_PCT))
    return max(size, 1)

while True:
    price = get_latest_price(TICKER)
    if price is None:
        time.sleep(60)
        continue

    # Kalman
    k_est = kalman_update(price)

    # Update window
    prices_window.append(price)
    if len(prices_window) > LOOKBACK:
        prices_window.pop(0)

    if len(prices_window) < LOOKBACK:
        time.sleep(60)
        continue

    z = zscore(prices_window)


    position = positions.get(TICKER, None)


    if position is None:
        size = calc_size(price)
        if z > Z_ENTRY:
            # SHORT
            api.submit_order(
                symbol=TICKER,
                qty=size,
                side='sell',
                type='market',
                time_in_force='gtc'
            )
            positions[TICKER] = {'type': 'short', 'entry': price, 'size': size,
                                 'sl': price*(1+SL_PCT), 'tp': price*(1-TP_PCT)}
            trades.append(positions[TICKER])
            print(f"SHORT ENTRY @ {price}, size={size}")
        elif z < -Z_ENTRY:
            # LONG
            api.submit_order(
                symbol=TICKER,
                qty=size,
                side='buy',
                type='market',
                time_in_force='gtc'
            )
            positions[TICKER] = {'type': 'long', 'entry': price, 'size': size,
                                 'sl': price*(1-SL_PCT), 'tp': price*(1+TP_PCT)}
            trades.append(positions[TICKER])
            print(f"LONG ENTRY @ {price}, size={size}")


    else:
        trade = positions[TICKER]
        exit_trade = False
        pnl = 0
        # LONG exit
        if trade['type'] == 'long':
            if price >= trade['tp'] or price <= trade['sl'] or z > -Z_EXIT:
                api.submit_order(
                    symbol=TICKER,
                    qty=trade['size'],
                    side='sell',
                    type='market',
                    time_in_force='gtc'
                )
                exit_trade = True
                pnl = (price - trade['entry']) * trade['size']
        # SHORT exit
        elif trade['type'] == 'short':
            if price <= trade['tp'] or price >= trade['sl'] or z < Z_EXIT:
                api.submit_order(
                    symbol=TICKER,
                    qty=trade['size'],
                    side='buy',
                    type='market',
                    time_in_force='gtc'
                )
                exit_trade = True
                pnl = (trade['entry'] - price) * trade['size']

        if exit_trade:
            trade['exit'] = price
            trade['pnl'] = pnl
            print(f"EXIT {trade['type'].upper()} @ {price}, PnL={pnl:.2f}")
            positions.pop(TICKER)
            cash += pnl

    time.sleep(30)
