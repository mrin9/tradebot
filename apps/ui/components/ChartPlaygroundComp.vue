<template>
  <div class="playground-container">
    <div class="chart-container-wrapper">
      <div ref="chartRef" class="chart-viewport"></div>
      <div v-if="loading" class="overlay">
        <i class="pi pi-spin pi-spinner text-3xl"></i>
        <p>Fetching Data...</p>
      </div>
    </div>

    <div class="button-strip">
      <Button label="Simple Annotation" @click="addSimpleAnnotation" class="p-button-outlined" />
      <Button label="Simple Tag" @click="addSimpleTag" class="p-button-outlined" />
      <Button label="Vertical Line" @click="addVerticalLine" class="p-button-outlined" />
      <Button label="Create Indicators" @click="createIndicators" class="p-button-outlined" />
      <Button label="Update Indicators" @click="updateIndicators" class="p-button-outlined" />
      <Button label="Remove Indicators" @click="removeIndicators" class="p-button-outlined" />
      <span class="button-divider"></span>
      <Button :label="macdActive ? 'Remove MACD' : 'MACD'" :icon="macdActive ? 'pi pi-times' : 'pi pi-chart-bar'"
        :severity="macdActive ? 'danger' : 'info'" @click="toggleMACD" class="p-button-outlined" />
      <Button :label="supertrendActive ? 'Remove Supertrend' : 'Supertrend'"
        :icon="supertrendActive ? 'pi pi-times' : 'pi pi-arrow-right-arrow-left'"
        :severity="supertrendActive ? 'danger' : 'success'" @click="toggleSupertrend" class="p-button-outlined" />
      <span class="button-divider"></span>
      <Button label="Clear All" icon="pi pi-trash" @click="clearOverlays" class="p-button-text p-button-danger" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import { init, dispose } from 'klinecharts';
import Button from 'primevue/button';

const chartRef = ref(null);
const chart = ref(null);
const loading = ref(false);
// const instrumentId = 42506;
const instrumentId = 26000; //NIFTY

// Toggle states for new indicators
const macdActive = ref(false);
const supertrendActive = ref(false);
const macdPaneId = ref(null);



const fetchTicks = async () => {
  loading.value = true;
  try {
    const res = await fetch(`/api/ticks?id=${instrumentId}&candle-interval=1m&limit=2000&skip-metadata=true`);
    const data = await res.json();
    return data.map(d => ({
      timestamp: d.t * 1000,
      open: d.o,
      high: d.h,
      low: d.l,
      close: d.c,
      volume: d.v || 0
    }));
  } catch (err) {
    console.error('Failed to fetch ticks:', err);
    return [];
  } finally {
    loading.value = false;
  }
};

const addSimpleAnnotation = () => {
  if (!chart.value) return;

  // Get visible range or just pick the middle point if possible
  // For simplicity, we'll pick a timestamp from the data that is likely visible
  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;

  const almostLastIndex = dataList.length - 10;
  const point = dataList[almostLastIndex];
  chart.value.createOverlay({
    name: 'simpleAnnotation',
    extendData: 'My Annotation',
    points: [{ timestamp: point.timestamp, value: point.high }],
    styles: {
      text: { color: '#ffffff', backgroundColor: 'red', size: 12, },
      polygon: { color: 'red', fill: true },
      line: { color: 'red', style: 'solid' }
    }
  });
};

const addSimpleTag = () => {
  if (!chart.value) return;
  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;

  const almostLastIndex = dataList.length - 15;
  const point = dataList[almostLastIndex];
  chart.value.createOverlay({
    name: 'simpleTag',
    extendData: 'My Tag',
    points: [{ timestamp: point.timestamp, value: point.high }],
    styles: {
      text: { color: '#ffffff', backgroundColor: 'red', size: 12, },
      polygon: { color: 'red', fill: true },
      line: { color: 'red', style: 'solid' }
    }
  });
};

const createIndicators = () => {
  if (!chart.value) return;
  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;
  chart.value.createIndicator({ name: 'EMA', calcParams: [3, 15] }, true, { id: 'candle_pane' });
};

const updateIndicators = () => {
  if (!chart.value) return;
  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;
  chart.value.overrideIndicator({
    name: 'EMA',
    calcParams: [10, 50]
  }, 'candle_pane'); // The second argument is the paneId
};

const removeIndicators = () => {
  if (!chart.value) return;
  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;
  chart.value.removeIndicator('candle_pane', 'EMA');
};

