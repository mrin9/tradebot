<template>
  <div class="analysis-chart-container" :class="{ 'is-fullscreen': isFullscreen }">
    <div class="chart-header">
      <div class="header-left">
        <Button :label="isAnnotationsVisible ? 'Hide Trades' : 'Show Trades'"
          :icon="isAnnotationsVisible ? 'pi pi-eye-slash' : 'pi pi-eye'" @click="toggleAnnotations" text />
        <Button :label="isIndicatorsVisible ? 'Hide Indicators' : 'Show Indicators'"
          :icon="isIndicatorsVisible ? 'pi pi-eye-slash' : 'pi pi-eye'" @click="toggleIndicators" text />
      </div>
      <div class="header-right">
        <Button :label="expandedPane === 'primary' ? 'Show Both' : 'Expand NIFTY'"
          :icon="expandedPane === 'primary' ? 'pi pi-clone' : 'pi pi-window-maximize'" @click="toggleExpand('primary')"
          text />
        <Button :label="expandedPane === 'secondary' ? 'Show Both' : 'Expand Option'"
          :icon="expandedPane === 'secondary' ? 'pi pi-clone' : 'pi pi-window-maximize'"
          @click="toggleExpand('secondary')" text />
        <Button :icon="isFullscreen ? 'pi pi-window-minimize' : 'pi pi-expand'" @click="toggleFullscreen" text />
      </div>
    </div>

    <div class="charts-wrapper" ref="wrapperRef">
      <!-- Nifty Chart (Primary) -->
      <div class="chart-pane primary-pane" v-show="expandedPane === 'both' || expandedPane === 'primary'">
        <div ref="primaryRef" class="chart-viewport"></div>
      </div>

      <!-- Option Chart (Secondary) -->
      <div class="chart-pane secondary-pane" v-show="expandedPane === 'both' || expandedPane === 'secondary'">
        <div ref="secondaryRef" class="chart-viewport"></div>
      </div>
    </div>

    <div v-if="loading" class="chart-overlay">
      <i class="pi pi-spin pi-spinner" style="font-size: 2rem"></i>
      <span>Loading Chart Data...</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue';
import { init, dispose } from 'klinecharts';
import Button from 'primevue/button';

const props = defineProps({
  primaryId: [Number, String],
  secondaryId: [Number, String],
  timeframe: { type: String, default: '1m' },
  indicators: { type: Array, default: () => [] },
  markers: { type: Array, default: () => [] },
  levels: { type: Array, default: () => [] },
  primarySymbol: { type: String, default: 'NIFTY' },
  secondarySymbol: { type: String, default: 'OPTION' },
  maxTimestamp: { type: Number, default: null }
});

const primaryRef = ref(null);
const secondaryRef = ref(null);
const primaryChart = ref(null);
const secondaryChart = ref(null);
const isFullscreen = ref(false);
const expandedPane = ref('both'); // 'both' | 'primary' | 'secondary'
const isAnnotationsVisible = ref(true);
const isIndicatorsVisible = ref(true);
const loading = ref(false);
const loadingMore = ref({ primary: false, secondary: false });
const hasMoreData = ref({ primary: true, secondary: true });
const lastProcessedTimestamp = ref({ primary: null, secondary: null });
const appliedIndicatorNames = ref([]);

const toggleFullscreen = () => {
  isFullscreen.value = !isFullscreen.value;
};

const toggleExpand = (pane) => {
  if (expandedPane.value === pane) {
    expandedPane.value = 'both';
  } else {
    expandedPane.value = pane;
  }
};
const toggleAnnotations = () => {
  if (!primaryChart.value || !secondaryChart.value) return;
  if (isAnnotationsVisible.value) {
    removeAnnotations();
  } else {
    applyAnnotations();
  }
};

const toggleIndicators = () => {
  if (!primaryChart.value || !secondaryChart.value) return;
  if (isIndicatorsVisible.value) {
    removeIndicators();
  } else {
    applyIndicators();
  }
};


