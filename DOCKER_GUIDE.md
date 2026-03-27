# Docker 部署指南

## 架构说明

本项目使用 Docker Compose 部署两个服务：
1. **API 服务**（FastAPI + MCP）- 端口 9898
2. **Dashboard 服务**（Streamlit）- 端口 8501

两个服务共享同一个 SQLite 数据库文件（`./data/monitoring.db`）。

## 快速开始

### 1. 构建并启动所有服务

```bash
# 构建镜像
docker-compose build

# 启动服务（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 2. 访问服务

- **Dashboard**: http://localhost:8501
- **API**: http://localhost:9898

### 3. 停止服务

```bash
docker-compose down
```

## 数据持久化

数据库文件存储在 `./data/monitoring.db`，即使容器重启也不会丢失数据。

### 备份数据库

```bash
# 备份数据库
docker-compose exec dashboard sqlite3 /app/data/monitoring.db ".backup /app/data/monitoring_backup.db"

# 或者从宿主机复制
cp ./data/monitoring.db ./data/monitoring_backup_$(date +%Y%m%d).db
```

### 清理数据

```bash
# 删除数据库（重新开始）
rm ./data/monitoring.db
docker-compose restart dashboard
```

## 单独操作服务

### 只启动 Dashboard

```bash
docker-compose up -d dashboard
```

### 只启动 API

```bash
docker-compose up -d api
```

### 查看某个服务的日志

```bash
# Dashboard 日志
docker-compose logs -f dashboard

# API 日志
docker-compose logs -f api
```

### 重启某个服务

```bash
docker-compose restart dashboard
```

## 开发模式

### 本地运行 Dashboard（热重载）

```bash
# 安装依赖
pip install -r requirements.txt

# 运行 Dashboard
cd dashboard
streamlit run app.py
```

Dashboard 会自动重载代码变更。

### 进入容器调试

```bash
# 进入 Dashboard 容器
docker-compose exec dashboard bash

# 进入 API 容器
docker-compose exec api bash

# 运行测试
docker-compose exec dashboard python test_monitoring.py
```

## 配置修改

### 修改端口

编辑 `docker-compose.yml`：

```yaml
services:
  dashboard:
    ports:
      - "你的端口:8501"  # 修改这里
```

### 修改环境变量

在 `docker-compose.yml` 中添加：

```yaml
services:
  dashboard:
    environment:
      - YOUR_VAR=value
```

### 挂载代码（开发模式）

```yaml
services:
  dashboard:
    volumes:
      - ./src:/app/src  # 挂载源代码
      - ./dashboard:/app/dashboard
```

## 生产环境部署

### 使用 .env 文件

创建 `.env` 文件：

```bash
# .env
STREAMLIT_SERVER_PORT=8501
STREAMLIT_SERVER_ADDRESS=0.0.0.0
```

### 启用 HTTPS

使用反向代理（如 nginx）：

```yaml
# docker-compose.prod.yml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/nginx/certs
    depends_on:
      - dashboard
      - api
```

### 限制资源

```yaml
services:
  dashboard:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
```

## 故障排查

### Dashboard 无法启动

```bash
# 检查容器状态
docker-compose ps

# 查看详细日志
docker-compose logs dashboard

# 检查端口占用
netstat -tunlp | grep 8501
```

### 数据库锁定错误

SQLite 不支持高并发写入。如果遇到锁定错误：

1. 减少并发请求
2. 考虑使用 PostgreSQL（修改 `db.py`）
3. 增加重试逻辑

### 清理并重建

```bash
# 停止并删除容器
docker-compose down

# 删除数据
rm -rf ./data

# 重新构建
docker-compose build --no-cache

# 启动
docker-compose up -d
```

## 监控和日志

### 查看实时日志

```bash
# 所有服务
docker-compose logs -f

# 特定服务
docker-compose logs -f dashboard
```

### 导出日志

```bash
docker-compose logs > logs_$(date +%Y%m%d).txt
```

### 监控容器资源

```bash
docker stats
```

## 升级和维护

### 更新代码

```bash
git pull

# 重新构建
docker-compose build

# 重启服务
docker-compose up -d
```

### 更新依赖

```bash
# 修改 requirements.txt 后
docker-compose build --no-cache
docker-compose up -d
```

## 多环境部署

### 开发环境

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### 生产环境

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

## 备份和恢复

### 完整备份

```bash
# 备份数据库和配置
tar -czf backup_$(date +%Y%m%d).tar.gz ./data ./docker-compose.yml ./.streamlit
```

### 恢复

```bash
tar -xzf backup_20260326.tar.gz
docker-compose up -d
```

## 常见问题

### Q: Dashboard 显示空白？

A: 检查是否有数据：
```bash
docker-compose exec dashboard python test_monitoring.py
```

### Q: API 和 Dashboard 数据不同步？

A: 确保它们使用同一个数据库文件（`./data/monitoring.db`）。

### Q: 如何更改数据库位置？

A: 修改 `docker-compose.yml` 中的 volumes 配置。

## 下一步

1. 接入真实数据源（修改 `test_bench.py`）
2. 配置邮件/钉钉告警
3. 添加用户认证
4. 设置定期备份

## 支持

遇到问题请查看：
- Docker 日志：`docker-compose logs`
- Dashboard 日志：`docker-compose logs dashboard`
- 测试脚本：`docker-compose exec dashboard python test_monitoring.py`
