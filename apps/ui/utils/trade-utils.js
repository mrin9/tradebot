/**
 * Common utilities for trade data processing and chart visualization
 */

/**
 * Safely parses various date formats into epoch seconds, specifically handling
 * the strict browser-specific parsing of IST strings like "10-FEB-2026 09:18".
 */
export function parseSafeTimestamp(ds) {
    if (!ds) return 0;
    if (typeof ds === 'number') return Math.floor(ds);

    // Check if it's already an ISO string
    if (ds.includes('T')) {
        return Math.floor(new Date(ds.endsWith('Z') || ds.includes('+') ? ds : ds + 'Z').getTime() / 1000);
    }

    // Format: "10-FEB-2026 09:18" (Implicitly IST / Asia/Kolkata)
    const months = { JAN: '01', FEB: '02', MAR: '03', APR: '04', MAY: '05', JUN: '06', JUL: '07', AUG: '08', SEP: '09', OCT: '10', NOV: '11', DEC: '12' };
    const parts = ds.split(' ');
    if (parts.length === 2 || parts.length === 3) {
        const dateParts = parts[0].split('-');
        if (dateParts.length === 3) {
            const timePart = parts[1].length === 5 ? parts[1] + ':00' : parts[1];
            // Format to ISO with IST offset to guarantee consistent browser parsing
            const str = `${dateParts[2]}-${months[dateParts[1].toUpperCase()]}-${dateParts[0].padStart(2, '0')}T${timePart}+05:30`;
            const ms = new Date(str).getTime();
            if (!isNaN(ms)) return Math.floor(ms / 1000);
        }
    }

    // Fallback
    const d = new Date(ds.endsWith('Z') ? ds : ds + 'Z');
    return isNaN(d) ? 0 : Math.floor(d.getTime() / 1000);
}

/**
 * Converts trade entry, exit, targets and break-even points into chart markers.
 * @param {Object} currentTrade - The selected instrument/trade data from store
 * @returns {Array} List of markers for klinecharts
 */