const fetchChartData = async (id, timeframe, endTime = null) => {
  if (!id) return { ticks: [], hasMoreOld: false, hasMoreNew: false };
  try {
    let url = `/api/ticks?id=${id}&candle-interval=${timeframe}&limit=1000`;
    if (endTime) {
      const isoStr = new Date(endTime * 1000).toISOString();
      url += `&end-dt=${isoStr}`;
    }
    const res = await fetch(url);
    const result = await res.json();

    // Support both old array-style and new object-style (fallback for safety)
    const rawTicks = Array.isArray(result) ? result : result.ticks;
    const hasMoreOld = result.hasMoreOld ?? (rawTicks.length >= 1000);
    const hasMoreNew = result.hasMoreNew ?? false;

    return {
      ticks: rawTicks.map(d => ({
        timestamp: d.t * 1000,
        open: d.o,
        high: d.h,
        low: d.l,
        close: d.c,
        volume: d.v || 0
      })),
      hasMoreOld,
      hasMoreNew
    };
  } catch (err) {
    console.error('Data Fetch Error:', err);
    return { ticks: [], hasMoreOld: false, hasMoreNew: false };
  }
};

const getMarkerColor = (type) => {
  switch (type) {
    case 'ENTRY': return getComputedStyle(document.documentElement).getPropertyValue('--color-profit').trim() || '#10b981';
    case 'EXIT': return getComputedStyle(document.documentElement).getPropertyValue('--color-loss').trim() || '#ef4444';
    case 'TARGET': return '#f59e0b'; // Orange
    default: return '#8b5cf6';       // Purple (BE)
  }
};

const applyIndicators = () => {
  if (!primaryChart.value || !secondaryChart.value) return;

  // Clear all previously applied indicators
  appliedIndicatorNames.value.forEach(name => {
    primaryChart.value.removeIndicator('candle_pane', name);
    secondaryChart.value.removeIndicator('candle_pane', name);
  });
  appliedIndicatorNames.value = [];

  // Filter indicators: Only allow trend indicators (EMA, SMA, etc.) on Compare page
  // Exclude RSI and VOL as per user request
  const filtered = props.indicators.filter(ind => !['RSI', 'VOL'].includes(ind.name));

  filtered.forEach(ind => {
    primaryChart.value.createIndicator(ind, true, { id: 'candle_pane' });
    secondaryChart.value.createIndicator(ind, true, { id: 'candle_pane' });
    appliedIndicatorNames.value.push(ind.name);
  });
  isIndicatorsVisible.value = true;
};

const removeIndicators = () => {
  if (!primaryChart.value || !secondaryChart.value) return;
  appliedIndicatorNames.value.forEach(name => {
    primaryChart.value.removeIndicator('candle_pane', name);
    secondaryChart.value.removeIndicator('candle_pane', name);
  });
  appliedIndicatorNames.value = [];
  isIndicatorsVisible.value = false;
};

const applyAnnotations = () => {
  if (!primaryChart.value || !secondaryChart.value) return;
  // Clear previous overlays of this type
  primaryChart.value.removeOverlay({ name: 'simpleAnnotation' });
  secondaryChart.value.removeOverlay({ name: 'simpleAnnotation' });

  props.markers.forEach((m) => {
    const markerColor = getMarkerColor(m.type);

    // Nifty Chart (Primary) -> Instrument Price (OptionPrice)
    let niftyLabel = `${m.optionPrice?.toFixed(1) || '0.0'}`;

    // Instrument Chart (Secondary) -> PnL (or Instrument Price for Entry)
    let optionLabel = '';
    if (m.type === 'ENTRY') {
      optionLabel = `${m.optionPrice?.toFixed(1) || '0.0'}`;
    } else {
      optionLabel = `${m.pnl?.toFixed(1) || '0.0'}`;
    }

    if (m.type === 'EXIT' && m.exitReason) {
      niftyLabel += ` ${m.exitReason}`;
      optionLabel += ` ${m.exitReason}`;
    }

    // Apply to Nifty Chart (Only if niftyPrice is valid)
    if (m.niftyPrice && m.niftyPrice > 0) {
      primaryChart.value.createOverlay({
        name: 'simpleAnnotation',
        id: `prim-${m.id}`,
        extendData: niftyLabel,
        points: [{ timestamp: (m.time * 1000), value: m.niftyPrice }],
        styles: {
          text: { color: '#ffffff', backgroundColor: markerColor, size: 11 },
          polygon: { color: markerColor, fill: true },
          line: { color: markerColor, style: 'solid' }
        }
      });
    }

    // Apply to Instrument Chart
    secondaryChart.value.createOverlay({
      name: 'simpleAnnotation',
      id: `sec-${m.id}`,
      extendData: optionLabel,
      points: [{ timestamp: (m.time * 1000), value: m.optionPrice }],
      styles: {
        text: { color: '#ffffff', backgroundColor: markerColor, size: 11 },
        polygon: { color: markerColor, fill: true },
        line: { color: markerColor, style: 'solid' }
      }
    });
  });
  isAnnotationsVisible.value = true;
};

