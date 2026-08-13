# Import standard library modules
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Import third party modules
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# Import Alpaca modules
from alpaca.data.historical.stock import (
    StockHistoricalDataClient,
    StockLatestTradeRequest,
)
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    AssetClass,
    AssetStatus,
    OrderSide,
    OrderType,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest


# ── Timezone ──────────────────────────────────────────────────────────────────
NY_TZ = ZoneInfo('America/New_York')

# ── Symbol ────────────────────────────────────────────────────────────────────
underlying_symbol = 'TQQQ'

# ── Strategy Parameters ───────────────────────────────────────────────────────
RSI_PERIOD      = 14                    # Standard medium-term RSI
MACD_FAST       = 12                    # MACD fast EMA
MACD_SLOW       = 26                    # MACD slow EMA
MACD_SIGNAL     = 9                     # MACD signal line EMA
MA_FAST         = 50                    # Higher-timeframe fast MA
MA_MID          = 100                   # Higher-timeframe mid MA
MA_SLOW         = 200                   # Higher-timeframe slow MA
BUY_POWER_LIMIT = 0.02                  # Fraction of buying power to use per trade
TIMEFRAME_MAIN  = TimeFrameUnit.Hour    # Primary trading timeframe
TIMEFRAME_TREND = TimeFrameUnit.Day     # Trend-defining timeframe
WINDOW_SIZE     = 5                     # Signal confirmation window (bars)

# ── Signal State ──────────────────────────────────────────────────────────────
rsi_bounce_bar        = None
macd_cross_bar        = None
rsi_retreat_bar       = None
macd_death_cross_bar  = None
macd_centerline_bar   = None
current_bar_index     = 0

# ── Environment / Credentials ─────────────────────────────────────────────────
load_dotenv()
API_KEY           = os.getenv("ALPACA_PAPER_API_KEY")
API_SECRET        = os.getenv("ALPACA_PAPER_SECRET_KEY")
ALPACA_PAPER_TRADE = os.getenv("ALPACA_PAPER_TRADE", "True")
trade_api_url     = os.getenv("TRADE_API_URL")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing Alpaca API credentials in environment variables.")

# ── Alpaca Clients ─────────────────────────────────────────────────────────────
trade_client      = TradingClient(api_key=API_KEY, secret_key=API_SECRET, paper=ALPACA_PAPER_TRADE, url_override=trade_api_url)
stock_data_client = StockHistoricalDataClient(api_key=API_KEY, secret_key=API_SECRET)


# ══════════════════════════════════════════════════════════════════════════════
# ALPACA HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sleep_until(target_time, chunk_seconds=30):
    """Pause until target_time (UTC) in small chunks for responsiveness."""
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)
    while True:
        now = datetime.now(timezone.utc)
        remaining = (target_time - now).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, chunk_seconds))


def fetch_bars(
    client: StockHistoricalDataClient,
    symbol: str,
    timeframe_unit: TimeFrameUnit,
    days: int = 90,
) -> pd.DataFrame:
    """Fetch OHLCV bars from Alpaca for the given symbol and lookback window."""
    today = datetime.now(NY_TZ).date()
    req = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(amount=1, unit=timeframe_unit),
        start=today - timedelta(days=days),
    )
    return client.get_stock_bars(req).df


def get_underlying_price(symbol: str) -> float:
    """Return the latest trade price for a symbol via Alpaca."""
    req  = StockLatestTradeRequest(symbol_or_symbols=symbol)
    resp = stock_data_client.get_stock_latest_trade(req)
    return resp[symbol].price


def calculate_buying_power_limit(buy_power_limit: float) -> float:
    """Return the dollar amount of buying power available for a single trade."""
    buying_power = float(trade_client.get_account().buying_power)
    return buying_power * buy_power_limit


def get_open_position(symbol: str):
    """Return (position_open, current_qty) for the given symbol."""
    try:
        position = trade_client.get_open_position(symbol)
        return True, int(position.qty)
    except Exception:
        return False, 0


