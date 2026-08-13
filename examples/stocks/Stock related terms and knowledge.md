# Stock Trading Terms & Knowledge

> This document summarizes key concepts, terms, and code patterns used in the
> RSI + MACD trading bot (`trading_bot_chatgpt.ipynb`).

---

## 1. `StockBarsRequest` — Fetching Historical Bar Data

```python
req = StockBarsRequest(
    symbol_or_symbols=[underlying_symbol],
    timeframe=TimeFrame(amount=1, unit=timeframe_unit),
    start=today - timedelta(days=days),
)
```

This block constructs a request for historical **OHLCV** (Open, High, Low, Close, Volume) bar data.

| Parameter | Purpose |
|-----------|---------|
| `symbol_or_symbols` | The stock ticker(s) to fetch data for (e.g. `"TQQQ"`) |
| `timeframe` | Each bar's width — e.g. `1 Hour` or `1 Day` depending on `timeframe_unit` |
| `start` | The beginning of the lookback window — `days` calendar days before today |

The result is a Pandas `DataFrame` with a `MultiIndex` of `(symbol, timestamp)` containing OHLCV columns for each bar.

---

## 2. Moving Averages — `ma50`, `ma100`, `ma200`

```python
ma50  = prices.rolling(MA_FAST).mean()   # MA_FAST = 50
ma100 = prices.rolling(MA_MID).mean()    # MA_MID  = 100
ma200 = prices.rolling(MA_SLOW).mean()   # MA_SLOW = 200
```

These are **Simple Moving Averages (SMAs)** — the average closing price over the last `N` bars at each point in time.

| Variable | Window | Constant | Role |
|----------|--------|----------|------|
| `ma50`  | 50 bars | `MA_FAST` | **Fast MA** — tracks short-to-medium term momentum; reacts quickly to recent price changes |
| `ma100` | 100 bars | `MA_MID` | **Mid MA** — smooths out more noise; middle-ground trend reference |
| `ma200` | 200 bars | `MA_SLOW` | **Slow MA** — classic long-term trend indicator; widely watched by traders and institutions |

### How they are used — the "MA Stack" Uptrend Filter

```python
in_uptrend = (ma_fast.iloc[-1] > ma_mid.iloc[-1]) and (ma_mid.iloc[-1] > ma_slow.iloc[-1])
```

All three MAs must be aligned in ascending order (**fast > mid > slow**), confirming that short, medium, and long-term momentum all point upward **before a buy signal is allowed**.

In the chart they are overlaid on the close price so you can visually identify trend alignment and crossovers.

---

## 3. `df_main` vs `df_trend` — Two-Timeframe Design

```python
# Primary trading timeframe: hourly bars, 300-day lookback
df_main  = fetch_bars(client, symbol, TIMEFRAME_MAIN,  days=300)

# Trend-defining timeframe: daily bars, just enough to fill MA200
df_trend = fetch_bars(client, symbol, TIMEFRAME_TREND, days=MA_SLOW + 10)
```

| | `df_main` | `df_trend` |
|---|---|---|
| **Timeframe** | Hourly (`TIMEFRAME_MAIN`) | Daily (`TIMEFRAME_TREND`) |
| **Lookback** | 300 days | `MA_SLOW + 10` = 210 days |
| **Bar count** | Many (≈300 × ~6.5 hrs/day) | Few (≈210 daily bars) |
| **Purpose** | RSI & MACD signal generation — detect entry/exit conditions on the primary trading timeframe | Trend filter — compute MA50/MA100/MA200 to confirm the stock is in an uptrend before allowing a buy |
| **Why separate?** | Hourly bars are fine-grained enough to catch short-term momentum shifts | Daily bars smooth out intraday noise, giving a cleaner read on the macro trend direction |

> **Design principle:** Trade on the hourly timeframe, but only in the direction of the daily trend.

---

## 4. RSI — Relative Strength Index

**RSI** stands for **Relative Strength Index**.

It is a **momentum oscillator** that measures the speed and magnitude of recent price changes to evaluate whether a stock is overbought or oversold. The value always falls between **0 and 100**.

