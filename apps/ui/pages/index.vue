<template>
  <div class="grid">
    <div class="col-12"></div>
    <div class="content-grid">
      <div class="main-chart-view">
        <ClientOnly>
          <DashboardChartContainerComp />
        </ClientOnly>
      </div>
    </div>
  </div>
</template>

<script setup>
import DashboardChartContainerComp from '~/components/DashboardChartContainerComp.vue';

useHead({
  title: 'Trade Bot - Dashboard'
});
</script>

<style scoped>
.welcome-header {
  margin-bottom: 2rem;
}

.welcome-header h1 {
  font-size: 2.25rem;
  font-weight: 800;
  margin: 0;
  color: var(--text-main);
}

.welcome-header p {
  color: var(--text-muted);
  font-size: 1.125rem;
  margin-top: 0.5rem;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.5rem;
}

@media (max-width: 1200px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