def submit_market_order(symbol: str, qty: int, side: OrderSide) -> object:
    """Submit a DAY market order and return the response."""
    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=side,
        type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )
    return trade_client.submit_order(req)


# ══════════════════════════════════════════════════════════════════════════════
# INDICATOR HELPERS — Popular Chart Indicators
# ══════════════════════════════════════════════════════════════════════════════

# ── 1. RSI — Relative Strength Index ──────────────────────────────────────────
def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Momentum oscillator (0–100).
    >70 overbought, <30 oversold.
    """
    deltas   = prices.diff().dropna()
    gains    = deltas.where(deltas > 0, 0)
    losses   = (-deltas).where(deltas < 0, 0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ── 2. MACD — Moving Average Convergence Divergence ───────────────────────────
def compute_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series]:
    """
    Returns (macd_line, signal_line).
    Golden cross (macd > signal) = bullish; death cross = bearish.
    """
    ema_fast    = prices.ewm(span=fast, adjust=False).mean()
    ema_slow    = prices.ewm(span=slow, adjust=False).mean()
    macd_line   = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


# ── 3. EMA — Exponential Moving Average ───────────────────────────────────────
def compute_ema(prices: pd.Series, period: int) -> pd.Series:
    """
    Weighted moving average giving more importance to recent prices.
    Faster to react than SMA — preferred for short-term signals.
    """
    return prices.ewm(span=period, adjust=False).mean()


# ── 4. SMA — Simple Moving Average ────────────────────────────────────────────
def compute_sma(prices: pd.Series, period: int) -> pd.Series:
    """
    Equal-weighted average over `period` bars.
    Used for MA50/100/200 trend-stack filter.
    """
    return prices.rolling(period).mean()


# ── 5. Bollinger Bands ────────────────────────────────────────────────────────
def compute_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (upper_band, middle_band, lower_band).
    Bands widen on high volatility, contract on low volatility.
    Price outside band + RSI extreme → mean-reversion entry.
    Narrow squeeze → anticipate breakout.
    """
    mid   = prices.rolling(period).mean()
    std   = prices.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


# ── 6. ATR — Average True Range ───────────────────────────────────────────────
def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Volatility indicator — average size of price moves per bar.
    Use for dynamic stop-loss placement and position sizing:
        stop = entry - ATR * multiplier
        shares = risk_dollars / (ATR * multiplier)
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(span=period, adjust=False).mean()  # Wilder's smoothing


# ── 7. ADX — Average Directional Index ───────────────────────────────────────
def compute_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (adx, plus_di, minus_di).
    ADX > 25 → trend strong enough to trade.
    ADX < 20 → choppy market, avoid trend-following.
    +DI > -DI → uptrend; -DI > +DI → downtrend.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    plus_dm  = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    # Where both DMs are positive, keep only the larger one
    mask = plus_dm > minus_dm
    plus_dm  = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)

    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_smooth      = true_range.ewm(span=period, adjust=False).mean()
    plus_di         = 100 * plus_dm.ewm(span=period, adjust=False).mean()  / atr_smooth
    minus_di        = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_smooth
    dx              = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx             = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


