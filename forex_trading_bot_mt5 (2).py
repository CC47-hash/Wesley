import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta

# --- CONFIGURATION ---
SYMBOL = "EURUSD"
TIMEFRAME = mt5.TIMEFRAME_M5
LOT = 0.1
SL_PIPS = 20   # Stop Loss in pips
TP_PIPS = 40   # Take Profit in pips
RISK_PER_TRADE = 0.01  # 1% of account balance

# --- MT5 CONNECTION ---
def connect_mt5():
    if not mt5.initialize():
        raise Exception("MT5 initialization failed")
    account_info = mt5.account_info()
    if account_info is None:
        raise Exception("MT5 account info not found")
    print(f"Connected to MT5, balance: {account_info.balance}")

# --- DATA FETCHING ---
def fetch_data(symbol, timeframe, bars=500):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

# --- STRATEGY IMPLEMENTATIONS ---
def detect_support_resistance(df, window=20, tolerance=0.002):
    supports = []
    resistances = []
    for i in range(window, len(df)-window):
        low = df['low'][i]
        high = df['high'][i]
        if all(low <= df['low'][i-window:i+window]) and \
           np.abs(df['low'][i] - df['low'][i-window:i+window].min()) < tolerance*low:
            supports.append((df.index[i], low))
        if all(high >= df['high'][i-window:i+window]) and \
           np.abs(df['high'][i] - df['high'][i-window:i+window].max()) < tolerance*high:
            resistances.append((df.index[i], high))
    return supports, resistances

def detect_candlestick_trend(df):
    signals = {}
    for i in range(1, len(df)):
        # Bullish engulfing
        if df['close'][i] > df['open'][i] and \
           df['open'][i] < df['close'][i-1] and \
           df['open'][i] < df['open'][i-1] and \
           df['close'][i] > df['open'][i-1]:
            signals[df.index[i]] = 'bullish'
        # Bearish engulfing
        elif df['close'][i] < df['open'][i] and \
             df['open'][i] > df['close'][i-1] and \
             df['open'][i] > df['open'][i-1] and \
             df['close'][i] < df['open'][i-1]:
            signals[df.index[i]] = 'bearish'
    return signals

def detect_moving_average(df, fast=10, slow=30):
    df['ma_fast'] = df['close'].rolling(fast).mean()
    df['ma_slow'] = df['close'].rolling(slow).mean()
    df['ma_signal'] = 0
    df.loc[df.index[fast:], 'ma_signal'] = np.where(df['ma_fast'][fast:] > df['ma_slow'][fast:], 1, -1)
    return df

def combine_signals(df):
    df = detect_moving_average(df)
    supports, resistances = detect_support_resistance(df)
    cdl_signals = detect_candlestick_trend(df)
    trades = []
    for i in range(1, len(df)):
        ma_signal = df['ma_signal'].iloc[i]
        candle_signal = 1 if cdl_signals.get(df.index[i]) == 'bullish' else -1 if cdl_signals.get(df.index[i]) == 'bearish' else 0
        support_signal = 1 if any(abs(df['low'].iloc[i] - level) < 0.001*df['low'].iloc[i] for _, level in supports) else 0
        resistance_signal = -1 if any(abs(df['high'].iloc[i] - level) < 0.001*df['high'].iloc[i] for _, level in resistances) else 0
        sr_signal = support_signal + resistance_signal
        signals = [s for s in [ma_signal, candle_signal, sr_signal] if s != 0]
        if len(signals) >= 2 and all(s == signals[0] for s in signals):
            direction = 'buy' if signals[0] > 0 else 'sell'
            trades.append({'index': df.index[i], 'direction': direction, 'price': df['close'].iloc[i]})
    return trades

# --- RISK MANAGEMENT ---
def calculate_lot(balance, risk_per_trade, sl_pips, symbol=SYMBOL):
    tick_size = mt5.symbol_info(symbol).point
    sl_value = sl_pips * tick_size
    # Approximate pip value for major pairs is $10/lot for 1 pip (can be improved for cross pairs)
    risk_amount = balance * risk_per_trade
    lot = risk_amount / (sl_pips * 10)
    lot = max(0.01, round(lot, 2))  # Minimum lot size is typically 0.01
    return lot

# --- TRADE EXECUTION ---
def place_trade(direction, price, sl_pips, tp_pips, lot, symbol=SYMBOL):
    deviation = 20
    point = mt5.symbol_info(symbol).point
    if direction == 'buy':
        order_type = mt5.ORDER_TYPE_BUY
        sl = price - sl_pips * point
        tp = price + tp_pips * point
    else:
        order_type = mt5.ORDER_TYPE_SELL
        sl = price + sl_pips * point
        tp = price - tp_pips * point

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": 123456,
        "comment": "multi-strategy bot trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Trade failed: {result.comment}")
    else:
        print(f"Trade placed: {direction} {lot} lots at {price}, SL: {sl}, TP: {tp}")

# --- MAIN LOOP (EXAMPLE) ---
def main():
    connect_mt5()
    df = fetch_data(SYMBOL, TIMEFRAME, bars=200)
    trades = combine_signals(df)
    account_info = mt5.account_info()
    last_trade_time = None

    for trade in trades:
        # Avoid duplicate trades on the same bar
        if last_trade_time == trade['index']:
            continue
        lot = calculate_lot(account_info.balance, RISK_PER_TRADE, SL_PIPS)
        place_trade(trade['direction'], trade['price'], SL_PIPS, TP_PIPS, lot)
        last_trade_time = trade['index']

if __name__ == "__main__":
    main()