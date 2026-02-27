<template>
  <Button type="button" @click="toggleDarkMode" rounded text primary :icon="isDark ? 'pi pi-moon' : 'pi pi-sun'" />
</template>

<script setup>
import { ref, onMounted } from 'vue';
import Button from 'primevue/button';

const isDark = ref(false);

const toggleDarkMode = () => {
  isDark.value = !isDark.value;
  updateTheme();
};

const updateTheme = () => {
  const element = document.querySelector('html');
  if (isDark.value) {
    element.classList.add('dark-mode');
    localStorage.setItem('theme', 'dark');
  } else {
    element.classList.remove('dark-mode');
    localStorage.setItem('theme', 'light');
  }
};

onMounted(() => {
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    isDark.value = true;
    updateTheme();
  }
});
</script>
