<template>
  <div :class="['layout-wrapper', { 'sidebar-collapsed': !sidebarVisible }, { 'analysis-mode': isAnalysisRoute }]">
    <!-- Glassmorphism Topbar -->
    <header class="layout-topbar">
      <div class="topbar-left">
        <Button :icon="sidebarVisible ? 'pi pi-align-left' : 'pi pi-align-justify'" text rounded
          @click="sidebarVisible = !sidebarVisible" class="menu-toggle-btn" />
        <span class="logo-text">TRADE BOT</span>
      </div>
      <div class="topbar-right">
        <div class="topbar-actions">
          <!-- Backtest Analysis Controls -->
          <template v-if="isAnalysisRoute && backtestStore.backtests.length > 0">
            <div class="analysis-controls flex align-items-center">
              <Select v-model="backtestStore.selectedBacktestId" :options="backtestStore.backtests" optionLabel="id"
                optionValue="id" placeholder="Select Backtest" @change="onBacktestChange" class="backtest-select"
                :loading="backtestStore.loading">
                <template #option="slotProps">
                  <div class="backtest-option" v-if="slotProps.option">
                    <span class="strategy-name">{{ slotProps.option.config?.strategy || 'Unknown Strategy' }}</span>
                    <span class="backtest-dates text-xs" v-if="slotProps.option.startDate">
                      {{ slotProps.option.startDate }} - {{ slotProps.option.endDate }}
                    </span>
                    <span class="backtest-dates text-xs"
                      v-else-if="slotProps.option.createdAt || slotProps.option.timestamp">
                      {{ slotProps.option.createdAt || slotProps.option.timestamp }}
                    </span>
                  </div>
                </template>
              </Select>
              <Button icon="pi pi-cog" v-if="backtestStore.selectedBacktest" @click="configVisible = true" text rounded
                severity="secondary" class="config-toggle-btn ml-2" title="Strategy Config" />
              <Button icon="pi pi-history" v-if="backtestStore.selectedBacktest" @click="historyVisible = true" text
                rounded severity="secondary" class="history-toggle-btn ml-2" title="Trade History Timeline" />
            </div>
            <div class="divider mx-3"></div>
          </template>

          <ThemeSwitcherComp />
          <Button icon="pi pi-bell" text rounded severity="secondary" class="ml-1" />
          <Button icon="pi pi-user" text rounded severity="secondary" class="ml-1" />
        </div>
      </div>
    </header>

    <!-- Strategy Config Modal (Global) -->
    <Dialog v-model:visible="configVisible" modal header="Backtest Configuration" :style="{ width: '40vw' }">
      <div class="config-display" v-if="backtestStore.selectedBacktest">
        <pre>{{ JSON.stringify(backtestStore.selectedBacktest.config, null, 2) }}</pre>
      </div>
    </Dialog>

    <!-- Trade History Drawer -->
    <Drawer v-model:visible="historyVisible" position="right" header="Execution Timeline" :style="{ width: '45vw' }"
      class="history-drawer">
      <div v-if="backtestStore.selectedBacktest" class="history-content">
        <!-- ML Model Info -->
        <div v-if="backtestStore.selectedBacktest?.config?.mlModelPath" class="ml-model-info mb-4">
          <Tag severity="info" class="w-full justify-content-start p-3">
            <div class="flex align-items-center gap-2">
              <i class="pi pi-microchip"></i>
              <span><strong>ML Model:</strong> {{ extractFilename(backtestStore.selectedBacktest.config.mlModelPath)
                }}</span>
            </div>
          </Tag>
        </div>

        <!-- Date Selector (for multiday) -->
        <div v-if="availableDates.length > 1" class="date-selector mb-4">
          <label class="block text-sm font-bold mb-2 text-secondary">SELECT DATE</label>
          <Select v-model="selectedHistoryDate" :options="availableDates" placeholder="Select Date" class="w-full" />
        </div>

        <!-- Instruments & Cycles Timeline -->
        <div v-if="groupedTradesByDate[selectedHistoryDate]" class="instruments-timeline">
          <div v-for="(instr, symbol) in groupedTradesByDate[selectedHistoryDate]" :key="symbol"
            class="instrument-section mb-5">
            <div class="instrument-header-row mb-3">
              <span class="symbol-name">{{ symbol }}</span>
              <Tag :value="formatCurrency(instr.totalPnl)" :severity="instr.totalPnl >= 0 ? 'success' : 'danger'"
                outlined />
            </div>

            <div class="cycles-timeline">
              <div v-for="cycle in instr.cycles" :key="cycle.id" class="cycle-timeline-card mb-4 p-3">
                <div class="cycle-header flex justify-content-between align-items-center mb-3" style="padding: 10px;">
                  <div class="flex align-items-center" style="gap:8px">
                    <span class="cycle-id-text">{{ cycle.id }}</span>
                    <Tag :value="cycle.duration" severity="secondary" icon="pi pi-clock" />
                    <Tag :value="formatCurrency(cycle.totalPnl)"
                      :severity="cycle.totalPnl >= 0 ? 'success' : 'danger'" />
                  </div>
                </div>

                <Timeline :value="cycle.executions" class="customized-timeline">
                  <template #opposite="slotProps">
                    <small class="text-secondary">{{ formatTimeOnly(slotProps.item.time) }}</small>
                  </template>
                  <template #content="slotProps">
                    <div class="execution-content">
                      <div class="exec-title flex align-items-center gap-2">
                        <Tag :value="slotProps.item.type" :severity="getExecutionSeverity(slotProps.item.type)"
                          class="exec-tag" />
                        <span class="exec-price">@ {{ slotProps.item.price }}</span>
                      </div>
                      <div class="exec-reason text-xs text-secondary mt-1">
                        {{ slotProps.item.reasonDesc || slotProps.item.reason }}
                      </div>
                    </div>
                  </template>
                </Timeline>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="flex flex-direction-column align-items-center justify-content-center p-8 text-secondary">
          <i class="pi pi-calendar-times mb-3" style="font-size: 3rem"></i>
          <p>No trades recorded for this date</p>
        </div>
      </div>
    </Drawer>

    <div class="layout-main-container">
      <!-- Glassmorphism Sidebar -->
      <aside class="layout-sidebar" :class="{ 'layout-sidebar-collapsed': !sidebarVisible }">
        <div class="sidebar-content">
          <nav class="sidebar-menu">
            <NuxtLink to="/" class="menu-item" title="Dashboard">
              <i class="pi pi-chart-line"></i>
              <span v-if="sidebarVisible">Dashboard</span>
            </NuxtLink>
            <NuxtLink to="/trade-compare" class="menu-item" title="Trade Compare">
              <i class="pi pi-clone"></i>
              <span v-if="sidebarVisible">Trade Compare</span>
            </NuxtLink>
            <NuxtLink to="/trade-review" class="menu-item" title="Trade Review">
              <i class="pi pi-chart-bar"></i>
              <span v-if="sidebarVisible">Trade Review</span>
            </NuxtLink>
            <NuxtLink to="/strategy-rules" class="menu-item" title="Strategy Rules">
              <i class="pi pi-book"></i>
              <span v-if="sidebarVisible">Strategy Rules</span>
            </NuxtLink>
            <NuxtLink to="/chart-playground" class="menu-item" title="Chart Playground">
              <i class="pi pi-play"></i>
              <span v-if="sidebarVisible">Chart Playground</span>
            </NuxtLink>
          </nav>

          <!-- Trades Tree (Grouped by Instrument) -->
          <div v-if="isAnalysisRoute && backtestStore.selectedBacktest" class="trades-sidebar-section">
            <div class="sidebar-header" v-if="sidebarVisible">INSTRUMENTS</div>
            <div class="trades-list" v-if="sidebarVisible">
              <Tree :value="treeNodes" selectionMode="single" @node-select="onNodeSelect"
                v-model:selectionKeys="selectionKeys" v-model:expandedKeys="expandedKeys" class="w-full trades-tree">
                <template #default="slotProps">
                  <div class="tree-node-content"
                    :class="{ 'instrument-node': slotProps.node.data.type === 'instrument' }">
                    <span class="node-label">{{ slotProps.node.label }}</span>
                    <span v-if="slotProps.node.data.type === 'trade'" class="node-pnl"
                      :class="slotProps.node.data.pnl >= 0 ? 'pos' : 'neg'">
                      ({{ slotProps.node.data.pnl >= 0 ? '+' : '' }}{{ slotProps.node.data.pnl?.toFixed(1) }})
                    </span>
                  </div>
                </template>
              </Tree>
            </div>
          </div>
        </div>
      </aside>

      <!-- Main Content Area -->
      <main class="layout-main">
        <slot />
      </main>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue';