export function generateMarkersFromTrade(currentTrade) {
    if (!currentTrade) return [];
    const list = [];
    const cycles = currentTrade.trades || [currentTrade];

    // Grouping by cycle to avoid duplicate ENTRY markers if we are processing fragments
    const processedCycles = new Set();

    cycles.forEach((trade, index) => {
        // DETECT NEW STRUCTURE (tradeCycles)
        if (trade.entry) {
            const cycleId = trade.cycleId || `idx-${index}`;

            // 1. Entry
            if (trade.entry.time && !processedCycles.has(cycleId)) {
                const entryTime = trade.entry.epochTime || parseSafeTimestamp(trade.entry.time);
                let optionPrice = trade.entry.price || 0;
                let niftyPrice = 0;

                if (trade.entry.transaction) {
                    const niftyMatch = trade.entry.transaction.match(/NIFTY:\s*([\d.]+)/);
                    if (niftyMatch) niftyPrice = parseFloat(niftyMatch[1]);
                }
                if (!optionPrice && trade.entry.totalPrice) optionPrice = trade.entry.totalPrice / 65;

                list.push({
                    id: `entry-${cycleId}-${entryTime}`,
                    time: entryTime,
                    niftyPrice: niftyPrice,
                    optionPrice: optionPrice,
                    pnl: 0,
                    label: 'ENTRY',
                    type: 'ENTRY',
                    cycleId: cycleId
                });
                processedCycles.add(cycleId);
            }

            // 2. Targets
            Object.keys(trade).forEach(key => {
                if (key.startsWith('target')) {
                    const t = trade[key];
                    if (t && t.time) {
                        const tTime = t.epochTime || parseSafeTimestamp(t.time);
                        let tOptionPrice = t.price || 0;
                        let tNiftyPrice = 0;
                        if (t.transaction) {
                            const niftyMatch = t.transaction.match(/NIFTY:\s*([\d.]+)/);
                            if (niftyMatch) tNiftyPrice = parseFloat(niftyMatch[1]);
                        }
                        if (!tOptionPrice && t.totalPrice) tOptionPrice = t.totalPrice / 65;

                        list.push({
                            id: `${key}-${cycleId}-${tTime}`,
                            time: tTime,
                            niftyPrice: tNiftyPrice,
                            optionPrice: tOptionPrice,
                            pnl: t.actionPnL || 0,
                            label: 'TARGET',
                            type: 'TARGET',
                            cycleId: cycleId
                        });
                    }
                }
            });

            // 3. Exit
            if (trade.exit && trade.exit.time) {
                const exitTime = trade.exit.epochTime || parseSafeTimestamp(trade.exit.time);
                let optionPrice = trade.exit.price || 0;
                let niftyPrice = 0;
                if (trade.exit.transaction) {
                    const niftyMatch = trade.exit.transaction.match(/NIFTY:\s*([\d.]+)/);
                    if (niftyMatch) niftyPrice = parseFloat(niftyMatch[1]);
                }
                if (!optionPrice && trade.exit.totalPrice) optionPrice = trade.exit.totalPrice / 65;

                const isTargetExit = trade.exit.signal?.startsWith('TARGET');
                const reasonMap = {
                    'STOPLOSS': 'SL',
                    'STOP_LOSS': 'SL',
                    'TRAILING_SL': 'TSL',
                    'EOD': 'EOD',
                    'STRATEGY': 'SIG',
                    'SIGNAL_EXIT': 'SIG',
                    'SIGNAL_FLIP': 'SIG'
                };
                const shortReason = reasonMap[trade.exit.signal] || (isTargetExit ? '' : trade.exit.signal || '');

                list.push({
                    id: `exit-${cycleId}-${exitTime}`,
                    time: exitTime,
                    niftyPrice: niftyPrice,
                    optionPrice: optionPrice,
                    pnl: trade.cyclePnL || 0,
                    label: isTargetExit ? 'TARGET' : 'EXIT',
                    type: isTargetExit ? 'TARGET' : 'EXIT',
                    exitReason: shortReason,
                    cycleId: cycleId
                });
            }

            return; // Skip legacy logic for this iteration
        }

        // --- LEGACY LOGIC ---
        const cycleId = trade.tradeCycle || `idx-${index}`;
        const entryTime = parseSafeTimestamp(trade.entryTime);

        if (entryTime && !processedCycles.has(cycleId)) {
            list.push({
                id: `entry-${cycleId}-${entryTime}`,
                time: entryTime,
                niftyPrice: trade.niftyPriceAtEntry,
                optionPrice: trade.entryPrice,
                pnl: 0,
                label: 'ENTRY',
                type: 'ENTRY',
                cycleId: cycleId
            });
            processedCycles.add(cycleId);
        }

        const exitTime = parseSafeTimestamp(trade.exitTime);
        if (exitTime) {
            const isTargetExit = trade.exitReason?.startsWith('TARGET');
            const reasonMap = {
                'STOPLOSS': 'SL',
                'STOP_LOSS': 'SL',
                'TRAILING_SL': 'TSL',
                'EOD': 'EOD',
                'STRATEGY': 'SIG',
                'SIGNAL_EXIT': 'SIG',
                'SIGNAL_FLIP': 'SIG'
            };
            const shortReason = reasonMap[trade.exitReason] || (isTargetExit ? '' : trade.exitReason || '');

            list.push({
                id: `exit-${index}-${exitTime}`,
                time: exitTime,
                niftyPrice: trade.niftyPriceAtExit || 0,
                optionPrice: trade.exitPrice,
                pnl: trade.pnl || 0,
                label: isTargetExit ? 'TARGET' : 'EXIT',
                type: isTargetExit ? 'TARGET' : 'EXIT',
                exitReason: shortReason,
                cycleId: cycleId
            });
        }

        // Add targets only if they are not already listed as exits (backup for legacy data)
        if (trade.targets && !trade.exitReason?.startsWith('TARGET')) {
            trade.targets.forEach((t, tIdx) => {
                list.push({
                    id: `target-${index}-${tIdx}-${t.time}`,
                    time: t.time,
                    niftyPrice: t.niftyPrice || trade.niftyPriceAtExit || trade.niftyPriceAtEntry,
                    optionPrice: t.fillPrice,
                    pnl: t.pnl || 0,
                    label: 'TARGET',
                    type: 'TARGET',
                    cycleId: cycleId
                });
            });
        }

        // Add BE nifty if available
        const beTime = parseSafeTimestamp(trade.breakEvenTime);
        if (trade.breakEvenNifty) {
            list.push({
                id: `be-${cycleId}-${beTime || entryTime}`,
                time: beTime || entryTime,
                niftyPrice: trade.breakEvenNifty,
                optionPrice: trade.breakEvenPrice || trade.entryPrice,
                label: 'BE',
                type: 'BE',
                cycleId: cycleId
            });
        }
    });

    // Special Requirement: Only the LAST marker of each trade cycle should have the exitReason suffix
    const lastMarkerMap = {}; // cycleId -> last marker index
    list.forEach((m, idx) => {
        if (!m.cycleId) return;
        if (m.type === 'ENTRY' || m.type === 'BE') return; // Suffix only for EXIT/TARGET

        const prevIdx = lastMarkerMap[m.cycleId];
        if (prevIdx === undefined || m.time > list[prevIdx].time) {
            lastMarkerMap[m.cycleId] = idx;
        }
    });

    // Clear suffixes from all but the last marker
    list.forEach((m, idx) => {
        if (m.type === 'ENTRY' || m.type === 'BE') return;
        if (lastMarkerMap[m.cycleId] !== idx) {
            m.exitReason = '';
        }
    });

    return list;
}