# ── 8. Stochastic Oscillator ──────────────────────────────────────────────────
def compute_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """
    Returns (%K, %D).
    >80 overbought, <20 oversold.
    Bullish: %K crosses above %D from below 20.
    Bearish: %K crosses below %D from above 80.
    Works best in ranging/sideways markets.
    """
    low_n  = df["low"].rolling(k_period).min()
    high_n = df["high"].rolling(k_period).max()
    k = 100 * (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


# ── 9. VWAP — Volume-Weighted Average Price ───────────────────────────────────
def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Intraday price benchmark weighted by volume. Resets each session.
    Price above VWAP → bullish bias; below → bearish bias.
    Institutions use VWAP as execution benchmark — price clusters around it.
    NOTE: meaningful only on intraday (minute/hour) bars within a single session.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    tp_vol        = typical_price * df["volume"]
    return tp_vol.cumsum() / df["volume"].cumsum()


# ── 10. OBV — On-Balance Volume ───────────────────────────────────────────────
def compute_obv(df: pd.DataFrame) -> pd.Series:
    """
    Running total: add volume on up-close, subtract on down-close.
    Rising OBV in an uptrend confirms accumulation.
    OBV divergence (price new high, OBV not) → distribution warning.
    """
    direction = df["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * df["volume"]).cumsum()


# ── 11. Fibonacci Retracement Levels ─────────────────────────────────────────
def compute_fibonacci_levels(df: pd.DataFrame, lookback: int = 50) -> dict[str, float]:
    """
    Returns key Fibonacci retracement price levels from the recent swing high/low.
    Key levels: 23.6%, 38.2%, 50.0%, 61.8% (golden ratio), 78.6%.
    Use for pullback entries and stop placement.
    """
    swing_high = df["high"].rolling(lookback).max().iloc[-1]
    swing_low  = df["low"].rolling(lookback).min().iloc[-1]
    diff       = swing_high - swing_low
    return {
        "swing_high": swing_high,
        "swing_low":  swing_low,
        "23.6%": swing_high - diff * 0.236,
        "38.2%": swing_high - diff * 0.382,
        "50.0%": swing_high - diff * 0.500,
        "61.8%": swing_high - diff * 0.618,  # golden ratio
        "78.6%": swing_high - diff * 0.786,
    }


# ── 12. Ichimoku Cloud ────────────────────────────────────────────────────────
def compute_ichimoku(df: pd.DataFrame) -> dict[str, pd.Series]:
    """
    Returns all five Ichimoku components as a dict.
    Price above cloud → bullish; below cloud → bearish.
    Tenkan/Kijun cross while above cloud → entry signal.
    Cloud thickness = strength of support/resistance.
    """
    high, low = df["high"], df["low"]
    tenkan = (high.rolling(9).max()  + low.rolling(9).min())  / 2   # conversion
    kijun  = (high.rolling(26).max() + low.rolling(26).min()) / 2   # base
    span_a = ((tenkan + kijun) / 2).shift(26)                        # leading A
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)  # leading B
    chikou = df["close"].shift(-26)                                   # lagging
    return {
        "tenkan":  tenkan,
        "kijun":   kijun,
        "span_a":  span_a,
        "span_b":  span_b,
        "chikou":  chikou,
    }


# ── 13. Parabolic SAR ─────────────────────────────────────────────────────────
def compute_parabolic_sar(
    df: pd.DataFrame,
    acceleration: float = 0.02,
    max_af: float = 0.20,
) -> pd.Series:
    """
    Returns a SAR series: dots below price = uptrend; above = downtrend.
    Use as a trailing stop — move stop-loss to SAR each bar to lock in profits.
    Avoid in sideways markets; SAR flips rapidly and generates false signals.
    """
    high   = df["high"].values
    low    = df["low"].values
    n      = len(high)
    sar    = np.zeros(n)
    ep     = 0.0        # extreme point
    af     = acceleration
    bull   = True       # start assuming uptrend

    sar[0] = low[0]
    ep     = high[0]

    for i in range(1, n):
        prev_sar = sar[i - 1]
        if bull:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = min(sar[i], low[i - 1], low[i - 2] if i >= 2 else low[i - 1])
            if low[i] < sar[i]:           # flip to downtrend
                bull   = False
                sar[i] = ep
                ep     = low[i]
                af     = acceleration
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + acceleration, max_af)
        else:
            sar[i] = prev_sar + af * (ep - prev_sar)
            sar[i] = max(sar[i], high[i - 1], high[i - 2] if i >= 2 else high[i - 1])
            if high[i] > sar[i]:          # flip to uptrend
                bull   = True
                sar[i] = ep
                ep     = high[i]
                af     = acceleration
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + acceleration, max_af)

    return pd.Series(sar, index=df.index)


