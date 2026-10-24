import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles/base.css'

// 认证机制待确认 P-26：
// dev 模式默认以「数据工程师（Maker）」身份登录，顶栏可切换角色以验证权限矩阵。
// 真实认证接入后只需替换 composables/useAuth.js 与 stores/auth.js 适配层。
useAuthStore().init()

createApp(App).use(router).mount('#app')
