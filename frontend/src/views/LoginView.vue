<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { authApi } from '@/api'
import ThemeSwitcher from '@/components/ThemeSwitcher.vue'
import { useAppStore } from '@/stores/app'
import { useThemeStore } from '@/stores/theme'

const store = useAppStore()
const theme = useThemeStore()
const router = useRouter()
const route = useRoute()

const form = reactive({ username: '', password: '', remember: true })
const loading = ref(false)
const checking = ref(true)
const formRef = ref(null)
const oauthLoading = ref(false)
const oauthError = ref('')

/** OAuth2 失败回跳的友好文案 */
const OAUTH_ERROR_TEXT = {
  invalid_state: '登录状态已失效或验证不通过，请重新发起登录',
  not_allowed: '该账号不在允许的白名单内，无法登录',
  token_failed: '与 OAuth2 提供方交换令牌失败，请检查系统配置后重试',
  provider_denied: '你已在提供方页面取消授权或提供方返回错误，请重试'
}

const oauthAvailable = computed(() => !!(store.authInfo || {}).oauth2_configured)
const providerName = computed(() => (store.authInfo || {}).oauth2_provider || 'OAuth')

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const providerHint = computed(() => {
  const info = store.authInfo || {}
  if (info.oauth2) {
    let text = `已启用 OAuth（${info.auth_provider || '第三方'}）`
    if (info.flower_compatible_mode) {
      text += ' [Flower 兼容模式]'
    }
    return text
  }
  return '凭据由服务端 --basic_auth / FLOWER_BASIC_AUTH 配置'
})

onMounted(async () => {
  theme.init()

  // OAuth2 授权回跳：后端 302 回站点根路径并携带 ?token / ?oauth_error
  // （前端为 hash 路由，这些参数在 location.search 上而非 route.query 上）
  const params = new URLSearchParams(window.location.search)
  const oauthToken = params.get('token')
  const oauthUser = params.get('user')
  const oauthErr = params.get('oauth_error')
  if (oauthToken || oauthErr) {
    // 先清理地址栏 query，避免令牌残留在 URL 中
    history.replaceState(history.state, '', window.location.pathname + window.location.hash)
    if (oauthErr) oauthError.value = OAUTH_ERROR_TEXT[oauthErr] || `OAuth2 登录失败（${oauthErr}）`
  }

  const enabled = await store.loadAuthConfig()
  checking.value = false

  if (oauthToken) {
    // OAuth2 登录成功：与账号密码登录同机制落地令牌（localStorage + Bearer）
    store.token = oauthToken
    if (oauthUser) {
      store.user = oauthUser
      localStorage.setItem('flower_user', oauthUser)
    }
    localStorage.setItem('flower_token', oauthToken)
    ElMessage.success('登录成功')
    router.replace({ name: 'dashboard' })
    return
  }

  // 服务端没开鉴权就没有登录的必要，直接放行到监控页
  if (!enabled) router.replace({ name: 'dashboard' })

  const remembered = localStorage.getItem('flower_login_user')
  if (remembered) form.username = remembered
})

async function submit() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    await store.login(form.username, form.password)
    if (form.remember) localStorage.setItem('flower_login_user', form.username)
    else localStorage.removeItem('flower_login_user')
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || { name: 'dashboard' })
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message
    ElMessage.error(typeof detail === 'string' ? detail : '用户名或密码错误')
  } finally {
    loading.value = false
  }
}

