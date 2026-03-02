/**
 * Custom klinechart indicators — shared across chart components.
 * Call registerCustomIndicators() once before chart init.
 */
import { registerIndicator } from 'klinecharts';

let _registered = false;

/**
 * Register all custom indicators.
 * Safe to call multiple times — indicators are only registered once.
 */
export function registerCustomIndicators() {
    if (_registered) return;
    _registered = true;
    _registerSupertrend();
}

// ─────────────────────────────────────────────
// Supertrend (ATR-based trend overlay)
// ─────────────────────────────────────────────
function _registerSupertrend() {
    registerIndicator({
        name: 'SUPERTREND',
        shortName: 'ST',
        calcParams: [10, 3],   // [ATR period, multiplier]
        series: 'price',       // overlays on candle pane
        precision: 2,
        figures: [
            {
                key: 'supertrend',
                title: 'ST: ',
                type: 'line',
                styles: (data, indicator, defaultStyles) => {
                    const dir = data.current?.indicatorData?.dir;
                    if (dir === 1) {
                        return { color: '#26a69a', size: 2 };   // bullish = green
                    }
                    return { color: '#ef5350', size: 2 };      // bearish = red
                }
            }
        ],
        calc: (dataList, indicator) => {
            const params = indicator.calcParams;
            const period = params[0];
            const multiplier = params[1];
            const result = [];

            let prevClose = null;
            let atr = null;
            const trList = [];

            let prevFinalUpperBand = null;
            let prevFinalLowerBand = null;
            let prevSupertrend = null;
            let prevDir = 1;

            for (let i = 0; i < dataList.length; i++) {
                const kline = dataList[i];
                const high = kline.high;
                const low = kline.low;
                const close = kline.close;
                const item = {};

                // True Range
                let tr;
                if (prevClose === null) {
                    tr = high - low;
                } else {
                    tr = Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose));
                }
                trList.push(tr);

                if (trList.length >= period) {
                    // Calculate ATR as SMA of TR
                    if (atr === null) {
                        // First ATR = simple average of first `period` TRs
                        let sum = 0;
                        for (let j = trList.length - period; j < trList.length; j++) { sum += trList[j]; }
                        atr = sum / period;
                    } else {
                        // Smoothed ATR (Wilder's method)
                        atr = (atr * (period - 1) + tr) / period;
                    }

                    const hl2 = (high + low) / 2;
                    const basicUpperBand = hl2 + (multiplier * atr);
                    const basicLowerBand = hl2 - (multiplier * atr);

                    // Final Upper Band
                    let finalUpperBand;
                    if (prevFinalUpperBand !== null) {
                        finalUpperBand = (basicUpperBand < prevFinalUpperBand || prevClose > prevFinalUpperBand)
                            ? basicUpperBand
                            : prevFinalUpperBand;
                    } else {
                        finalUpperBand = basicUpperBand;
                    }

                    // Final Lower Band
                    let finalLowerBand;
                    if (prevFinalLowerBand !== null) {
                        finalLowerBand = (basicLowerBand > prevFinalLowerBand || prevClose < prevFinalLowerBand)
                            ? basicLowerBand
                            : prevFinalLowerBand;
                    } else {
                        finalLowerBand = basicLowerBand;
                    }

                    // Determine direction
                    let dir;
                    if (prevSupertrend === null) {
                        dir = 1;
                    } else if (prevSupertrend === prevFinalUpperBand) {
                        dir = close > finalUpperBand ? 1 : -1;
                    } else {
                        dir = close < finalLowerBand ? -1 : 1;
                    }

                    const supertrend = dir === 1 ? finalLowerBand : finalUpperBand;

                    item.supertrend = supertrend;
                    item.dir = dir;

                    prevFinalUpperBand = finalUpperBand;
                    prevFinalLowerBand = finalLowerBand;
                    prevSupertrend = supertrend;
                    prevDir = dir;
                }

                prevClose = close;
                result.push(item);
            }
            return result;
        }
    });
}