const addVerticalLine = () => {
  if (!chart.value) return;

  const dataList = chart.value.getDataList();
  if (dataList.length === 0) return;

  // Find a timestamp that is approx 9:15 AM
  // IST is UTC+5:30. 9:15 AM IST = 03:45 UTC
  // We can search for the first candle of the day if multiple days exist, or just 09:15 IST
  const targetTimestamp = dataList.find(d => {
    const date = new Date(d.timestamp);
    // Assuming IST timezone in Date object if browser is in IST, otherwise we might need adjustment
    // But the chart is set to Asia/Kolkata, so timestamps should align.
    const hours = date.getHours();
    const minutes = date.getMinutes();
    return (hours === 9 && minutes >= 15 && minutes <= 20); // First candle of market
  })?.timestamp || dataList[0].timestamp;

  chart.value.createOverlay({
    name: 'verticalStraightLine',
    points: [{ timestamp: targetTimestamp }],
    styles: {
      line: { color: '#ffffff', size: 3, style: 'solid' }
    }
  });
};

// ─────────────────────────────────────────────
// MACD toggle  (built-in klinechart indicator)
// ─────────────────────────────────────────────
const toggleMACD = () => {
  if (!chart.value) return;
  if (macdActive.value) {
    // Remove
    if (macdPaneId.value) {
      chart.value.removeIndicator(macdPaneId.value, 'MACD');
    }
    macdActive.value = false;
    macdPaneId.value = null;
  } else {
    // Create in a new sub-pane
    const paneId = chart.value.createIndicator({
      name: 'MACD',
      calcParams: [12, 26, 9]
    });
    macdPaneId.value = paneId;
    macdActive.value = true;
  }
};

// ─────────────────────────────────────────────
// Supertrend toggle  (custom registered indicator)
// ─────────────────────────────────────────────
const toggleSupertrend = () => {
  if (!chart.value) return;
  if (supertrendActive.value) {
    chart.value.removeIndicator('candle_pane', 'SUPERTREND');
    supertrendActive.value = false;
  } else {
    chart.value.createIndicator(
      { name: 'SUPERTREND', calcParams: [10, 3] },
      false,
      { id: 'candle_pane' }
    );
    supertrendActive.value = true;
  }
};

const clearOverlays = () => {
  chart.value?.removeOverlay();
  // Also remove indicator toggles
  if (macdActive.value && macdPaneId.value) {
    chart.value?.removeIndicator(macdPaneId.value, 'MACD');
    macdActive.value = false;
    macdPaneId.value = null;
  }
  if (supertrendActive.value) {
    chart.value?.removeIndicator('candle_pane', 'SUPERTREND');
    supertrendActive.value = false;
  }
};

onMounted(async () => {
  if (!chartRef.value) return;

  // Register custom indicators (Supertrend, etc.) — shared across charts
  registerCustomIndicators();

  chart.value = init(chartRef.value);
  chart.value.setTimezone('Asia/Kolkata');
  const isDark = document.documentElement.classList.contains('dark-mode');
  chart.value.setStyles(isDark ? 'dark' : 'light');
  chart.value.setStyles({
    candle: {
      priceMark: {
        last: {
          show: false // Disables the last-prace  horizontal line 
        },
        high: {
          show: false // Disables the highest price text on the candle
        },
        low: {
          show: false // Disables the lowest price text on the candle
        }
      }
    }
  });
  chart.value.createIndicator({ name: 'EMA', calcParams: [5, 21] }, true, { id: 'candle_pane' });
  const data = await fetchTicks();
  if (data.length) {
    chart.value.applyNewData(data);
  }
});

onUnmounted(() => {
  if (chart.value) {
    dispose(chartRef.value);
  }
});
</script>

<style scoped>
.playground-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-card);
  border-radius: var(--border-radius);
  border: 1px solid var(--layout-border);
  overflow: hidden;
}

.playground-header {
  padding: 1rem;
  border-bottom: 1px solid var(--layout-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.instrument-info .badge {
  background: var(--primary-color);
  color: white;
  padding: 0.25rem 0.75rem;
  border-radius: 20px;
  font-size: 0.8rem;
  font-weight: 600;
}

.chart-container-wrapper {
  flex: 1;
  position: relative;
  min-height: 0;
}

.chart-viewport {
  width: 100%;
  height: 100%;
}

.overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: white;
  z-index: 10;
}

.button-strip {
  padding: .5rem;
  border-top: 1px solid var(--layout-border);
  display: flex;
  gap: .5rem;
  justify-content: center;
  align-items: center;
  background: var(--surface-ground);
  flex-wrap: wrap;
}

.button-divider {
  width: 1px;
  height: 24px;
  background: var(--layout-border);
  margin: 0 0.25rem;
}
</style>