```python
def compute_rsi(prices, period):
    deltas   = prices.diff().dropna()
    gains    = deltas.where(deltas > 0, 0)
    losses   = (-deltas).where(deltas < 0, 0)
    avg_gain = gains.rolling(period).mean()
    avg_loss = losses.rolling(period).mean()
    rs       = avg_gain / avg_loss
    rsi      = 100 - (100 / (1 + rs))
    return rsi
```

### RSI Interpretation

| RSI Value | Interpretation |
|-----------|---------------|
| **> 70** | **Overbought** — price may have risen too fast; possible reversal downward |
| **30 – 70** | Neutral — no strong directional signal |
| **< 30** | **Oversold** — price may have fallen too fast; possible reversal upward |

### How RSI is used in this strategy

| Signal | Condition | Meaning |
|--------|-----------|---------|
| **Entry (Buy)** | RSI crosses back **above 30** | Oversold bounce — potential buying opportunity |
| **Exit (Sell)** | RSI crosses back **below 65–70** | Overbought retreat — potential time to close the position |

The RSI is calculated with a **14-bar period** (`RSI_PERIOD = 14`), which is the standard setting used by most traders.

### `RSI_PERIOD` — Unit & Meaning

```python
RSI_PERIOD = 14  # Standard medium‑term RSI
```

The unit of `RSI_PERIOD` is **bars**, and a "bar" corresponds to whatever timeframe the data uses.

Since `compute_rsi` is called on `df_main` which uses `TIMEFRAME_MAIN = TimeFrameUnit.Hour`:

> **14 bars = 14 hours** of price history used to compute each RSI value.