# ── 14. CCI — Commodity Channel Index ────────────────────────────────────────
def compute_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Measures deviation of price from its statistical mean.
    >+100 overbought, <-100 oversold.
    Zero-line crossover → momentum shift signal.
    """
    tp  = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma) / (0.015 * mad)


# ── 15. Williams %R ───────────────────────────────────────────────────────────
def compute_williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Inverted Stochastic: range is −100 to 0.
    > −20 overbought; < −80 oversold.
    Fast and sensitive — best paired with a slower trend indicator (ADX/MACD).
    """
    highest_high = df["high"].rolling(period).max()
    lowest_low   = df["low"].rolling(period).min()
    return -100 * (highest_high - df["close"]) / (highest_high - lowest_low).replace(0, np.nan)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def detect_bb_squeeze(upper: pd.Series, lower: pd.Series, lookback: int = 20) -> bool:
    """True when the current Bollinger Band width is near its recent minimum — breakout likely."""
    band_width = upper - lower
    return band_width.iloc[-1] < band_width.rolling(lookback).min().iloc[-1] * 1.05


def detect_obv_divergence(df: pd.DataFrame) -> bool:
    """True when price is at a 20-bar high but OBV is not — bearish distribution signal."""
    obv            = compute_obv(df)
    price_new_high = df["close"].iloc[-1] == df["close"].rolling(20).max().iloc[-1]
    obv_new_high   = obv.iloc[-1] == obv.rolling(20).max().iloc[-1]
    return price_new_high and not obv_new_high


