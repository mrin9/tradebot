<template>
  <div class="rules-page-container">
    <ClientOnly>
      <StrategyRulesComp />
    </ClientOnly>
  </div>
</template>

<script setup>
import StrategyRulesComp from '~/components/StrategyRulesComp.vue';

useHead({
  title: 'Strategy Rules - Trade Bot'
});
</script>

<style scoped>
.rules-page-container {
  padding: 0rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
