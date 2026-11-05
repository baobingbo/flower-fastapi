# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.9.0] - 2025-07-16

### Added
- **用户模块JWT迁移**：`/api/auth/login` 返回JWT Bearer token，`get_current_user()` 仅校验 Bearer 认证
- **登录限流（S-1）**：新增 `backend/app/services/rate_limiter.py`，基于滑动窗口计数器的 `LoginRateLimiter` 类；`POST /api/auth/login` 失败 5 次后返回 429，支持 `GET /api/auth/lockout/status` 查询锁定状态；登录成功后自动重置计数器
- **密码复杂度校验（S-2）**：`security.py` 扩展 `_WEAK_PASSWORDS` 弱密码黑名单至 10 个常用弱密码（`password`, `123456`, `admin`, `qwerty`, `letmein`, `welcome`, `monkey`, `dragon`, `master`, `login`）；`validate_password()` 校验长度/大小写/数字/特殊字符（配置驱动）；`POST /api/auth/password/change` 强制调用校验
- **时序侧信道防御（S-4）**：`verify_basic_credentials()` 遍历全部凭据列表，无 early-exit，始终执行 `hmac.compare_digest`，最终 OR 结果

### Changed
- **鉴权方式**：`get_current_user()` 仅支持 `Authorization: Bearer <token>`，不再从请求头解析 Basic Auth
- 密码策略改为可配置：`password_min_length`、`password_require_upper`、`password_require_digit`、`password_require_special` 通过环境变量或运行时配置设置

### Breaking Changes
- **Basic Auth Header 不再支持**：所有需要鉴权的接口（`/api/system` 等）仅接受 `Authorization: Bearer <token>`，`Authorization: Basic base64(user:pass)` 将返回 401
- 迁移指南见 [docs/鉴权迁移指南.md](docs/鉴权迁移指南.md)
- 过渡期：设置 `legacy_basic_auth_enabled=True`（环境变量或运行时配置）可保留 Basic Auth 兼容 2 周

### Security
- S-1: 登录限流防止暴力破解
- S-2: 密码复杂度防止弱密码
- S-4: 时序侧信道防御防止凭据枚举