def near_fibonacci_support(df: pd.DataFrame, tolerance: float = 0.005) -> bool:
    """True when the latest close is within `tolerance` of the 61.8% Fibonacci level."""
    fib    = compute_fibonacci_levels(df)
    price  = df["close"].iloc[-1]
    target = fib["61.8%"]
    return abs(price - target) / target < tolerance


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Enhanced trading loop with full indicator suite."""
    logging.basicConfig(
        filename="trade_log.txt",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.info("=== Enhanced Strategy started ===")

    # remembers whether the market was open in the previous iteration
    clock       = trade_client.get_clock()
    market_open = clock.is_open

    # Set tracking signal flags over a predefined window
    global rsi_bounce_bar, macd_cross_bar, rsi_retreat_bar, macd_death_cross_bar, macd_centerline_bar, current_bar_index
    rsi_bounce_bar       = None
    macd_cross_bar       = None
    rsi_retreat_bar      = None
    macd_death_cross_bar = None
    macd_centerline_bar  = None
    current_bar_index    = 0

    while True:
        clock = trade_client.get_clock()

        # Detect if the market has just transitioned from open to closed.
        if market_open and not clock.is_open:
            logging.info("Market closed. Sleeping until next open at %s", clock.next_open)
            market_open = False
            sleep_until(clock.next_open)
            continue

        # Detect if the market has just transitioned from closed to open.
        if (not market_open) and clock.is_open:
            logging.info("Market opened. Resuming trading.")
            market_open = True

        # Detect if the market is closed (e.g., at script start or unexpected state), exit to prevent trading.
        if not clock.is_open:
            logging.info("Market is closed. Exiting.")
            exit(0)

        # ── Fetch data ────────────────────────────────────────────────────────
        df_main  = fetch_bars(stock_data_client, underlying_symbol, TIMEFRAME_MAIN,  days=MA_SLOW + 100)
        df_trend = fetch_bars(stock_data_client, underlying_symbol, TIMEFRAME_TREND, days=MA_SLOW + 10)
        logging.info("Fetched %d main bars and %d trend bars", len(df_main), len(df_trend))

        # MultiIndex → flat column names (symbol, timestamp) → drop symbol level
        if isinstance(df_main.index, pd.MultiIndex):
            df_main  = df_main.droplevel(0)
        if isinstance(df_trend.index, pd.MultiIndex):
            df_trend = df_trend.droplevel(0)

        current_bar_index       = len(df_main) - 1
        position_open, current_qty = get_open_position(underlying_symbol)

        # ── Trend filter (daily MAs) ───────────────────────────────────────────
        ma_fast = compute_sma(df_trend["close"], MA_FAST)
        ma_mid  = compute_sma(df_trend["close"], MA_MID)
        ma_slow = compute_sma(df_trend["close"], MA_SLOW)
        in_uptrend = (
            not (ma_fast.isna().any() or ma_mid.isna().any() or ma_slow.isna().any())
            and ma_fast.iloc[-1] > ma_mid.iloc[-1] > ma_slow.iloc[-1]
        )

        # ── Core momentum indicators (hourly) ─────────────────────────────────
        prices     = df_main["close"]
        rsi_series = compute_rsi(prices, RSI_PERIOD)
        macd_line, signal_line = compute_macd(prices, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

        rsi_now   = rsi_series.iloc[-1];  rsi_prev  = rsi_series.iloc[-2]
        macd_now  = macd_line.iloc[-1];   macd_prev = macd_line.iloc[-2]
        sig_now   = signal_line.iloc[-1]; sig_prev  = signal_line.iloc[-2]

        # ── Supplemental indicators ───────────────────────────────────────────
        ema9  = compute_ema(prices, 9)
        ema21 = compute_ema(prices, 21)
        bb_upper, bb_mid, bb_lower = compute_bollinger_bands(prices)
        atr   = compute_atr(df_main)
        adx, plus_di, minus_di = compute_adx(df_main)
        stoch_k, stoch_d = compute_stochastic(df_main)
        vwap  = compute_vwap(df_main)
        obv   = compute_obv(df_main)
        cci   = compute_cci(df_main)
        wpr   = compute_williams_r(df_main)
        sar   = compute_parabolic_sar(df_main)
        ichi  = compute_ichimoku(df_main)
        fib   = compute_fibonacci_levels(df_main)

        # Latest supplemental values
        adx_val     = adx.iloc[-1]
        stoch_k_now = stoch_k.iloc[-1];  stoch_k_prev = stoch_k.iloc[-2]
        stoch_d_now = stoch_d.iloc[-1];  stoch_d_prev = stoch_d.iloc[-2]
        cci_now     = cci.iloc[-1]
        wpr_now     = wpr.iloc[-1]
        sar_now     = sar.iloc[-1]
        above_vwap  = prices.iloc[-1] > vwap.iloc[-1]
        price_above_cloud = prices.iloc[-1] > max(
            ichi["span_a"].iloc[-1] if not pd.isna(ichi["span_a"].iloc[-1]) else 0,
            ichi["span_b"].iloc[-1] if not pd.isna(ichi["span_b"].iloc[-1]) else 0,
        )
        bb_squeeze  = detect_bb_squeeze(bb_upper, bb_lower)
        obv_diverge = detect_obv_divergence(df_main)

        logging.info(
            "Indicators — RSI: %.1f | MACD: %.4f | ADX: %.1f | CCI: %.1f | %%R: %.1f | "
            "SAR: %.2f | VWAP: %.2f | AboveVWAP: %s | CloudBullish: %s | BBSqueeze: %s",
            rsi_now, macd_now, adx_val, cci_now, wpr_now,
            sar_now, vwap.iloc[-1], above_vwap, price_above_cloud, bb_squeeze,
        )

        # ── Position sizing ───────────────────────────────────────────────────
        buying_power_limit = calculate_buying_power_limit(BUY_POWER_LIMIT)
        current_price      = get_underlying_price(underlying_symbol)
        position_size      = int(buying_power_limit / current_price)

        # ── Entry signal detection ────────────────────────────────────────────
        if (rsi_prev < 30) and (rsi_now > 30):
            rsi_bounce_bar = current_bar_index
        if (macd_prev < sig_prev) and (macd_now > sig_now):
            macd_cross_bar = current_bar_index

        # ── Entry logic ───────────────────────────────────────────────────────
        # Base: RSI bounce + MACD golden cross within WINDOW_SIZE bars + uptrend
        # Enhanced confirmations: ADX trend strength, Stochastic, VWAP bias, Ichimoku cloud
        base_entry = (
            not position_open
            and in_uptrend
            and position_size > 0
            and rsi_bounce_bar is not None
            and macd_cross_bar is not None
            and abs(rsi_bounce_bar - macd_cross_bar) <= WINDOW_SIZE
        )
        enhanced_confirm = (
            adx_val > 20                                                         # trend exists
            and above_vwap                                                       # bullish intraday bias
            and price_above_cloud                                                 # Ichimoku bullish
            and (stoch_k_prev < stoch_d_prev) and (stoch_k_now > stoch_d_now)   # stoch golden cross
            and wpr_now > -80                                                    # not deeply oversold
            and cci_now > -100                                                   # not CCI oversold extreme
            and prices.iloc[-1] > sar_now                                        # SAR uptrend
        )

        if base_entry and enhanced_confirm:
            res = submit_market_order(underlying_symbol, position_size, OrderSide.BUY)
            logging.info(
                "BUY ORDER SUBMITTED — Symbol: %s | Qty: %d | Est.Price: $%.2f | "
                "ATR: %.2f | ADX: %.1f | OrderID: %s | SubmittedAt: %s",
                underlying_symbol, position_size, current_price,
                atr.iloc[-1], adx_val, res.id, res.submitted_at,
            )
            rsi_bounce_bar = None
            macd_cross_bar = None

        # ── Exit signal detection ─────────────────────────────────────────────
        if (rsi_prev > 70) and (rsi_now < 65):
            rsi_retreat_bar = current_bar_index
        if (macd_prev > sig_prev) and (macd_now < sig_now):
            macd_death_cross_bar = current_bar_index
        elif macd_prev > 0 and macd_now < 0:
            macd_centerline_bar = current_bar_index

        # ── Exit logic ────────────────────────────────────────────────────────
        # Base: RSI retreat + MACD death cross or centerline drop within WINDOW_SIZE bars
        # Enhanced: also exit on Parabolic SAR flip, OBV divergence, or CCI extreme
        if position_open:
            base_exit = rsi_retreat_bar is not None and (
                (macd_death_cross_bar is not None and abs(rsi_retreat_bar - macd_death_cross_bar) <= WINDOW_SIZE)
                or (macd_centerline_bar is not None and abs(rsi_retreat_bar - macd_centerline_bar) <= WINDOW_SIZE)
            )
            sar_flip      = prices.iloc[-1] < sar_now      # SAR flipped above price
            forced_exit   = sar_flip or obv_diverge         # hard exits regardless of RSI/MACD

            if base_exit or forced_exit:
                exit_reason = "BASE_SIGNALS" if base_exit else ("SAR_FLIP" if sar_flip else "OBV_DIVERGENCE")
                res = submit_market_order(underlying_symbol, current_qty, OrderSide.SELL)
                logging.info(
                    "SELL ORDER SUBMITTED — Symbol: %s | Qty: %d | Est.Price: $%.2f | "
                    "Reason: %s | OrderID: %s | SubmittedAt: %s",
                    underlying_symbol, current_qty, current_price,
                    exit_reason, res.id, res.submitted_at,
                )
                rsi_retreat_bar      = None
                macd_death_cross_bar = None
                macd_centerline_bar  = None

        # ── Sleep until next top-of-hour bar ──────────────────────────────────
        next_run = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        sleep_until(next_run, chunk_seconds=30)


if __name__ == "__main__":
    main()