const removeAnnotations = () => {
  primaryChart.value.removeOverlay({ name: 'simpleAnnotation' });
  secondaryChart.value.removeOverlay({ name: 'simpleAnnotation' });
  isAnnotationsVisible.value = false;
};

const loadMore = async (chart, id, type) => {
  if (loadingMore.value[type] || !hasMoreData.value[type]) return;

  const dataList = chart.getDataList();
  if (!dataList.length) return;

  const earliestTimestamp = dataList[0].timestamp;

  // Throttle: don't request again for the same boundary timestamp
  if (lastProcessedTimestamp.value[type] === earliestTimestamp) return;
  lastProcessedTimestamp.value[type] = earliestTimestamp;

  loadingMore.value[type] = true;
  try {
    const result = await fetchChartData(id, props.timeframe, (earliestTimestamp / 1000) - 1);

    if (result.ticks.length) {
      const lastNewTs = result.ticks[result.ticks.length - 1].timestamp;

      if (lastNewTs < earliestTimestamp) {
        chart.applyMoreData(result.ticks);
      }
      hasMoreData.value[type] = result.hasMoreOld;
    } else {
      hasMoreData.value[type] = false;
    }
  } catch (err) {
    console.error(`[loadMore] ${type} error:`, err);
  } finally {
    loadingMore.value[type] = false;
  }
};

const initCharts = async () => {
  if (!primaryRef.value || !secondaryRef.value) return;

  loading.value = true;
  try {
    const isDark = document.documentElement.classList.contains('dark-mode');

    // Initialize Primary
    primaryChart.value = init(primaryRef.value);
    if (primaryChart.value) {
      primaryChart.value.setTimezone('Asia/Kolkata');
      primaryChart.value.setStyles(isDark ? 'dark' : 'light');
      // primaryChart.value.setStyles({ yAxis: { size: 80 } });
      primaryChart.value.setStyles({
        yAxis: {
          size: 80,
          gap: {
            top: 0.5,
            bottom: 0.3
          }
        }
      });

      primaryChart.value.setStyles({
        candle: {
          priceMark: {
            last: { show: false },
            high: { show: false },
            low: { show: false }
          }
        }
      });
      primaryChart.value.subscribeAction('onScroll', () => {
        const range = primaryChart.value.getVisibleRange();
        if (range.from <= 0) {
          loadMore(primaryChart.value, props.primaryId, 'primary');
        }
      });
    }

    // Initialize Secondary
    secondaryChart.value = init(secondaryRef.value);
    if (secondaryChart.value) {
      secondaryChart.value.setTimezone('Asia/Kolkata');
      secondaryChart.value.setStyles(isDark ? 'dark' : 'light');
      secondaryChart.value.setStyles({
        yAxis: {
          size: 80,
          gap: {
            top: 0.5,
            bottom: 0.3
          }
        }
      });
      secondaryChart.value.setStyles({
        candle: {
          priceMark: {
            last: { show: false },
            high: { show: false },
            low: { show: false }
          }
        }
      });
      secondaryChart.value.subscribeAction('onScroll', () => {
        const range = secondaryChart.value.getVisibleRange();
        if (range.from <= 0) {
          loadMore(secondaryChart.value, props.secondaryId, 'secondary');
        }
      });
    }

    // Load Initial Data
    const [pResult, sResult] = await Promise.all([
      fetchChartData(props.primaryId, props.timeframe, props.maxTimestamp),
      fetchChartData(props.secondaryId, props.timeframe, props.maxTimestamp)
    ]);

    hasMoreData.value.primary = pResult.hasMoreOld;
    hasMoreData.value.secondary = sResult.hasMoreOld;

    if (primaryChart.value && pResult.ticks.length) primaryChart.value.applyNewData(pResult.ticks);
    if (secondaryChart.value && sResult.ticks.length) secondaryChart.value.applyNewData(sResult.ticks);

    primaryChart.value?.setBarSpace(12);
    secondaryChart.value?.setBarSpace(12);

    if (isAnnotationsVisible.value) applyAnnotations();
    if (isIndicatorsVisible.value) applyIndicators();
  } catch (err) {
    console.error('Chart Init Error:', err);
  } finally {
    loading.value = false;
  }
};

