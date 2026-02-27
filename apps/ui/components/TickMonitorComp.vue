<template>
  <div class="tick-monitor">
    <!-- Header Controls -->
    <div class="monitor-header">
      <div class="header-left">
        <h2 class="page-title"><i class="pi pi-wave-pulse"></i> Tick Monitor</h2>
        <Tag :severity="isConnected ? 'success' : 'danger'" :value="isConnected ? 'Socket Connected' : 'Disconnected'"
          class="conn-tag" />
      </div>
      <div class="header-right">
        <Select v-model="selectedDate" :options="availableDates" placeholder="Select Date" class="date-select"
          :disabled="isRunning" />
        <InputNumber v-model="interval" :min="1" :max="30" suffix="s" :disabled="isRunning" class="interval-input" />
        <Button :label="isRunning ? 'Stop' : 'Start'" :icon="isRunning ? 'pi pi-stop' : 'pi pi-play'"
          :severity="isRunning ? 'danger' : 'success'" @click="toggleSimulation" :loading="isLoading" />
        <Button icon="pi pi-trash" severity="secondary" text @click="clearLog" title="Clear Log" />
      </div>
    </div>

    <!-- Status Bar -->
    <div class="status-bar">
      <div class="stat">
        <span class="stat-label">Status</span>
        <span :class="['stat-value', isRunning ? 'txt-profit' : 'txt-muted']">
          {{ isRunning ? '🟢 Running' : '🔴 Stopped' }}
        </span>
      </div>
      <div class="stat">
        <span class="stat-label">Ticks Received</span>
        <span class="stat-value">{{ ticksReceived }}</span>
      </div>
      <div class="stat" v-if="lastTick">
        <span class="stat-label">LTP</span>
        <span class="stat-value stat-ltp">{{ lastTick.LastTradedPrice }}</span>
      </div>
      <div class="stat" v-if="lastTick">
        <span class="stat-label">Change</span>
        <span :class="['stat-value', lastTick.PercentChange >= 0 ? 'txt-profit' : 'txt-loss']">
          {{ lastTick.PercentChange >= 0 ? '+' : '' }}{{ lastTick.PercentChange?.toFixed(2) }}%
        </span>
      </div>
      <div class="stat" v-if="lastTick">
        <span class="stat-label">Day Range</span>
        <span class="stat-value">{{ lastTick.Low }} – {{ lastTick.High }}</span>
      </div>
    </div>

    <!-- Tick Log Table -->
    <div class="tick-log-container" ref="logContainer">
      <table class="tick-table" v-if="ticks.length > 0">
        <thead>
          <tr>
            <th>Time</th>
            <th>LTP</th>
            <th>Open</th>
            <th>High</th>
            <th>Low</th>
            <th>Close</th>
            <th>Volume</th>
            <th>%Chg</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(tick, idx) in displayedTicks" :key="idx" class="tick-row">
            <td class="col-time">{{ formatTimestamp(tick.ExchangeTimeStamp) }}</td>
            <td class="col-ltp">{{ tick.LastTradedPrice }}</td>
            <td>{{ tick.Open }}</td>
            <td>{{ tick.High }}</td>
            <td>{{ tick.Low }}</td>
            <td>{{ tick.Close }}</td>
            <td>{{ tick.TotalTradedQuantity?.toLocaleString() }}</td>
            <td :class="tick.PercentChange >= 0 ? 'txt-profit' : 'txt-loss'">
              {{ tick.PercentChange >= 0 ? '+' : '' }}{{ tick.PercentChange?.toFixed(2) }}%
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">
        <i class="pi pi-inbox"></i>
        <p>No tick data yet. Select a date and press <strong>Start</strong> to begin simulation.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue';
import { io } from 'socket.io-client';
import Button from 'primevue/button';
import Select from 'primevue/select';
import InputNumber from 'primevue/inputnumber';
import Tag from 'primevue/tag';

const API_BASE = '/api/simulation';
const MAX_DISPLAY = 200;

const selectedDate = ref(null);
const interval = ref(5);
const isRunning = ref(false);
const isLoading = ref(false);
const isConnected = ref(false);
const ticksReceived = ref(0);
const availableDates = ref([]);
const ticks = ref([]);
const logContainer = ref(null);

let socket = null;

const lastTick = computed(() => ticks.value.length > 0 ? ticks.value[ticks.value.length - 1] : null);
const displayedTicks = computed(() => ticks.value.slice(-MAX_DISPLAY));