/**
 * Parses a trade cycle to generate horizontal price levels (Entry, SL, BE).
 * @param {Object} currentTrade - The selected instrument/trade data
 * @returns {Array} List of price levels { price, label, color }
 */
export function parseTradeCycle(currentTrade) {
    if (!currentTrade) return [];

    const list = [];
    const cycles = currentTrade.trades || [currentTrade];

    cycles.forEach(trade => {
        // DETECT NEW STRUCTURE
        if (trade.entry) {
            let entryPrice = trade.entry.price || 0;
            if (!entryPrice && trade.entry.transaction) {
                const priceMatch = trade.entry.transaction.match(/at\s+([\d.]+)/);
                if (priceMatch) entryPrice = parseFloat(priceMatch[1]);
            }
            if (!entryPrice && trade.entry.totalPrice) entryPrice = trade.entry.totalPrice / 65;
            if (entryPrice) {
                list.push({ price: entryPrice, label: 'Entry Price', color: '#3b82f6' });
            }
            // new schema doesn't explicitly log BE or SL triggers as horizontal lines yet 
            // but we can add them later if they are in the JSON.
            return;
        }

        // LEGACY LOGIC
        if (trade.entryPrice) {
            list.push({ price: trade.entryPrice, label: 'Entry Price', color: '#3b82f6' });
        }

        if (trade.breakEvenTriggered || trade.breakEvenPrice) {
            list.push({ price: trade.breakEvenPrice, label: 'BE', color: '#10b981' });
        }

        if (trade.stopLossPrice) {
            list.push({ price: trade.stopLossPrice, label: 'SL', color: '#ef4444' });
        }
    });

    return list;
}

/**
 * Formats candle timeframe seconds into a readable string (e.g., "1m", "30s").
 * @param {number} sec - Timeframe in seconds
 * @returns {string}
 */
export function formatTimeframe(sec) {
    if (!sec) return '1m';
    return sec < 60 ? `${sec}s` : `${sec / 60}m`;
}

/**
 * Calculates the maximum timestamp for chart data based on the last exit time plus some buffer.
 * @param {Object} currentTrade - The selected instrument/trade data
 * @returns {number|null} Max timestamp in seconds
 */
export function GetMaxTimestampOfTrade(currentTrade) {
    if (!currentTrade) return null;

    const cycles = currentTrade.trades || [currentTrade];
    if (!cycles.length) return null;

    let lastExit = 0;
    cycles.forEach(trade => {
        let tradeExitTime;
        if (trade.exit && trade.exit.time) {
            tradeExitTime = trade.exit.time;
        } else if (trade.exitTime) {
            tradeExitTime = trade.exitTime;
        }

        const exitTime = parseSafeTimestamp(tradeExitTime);
        if (exitTime && exitTime > lastExit) {
            lastExit = exitTime;
        }
    });

    if (lastExit === 0) return null;

    // Add 1 hour buffer (3600 seconds)
    return lastExit + 3600;
}

/**
 * Extracts indicator definitions from backtest configuration.
 * @param {Object} config - Backtest config object
 * @returns {Array} List of indicator definitions
 */
export function getIndicatorsFromConfig(config) {
    if (!config) {
        return [{ name: 'EMA', calcParams: [5, 21] }]; // Default fallback
    }

    // New path: structured overlays (dynamic_strategy and future strategies)
    if (config.indicatorOverlays?.length) {
        return config.indicatorOverlays;
    }

    // Legacy path: flat strategyParams (crossover_and_rsi, crossover_and_strend)
    if (!config.strategyParams) {
        return [{ name: 'EMA', calcParams: [5, 21] }];
    }

    const params = config.strategyParams;
    const indicators = [];

    // Combine fast and slow into one MA/EMA indicator if they are the same type
    if (params.fastType === params.slowType && params.fastPeriod && params.slowPeriod) {
        indicators.push({
            name: params.fastType.toUpperCase(),
            calcParams: [params.fastPeriod, params.slowPeriod]
        });
    } else {
        if (params.fastType && params.fastPeriod) {
            indicators.push({ name: params.fastType.toUpperCase(), calcParams: [params.fastPeriod] });
        }
        if (params.slowType && params.slowPeriod) {
            indicators.push({ name: params.slowType.toUpperCase(), calcParams: [params.slowPeriod] });
        }
    }

    // Add RSI if present in config
    if (params.rsiPeriod) {
        indicators.push({ name: 'RSI', calcParams: [params.rsiPeriod] });
    }

    return indicators;
}
