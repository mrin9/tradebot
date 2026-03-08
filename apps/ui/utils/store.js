import { reactive, computed } from 'vue';

export const backtestStore = reactive({
    backtests: [],
    selectedBacktestId: null,
    selectedBacktest: null,
    selectedTradeIndex: -1,
    selectedInstrumentId: null,
    selectedInstrumentDesc: null,
    selectedCycleId: null,
    loading: false,

    get currentTrade() {
        if (!this.selectedBacktest) return null;
        const trades = this.selectedBacktest.instrumentsTraded || this.selectedBacktest.tradeCycles || this.selectedBacktest.trades || [];

        // 1. Specific Trade/Execution View
        if (this.selectedTradeIndex !== -1) {
            return trades[this.selectedTradeIndex];
        }

        // 2. Cycle-level View (Aggregates multiple executions/chunks)
        if (this.selectedCycleId && (this.selectedInstrumentId || this.selectedInstrumentDesc)) {
            const instrId = this.selectedInstrumentId || this.selectedInstrumentDesc;
            const cycleTrades = trades.filter(t => {
                const mapInstrId = t.entry?.exchangeInstrumentId || t.entry?.symbol || t.instrumentId || t.symbol || t.entry?.description || t.entry?.instrumentDescription;
                const mapCycleId = t.cycleId || t.tradeCycle;
                return mapInstrId === instrId && mapCycleId === this.selectedCycleId;
            });

            if (cycleTrades.length > 0) {
                return {
                    instrumentId: instrId,
                    instrumentDesc: this.selectedInstrumentDesc || instrId,
                    trades: cycleTrades,
                    isCycleView: true
                };
            }
        }

        // 3. Instrument-level View (Aggregates all cycles)
        if (this.selectedInstrumentId) {
            const instrId = this.selectedInstrumentId;
            const instrumentTrades = trades.filter(t => {
                // Prefer descriptive symbol for instrumentId to help backend resolution if IDs are inconsistent
                const instrumentId = t.entry?.description || t.entry?.instrumentDescription || t.entry?.exchangeInstrumentId || t.entry?.symbol || t.instrumentId || t.symbol;
                // Note: instrMap is not defined in this snippet, assuming it's available in the actual context or needs to be handled.
                // For now, it's commented out to avoid reference errors if not present.
                // const symbol = t.entry?.description || t.entry?.instrumentDescription || instrMap[instrumentId] || t.symbol || t.instrumentDesc || t.id || 'Unknown';
                return instrumentId === instrId;
            });
            if (instrumentTrades.length === 0) return null;

            return {
                instrumentId: instrId,
                instrumentDesc: this.selectedInstrumentDesc || instrId,
                trades: instrumentTrades,
                isInstrumentView: true,
                backtestRange: {
                    start: this.selectedBacktest.startDate || this.selectedBacktest.config?.startDate,
                    end: this.selectedBacktest.endDate || this.selectedBacktest.config?.endDate
                }
            };
        }

        return null;
    },

    async fetchBacktests() {
        this.loading = true;
        try {
            const res = await fetch('/api/backtests');
            if (res.ok) {
                this.backtests = await res.json();
                // If we have backtests but none selected, select the first one if on an analysis route
                if (this.backtests.length > 0 && !this.selectedBacktestId) {
                    // Logic to handle auto-selection could go here if desired, 
                    // but usually AppShell handles it or we wait for user.
                }
            }
        } catch (e) {
            console.error('Failed to fetch backtests:', e);
        } finally {
            this.loading = false;
        }
    },

    async selectBacktest(id) {
        if (!id) {
            this.selectedBacktest = null;
            this.selectedBacktestId = null;
            this.selectedTradeIndex = -1;
            this.selectedInstrumentId = null;
            this.selectedInstrumentDesc = null;
            this.selectedCycleId = null;
            return;
        }
        this.selectedBacktestId = id;
        this.selectedInstrumentId = null;
        this.selectedInstrumentDesc = null;
        this.selectedCycleId = null;
        this.selectedTradeIndex = -1;
        this.loading = true;
        try {
            const res = await fetch(`/api/backtests/${id}`);
            if (res.ok) {
                const data = await res.json();
                if (data && Object.keys(data).length > 0) {
                    this.selectedBacktest = data;
                    // Auto-select first instrument if available
                    const trades = this.selectedBacktest.instrumentsTraded || this.selectedBacktest.tradeCycles || this.selectedBacktest.trades || [];
                    this.selectedTradeIndex = (trades.length > 0) ? 0 : -1;
                } else {
                    console.warn(`Backtest details empty for ID: ${id}`);
                    this.selectedBacktest = null;
                    this.selectedTradeIndex = -1;
                }
            }
        } catch (e) {
            console.error('Failed to fetch backtest details:', e);
            this.selectedBacktest = null;
            this.selectedTradeIndex = -1;
        } finally {
            this.loading = false;
        }
    }
});
