<template>
  <div class="strategy-rules-page">
    <div class="page-header">
      <div class="page-header-top">
        <div>
          <h1><i class="pi pi-book"></i> Strategy Rules</h1>
          <p class="subtitle">{{ rules.length }} rules loaded from the engine</p>
        </div>
        <Button label="Reset to Defaults" icon="pi pi-refresh" severity="secondary" outlined size="small"
          @click="resetRules" :loading="resetting" />
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <i class="pi pi-spin pi-spinner" style="font-size:2rem"></i>
    </div>

    <div v-else class="rules-grid">
      <div v-for="rule in rules" :key="rule.rule_id" class="rule-card">
        <!-- Card Header -->
        <div class="rule-header">
          <div class="rule-title-row">
            <div class="rule-meta">
              <Tag :value="rule.category" :severity="categoryColor(rule.category)" class="cat-tag" />
              <Tag :value="rule.enabled ? 'ENABLED' : 'DISABLED'" :severity="rule.enabled ? 'success' : 'danger'"
                class="status-tag" />
            </div>
            <div class="rule-actions">
              <Button icon="pi pi-book" text rounded size="small" severity="secondary" title="View Documentation"
                @click="openDrawer(rule)" />
              <Button icon="pi pi-pencil" text rounded size="small" severity="secondary" title="Edit Rule"
                @click="openEditDialog(rule)" />
            </div>
          </div>
          <h2 class="rule-name">{{ rule.name }}</h2>
          <div class="rule-id">{{ rule.rule_id }}</div>
          <p class="rule-goal">{{ rule.goal }}</p>
        </div>

        <!-- Indicators -->
        <div class="rule-section">
          <div class="section-label"><i class="pi pi-chart-line"></i> Indicators</div>
          <div class="indicators-list">
            <span v-for="ind in rule.indicators" :key="ind.indicatorId" v-tooltip.top="indicatorTooltip(ind)"
              class="indicator-chip">
              {{ indicatorShorthand(ind) }}
            </span>
          </div>
        </div>

        <!-- Entry Conditions -->
        <div class="rule-section">
          <div class="section-label">
            <i class="pi pi-sign-in"></i> Entry
            <Tag :value="rule.entry.operator" severity="info" class="op-tag" />
          </div>
          <div class="signals-row" v-if="rule.entry.signals">
            <span class="signal-label">Signal</span>
            <Tag v-if="rule.entry.signals['1']" :value="rule.entry.signals['1'] + ' (+1)'"
              :severity="rule.entry.signals['1'] === 'Buy CALL' ? 'success' : 'warn'" class="signal-tag" />
            <Tag v-if="rule.entry.signals['-1']" :value="rule.entry.signals['-1'] + ' (-1)'"
              :severity="rule.entry.signals['-1'] === 'Buy PUT' ? 'warn' : rule.entry.signals['-1'] === 'exit' ? 'danger' : 'success'"
              class="signal-tag" />
          </div>
          <div class="conditions-list">
            <div v-for="(cond, ci) in rule.entry.conditions" :key="ci" class="condition-chip">
              <span class="cond-badge">{{ cond.type }}</span>
              <span class="cond-detail">{{ formatCondition(cond) }}</span>
            </div>
          </div>
        </div>

        <!-- Exit Conditions -->
        <div class="rule-section">
          <div class="section-label">
            <i class="pi pi-sign-out"></i> Exit
            <Tag :value="rule.exit.operator" severity="warn" class="op-tag" />
          </div>
          <div class="conditions-list">
            <div v-for="(cond, ci) in rule.exit.conditions" :key="ci" class="condition-chip">
              <span class="cond-badge">{{ cond.type }}</span>
              <span class="cond-detail">{{ formatCondition(cond) }}</span>
            </div>
          </div>
        </div>

        <!-- Restrictions -->
        <div class="rule-section"
          v-if="rule.restrictions && (rule.restrictions.avoidWindows?.length || rule.restrictions.maxTradesPerDay)">
          <div class="section-label"><i class="pi pi-shield"></i> Restrictions</div>
          <div class="restrictions-row">
            <Tag v-for="(w, wi) in (rule.restrictions.avoidWindows || [])" :key="wi"
              :value="'🚫 ' + w.from + '–' + w.to" severity="danger" class="restriction-tag" />
            <Tag v-if="rule.restrictions.maxTradesPerDay"
              :value="'Max ' + rule.restrictions.maxTradesPerDay + ' trades/day'" severity="secondary"
              class="restriction-tag" />
          </div>
        </div>

        <!-- Applicable To -->
        <div class="rule-footer">
          <div class="applicable-row">
            <Tag v-for="inst in rule.applicableTo" :key="inst" :value="inst" severity="contrast" class="inst-tag" />
          </div>
        </div>
      </div>
    </div>

    <!-- Documentation Drawer -->
    <Drawer v-model:visible="drawerVisible" position="right" :header="drawerRule?.name || 'Documentation'"
      class="doc-drawer" :pt="{ root: { style: 'width: 650px' } }">
      <div v-if="drawerRule" class="drawer-content">
        <div class="drawer-meta">
          <Tag :value="drawerRule.category" :severity="categoryColor(drawerRule.category)" />
          <Tag :value="drawerRule.rule_id" severity="secondary" />
        </div>
        <div class="markdown-body" v-html="renderedMarkdown"></div>
      </div>
    </Drawer>

    <!-- Edit Dialog -->
    <Dialog v-model:visible="editDialogVisible" modal :header="'Edit: ' + (editingRule?.name || '')"
      :style="{ width: '600px' }" class="edit-dialog">
      <div v-if="editingRule" class="edit-form">
        <div class="edit-field">
          <label>Name</label>
          <InputText v-model="editForm.name" class="w-full" />
        </div>
        <div class="edit-field">
          <label>Goal</label>
          <Textarea v-model="editForm.goal" rows="3" class="w-full" />
        </div>
        <div class="edit-row">
          <div class="edit-field flex-1">
            <label>Category</label>
            <Select v-model="editForm.category" :options="categoryOptions" class="w-full" />
          </div>
          <div class="edit-field flex-1">
            <label>Enabled</label>
            <ToggleSwitch v-model="editForm.enabled" />
          </div>
        </div>
        <div class="edit-field">
          <label>Max Trades / Day</label>
          <InputNumber v-model="editForm.maxTradesPerDay" :min="1" :max="20" class="w-full" />
        </div>
      </div>
      <template #footer>
        <div class="edit-footer">
          <Button label="Cancel" text severity="secondary" @click="editDialogVisible = false" />
          <Button label="Save" icon="pi pi-check" @click="saveRule" :loading="saving" />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
