import Aura from '@primeuix/themes/aura';

export default defineNuxtConfig({
    compatibilityDate: '2024-04-03',
    devtools: { enabled: true },
    modules: [
        '@primevue/nuxt-module'
    ],
    primevue: {
        usePrimeVue: true,
        autoImport: true,
        options: {
            theme: {
                preset: Aura,
                options: {
                    darkModeSelector: '.dark-mode',
                    cssLayer: false
                }
            }
        }
    },
    css: [
        '~/assets/css/theme.css',
        '~/assets/css/utilities.css',
        '~/assets/css/layout.css'
    ],
    vite: {
        server: {
            proxy: {
                '/api': {
                    target: 'http://127.0.0.1:8000',
                    changeOrigin: true
                },
                '/simulation-socket': {
                    target: 'ws://127.0.0.1:8000',
                    ws: true
                }
            }
        }
    }
});
