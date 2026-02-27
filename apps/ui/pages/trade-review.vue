<template>
  <div class="review-page-container">
    <ClientOnly>
      <TradeReviewComp />
    </ClientOnly>
  </div>
</template>

<script setup>
import TradeReviewComp from '~/components/TradeReviewComp.vue';

useHead({
  title: 'Trade Review - Trade Bot'
});
</script>

<style scoped>
.review-page-container {
  padding: 0rem;
  height: 100%;
  display: flex;
  flex-direction: column;
}
</style>