import Tag from 'primevue/tag';
import Button from 'primevue/button';
import InputText from 'primevue/inputtext';
import Textarea from 'primevue/textarea';
import InputNumber from 'primevue/inputnumber';
import Select from 'primevue/select';
import ToggleSwitch from 'primevue/toggleswitch';
import Dialog from 'primevue/dialog';
import Drawer from 'primevue/drawer';
import Tooltip from 'primevue/tooltip';
import { marked } from 'marked';

const vTooltip = Tooltip;

const rules = ref([]);
const loading = ref(true);

// Drawer state
const drawerVisible = ref(false);
const drawerRule = ref(null);

// Edit dialog state
const editDialogVisible = ref(false);
const editingRule = ref(null);
const editForm = reactive({ name: '', goal: '', category: '', enabled: true, maxTradesPerDay: null });
const saving = ref(false);
const categoryOptions = ['SCALP', 'TREND', 'SWING', 'REVERSAL'];
const resetting = ref(false);

const renderedMarkdown = computed(() => {
  if (!drawerRule.value?.explanation) return '<p class="no-docs">No documentation available for this rule.</p>';
  return marked.parse(drawerRule.value.explanation);
});

// --- Data ---
async function fetchRules() {
  loading.value = true;
  try {
    const res = await fetch('/api/strategy-rules');
    if (res.ok) rules.value = await res.json();
  } catch (e) {
    console.error('Failed to fetch strategy rules:', e);
  } finally {
    loading.value = false;
  }
}

