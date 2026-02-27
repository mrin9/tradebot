<template>
  <div class="compare-page-container">
    <ClientOnly>
      <TradeCompareComp />
    </ClientOnly>
  </div>
</template>

<script setup>
import TradeCompareComp from '~/components/TradeCompareComp.vue';

useHead({
  title: 'Trade Compare - Trade Bot'
});
</script>

<style scoped>
.compare-page-container {
  padding: 0rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
