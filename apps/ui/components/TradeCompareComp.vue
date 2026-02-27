<template>
  <div class="compare-charts-wrapper">
    <template v-if="backtestStore.selectedBacktest">
      <div class="charts-container">
        <CompareChartComp :primaryId="26000" :secondaryId="currentTrade?.instrumentId" :timeframe="candleTimeframe"
          :indicators="indicators" :markers="markers" :levels="levels" :primarySymbol="'NIFTY'"
          :secondarySymbol="currentTrade?.instrumentDesc || 'Contract'" :maxTimestamp="maxTimestamp" />
      </div>
    </template>

    <div v-else class="empty-state">
      <div class="empty-content">
        <i class="pi pi-search-plus" style="font-size: 3rem; color: var(--text-secondary)"></i>
        <h2>Trade Analysis Dashboard</h2>
        <p>Please select a backtest from the top dropdown to visualize performance</p>
        <Button label="Refresh Backtests" icon="pi pi-refresh" @click="backtestStore.fetchBacktests()" class="mt-3" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';
import Button from 'primevue/button';
import CompareChartComp from './CompareChartComp.vue';
import { backtestStore } from '../lib/store';
import {
  generateMarkersFromTrade,
  parseTradeCycle,
  formatTimeframe,
  GetMaxTimestampOfTrade,
  getIndicatorsFromConfig
} from '../lib/trade-utils';

const currentTrade = computed(() => backtestStore.currentTrade);

const indicators = computed(() => {
  return getIndicatorsFromConfig(backtestStore.selectedBacktest?.config);
});

const candleTimeframe = computed(() => {
  const sec = backtestStore.selectedBacktest?.config?.candleTimeframeSeconds || 60;
  return formatTimeframe(sec);
});

const markers = computed(() => {
  return generateMarkersFromTrade(currentTrade.value);
});

const levels = computed(() => {
  if (currentTrade.value?.isInstrumentView) return [];
  return parseTradeCycle(currentTrade.value);
});

const maxTimestamp = computed(() => {
  if (!currentTrade.value) return null;
  return GetMaxTimestampOfTrade(currentTrade.value);
});
</script>

<style scoped>
.compare-charts-wrapper {
  height: calc(100vh - var(--layout-topbar-height) - 2rem);
  display: flex;
  flex-direction: column;
}

.view-actions {
  display: flex;
  justify-content: flex-end;
  padding-bottom: 0.75rem;
}

.charts-container {
  flex: 1;
  min-height: 0;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-secondary);
}

.empty-content {
  background: var(--surface-card);
  padding: 3rem;
  border-radius: 16px;
  border: 1px solid var(--layout-border);
}

.empty-content h2 {
  margin-top: 1.5rem;
  color: var(--text-color);
}

.config-display {
  background: var(--surface-ground);
  padding: 1rem;
  border-radius: 8px;
  font-family: 'Monaco', monospace;
  font-size: 0.85rem;
  max-height: 400px;
  overflow-y: auto;
}

.config-btn {
  border-width: 2px !important;
  font-weight: 700 !important;
}

pre {
  margin: 0;
}
</style>
