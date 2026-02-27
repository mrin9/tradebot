<template>
    <div class="analysis-chart-container" :class="{ 'is-fullscreen': isFullscreen }">
        <div class="chart-header">
            <div class="header-left">
                <Button :label="isAnnotationsVisible ? 'Hide Trades' : 'Show Trades'"
                    :icon="isAnnotationsVisible ? 'pi pi-eye-slash' : 'pi pi-eye'" @click="toggleAnnotations" text />
                <Button :label="isIndicatorsVisible ? 'Hide Indicators' : 'Show Indicators'"
                    :icon="isIndicatorsVisible ? 'pi pi-eye-slash' : 'pi pi-eye'" @click="toggleIndicators" text />
                <Button :label="isVolumeVisible ? 'Hide Volume' : 'Show Volume'"
                    :icon="isVolumeVisible ? 'pi pi-chart-bar' : 'pi pi-chart-bar'" @click="toggleVolume" text />
                <Button :label="isRSIVisible ? 'Hide RSI' : 'Show RSI'"
                    :icon="isRSIVisible ? 'pi pi-sliders-h' : 'pi pi-sliders-h'" @click="toggleRSI" text />
                <span class="header-divider ml-2 mr-2"></span>
                <SelectButton v-model="annotationMode" :options="['Price', 'PnL']" aria-labelledby="basic"
                    class="header-toggle" />
            </div>
            <div class="header-right">
                <Button :icon="isFullscreen ? 'pi pi-window-minimize' : 'pi pi-expand'" @click="toggleFullscreen"
                    text />
            </div>
        </div>

        <div class="charts-wrapper" ref="wrapperRef">
            <div class="chart-pane">
                <div ref="chartRef" class="chart-viewport"></div>
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
import SelectButton from 'primevue/selectbutton';

const props = defineProps({
    instrumentId: [Number, String],
    timeframe: { type: String, default: '1m' },
    indicators: { type: Array, default: () => [] },
    markers: { type: Array, default: () => [] },
    levels: { type: Array, default: () => [] },
    symbol: { type: String, default: 'Instrument' },
    maxTimestamp: { type: Number, default: null }
});

const chartRef = ref(null);
const chartInstance = ref(null);
const isFullscreen = ref(false);
const isAnnotationsVisible = ref(true);
const isIndicatorsVisible = ref(true);
const isVolumeVisible = ref(true);
const isRSIVisible = ref(false);
const loading = ref(false);
const loadingMore = ref(false);
const hasMoreData = ref(true);
const lastProcessedTimestamp = ref(null);
const appliedIndicatorNames = ref([]);
const annotationMode = ref('PnL');

const toggleFullscreen = () => {
    isFullscreen.value = !isFullscreen.value;
};

const toggleAnnotations = () => {
    if (!chartInstance.value) return;
    if (isAnnotationsVisible.value) {
        removeAnnotations();
    } else {
        applyAnnotations();
    }
};

const toggleIndicators = async () => {
    if (!chartInstance.value) return;
    if (isIndicatorsVisible.value) {
        removeIndicators();
    } else {
        isIndicatorsVisible.value = true;
        await nextTick();
        applyIndicators();
    }
};

const toggleVolume = async () => {
    if (!chartInstance.value) return;
    if (isVolumeVisible.value) {
        chartInstance.value.removeIndicator('volume_pane', 'VOL');
        isVolumeVisible.value = false;
    } else {
        isVolumeVisible.value = true;
        await nextTick();
        chartInstance.value.createIndicator({ name: 'VOL', calcParams: [] }, true, { id: 'volume_pane' });
    }
};

const toggleRSI = async () => {
    if (!chartInstance.value) return;
    if (isRSIVisible.value) {
        chartInstance.value.removeIndicator('rsi_pane', 'RSI');
        isRSIVisible.value = false;
    } else {
        isRSIVisible.value = true;
        await nextTick();
        const rsiConfig = props.indicators.find(ind => ind.name === 'RSI') || { name: 'RSI', calcParams: [14] };
        chartInstance.value.createIndicator(rsiConfig, true, { id: 'rsi_pane' });
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
        case 'TARGET': return '#f59e0b';
        default: return '#8b5cf6';
    }
};

