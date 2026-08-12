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