// --- Edit Dialog ---
function openEditDialog(rule) {
  editingRule.value = rule;
  editForm.name = rule.name;
  editForm.goal = rule.goal;
  editForm.category = rule.category;
  editForm.enabled = rule.enabled;
  editForm.maxTradesPerDay = rule.restrictions?.maxTradesPerDay || null;
  editDialogVisible.value = true;
}

async function saveRule() {
  saving.value = true;
  try {
    const body = {
      name: editForm.name,
      goal: editForm.goal,
      category: editForm.category,
      enabled: editForm.enabled,
    };
    if (editForm.maxTradesPerDay !== null) {
      body['restrictions.maxTradesPerDay'] = editForm.maxTradesPerDay;
    }
    const res = await fetch(`/api/strategy-rules/${editingRule.value.rule_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (res.ok) {
      // Update local state
      const rule = rules.value.find(r => r.rule_id === editingRule.value.rule_id);
      rule.name = editForm.name;
      rule.goal = editForm.goal;
      rule.category = editForm.category;
      rule.enabled = editForm.enabled;
      if (editForm.maxTradesPerDay !== null && rule.restrictions) {
        rule.restrictions.maxTradesPerDay = editForm.maxTradesPerDay;
      }
      editDialogVisible.value = false;
    }
  } catch (e) {
    console.error('Failed to save rule:', e);
  } finally {
    saving.value = false;
  }
}

// --- Drawer ---
function openDrawer(rule) {
  drawerRule.value = rule;
  drawerVisible.value = true;
}

// --- Formatters ---
function categoryColor(cat) {
  const map = { SCALP: 'warn', TREND: 'info', SWING: 'success', REVERSAL: 'danger' };
  return map[cat] || 'secondary';
}

function indicatorShorthand(ind) {
  const type = ind.type.toUpperCase();
  const vals = Object.values(ind.params);
  return `${type}-${vals.join('-')}`;
}

function indicatorTooltip(ind) {
  const type = ind.type.charAt(0).toUpperCase() + ind.type.slice(1);
  const label = ind.displayLabel || ind.indicatorId;
  const params = Object.entries(ind.params).map(([k, v]) => `${k.charAt(0).toUpperCase() + k.slice(1)}: ${v}`).join(', ');
  const tf = formatTimeframe(ind.timeframe);
  return `${label} (${type}) › ${params}, Candle: ${tf}`;
}

function formatTimeframe(tf) {
  if (tf >= 3600) return `${tf / 3600}h`;
  if (tf >= 60) return `${tf / 60}m`;
  return `${tf}s`;
}

function formatCondition(cond) {
  switch (cond.type) {
    case 'crossover':
      return `${cond.fastIndicatorId || cond.fast} ✕↑ ${cond.slowIndicatorId || cond.slow}`;
    case 'crossunder':
      return `${cond.fastIndicatorId || cond.fast} ✕↓ ${cond.slowIndicatorId || cond.slow}`;
    case 'threshold':
      return `${cond.indicatorId || cond.indicator} ${cond.op} ${cond.value}`;
    case 'direction_match':
      return `${cond.indicatorId || cond.indicator} dir ${cond.op} ${cond.value}`;
    case 'slope':
      return `${cond.indicatorId || cond.indicator} slope ${cond.op} ${cond.value}`;
    case 'compare':
      return `${cond.left} ${cond.op} ${cond.right}`;
    default:
      return JSON.stringify(cond);
  }
}

async function resetRules() {
  resetting.value = true;
  try {
    const res = await fetch('/api/strategy-rules/reset', { method: 'POST' });
    if (res.ok) {
      await fetchRules();
    }
  } catch (e) {
    console.error('Failed to reset rules:', e);
  } finally {
    resetting.value = false;
  }
}

onMounted(fetchRules);
</script>

<style scoped>
.strategy-rules-page {
  padding: 0.5rem;
}

.page-header {
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.page-header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.page-header h1 i {
  color: var(--primary-color);
}

.subtitle {
  margin: 0.25rem 0 0 0;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 200px;
  color: var(--text-secondary);
}

/* Rules Grid */
.rules-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 1rem;
}

/* Rule Card */
.rule-card {
  background: var(--layout-glass-bg);
  border: 1px solid var(--layout-border);
  border-radius: var(--card-border-radius);
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  transition: all 0.3s ease;
}

.rule-card:hover {
  border-color: rgba(var(--p-primary-500), 0.3);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

/* Header */
.rule-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.rule-meta {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.rule-actions {
  display: flex;
  gap: 0.25rem;
}

.rule-name {
  margin: 0.5rem 0 0;
  font-size: 1.1rem;
  font-weight: 800;
}

.rule-id {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.7rem;
  color: var(--text-secondary);
  margin-top: 0.15rem;
}

.rule-goal {
  margin: 0.5rem 0 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* Sections */
.rule-section {
  border-top: 1px solid var(--layout-border);
  padding-top: 0.75rem;
}

.section-label {
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-label i {
  font-size: 0.85rem;
}

.op-tag {
  font-size: 0.65rem !important;
  padding: 0.1rem 0.4rem !important;
}

/* Indicators — compact shorthand chips */
.indicators-list {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.indicator-chip {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.3rem 0.6rem;
  border-radius: 6px;
  background: rgba(var(--p-primary-500), 0.08);
  border: 1px solid rgba(var(--p-primary-500), 0.15);
  color: var(--primary-color);
  cursor: default;
  transition: all 0.2s;
}

.indicator-chip:hover {
  background: rgba(var(--p-primary-500), 0.15);
  border-color: var(--primary-color);
}

/* Conditions */
.conditions-list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.condition-chip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  padding: 0.3rem 0.5rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border: 1px solid var(--layout-border);
}

.cond-badge {
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  background: rgba(var(--p-primary-500), 0.12);
  color: var(--primary-color);
  white-space: nowrap;
  min-width: 85px;
  text-align: center;
}

.cond-detail {
  font-family: 'Monaco', 'Menlo', monospace;
  font-size: 0.75rem;
}

/* Signals */
.signals-row {
  display: flex;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
  align-items: center;
}

.signal-label {
  font-size: 0.7rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin-right: 0.15rem;
}

.signal-tag {
  font-size: 0.7rem !important;
  font-family: 'Monaco', 'Menlo', monospace;
}

/* Restrictions */
.restrictions-row {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.restriction-tag {
  font-size: 0.7rem !important;
}

/* Footer */
.rule-footer {
  border-top: 1px solid var(--layout-border);
  padding-top: 0.75rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.applicable-row {
  display: flex;
  gap: 0.35rem;
}

.inst-tag {
  font-size: 0.7rem !important;
}

/* Drawer */
.drawer-content {
  padding: 0.5rem;
}

.drawer-meta {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.25rem;
}

/* Markdown Styling */
.markdown-body {
  font-size: 0.9rem;
  line-height: 1.7;
  color: var(--text-color);
}

.markdown-body :deep(h2) {
  font-size: 1.25rem;
  font-weight: 800;
  margin: 0 0 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid var(--layout-border);
}

.markdown-body :deep(h3) {
  font-size: 1rem;
  font-weight: 800;
  margin: 1.25rem 0 0.5rem;
  color: var(--primary-color);
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.75rem 0;
  font-size: 0.82rem;
}

.markdown-body :deep(th) {
  background: rgba(var(--p-primary-500), 0.08);
  font-weight: 800;
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 2px solid var(--layout-border);
}

.markdown-body :deep(td) {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--layout-border);
  vertical-align: top;
}

.markdown-body :deep(strong) {
  color: var(--text-color);
}

.markdown-body :deep(code) {
  font-size: 0.8rem;
  background: rgba(var(--p-primary-500), 0.08);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  color: var(--primary-color);
}

.markdown-body :deep(ol),
.markdown-body :deep(ul) {
  padding-left: 1.25rem;
  margin: 0.5rem 0;
}

.markdown-body :deep(li) {
  margin-bottom: 0.35rem;
}

.markdown-body :deep(p) {
  margin: 0.5rem 0;
}

.markdown-body :deep(em) {
  color: var(--text-secondary);
}

.no-docs {
  color: var(--text-secondary);
  font-style: italic;
}

/* Edit Dialog */
.edit-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.edit-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.edit-field label {
  font-size: 0.78rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.edit-row {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.flex-1 {
  flex: 1;
}

.w-full {
  width: 100%;
}

.edit-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}
</style>