import Button from 'primevue/button';
import Select from 'primevue/select';
import Dialog from 'primevue/dialog';
import Drawer from 'primevue/drawer';
import Timeline from 'primevue/timeline';
import Tag from 'primevue/tag';
import Tree from 'primevue/tree';
import ThemeSwitcherComp from '~/components/ThemeSwitcherComp.vue';

const getDateYYYYMMDD = (tObj) => {
  if (!tObj) return 'Unknown';
  let epoch = tObj.epochTime;
  if (!epoch && tObj.time) epoch = parseSafeTimestamp(tObj.time);
  if (!epoch && typeof tObj === 'string') epoch = parseSafeTimestamp(tObj);
  if (!epoch) return 'Unknown';

  const d = new Date(epoch * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const route = useRoute();
const sidebarVisible = ref(true);
const currentPath = computed(() => route.path);
const configVisible = ref(false);
const historyVisible = ref(false);
const selectedHistoryDate = ref(null);
const expandedKeys = ref({});

const selectionKeys = computed(() => {
  if (backtestStore.selectedTradeIndex !== -1) {
    return { [`trade-${backtestStore.selectedTradeIndex}`]: true };
  }
  if (backtestStore.selectedCycleId && backtestStore.selectedInstrumentId) {
    return { [`${backtestStore.selectedInstrumentId}-${backtestStore.selectedCycleId}`]: true };
  }
  if (backtestStore.selectedInstrumentId) {
    return { [backtestStore.selectedInstrumentId]: true };
  }
  return {};
});

const isAnalysisRoute = computed(() =>
  currentPath.value.startsWith('/trade-compare') ||
  currentPath.value.startsWith('/trade-review')
);

const treeNodes = computed(() => {
  const trades = backtestStore.selectedBacktest?.instrumentsTraded || backtestStore.selectedBacktest?.tradeCycles || backtestStore.selectedBacktest?.trades || [];
  const instrumentGroups = {};

  trades.forEach((t, index) => {
    const symbol = t.entry?.instrumentDescription || t.entry?.exchangeInstrumentId || t.symbol || t.instrumentDesc || t.id || 'Unknown';
    if (!instrumentGroups[symbol]) {
      instrumentGroups[symbol] = {
        key: symbol,
        label: symbol,
        data: { type: 'instrument', id: t.entry?.instrumentDescription || t.entry?.exchangeInstrumentId || t.instrumentId || t.symbol, desc: symbol },
        children: {} // Temp object to group by cycle
      };
    }

    const cycleId = t.cycleId || t.tradeCycle || 'N/A';
    const entryTimeStr = formatTimeLocalized(t.entry);
    if (!instrumentGroups[symbol].children[cycleId]) {
      instrumentGroups[symbol].children[cycleId] = {
        key: `${symbol}-${cycleId}`,
        label: `${cycleId} (${entryTimeStr})`,
        data: { type: 'cycle', instrumentId: t.entry?.instrumentDescription || t.entry?.exchangeInstrumentId || t.instrumentId || t.symbol, cycleId: cycleId },
        children: []
      };
    }

    const exitTimeStr = formatTimeLocalized(t.exit || t.exitTime);
    const exitReason = t.exit?.signal || t.exit?.reason || t.exitReason || 'OPEN';
    const label = `${exitTimeStr} [${exitReason}]`;
    const pnl = t.cyclePnL !== undefined ? t.cyclePnL : t.pnl;

    instrumentGroups[symbol].children[cycleId].children.push({
      key: `trade-${index}`,
      label: label,
      data: { type: 'trade', index: index, pnl: pnl }
    });
  });

  return Object.values(instrumentGroups).map(instr => ({
    ...instr,
    children: Object.values(instr.children)
  }));
});

const availableDates = computed(() => {
  const trades = backtestStore.selectedBacktest?.tradeCycles || backtestStore.selectedBacktest?.trades || [];
  const dates = new Set();
  trades.forEach(t => {
    const entryObj = t.entry || t.entryTime;
    if (entryObj) {
      dates.add(getDateYYYYMMDD(entryObj));
    }
  });
  const sorted = Array.from(dates).sort((a, b) => b.localeCompare(a));
  if (sorted.length > 0 && !selectedHistoryDate.value) {
    selectedHistoryDate.value = sorted[0];
  }
  return sorted;
});

const groupedTradesByDate = computed(() => {
  const trades = backtestStore.selectedBacktest?.tradeCycles || backtestStore.selectedBacktest?.trades || [];
  const groups = {};

  trades.forEach(t => {
    const entryObj = t.entry || t.entryTime;
    const exitObj = t.exit || t.exitTime;

    // Determine timestamps once here to reuse
    let entryEp = t.entry?.epochTime || parseSafeTimestamp(t.entry?.time || t.entryTime);
    let exitEp = t.exit?.epochTime || parseSafeTimestamp(t.exit?.time || t.exitTime);

    const date = entryObj ? getDateYYYYMMDD(entryObj) : 'Unknown';
    if (!groups[date]) groups[date] = {};

    const symbol = t.entry?.instrumentDescription || t.entry?.exchangeInstrumentId || t.symbol || t.id || 'Unknown';
    if (!groups[date][symbol]) groups[date][symbol] = { totalPnl: 0, cycles: {} };

    const cycleId = t.cycleId || t.tradeCycle || 'N/A';
    if (!groups[date][symbol].cycles[cycleId]) {
      groups[date][symbol].cycles[cycleId] = {
        id: cycleId,
        totalPnl: 0,
        startTime: entryT,
        endTime: exitT,
        executions: []
      };
    }

    const cycle = groups[date][symbol].cycles[cycleId];
    const pnl = t.cyclePnL !== undefined ? t.cyclePnL : (t.pnl || 0);
    cycle.totalPnl += pnl;
    groups[date][symbol].totalPnl += pnl;

    // Update cycle boundaries
    if (entryEp && (!cycle.startTime || entryEp < cycle.startTime)) cycle.startTime = entryEp;
    if (exitEp && (!cycle.endTime || exitEp > cycle.endTime)) cycle.endTime = exitEp;

    // Add Entry execution
    if (!cycle.executions.some(e => e.type === 'ENTRY')) {
      let entryPrice = t.entryPrice;
      if (t.entry && !entryPrice) {
        entryPrice = t.entry.price || 0;
        if (!entryPrice && t.entry.transaction) {
          const m = t.entry.transaction.match(/(?:@|at)\s+([\d.]+)/);
          if (m) entryPrice = parseFloat(m[1]);
        }
        if (!entryPrice && t.entry.totalPrice) entryPrice = t.entry.totalPrice / 65;
      }

      cycle.executions.push({
        type: 'ENTRY',
        time: entryEp,
        price: entryPrice,
        reason: t.entry?.signal || t.signal,
        reasonDesc: t.entry?.signalDescription || t.entryReasonDescription
      });
    }

    // Add Exit execution
    let exitPrice = t.exitPrice;
    if (t.exit && !exitPrice) {
      exitPrice = t.exit.price || 0;
      if (!exitPrice && t.exit.transaction) {
        const m = t.exit.transaction.match(/(?:@|at)\s+([\d.]+)/);
        if (m) exitPrice = parseFloat(m[1]);
      }
      if (!exitPrice && t.exit.totalPrice) exitPrice = t.exit.totalPrice / 65;
    }

    cycle.executions.push({
      type: t.exit?.signal || t.exit?.reason || t.exitReason || 'EXIT',
      time: exitEp,
      price: exitPrice,
      reason: t.exit?.signal || t.exit?.reason || t.exitReason,
      reasonDesc: t.exit?.signalDescription || t.exitReasonDescription
    });
  });

  // Post-process to sort executions and calculate durations
  Object.keys(groups).forEach(date => {
    Object.keys(groups[date]).forEach(symbol => {
      const instr = groups[date][symbol];
      instr.cycles = Object.values(instr.cycles).map(cycle => {
        cycle.executions.sort((a, b) => a.time - b.time);
        cycle.duration = calculateDuration(cycle.startTime, cycle.endTime);
        return cycle;
      }).sort((a, b) => a.startTime - b.startTime);
    });
  });

  return groups;
});

const calculateDuration = (sEp, eEp) => {
  if (!sEp || !eEp) return 'N/A';
  const diffMs = (eEp - sEp) * 1000;

  const totalMinutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;

  if (hours > 0) {
    return `${hours} hr${hours > 1 ? 's' : ''} ${mins} min${mins !== 1 ? 's' : ''}`;
  }
  return `${mins} min${mins !== 1 ? 's' : ''}`;
};

const formatTimeOnly = (ep) => {
  if (!ep) return '';
  const date = new Date(ep * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
};

const extractFilename = (path) => {
  if (!path) return '';
  return path.split('/').pop().split('\\').pop();
};

const getExecutionSeverity = (type) => {
  if (type === 'ENTRY') return 'info';
  if (type === 'EOD') return 'secondary';
  if (type.startsWith('TARGET')) return 'success';
  if (type.includes('SL')) return 'danger';
  return 'warn';
};

const formatCurrency = (val) => {
  return (val >= 0 ? '+' : '') + val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const onNodeSelect = (node) => {
  if (node.data.type === 'instrument') {
    backtestStore.selectedInstrumentId = node.data.id;
    backtestStore.selectedInstrumentDesc = node.data.desc;
    backtestStore.selectedTradeIndex = -1;
    backtestStore.selectedCycleId = null;
  } else if (node.data.type === 'cycle') {
    backtestStore.selectedInstrumentId = node.data.instrumentId;
    backtestStore.selectedInstrumentDesc = node.label; // Or instrumentGroup key
    backtestStore.selectedCycleId = node.data.cycleId;
    backtestStore.selectedTradeIndex = -1;
  } else {
    backtestStore.selectedTradeIndex = node.data.index;
    backtestStore.selectedInstrumentId = null;
    backtestStore.selectedInstrumentDesc = null;
    backtestStore.selectedCycleId = null;
  }
};

const onBacktestChange = (e) => {
  backtestStore.selectBacktest(e.value);
};

const selectTrade = (index) => {
  backtestStore.selectedTradeIndex = index;
};

const formatTimeLocalized = (tObj) => {
  if (!tObj) return '';
  try {
    let epoch = 0;
    if (typeof tObj === 'object') {
      epoch = tObj.epochTime || parseSafeTimestamp(tObj.time);
    } else {
      epoch = parseSafeTimestamp(tObj);
    }
    const date = new Date(epoch * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return tObj?.time || tObj;
  }
};

onMounted(() => {
  if (isAnalysisRoute.value) {
    backtestStore.fetchBacktests();
  }
});
</script>

<style scoped>
.topbar-actions {
  display: flex;
  align-items: center;
}

:deep(.backtest-select) {
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  backdrop-filter: blur(8px);
  width: 200px;
}

.flex {
  display: flex;
}

.align-items-center {
  align-items: center;
}

.ml-1 {
  margin-left: 0.25rem;
}

.ml-2 {
  margin-left: 0.5rem;
}

.mr-2 {
  margin-right: 0.5rem;
}

.mx-3 {
  margin-left: 1rem;
  margin-right: 1rem;
}

.divider {
  width: 1px;
  height: 24px;
  background: var(--layout-border);
}

.config-display {
  background: var(--surface-ground);
  padding: 1rem;
  border-radius: var(--card-border-radius);
  font-family: 'Monaco', monospace;
  font-size: 0.85rem;
  max-height: 400px;
  overflow-y: auto;
}

pre {
  margin: 0;
}

.backtest-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.strategy-name {
  font-weight: 700;
  font-size: 0.85rem;
}

.backtest-dates {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.backtest-roi {
  font-size: 0.75rem;
  font-weight: 800;
}

.pos {
  color: #10b981;
}

.neg {
  color: #ef4444;
}

.trades-sidebar-section {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--layout-border);
}

.trades-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem;
  max-height: calc(100vh - 350px);
  overflow-y: auto;
  padding-right: 0.25rem;
}

.instrument-group {
  margin-bottom: 1.5rem;
}

.instrument-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 0.5rem 0.5rem 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  margin-bottom: 0.5rem;
}

.group-symbol {
  font-size: 0.85rem;
  font-weight: 800;
  color: var(--primary-color);
}

.cycle-tag {
  font-size: 0.65rem !important;
  font-weight: 700 !important;
  padding: 0.1rem 0.4rem !important;
}

.cycles-list {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

/* Tree styling */
:deep(.trades-tree) {
  background: transparent !important;
  border: none !important;
  padding: 0 !important;
}

:deep(.p-tree-node-content) {
  padding: 0.4rem 0.5rem !important;
  border-radius: 6px !important;
  transition: background 0.15s !important;
}

:deep(.p-tree-node-content:hover) {
  background: rgba(255, 255, 255, 0.05) !important;
}

:deep(.p-tree-node-content.p-tree-node-selected) {
  background: rgba(var(--primary-color-rgb), 0.15) !important;
}

:deep(.p-tree-node-label) {
  width: 100%;
}

:deep(.p-tree-node-icon) {
  color: var(--text-secondary) !important;
  font-size: 0.8rem !important;
}

.tree-node-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 0.5rem;
}

.instrument-node .node-label {
  font-weight: 800;
  color: var(--primary-color);
  font-size: 0.85rem;
}

.node-label {
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node-pnl {
  font-size: 0.75rem;
  font-weight: 700;
}

/* Scrollbar styling for trades list */
.trades-list::-webkit-scrollbar {
  width: 4px;
}

.trades-list::-webkit-scrollbar-track {
  background: transparent;
}

.trades-list::-webkit-scrollbar-thumb {
  background: var(--layout-border);
  border-radius: 10px;
}

/* History Drawer Styles */
.history-content {
  padding: 0.5rem;
}

.instrument-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px solid var(--layout-border);
  padding-bottom: 0.5rem;
}

.symbol-name {
  font-size: 1.1rem;
  font-weight: 800;
  color: var(--primary-color);
}

.cycle-header {
  width: 100%;
}

.cycle-id-text {
  font-weight: 800;
  font-size: 0.9rem;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.pnl-pos {
  color: var(--p-green-400);
}

.pnl-neg {
  color: var(--p-red-400);
}

.cycle-timeline-card {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--layout-border);
  border-radius: var(--card-border-radius);
  margin-top: 1rem;
}

.exec-tag {
  font-size: 0.65rem !important;
  font-weight: 800 !important;
}

.exec-price {
  font-family: 'Monaco', monospace;
  font-size: 0.85rem;
}

:deep(.customized-timeline .p-timeline-event-opposite) {
  flex: 0;
  min-width: 60px;
  text-align: left;
}

:deep(.customized-timeline .p-timeline-event-content) {
  padding-bottom: 1.5rem;
}
</style>
