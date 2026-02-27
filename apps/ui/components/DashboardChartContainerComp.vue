<template>
  <div class="chart-container-wrapper">
    <div class="chart-viewport" ref="chartRef"></div>
    <div v-if="loading" class="chart-loader">
      <i class="pi pi-spin pi-spinner" style="font-size: 2rem"></i>
      <span>Loading Market Data...</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { KLineChartPro } from '@klinecharts/pro';
import '@klinecharts/pro/dist/klinecharts-pro.css';

const chartRef = ref(null);
const chartInstance = ref(null);
const selectedInstrument = ref(null);
const instruments = ref([]);
const loading = ref(false);

// Fetch available instruments
const fetchInstruments = async () => {
  try {
    console.log('Fetching instruments from /api/instruments...');
    const response = await fetch('/api/instruments');
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    console.log('Instruments fetched:', data.length);
    instruments.value = data;

    // Auto-select Nifty Index if available
    const nifty = data.find(i => i.exchangeInstrumentID === 26000);
    if (nifty) {
      selectedInstrument.value = nifty;
    }
  } catch (e) {
    console.error("Failed to fetch instruments:", e);
  }
};

onMounted(() => {
  const isDark = document.documentElement.classList.contains('dark-mode');

  const localDatafeed = {
    searchSymbols: async (search) => {
      console.log('searchSymbols called:', search);
      const query = (search || '').toLowerCase();
      return instruments.value
        .filter(i =>
          i.description.toLowerCase().includes(query) ||
          i.exchangeInstrumentID.toString().includes(query)
        )
        .map(i => {
          const strikePart = i.strikePrice ? `  ₹${i.strikePrice}` : '';
          return {
            ticker: i.exchangeInstrumentID.toString(),
            name: strikePart,
            shortName: i.description,
            exchange: '',
            pricePrecision: 2,
            volumePrecision: 0
          };
        });
    },
    getHistoryKLineData: async (symbol, period, from, to) => {
      console.log('getHistoryKLineData request:', { symbol: symbol?.ticker, period: period?.text, from, to });
      if (!symbol?.ticker || !period) {
        return [];
      }

      // Sync Vue state if native chart selection changed the instrument
      if (selectedInstrument.value?.exchangeInstrumentID.toString() !== symbol.ticker) {
        const instrument = instruments.value.find(i => i.exchangeInstrumentID.toString() === symbol.ticker);
        if (instrument) {
          console.log('Syncing selectedInstrument from native chart selection:', instrument.description);
          selectedInstrument.value = instrument;
        }
      }

      loading.value = true;
      try {
        const timespanMapping = { 'minute': 'm', 'hour': 'h', 'day': 'd' };
        const interval = `${period.multiplier}${timespanMapping[period.timespan] || 'm'}`;

        // Primary fetch with date range
        const startDt = new Date(from).toISOString();
        const endDt = new Date(to).toISOString();

        let res = await fetch(`/api/ticks?id=${symbol.ticker}&start-dt=${startDt}&end-dt=${endDt}&candle-interval=${interval}&skip-metadata=true`);
        let data = await res.json();

        // FALLBACK: If current range is empty (likely due to future clock in browser),
        // fetch the absolute latest 5000 candles from the database.
        if (data.length === 0) {
          console.log('Range empty, triggering LATEST DATA fallback for:', symbol.ticker);
          const fallbackRes = await fetch(`/api/ticks?id=${symbol.ticker}&candle-interval=${interval}&limit=5000&skip-metadata=true`);
          data = await fallbackRes.json();
        }

        return data.map(d => ({
          timestamp: d.t * 1000,
          open: d.o,
          high: d.h,
          low: d.l,
          close: d.c,
          volume: d.v || 0
        }));
      } catch (err) {
        console.error('Datafeed Error:', err);
        return [];
      } finally {
        loading.value = false;
      }
    },
    subscribe: (symbol, period, callback) => {
      console.log('Real-time subscription not implemented yet');
    },
    unsubscribe: (symbol, period) => {
      console.log('Real-time unsubscription not implemented yet');
    }
  };

  chartInstance.value = new KLineChartPro({
    container: chartRef.value,
    styles: {
      watermark: { visible: false }
    },
    timezone: 'Asia/Kolkata',
    datafeed: localDatafeed,
    locale: 'en-US',
    symbol: {
      ticker: selectedInstrument.value?.exchangeInstrumentID.toString() || '26000',
      name: (selectedInstrument.value?.description || 'NIFTY Index') + (selectedInstrument.value?.strikePrice ? `  ₹${selectedInstrument.value.strikePrice}` : ''),
      shortName: selectedInstrument.value?.description || 'NIFTY Index',
      exchange: '',
      pricePrecision: 2,
      volumePrecision: 0
    },
    period: { multiplier: 1, timespan: 'minute', text: '1m' }
  });

  // Explicitly set theme after construction to ensure Pro UI elements
  // (header, menus) sync correctly on initial load/refresh.
  try {
    chartInstance.value.setTheme(isDark ? 'dark' : 'light');
  } catch (e) {
    console.error('Initial setTheme failed:', e);
  }

  window.chartInstance = chartInstance.value;

  // Theme Sync
  const updateChartTheme = () => {
    if (!chartInstance.value) return;
    const isDark = document.documentElement.classList.contains('dark-mode');
    // KLineChartPro uses setTheme instead of setStyles for overall UI
    try {
      chartInstance.value.setTheme(isDark ? 'dark' : 'light');
    } catch (e) {
      // Fallback to base chart setStyles if setTheme fails
      chartInstance.value.setStyles(isDark ? 'dark' : 'light');
    }
  };

  const themeObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.attributeName === 'class') {
        updateChartTheme();
      }
    });
  });

  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

  onUnmounted(() => {
    themeObserver.disconnect();
    // KLineChartPro doesn't have a direct dispose on the instance sometimes,
    // but we can try to clean up if it provides a method or through container
  });

  fetchInstruments();
});
</script>

<style>
/* Base Chart Styles */
html.dark-mode .klinecharts-pro {
  background-color: transparent !important;
}

/* Force hide the bag icon/watermark logo */
[class*="watermark"],
[class*="logo"] {
  display: none !important;
}
</style>

<style scoped>
.chart-viewport {
  flex: 1;
  min-height: 600px;
  width: 100%;
}

.chart-loader {
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
  z-index: 10;
  color: white;
}
</style>
