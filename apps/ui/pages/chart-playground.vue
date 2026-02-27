<template>
  <div class="playground-page-container">
    <ClientOnly>
      <ChartPlaygroundComp />
    </ClientOnly>
  </div>
</template>

<script setup>
import ChartPlaygroundComp from '~/components/ChartPlaygroundComp.vue';

useHead({
  title: 'Chart Playground - Trade Bot'
});
</script>

<style scoped>
.playground-page-container {
  padding: 0rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