function formatTimestamp(ts) {
  if (!ts) return '';
  // The simulator shifts by XTS_TIME_OFFSET (19800s), reverse it for display
  const epoch = (ts - 19800) * 1000;
  return new Date(epoch).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function connectSocket() {
  socket = io(window.location.origin, {
    path: '/simulation-socket',
    transports: ['polling', 'websocket'],
  });

  socket.on('connect', () => {
    isConnected.value = true;
    console.log('[TickMonitor] Socket connected:', socket.id);
  });

  socket.on('disconnect', () => {
    isConnected.value = false;
    console.log('[TickMonitor] Socket disconnected');
  });

  socket.on('1501-json-full', (data) => {
    ticks.value.push(data);
    ticksReceived.value++;
    // Auto-scroll to bottom
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight;
      }
    });
  });
}

async function fetchAvailableDates() {
  try {
    const res = await fetch(`${API_BASE}/dates`);
    const data = await res.json();
    availableDates.value = data.dates || [];
    if (availableDates.value.length > 0 && !selectedDate.value) {
      selectedDate.value = availableDates.value[0];
    }
  } catch (e) {
    console.error('[TickMonitor] Failed to fetch dates:', e);
  }
}

async function fetchStatus() {
  try {
    const res = await fetch(`${API_BASE}/status`);
    const data = await res.json();
    isRunning.value = data.is_running;
    ticksReceived.value = data.ticks_emitted || ticksReceived.value;
  } catch (e) {
    // Ignore status fetch errors
  }
}

async function startSimulation() {
  isLoading.value = true;
  try {
    const res = await fetch(`${API_BASE}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: selectedDate.value, interval: interval.value }),
    });
    const data = await res.json();
    if (res.ok) {
      isRunning.value = true;
    } else {
      console.error('[TickMonitor] Start failed:', data.detail);
    }
  } catch (e) {
    console.error('[TickMonitor] Start error:', e);
  } finally {
    isLoading.value = false;
  }
}

async function stopSimulation() {
  isLoading.value = true;
  try {
    await fetch(`${API_BASE}/stop`, { method: 'POST' });
    isRunning.value = false;
  } catch (e) {
    console.error('[TickMonitor] Stop error:', e);
  } finally {
    isLoading.value = false;
  }
}

async function toggleSimulation() {
  if (isRunning.value) {
    await stopSimulation();
  } else {
    await startSimulation();
  }
}

function clearLog() {
  ticks.value = [];
  ticksReceived.value = 0;
}

onMounted(() => {
  fetchAvailableDates();
  fetchStatus();
  connectSocket();
});

onBeforeUnmount(() => {
  if (socket) {
    socket.disconnect();
  }
});
</script>

<style scoped>
.tick-monitor {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 0;
}

/* --- Header --- */
.monitor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  background: var(--surface-card);
  border-bottom: 1px solid var(--layout-border);
  flex-wrap: wrap;
  gap: 0.75rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.page-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

:deep(.date-select) {
  width: 160px;
  background: rgba(255, 255, 255, 0.05) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
}

:deep(.interval-input) {
  width: 90px;
}

/* --- Status Bar --- */
.status-bar {
  display: flex;
  padding: 0.75rem 1.5rem;
  gap: 2rem;
  background: var(--surface-ground);
  border-bottom: 1px solid var(--layout-border);
  flex-wrap: wrap;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.stat-label {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  font-weight: 700;
}

.stat-value {
  font-size: 0.9rem;
  font-weight: 700;
}

.stat-ltp {
  font-size: 1.1rem;
  font-weight: 800;
}



.text-muted {
  color: var(--text-secondary);
}

/* --- Tick Log --- */
.tick-log-container {
  flex: 1;
  overflow-y: auto;
  padding: 0 1.5rem 1rem;
  background: var(--surface-ground);
}

.tick-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
  font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
}

.tick-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
}

.tick-table th {
  padding: 0.6rem 0.75rem;
  text-align: left;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  font-weight: 700;
  border-bottom: 1px solid var(--layout-border);
  background: var(--surface-ground);
}

.tick-table td {
  padding: 0.45rem 0.75rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.tick-row {
  transition: background 0.15s;
}

.tick-row:hover {
  background: rgba(255, 255, 255, 0.04);
}

.col-time {
  color: var(--text-secondary);
  font-size: 0.75rem;
}

.col-ltp {
  font-weight: 800;
  font-size: 0.85rem;
}

/* --- Empty State --- */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 300px;
  color: var(--text-secondary);
  gap: 1rem;
}

.empty-state i {
  font-size: 3rem;
  opacity: 0.3;
}

.empty-state p {
  font-size: 0.95rem;
  text-align: center;
  max-width: 400px;
}

/* --- Scrollbar --- */
.tick-log-container::-webkit-scrollbar {
  width: 6px;
}

.tick-log-container::-webkit-scrollbar-track {
  background: transparent;
}

.tick-log-container::-webkit-scrollbar-thumb {
  background: var(--layout-border);
  border-radius: 10px;
}
</style>