let primaryObserver = null;
let secondaryObserver = null;

onMounted(async () => {
  await initCharts();

  if (primaryRef.value) {
    primaryObserver = new ResizeObserver(() => {
      primaryChart.value?.resize();
    });
    primaryObserver.observe(primaryRef.value);
  }

  if (secondaryRef.value) {
    secondaryObserver = new ResizeObserver(() => {
      secondaryChart.value?.resize();
    });
    secondaryObserver.observe(secondaryRef.value);
  }
});

onUnmounted(() => {
  if (primaryObserver) primaryObserver.disconnect();
  if (secondaryObserver) secondaryObserver.disconnect();
  if (primaryChart.value) dispose(primaryRef.value);
  if (secondaryChart.value) dispose(secondaryRef.value);
});

watch(() => [props.primaryId, props.secondaryId, props.timeframe, props.maxTimestamp], async () => {
  loading.value = true;
  hasMoreData.value = { primary: true, secondary: true };
  lastProcessedTimestamp.value = { primary: null, secondary: null };
  const [pResult, sResult] = await Promise.all([
    fetchChartData(props.primaryId, props.timeframe, props.maxTimestamp),
    fetchChartData(props.secondaryId, props.timeframe, props.maxTimestamp)
  ]);

  hasMoreData.value.primary = pResult.hasMoreOld;
  hasMoreData.value.secondary = sResult.hasMoreOld;

  primaryChart.value?.applyNewData(pResult.ticks);
  secondaryChart.value?.applyNewData(sResult.ticks);
  if (isIndicatorsVisible.value) applyIndicators();
  if (isAnnotationsVisible.value) applyAnnotations();
  loading.value = false;
});

watch(() => props.markers, () => {
  applyAnnotations();
}, { deep: true });

watch(() => props.indicators, () => {
  if (isIndicatorsVisible.value) {
    removeIndicators();
    applyIndicators();
  }
}, { deep: true });

</script>

<style scoped>
.analysis-chart-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-card);
  border-radius: var(--card-border-radius);
  overflow: hidden;
  position: relative;
  border: 1px solid var(--layout-border);
}

.analysis-chart-container.is-fullscreen {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9999;
  border-radius: 0;
  background-color: var(--layout-bg) !important;
}

.chart-header {
  display: flex;
  padding: 0.5rem;
  justify-content: space-between;
  align-items: center;
  background: var(--surface-section);
  border-bottom: 1px solid var(--layout-border);
}

.header-left {
  display: flex;
  align-items: center;
}

.charts-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.chart-pane {
  flex: 1 1 0%;
  position: relative;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.chart-viewport {
  flex: 1;
  width: 100%;
  min-height: 0;
}

.chart-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1rem;
  z-index: 100;
  color: white;
}
</style>