const applyIndicators = () => {
    if (!chartInstance.value || !props.indicators) return;

    // Proactively remove standard indicators to avoid overlaps
    chartInstance.value.removeIndicator('candle_pane', 'EMA');
    chartInstance.value.removeIndicator('candle_pane', 'SMA');

    // Clear all previously tracked indicators from candle_pane
    appliedIndicatorNames.value.forEach(name => {
        chartInstance.value.removeIndicator('candle_pane', name);
    });
    appliedIndicatorNames.value = [];

    // Filter out RSI and VOL as they have their own toggles/panes
    const trendIndicators = props.indicators.filter(ind => ind.name !== 'RSI' && ind.name !== 'VOL');

    trendIndicators.forEach(ind => {
        chartInstance.value.createIndicator(ind, true, { id: 'candle_pane' });
        appliedIndicatorNames.value.push(ind.name);
    });
    isIndicatorsVisible.value = true;
};

const removeIndicators = () => {
    if (!chartInstance.value) return;
    appliedIndicatorNames.value.forEach(name => {
        chartInstance.value.removeIndicator('candle_pane', name);
    });
    appliedIndicatorNames.value = [];
    isIndicatorsVisible.value = false;
};

const applyAnnotations = () => {
    if (!chartInstance.value) return;
    // Clear only simpleAnnotation overlays to avoid removing indicators etc.
    chartInstance.value.removeOverlay({ name: 'simpleAnnotation' });

    props.markers.forEach((m) => {
        const markerColor = getMarkerColor(m.type);

        // Label logic: ENTRY shows price, EXIT/TARGET shows PnL (or Price if mode is Price)
        let label = '';
        if (m.type === 'ENTRY') {
            const price = m.optionPrice ?? m.niftyPrice;
            label = `${price?.toFixed(1) || '0.0'}`;
        } else {
            if (annotationMode.value === 'Price') {
                const price = m.optionPrice ?? m.niftyPrice;
                label = `${price?.toFixed(1) || '0.0'}`;
            } else {
                label = `${m.pnl?.toFixed(1) || '0.0'}`;
            }
        }

        if (m.exitReason) {
            label += ` ${m.exitReason}`;
        }

        const plotPrice = m.optionPrice ?? m.niftyPrice;

        chartInstance.value.createOverlay({
            name: 'simpleAnnotation',
            id: `rev-${m.id}`,
            extendData: label,
            points: [{ timestamp: (m.time * 1000), value: plotPrice }],
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
    if (!chartInstance.value) return;
    chartInstance.value.removeOverlay({ name: 'simpleAnnotation' });
    isAnnotationsVisible.value = false;
};

const loadMore = async () => {
    if (loadingMore.value || !hasMoreData.value || !chartInstance.value) return;

    const dataList = chartInstance.value.getDataList();
    if (!dataList.length) return;

    const earliestTimestamp = dataList[0].timestamp;
    if (lastProcessedTimestamp.value === earliestTimestamp) return;
    lastProcessedTimestamp.value = earliestTimestamp;

    loadingMore.value = true;
    try {
        const result = await fetchChartData(props.instrumentId, props.timeframe, (earliestTimestamp / 1000) - 1);
        if (result.ticks.length) {
            if (result.ticks[result.ticks.length - 1].timestamp < earliestTimestamp) {
                chartInstance.value.applyMoreData(result.ticks);
            }
            hasMoreData.value = result.hasMoreOld;
        } else {
            hasMoreData.value = false;
        }
    } catch (err) {
        console.error('[loadMore] error:', err);
    } finally {
        loadingMore.value = false;
    }
};

const initCharts = async () => {
    if (!chartRef.value) return;

    loading.value = true;
    try {
        const isDark = document.documentElement.classList.contains('dark-mode');
        chartInstance.value = init(chartRef.value);
        if (chartInstance.value) {
            chartInstance.value.setTimezone('Asia/Kolkata');
            chartInstance.value.setStyles(isDark ? 'dark' : 'light');
            chartInstance.value.setStyles({
                yAxis: {
                    size: 80,
                    gap: { top: 0.5, bottom: 0.3 }
                },
                candle: {
                    priceMark: { last: { show: false }, high: { show: false }, low: { show: false } }
                }
            });

            chartInstance.value.subscribeAction('onScroll', () => {
                const range = chartInstance.value.getVisibleRange();
                if (range.from <= 0) {
                    loadMore();
                }
            });
        }

        const result = await fetchChartData(props.instrumentId, props.timeframe, props.maxTimestamp);
        hasMoreData.value = result.hasMoreOld;

        if (chartInstance.value && result.ticks.length) {
            chartInstance.value.applyNewData(result.ticks);
            chartInstance.value.setBarSpace(12);
        }

        if (isAnnotationsVisible.value) {
            applyAnnotations();
        }
        if (isIndicatorsVisible.value) {
            applyIndicators();
        }
        if (isVolumeVisible.value) {
            chartInstance.value.createIndicator({ name: 'VOL', calcParams: [] }, true, { id: 'volume_pane' });
        }
        if (isRSIVisible.value) {
            const rsiConfig = props.indicators.find(ind => ind.name === 'RSI') || { name: 'RSI', calcParams: [14] };
            chartInstance.value.createIndicator(rsiConfig, true, { id: 'rsi_pane' });
        }
    } catch (err) {
        console.error('Chart Init Error:', err);
    } finally {
        loading.value = false;
    }
};

let resizeObserver = null;

onMounted(async () => {
    await initCharts();
    if (chartRef.value) {
        resizeObserver = new ResizeObserver(() => {
            chartInstance.value?.resize();
        });
        resizeObserver.observe(chartRef.value);
    }
});

onUnmounted(() => {
    if (resizeObserver) resizeObserver.disconnect();
    if (chartInstance.value) dispose(chartRef.value);
});

watch(() => [props.instrumentId, props.timeframe, props.maxTimestamp], async () => {
    loading.value = true;
    hasMoreData.value = true;
    lastProcessedTimestamp.value = null;

    const result = await fetchChartData(props.instrumentId, props.timeframe, props.maxTimestamp);
    hasMoreData.value = result.hasMoreOld;

    chartInstance.value?.applyNewData(result.ticks);
    if (isIndicatorsVisible.value) applyIndicators();
    if (isAnnotationsVisible.value) applyAnnotations();
    if (isVolumeVisible.value) chartInstance.value?.createIndicator({ name: 'VOL', calcParams: [] }, true, { id: 'volume_pane' });
    if (isRSIVisible.value) {
        const rsiConfig = props.indicators.find(ind => ind.name === 'RSI') || { name: 'RSI', calcParams: [14] };
        chartInstance.value?.createIndicator(rsiConfig, true, { id: 'rsi_pane' });
    }
    loading.value = false;
});

watch(() => props.markers, () => {
    if (isAnnotationsVisible.value) {
        applyAnnotations();
    }
}, { deep: true });

watch(() => annotationMode.value, () => {
    if (isAnnotationsVisible.value) {
        applyAnnotations();
    }
});

watch(() => props.indicators, () => {
    if (isIndicatorsVisible.value) {
        removeIndicators();
        applyIndicators();
    }
    if (isRSIVisible.value) {
        chartInstance.value?.removeIndicator('rsi_pane', 'RSI');
        const rsiConfig = props.indicators.find(ind => ind.name === 'RSI') || { name: 'RSI', calcParams: [14] };
        chartInstance.value?.createIndicator(rsiConfig, true, { id: 'rsi_pane' });
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

.header-divider {
    width: 1px;
    height: 20px;
    background: var(--layout-border);
}

:deep(.header-toggle .p-button) {
    font-size: 0.75rem;
    padding: 0.25rem 0.75rem;
}

.charts-wrapper {
    flex: 1;
    display: flex;
    flex-direction: column;
}

.chart-pane {
    flex: 1;
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
