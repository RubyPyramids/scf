# SCF Feature Formulas (exact math)

Time base: recompute features every 5–10s. Use sliding windows; align on block time.

## Volatility Compression (VC)
- ATR%_W = EMA over window W of true range as a percentage of price.
  TR_t = max( high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}| )
  ATR_W = EMA(TR_t, W)
  ATR%_W = ATR_W / EMA(close_t, W)

- vc_ratio = ATR%_15m / ATR%_24h  (use bar-aggregated swaps to form OHLC)
- sigma15 = std(returns over 15m)
- intertrade_ms_slope = slope(EMA(Δms between swaps), 15m)

Condition: vc_ratio ≤ θ_vc and intertrade_ms_slope > 0 and sigma15 decreasing.

## Order-Flow Stillness (OFS)
- CVD_t = CVD_{t-1} + (quote_amt if taker buy else -quote_amt)
- cvd_slope_1h = slope(CVD over last 60m); take absolute value for stillness.
- swap_size_cv_15m = std(swap_size)/mean(swap_size) over 15m
- alternation_idx_15m = (# of sign changes between consecutive swaps) / (count-1)

Condition: |cvd_slope_1h| in bottom decile ≤ θ_ofs; swap_size_cv_15m ≤ θ; alternation_idx_15m ≥ θ.

## Liquidity Thinness (LT) without fragility
For AMM with reserves (x, y), fee f, price p = y/x.
Move price by +1% via Δx. Solve the constant-product including fee to approximate cost.
Compute depth_1p0 as notional in SOL required. Repeat along a small ladder to derive continuity:

depth_continuity = mean( min( depth_{step i}, depth_{step i+1} ) / max( depth_{step i}, depth_{step i+1} ) )

We require: depth_1p0 ≤ θ_lt and depth_continuity ≥ θ_cont and lp_top10_share ≤ θ_lp.

## Wallet Convergence (WC)
- Wallet Quality Score QS ∈ [0,1]: 0.28 P + 0.18 R + 0.18 E + 0.14 H + 0.12 C − 0.10 B (clipped)
- arrivals/min A: count of first-buys with QS ≥ θ_qs in sliding 10–15m window / minutes
- Gini-directionality ΔG: compute Gini of net inflow across top-N NEW buyers; require ΔG negative over window (distribution broadening)
- Cohort Jaccard J: overlap between set of new QS≥θ wallets and prior-winners set W*

Boolean:  A ≥ 3/min ∧ ΔG ≤ −0.05 ∧ J ≥ 0.12 ∧ whale_share ≤ 0.25
Score:    0.45·min(1,A/5) + 0.25·min(1,(−ΔG)/0.08) + 0.30·min(1, J/0.2)

## Retail Quiet (RQ)
Without external APIs:
- watchers_proxy = (# of first-buy dust ≤ $3) + (# of read-only signers touching pool accounts)
- Condition: slope(watchers_proxy, 15–30m) > 0 AND swaps/min z-score ≤ 0.5

## Regime metrics
- regime_cr = zscore decrease of ATR%_24h and swap variance + increase of spread persistence across sector (Raydium+Orca).
- regime_td = zscore of |cvd_slope| + orderbook bid/ask skew (where available).
- regime_cp = rolling EV of anchor cohort actions over last N impulses.