This period was introduced by J. Welles Wilder (RSI's creator) in 1978 and remains the most widely used default across all timeframes. The same `RSI_PERIOD = 14` is also applied when computing RSI on `df_trend` (daily bars), where it would represent **14 trading days** instead.

---

## 5. MACD — Moving Average Convergence Divergence

**MACD** stands for **Moving Average Convergence Divergence**.

It is a **trend-following momentum indicator** derived from the difference between two Exponential Moving Averages (EMAs).

```python
def compute_macd(prices, fast, slow, signal):
    ema_fast    = prices.ewm(span=fast, adjust=False).mean()       # fast EMA (12)
    ema_slow    = prices.ewm(span=slow, adjust=False).mean()       # slow EMA (26)
    macd_line   = ema_fast - ema_slow                              # MACD line
    signal_line = macd_line.ewm(span=signal, adjust=False).mean() # signal   (9)
    return macd_line, signal_line
```

### Components

| Component | Description |
|-----------|-------------|
| **MACD line** | `EMA(12) − EMA(26)` — measures momentum |
| **Signal line** | `EMA(9)` of the MACD line — smoothed trigger |
| **Histogram** | `MACD − Signal` — visual gap; green = bullish, red = bearish |

### How MACD is used in this strategy

| Signal | Condition | Meaning |
|--------|-----------|---------|
| **Golden cross (Entry)** | MACD crosses **above** signal line | Bullish momentum building — potential buy |
| **Death cross (Exit)** | MACD crosses **below** signal line | Bearish momentum — potential sell |
| **Centerline drop (Exit)** | MACD crosses **below zero** | Strong bearish signal — momentum has fully reversed |

---

## 6. Combined Entry & Exit Logic

The strategy requires **confirmation from both RSI and MACD** within a rolling window (`WINDOW_SIZE = 5` bars) to filter out false signals.

### Entry (Buy)
All three conditions must be met:
1. `in_uptrend` — daily MA stack is bullish (MA50 > MA100 > MA200)
2. RSI bounced above 30 within the last 5 bars
3. MACD golden cross within the last 5 bars

### Exit (Sell)
Position is closed when:
1. RSI retreated below 65–70 within the last 5 bars, **AND**
2. Either a MACD death cross **or** MACD centerline drop within the last 5 bars

---

## 7. Stochastic Oscillator

The **Stochastic Oscillator** compares a stock's **closing price to its recent price range** over a lookback period to detect potential reversals. Like RSI, it outputs a value between **0 and 100**.

### Formula

```
%K = (Close - Lowest Low) / (Highest High - Lowest Low) × 100
%D = SMA(3) of %K   ← signal line
```

| Line | Description |
|------|-------------|
| **%K** | The raw stochastic value — how close the current price is to the top of its recent range |
| **%D** | A 3-period smoothed average of %K — acts as the trigger/signal line |

### Interpretation

| Value | Interpretation |
|-------|---------------|
| **> 80** | **Overbought** — price is near the top of its range; possible reversal down |
| **20 – 80** | Neutral — no strong directional signal |
| **< 20** | **Oversold** — price is near the bottom of its range; possible reversal up |

A **bullish signal** occurs when %K crosses **above** %D from below the 20 line.  
A **bearish signal** occurs when %K crosses **below** %D from above the 80 line.

### Use Cases

| Use Case | How |
|----------|-----|
| **Reversal detection** | Primary purpose — spot when price is stretched to an extreme relative to its recent range |
| **Confirm RSI signals** | Use Stochastic alongside RSI; if both show oversold at the same time, the bounce signal is stronger |
| **Divergence** | Price makes a new low but Stochastic doesn't → hidden bullish divergence, potential reversal |
| **Ranging markets** | Works best in sideways/choppy markets; less reliable in strong trending markets |

### Example: Pairing with this strategy's RSI

```python
# Pseudocode: add Stochastic as an extra confirmation filter
low_14  = prices.rolling(14).min()
high_14 = prices.rolling(14).max()
k = (prices - low_14) / (high_14 - low_14) * 100
d = k.rolling(3).mean()

# Stronger entry: RSI bounce + MACD cross + Stochastic %K crosses above %D below 20
stoch_confirm = (k.iloc[-2] < d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]) and (k.iloc[-1] < 30)
```

> **Key difference from RSI:** RSI measures the *speed* of price changes (momentum); Stochastic measures *where* the close sits within its recent high-low range (position). They complement each other well.

---

## 8. Bollinger Bands

**Bollinger Bands** measure **volatility** by placing an upper and lower envelope around a moving average. The bands widen when volatility increases and contract when it decreases.

### Formula

```
Middle Band = SMA(20)
Upper Band  = SMA(20) + (2 × Standard Deviation over 20 bars)
Lower Band  = SMA(20) - (2 × Standard Deviation over 20 bars)
```

| Band | Description |
|------|-------------|
| **Middle Band** | 20-period SMA — the baseline trend |
| **Upper Band** | 2 standard deviations above the middle — statistically ~95% of prices stay below this |
| **Lower Band** | 2 standard deviations below the middle — statistically ~95% of prices stay above this |

### Interpretation

| Condition | Meaning |
|-----------|---------|
| Price touches **upper band** | Overbought relative to recent volatility — possible pullback |
| Price touches **lower band** | Oversold relative to recent volatility — possible bounce |
| **Band squeeze** (bands narrow) | Volatility is compressing — a large breakout move is likely coming soon |
| **Band expansion** (bands widen) | High volatility — trend is accelerating |
| Price **walks the upper band** | Strong uptrend — price repeatedly hugs the top |
| Price **walks the lower band** | Strong downtrend — price repeatedly hugs the bottom |

### Use Cases

| Use Case | How |
|----------|-----|
| **Mean reversion** | Buy when price touches the lower band + RSI oversold; sell when it reaches the middle or upper band |
| **Breakout confirmation** | A close *outside* the band after a squeeze signals the start of a strong directional move |
| **Volatility filter** | Avoid trading during a squeeze (uncertain direction); wait for the breakout |
| **Stop-loss placement** | Place stops just outside the opposite band |

### Example: Adding Bollinger Bands to the existing strategy

```python
# Compute Bollinger Bands on df_main (hourly prices)
bb_period = 20
bb_std    = 2

bb_mid   = prices.rolling(bb_period).mean()
bb_std_s = prices.rolling(bb_period).std()
bb_upper = bb_mid + bb_std * bb_std_s
bb_lower = bb_mid - bb_std * bb_std_s

# Extra entry filter: price near or below the lower band (oversold zone)
near_lower_band = prices.iloc[-1] <= bb_lower.iloc[-1] * 1.01  # within 1% of lower band

# Extra exit filter: price near or above the upper band (overbought zone)
near_upper_band = prices.iloc[-1] >= bb_upper.iloc[-1] * 0.99
```

### Band Squeeze Detection

```python
# Squeeze: current band width is near its 20-bar minimum
band_width     = bb_upper - bb_lower
squeeze_active = band_width.iloc[-1] < band_width.rolling(20).min().iloc[-1] * 1.05
```

> **Key difference from RSI/Stochastic:** Bollinger Bands are **price-relative and volatility-adaptive** — they automatically adjust to market conditions. RSI and Stochastic give fixed overbought/oversold thresholds; Bollinger Bands give dynamic ones based on recent volatility.


---

## 9. Popular Chart Indicators — Overview

The table below lists the most widely used technical indicators across equity traders, categorized by their primary function.

| Indicator | Category | Primary Use |
|-----------|----------|-------------|
| SMA / EMA | Trend | Direction, crossovers |
| MACD | Trend + Momentum | Signal line crossovers, divergence |
| RSI | Momentum | Overbought/oversold, divergence |
| Stochastic Oscillator | Momentum | Reversal detection in ranges |
| Bollinger Bands | Volatility | Band squeezes, breakouts, mean reversion |
| ATR | Volatility | Stop-loss sizing, volatility filter |
| ADX | Trend Strength | Confirm if a trend is worth trading |
| VWAP | Volume + Price | Institutional reference, intraday bias |
| OBV | Volume | Confirm price moves with volume |
| Fibonacci Retracement | Price Levels | Support/resistance zones |
| Ichimoku Cloud | Trend + Support/Resistance | All-in-one trend system |
| Parabolic SAR | Trend | Trailing stop placement |
| CCI | Momentum | Overbought/oversold, cycle timing |
| Williams %R | Momentum | Fast overbought/oversold |

---

## 10. EMA — Exponential Moving Average

The **EMA** is a moving average that gives **more weight to recent prices**, making it more responsive to price changes than the SMA.

### Formula

```
EMA = Price × k + EMA(previous) × (1 − k)
where k = 2 / (period + 1)
```

### Common Periods

| Period | Use Case |
|--------|----------|
| 9 / 21 | Short-term momentum, intraday |
| 50 | Medium-term trend |
| 100 / 200 | Long-term trend filter |

### Use Cases

| Use Case | How |
|----------|-----|
| **Trend direction** | Price above EMA = uptrend; below = downtrend |
| **Dynamic support/resistance** | Price often bounces off the 21 or 50 EMA in trending markets |
| **EMA crossover** | 9 EMA crossing above 21 EMA → bullish momentum; below → bearish |
| **MACD construction** | MACD is built from 12 and 26 EMAs — understanding EMA explains MACD |

```python
ema_fast = prices.ewm(span=9, adjust=False).mean()
ema_slow = prices.ewm(span=21, adjust=False).mean()
crossover_up = (ema_fast.iloc[-2] < ema_slow.iloc[-2]) and (ema_fast.iloc[-1] > ema_slow.iloc[-1])
```

> **SMA vs EMA:** SMA treats all bars equally — better for long-term trend analysis. EMA reacts faster to recent changes — better for short-term signals. Most active traders prefer EMA.

---

## 11. ATR — Average True Range

**ATR** measures **how much a stock moves on average per bar**, capturing volatility regardless of direction.

### Formula

```
True Range = max(High - Low, |High - Prev Close|, |Low - Prev Close|)
ATR = Wilder's smoothed average of True Range over N periods (default 14)
```

### Interpretation

| ATR Value | Meaning |
|-----------|---------|
| **High ATR** | High volatility — large price swings expected |
| **Low ATR** | Low volatility — price is consolidating |
| **Rising ATR** | Volatility expanding — trend may be accelerating |
| **Falling ATR** | Volatility contracting — market may be pausing |

### Use Cases

| Use Case | How |
|----------|-----|
| **Stop-loss sizing** | Place stop at `entry - (ATR × multiplier)` — adapts to current volatility |
| **Position sizing** | Risk fixed dollar amount: `shares = risk_amount / (ATR × multiplier)` |
| **Volatility filter** | Avoid trading when ATR is extremely low (no movement) or high (chaotic) |
| **Breakout confirmation** | A breakout on high ATR has more conviction than one on low ATR |

```python
high, low, close = df["high"], df["low"], df["close"]
prev_close = close.shift(1)
true_range = pd.concat([
    high - low,
    (high - prev_close).abs(),
    (low - prev_close).abs()
], axis=1).max(axis=1)

atr = true_range.ewm(span=14, adjust=False).mean()  # Wilder's smoothing

# Dynamic stop-loss example
stop_loss = entry_price - (atr.iloc[-1] * 2)
```

---

## 12. ADX — Average Directional Index

**ADX** measures the **strength** of a trend — not direction. A high ADX means a strong trend (up or down); a low ADX means a weak or sideways market.

### Components

| Component | Description |
|-----------|-------------|
| **ADX** | Trend strength (0–100), direction-neutral |
| **+DI** | Positive Directional Indicator — upward pressure |
| **−DI** | Negative Directional Indicator — downward pressure |

### Interpretation

| ADX Value | Trend Strength |
|-----------|---------------|
| < 20 | No trend / weak — avoid trend-following strategies |
| 20–40 | Emerging or moderate trend |
| 40–60 | Strong trend |
| > 60 | Very strong trend — often unsustainable |

### Use Cases

| Use Case | How |
|----------|-----|
| **Trend filter** | Only use RSI/MACD buy signals when ADX > 25 (confirms a trend exists) |
| **Avoid choppy markets** | If ADX < 20, skip trend-following strategies; consider mean reversion instead |
| **Directional bias** | +DI above −DI → uptrend; −DI above +DI → downtrend |
| **Crossover entry** | +DI crossing above −DI while ADX > 20 → strong bullish signal |

```python
# Pseudocode: use ADX to gate trend-following entries
adx_strong_trend = adx.iloc[-1] > 25
di_bullish = plus_di.iloc[-1] > minus_di.iloc[-1]

# Only buy if trend is confirmed
if adx_strong_trend and di_bullish and rsi_signal and macd_signal:
    place_buy_order()
```

---

## 13. VWAP — Volume-Weighted Average Price

**VWAP** is the average price a stock has traded at throughout the day, **weighted by volume**. It resets at the start of each trading session.

### Formula

```
VWAP = Cumulative(Price × Volume) / Cumulative(Volume)
```

### Interpretation

| Condition | Meaning |
|-----------|---------|
| Price **above VWAP** | Bullish intraday bias — buyers in control |
| Price **below VWAP** | Bearish intraday bias — sellers in control |
| Price **approaching VWAP from above** | Potential support zone |
| Price **approaching VWAP from below** | Potential resistance zone |

### Use Cases

| Use Case | How |
|----------|-----|
| **Institutional benchmark** | Institutions use VWAP to assess execution quality — price clusters around it |
| **Intraday bias filter** | Only take long trades when price is above VWAP |
| **Mean reversion entry** | Buy pullbacks to VWAP in a trending market |
| **Momentum breakout** | A strong close above VWAP after opening below it signals bullish momentum |

```python
df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
df["tp_vol"]        = df["typical_price"] * df["volume"]
df["vwap"]          = df["tp_vol"].cumsum() / df["volume"].cumsum()

above_vwap = df["close"].iloc[-1] > df["vwap"].iloc[-1]
```

> **Important:** VWAP is an **intraday indicator** — it should be recalculated from the session open each day. It is less meaningful on daily/weekly charts.

---

## 14. OBV — On-Balance Volume

**OBV** adds volume on up-days and subtracts volume on down-days to create a running total. It shows whether **volume is flowing into or out of a stock**.

### Formula

```
If Close > Prev Close:  OBV = OBV(prev) + Volume
If Close < Prev Close:  OBV = OBV(prev) - Volume
If Close = Prev Close:  OBV = OBV(prev)
```

### Use Cases

| Use Case | How |
|----------|-----|
| **Confirm breakouts** | Price breaks resistance AND OBV makes a new high → high-conviction breakout |
| **Divergence** | Price makes new high but OBV doesn't → distribution (smart money selling into rally) |
| **Trend confirmation** | Rising OBV in an uptrend confirms institutional accumulation |
| **Reversal warning** | Falling OBV while price stays flat → hidden selling pressure |

```python
direction = df["close"].diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
df["obv"] = (direction * df["volume"]).cumsum()

# Divergence: price at new high but OBV is not
price_new_high = df["close"].iloc[-1] == df["close"].rolling(20).max().iloc[-1]
obv_new_high   = df["obv"].iloc[-1] == df["obv"].rolling(20).max().iloc[-1]
bearish_divergence = price_new_high and not obv_new_high
```

---

## 15. Fibonacci Retracement

**Fibonacci Retracement** identifies potential **support and resistance levels** by applying Fibonacci ratios to a prior price swing (high to low or low to high).

### Key Levels

| Level | Significance |
|-------|-------------|
| **23.6%** | Shallow retracement — strong trend momentum |
| **38.2%** | Common first bounce zone in uptrends |
| **50.0%** | Psychological midpoint — widely watched |
| **61.8%** | "Golden ratio" — strongest retracement level |
| **78.6%** | Deep retracement — trend may be weakening |

### Use Cases

| Use Case | How |
|----------|-----|
| **Entry on pullback** | After an uptrend, buy when price pulls back to the 38.2% or 61.8% level |
| **Stop placement** | Place stop just below the 61.8% level (if it breaks, the trend is likely over) |
| **Target projection** | Use extension levels (127.2%, 161.8%) to project where price may go after a breakout |
| **Confluence zones** | 61.8% Fib + 200 EMA + prior support = high-probability reversal zone |

```python
# Compute retracement levels from a swing high and swing low
swing_high = df["high"].rolling(50).max().iloc[-1]
swing_low  = df["low"].rolling(50).min().iloc[-1]
diff       = swing_high - swing_low

fib_levels = {
    "23.6%": swing_high - diff * 0.236,
    "38.2%": swing_high - diff * 0.382,
    "50.0%": swing_high - diff * 0.500,
    "61.8%": swing_high - diff * 0.618,
    "78.6%": swing_high - diff * 0.786,
}

# Check if current price is near the 61.8% level
near_golden_ratio = abs(df["close"].iloc[-1] - fib_levels["61.8%"]) / fib_levels["61.8%"] < 0.005
```

---

## 16. Ichimoku Cloud

The **Ichimoku Cloud** (Ichimoku Kinko Hyo) is an all-in-one trend system that shows support/resistance, trend direction, and momentum in a single view.

### Components

| Component | Formula | Interpretation |
|-----------|---------|----------------|
| **Tenkan-sen** (Conversion) | `(9-high + 9-low) / 2` | Short-term trend |
| **Kijun-sen** (Base) | `(26-high + 26-low) / 2` | Medium-term trend, key support/resistance |
| **Senkou Span A** | `(Tenkan + Kijun) / 2`, plotted 26 bars ahead | Leading cloud edge |
| **Senkou Span B** | `(52-high + 52-low) / 2`, plotted 26 bars ahead | Leading cloud edge |
| **Chikou Span** | Current close, plotted 26 bars back | Lagging confirmation |
| **Kumo (Cloud)** | Area between Span A and Span B | Support/resistance zone |

### Use Cases

| Use Case | How |
|----------|-----|
| **Trend filter** | Price above cloud = bullish; below cloud = bearish; inside cloud = neutral |
| **Entry signal** | Tenkan crosses above Kijun while price is above the cloud → buy |
| **Support/Resistance** | Cloud provides a dynamic S/R zone; thicker cloud = stronger S/R |
| **Momentum confirmation** | Chikou Span above price from 26 bars ago confirms bullish momentum |

```python
high, low = df["high"], df["low"]

tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
span_a   = ((tenkan + kijun) / 2).shift(26)
span_b   = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)

price_above_cloud = df["close"].iloc[-1] > max(span_a.iloc[-1], span_b.iloc[-1])
tk_cross_bullish  = (tenkan.iloc[-2] < kijun.iloc[-2]) and (tenkan.iloc[-1] > kijun.iloc[-1])
```

---

## 17. Parabolic SAR

**Parabolic SAR** (Stop and Reverse) places dots above or below price to indicate trend direction and acts as a **trailing stop**.

### Interpretation

| Position | Meaning |
|----------|---------|
| Dots **below** price | Uptrend — SAR acts as rising support |
| Dots **above** price | Downtrend — SAR acts as falling resistance |
| Price crosses SAR | Trend reversal signal — flip position |

### Use Cases

| Use Case | How |
|----------|-----|
| **Trailing stop** | Move stop-loss to the SAR value each bar to lock in profits |
| **Trend direction filter** | Only take long entries when SAR is below price |
| **Exit signal** | Close long when price crosses below SAR |
| **Whipsaw warning** | Avoid using in sideways markets — SAR flips rapidly and generates false signals |

```python
# Using ta-lib for Parabolic SAR
import talib
sar = talib.SAR(df["high"].values, df["low"].values, acceleration=0.02, maximum=0.2)

in_uptrend_sar = df["close"].iloc[-1] > sar[-1]
trailing_stop  = sar[-1]  # place stop here
```

---

## 18. CCI — Commodity Channel Index

**CCI** measures how far price has deviated from its statistical mean, identifying **overbought/oversold conditions and cyclical turning points**.

### Formula

```
Typical Price (TP)  = (High + Low + Close) / 3
CCI = (TP - SMA(TP, 20)) / (0.015 × Mean Absolute Deviation)
```

### Interpretation

| CCI Value | Interpretation |
|-----------|---------------|
| **> +100** | Overbought — potential reversal or continuation of strong uptrend |
| **−100 to +100** | Neutral — no extreme |
| **< −100** | Oversold — potential reversal or continuation of strong downtrend |

### Use Cases

| Use Case | How |
|----------|-----|
| **Overbought/oversold** | Buy when CCI crosses back above −100; sell when it crosses back below +100 |
| **Trend confirmation** | CCI staying above +100 for multiple bars signals a strong uptrend |
| **Divergence** | Price makes new high but CCI makes lower high → bearish divergence |
| **Zero-line cross** | CCI crossing above 0 from below → bullish momentum shift |

---

## 19. Williams %R

**Williams %R** is nearly identical to the Stochastic %K but **inverted** — it measures where price is relative to its recent high, making it fast and sensitive.

### Formula

```
%R = (Highest High − Close) / (Highest High − Lowest Low) × −100
```

### Interpretation

| Value | Interpretation |
|-------|---------------|
| **−0 to −20** | Overbought |
| **−20 to −80** | Neutral |
| **−80 to −100** | Oversold |

### Use Cases

| Use Case | How |
|----------|-----|
| **Fast reversal detection** | Buy when %R crosses above −80; sell when it crosses below −20 |
| **Momentum confirmation** | %R staying near 0 in a rally = strong momentum |
| **Divergence** | Price falls to new low but %R doesn't reach −100 → bullish divergence |
| **Pair with slower indicators** | Use Williams %R for timing, ADX for confirming trend strength |

---

## 20. Chart Patterns

Chart patterns are recurring price formations that signal probable future direction. They are broadly split into **continuation** (trend resumes) and **reversal** (trend changes) patterns.

---

### 20.1 Head and Shoulders (Reversal)

A **bearish reversal** pattern with three peaks: left shoulder, head (highest), right shoulder. The **neckline** (support connecting the two troughs) is the key level.

```
       Head
      /    \
L.S /      \ R.S
   /        \
──────────────  ← Neckline
```

| Signal | Condition |
|--------|-----------|
| **Bearish** | Price breaks **below** the neckline after forming the right shoulder |
| **Target** | Measure head-to-neckline distance, project it downward from breakout |

**Inverse Head and Shoulders** = same pattern flipped = bullish reversal.

---

### 20.2 Double Top / Double Bottom (Reversal)

**Double Top** — price tests the same resistance level twice, fails both times → bearish reversal.  
**Double Bottom** — price tests the same support level twice, bounces both times → bullish reversal.

| Pattern | Entry | Stop | Target |
|---------|-------|------|--------|
| Double Top | Break below the trough between the two peaks | Above the second peak | Measure peak-to-trough height, project down |
| Double Bottom | Break above the peak between the two troughs | Below the second bottom | Measure trough-to-peak height, project up |

---

### 20.3 Cup and Handle (Continuation)

A **bullish continuation** pattern shaped like a teacup. A rounded recovery (the cup) is followed by a small consolidation pullback (the handle) before a breakout.

| Stage | Description |
|-------|-------------|
| **Cup** | Gradual U-shaped decline and recovery back to the prior high |
| **Handle** | Small, tight downward drift (<15% of cup depth) |
| **Breakout** | Price clears the rim of the cup on high volume → buy |

**Target** = depth of the cup added to the breakout price.

---

### 20.4 Triangle Patterns (Continuation / Reversal)

| Type | Shape | Bias |
|------|-------|------|
| **Ascending Triangle** | Flat top, rising lower trendline | Bullish breakout expected above flat top |
| **Descending Triangle** | Flat bottom, falling upper trendline | Bearish breakdown expected below flat bottom |
| **Symmetrical Triangle** | Converging trendlines (neither flat) | Neutral — breakout direction follows prior trend |

**Entry:** On close outside the triangle boundary.  
**Target:** Height of the widest part of the triangle, projected from the breakout point.

---

### 20.5 Flag and Pennant (Continuation)

Short-term consolidation patterns that form after a sharp price move (the **flagpole**), signaling the trend is pausing before continuing.

| Pattern | Shape | Entry |
|---------|-------|-------|
| **Flag** | Small rectangular channel counter to the trend | Breakout of the channel in the trend direction |
| **Pennant** | Small symmetrical triangle after the flagpole | Breakout above the converging trendlines |

**Target:** Length of the flagpole added to the breakout point.

---

### 20.6 Wedge Patterns

| Type | Shape | Signal |
|------|-------|--------|
| **Rising Wedge** | Both trendlines slope upward, converging | Bearish reversal — break below lower trendline |
| **Falling Wedge** | Both trendlines slope downward, converging | Bullish reversal — break above upper trendline |

Rising wedges are bearish even in uptrends (losing momentum); falling wedges are bullish even in downtrends (selling pressure exhausting).

---

### 20.7 Key Candlestick Patterns

| Pattern | Type | Signal |
|---------|------|--------|
| **Doji** | Single bar | Indecision — buyers and sellers equal; watch for follow-through |
| **Hammer** | Single bar | Bullish reversal — long lower wick, small body at the top |
| **Shooting Star** | Single bar | Bearish reversal — long upper wick, small body at the bottom |
| **Bullish Engulfing** | Two bars | Bullish reversal — second bar completely engulfs prior red bar |
| **Bearish Engulfing** | Two bars | Bearish reversal — second bar completely engulfs prior green bar |
| **Morning Star** | Three bars | Bullish reversal — large down bar, small indecision bar, large up bar |
| **Evening Star** | Three bars | Bearish reversal — large up bar, small indecision bar, large down bar |
| **Three White Soldiers** | Three bars | Strong bullish continuation — three consecutive large green bars |
| **Three Black Crows** | Three bars | Strong bearish continuation — three consecutive large red bars |

> **Important:** Candlestick patterns are most reliable when they form at **key S/R levels** and are **confirmed by volume** or a secondary indicator (RSI, MACD).

---

## 21. Indicator Combinations — Common Strategies

| Strategy | Indicators Used | Logic Summary |
|----------|----------------|---------------|
| **RSI + MACD** (base strategy) | RSI, MACD, MA stack | RSI oversold bounce + MACD golden cross in uptrend |
| **Trend + Momentum** | ADX, EMA crossover, RSI | ADX > 25, EMA cross, RSI not overbought |
| **Breakout** | ATR, Bollinger Bands, OBV | Band squeeze breaks, confirmed by volume surge |
| **Mean Reversion** | Bollinger Bands, RSI, Stochastic | Price at lower band + RSI < 30 + Stoch oversold |
| **Intraday Scalp** | VWAP, EMA 9/21, Williams %R | Price reclaims VWAP + EMA cross + %R exits oversold |
| **Multi-Timeframe** | Ichimoku (daily) + RSI/MACD (hourly) | Daily cloud bullish, hourly TK cross + RSI signal |