/** 通用 OAuth2 授权码登录：取 redirect_url 后整页跳转提供方授权页 */
async function oauthLogin() {
  if (oauthLoading.value) return
  oauthLoading.value = true
  try {
    const res = await authApi.oauthLogin()
    const url = res && res.redirect_url
    if (!url) throw new Error('missing redirect_url')
    window.location.href = url
  } catch (err) {
    const detail = err?.response?.data?.detail || err?.message
    ElMessage.error(typeof detail === 'string' && detail ? detail : 'OAuth2 登录发起失败')
    oauthLoading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <!-- 装饰层：液态光斑，颜色全部取自主题令牌 -->
    <div class="orb orb-a" />
    <div class="orb orb-b" />
    <div class="orb orb-c" />
    <div class="grid-lines" />

    <div class="login-topbar">
      <ThemeSwitcher />
    </div>

    <div class="login-wrap">
      <div class="login-hero">
        <div class="hero-logo">🌸</div>
        <h1 class="hero-title">FlowerUI</h1>
        <p class="hero-sub">Celery 实时监控与管理平台</p>
        <ul class="hero-points">
          <li><el-icon><Odometer /></el-icon>实时吞吐趋势与任务状态分布</li>
          <li><el-icon><Cpu /></el-icon>Worker 进程池伸缩与队列消费控制</li>
          <li><el-icon><Promotion /></el-icon>任务下发、撤销、限流与结果追踪</li>
        </ul>
      </div>

      <div class="login-card" v-loading="checking">
        <div class="card-head">
          <div class="card-title">登录</div>
          <div class="card-sub">服务端已开启访问鉴权，请先验证身份</div>
        </div>

        <div v-if="oauthError" class="oauth-error">{{ oauthError }}</div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          hide-required-asterisk
          autocomplete="off"
          @keyup.enter="submit"
        >
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" name="fu-login-user" autocomplete="off">
              <template #prefix><el-icon><User /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              show-password
              name="fu-login-pass"
              autocomplete="off"
            >
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>

          <div class="row-between">
            <el-checkbox v-model="form.remember" size="small">记住用户名</el-checkbox>
            <span class="text-muted tip-sm">令牌有效期由服务端配置</span>
          </div>

          <el-button type="primary" class="login-btn" :loading="loading" @click="submit">
            登录
          </el-button>
        </el-form>

        <template v-if="oauthAvailable">
          <div class="oauth-divider"><span>其它登录方式</span></div>
          <el-button class="login-btn" plain :loading="oauthLoading" @click="oauthLogin">
            使用 {{ providerName }} 登录
          </el-button>
        </template>

        <div class="login-tip">{{ providerHint }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background-color: var(--fu-bg);
  background-image: var(--fu-app-bg-image);
  padding: 24px;
}

/* ---------------- 装饰 ---------------- */
.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(70px);
  opacity: 0.5;
  pointer-events: none;
}

.orb-a {
  width: 420px;
  height: 420px;
  background: var(--fu-brand);
  top: -110px;
  left: -80px;
  animation: float-a 18s var(--fu-ease) infinite alternate;
}

.orb-b {
  width: 380px;
  height: 380px;
  background: var(--fu-chart-5);
  bottom: -120px;
  right: -70px;
  animation: float-b 22s var(--fu-ease) infinite alternate;
}

.orb-c {
  width: 300px;
  height: 300px;
  background: var(--fu-chart-2);
  top: 46%;
  right: 22%;
  opacity: 0.28;
  animation: float-c 26s var(--fu-ease) infinite alternate;
}

@keyframes float-a {
  to {
    transform: translate(70px, 60px) scale(1.12);
  }
}

@keyframes float-b {
  to {
    transform: translate(-60px, -50px) scale(1.08);
  }
}

@keyframes float-c {
  to {
    transform: translate(-40px, 60px) scale(0.92);
  }
}

.grid-lines {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.32;
  background-image:
    linear-gradient(var(--fu-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--fu-border) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(ellipse 80% 60% at 50% 50%, #000 20%, transparent 78%);
  -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 50%, #000 20%, transparent 78%);
}

.login-topbar {
  position: absolute;
  top: 18px;
  right: 22px;
  z-index: 3;
}

/* ---------------- 主体 ---------------- */
.login-wrap {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 64px;
  max-width: 980px;
  width: 100%;
  justify-content: center;
}

.login-hero {
  max-width: 380px;
  color: var(--fu-text);
}

.hero-logo {
  font-size: 46px;
  line-height: 1;
}

.hero-title {
  font-size: 40px;
  font-weight: 750;
  margin: 14px 0 6px;
  letter-spacing: -0.5px;
  background: linear-gradient(120deg, var(--fu-text) 20%, var(--fu-brand) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-sub {
  font-size: 15px;
  color: var(--fu-text-muted);
  margin: 0 0 26px;
}

.hero-points {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 12px;
}

.hero-points li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
  color: var(--fu-text-secondary);
}

.hero-points .el-icon {
  color: var(--fu-brand);
  flex-shrink: 0;
}

/* ---------------- 卡片 ---------------- */
.login-card {
  width: 372px;
  flex-shrink: 0;
  background-color: var(--fu-card);
  background-image: var(--fu-card-bg-image);
  border: 1px solid var(--fu-border);
  border-radius: var(--fu-radius-lg);
  padding: 30px 30px 24px;
  box-shadow: var(--fu-shadow-lg);
}

.card-head {
  margin-bottom: 22px;
}

.card-title {
  font-size: 21px;
  font-weight: 700;
  color: var(--fu-text);
}

.card-sub {
  font-size: 12.5px;
  color: var(--fu-text-muted);
  margin-top: 5px;
}

.row-between {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -4px 0 16px;
}

.tip-sm {
  font-size: 11.5px;
}

.login-btn {
  width: 100%;
}

.login-tip {
  margin-top: 18px;
  font-size: 11.5px;
  color: var(--fu-text-muted);
  text-align: center;
  line-height: 1.6;
}

/* ---------------- OAuth2 ---------------- */
.oauth-error {
  margin-bottom: 16px;
  padding: 9px 12px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--el-color-danger) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--el-color-danger) 40%, transparent);
  color: var(--el-color-danger);
  font-size: 12.5px;
  line-height: 1.5;
}

.oauth-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 18px 0 12px;
  font-size: 12px;
  color: var(--fu-text-muted);
}

.oauth-divider::before,
.oauth-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--fu-border);
}

@media (max-width: 880px) {
  .login-hero {
    display: none;
  }

  .login-wrap {
    gap: 0;
  }
}
</style>