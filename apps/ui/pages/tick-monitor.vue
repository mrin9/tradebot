<template>
  <div class="monitor-page-container">
    <ClientOnly>
      <TickMonitorComp />
    </ClientOnly>
  </div>
</template>

<script setup>
import TickMonitorComp from '~/components/TickMonitorComp.vue';

useHead({
  title: 'Tick Monitor - Trade Bot'
});
</script>

<style scoped>
.monitor-page-container {
  padding: 0rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
