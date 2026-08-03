# 锐取科技化学品展示与下单平台

面向内部客户的化学品采购平台，支持产品展示、购物车、下单（不付款）、后台审核与聚水潭订单导出。

## 技术栈

- **后端**：Django 5.2 + Python 3.11
- **数据库**：SQLite（开发）/ PostgreSQL（生产）
- **前端**：Django Templates + Vanilla JS + CSS
- **部署**：Docker + Caddy（可选）

## 功能概览

| 模块 | 功能 |
|------|------|
| 产品展示 | 三级分类、搜索筛选、品牌/属性过滤、产品详情、SKU 选型 |
| 价格保护 | 未登录用户不可见价格，显示"登录后查看" |
| 注册机制 | 内部审核制 — 客户提交申请 → 管理员后台审核 → 通过后登录 |
| 购物车 | 加购、改数量、删商品 |
| 下单 | 提交后进入"待公司确认"状态，不跳转支付 |
| 后台管理 | 订单审核（确认/拒绝）、聚水潭 Excel 导出、注册申请审核 |
| 商品管理 | 产品/SKU/分类/属性导入导出（Excel） |

## 快速启动

### 环境要求

- Python 3.11+（建议使用 Conda 或 venv）
- Docker（可选，用于生产部署）

### 本地开发（推荐）

```bash
# 1. 创建虚拟环境
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 初始化数据库
.venv/bin/python manage.py migrate

# 3. 导入示例数据（92 个分类、210 个产品、1050 个 SKU）
.venv/bin/python manage.py seed_data --clear --products-per-category=3 --skus-per-product=5

# 4. 创建管理员账号
.venv/bin/python manage.py createsuperuser

# 5. 启动开发服务器
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

访问：
- 前台：http://127.0.0.1:8000/
- 后台：http://127.0.0.1:8000/admin/

### Docker 开发（可选）

```bash
./start_server_dev.sh
```

访问：
- Caddy HTTP：http://localhost:8080/
- Caddy HTTPS：https://localhost:8443/
- 前台直连：http://127.0.0.1:8000/
- 后台直连：http://127.0.0.1:8000/admin/

### 生产部署

```bash
./start_server_prod.sh
```

详情参考 [生产域名配置](#生产域名配置) 章节。

## 项目结构

```
ruiqu-mall/
├── accounts/          # 客户账号、注册申请审核、用户资料
├── cart/             # 购物车（Session 存储）
├── catalog/          # 产品、SKU、分类、分类属性
│   ├── management/commands/
│   │   └── seed_data.py    # 种子数据命令
│   └── models.py           # Category, Product, SKU, CategoryAttribute
├── core/             # 系统配置、审计日志
├── customers/       # 客户信息、收货地址
├── integrations/     # 聚水潭导出、字段映射
├── orders/           # 订单、订单明细
├── ruiqu/           # Django 项目配置
├── static/          # CSS、JS、图片资源
└── templates/       # HTML 模板
```

## 核心业务流程

### 1. 客户注册与审核

1. 客户访问 `/accounts/register/` 填写注册申请（公司名、联系人、电话、用户名）
2. 申请进入"待审核"状态
3. 管理员在后台 `/admin/accounts/registrationrequest/` 审核
4. 点击"通过"自动创建账号；点击"拒绝"记录原因

### 2. 产品浏览与选型

1. 首页展示一级分类入口，鼠标悬停显示二级/三级分类
2. 分类页按分类展示产品列表，支持品牌、颜色、包规、分类属性筛选
3. 产品详情页选择 SKU 颜色、包规等属性，确认后加入购物车

### 3. 下单与审核

1. 客户登录后选择购物车商品，填写收货地址，提交订单
2. 订单状态为"待公司确认"，流转到后台
3. 管理员审核订单：
   - 点击"确认" → 状态变为"待导入聚水潭"
   - 点击"拒绝" → 状态变为"已取消"
4. 管理员可在订单详情页修改价格、数量、库存确认状态
5. 点击"导出聚水潭模板"生成 Excel 文件下载

### 4. 聚水潭导出

在 Django Admin 的订单列表中勾选已确认订单，执行"导出选中订单为聚水潭模板"。

导出前校验：收货人/电话/地址不为空、SKU 聚水潭编码不为空、数量>0、单价已确认。

导出文件保存在 `media/jst_exports/`，批次记录在"聚水潭导出批次"。

## 商品数据导入

### 导入分类和属性模板

```bash
docker compose run --rm web python manage.py import_categories 总目录.xlsx
```

### 导入商品/SKU

```bash
# 正式导入（校验价格和分类必填）
docker compose run --rm web python manage.py import_products 商品资料.xlsx

# 开发测试导入（允许价格和分类为空）
docker compose run --rm web python manage.py import_products 商品资料.xlsx --dev-allow-missing-price-category
```

## 测试

```bash
# 系统检查
.venv/bin/python manage.py check

# 运行测试
.venv/bin/python manage.py test
```

## 生产域名配置

上线到 `ruiqu168.com` 时，在 `.env` 或启动脚本中设置：

```bash
export DJANGO_DEBUG=False
export DJANGO_SECRET_KEY='your-secret-key-here'
export DJANGO_ALLOWED_HOSTS='ruiqu168.com,www.ruiqu168.com'
export DJANGO_CSRF_TRUSTED_ORIGINS='https://ruiqu168.com,https://www.ruiqu168.com'
export CADDY_SITE_ADDRESS='ruiqu168.com, www.ruiqu168.com'
```

Caddy 会自动申请和续期 HTTPS 证书。确保域名 DNS 已指向服务器，防火墙放行 `80/tcp`、`443/tcp`、`443/udp`。

生产环境收集静态文件：

```bash
docker compose run --rm web python manage.py collectstatic --noinput
```

使用 Docker + Caddy 启动生产服务：

```bash
./start_server_prod.sh
```

## 常用命令

| 命令 | 说明 |
|------|------|
| `seed_data --clear` | 清空并重新生成示例数据 |
| `seed_data --products-per-category=5` | 每个叶子分类生成 5 个产品 |
| `createsuperuser` | 创建管理员账号 |
| `import_categories <file>` | 导入分类 Excel |
| `import_products <file>` | 导入商品 Excel |
| `migrate` | 执行数据库迁移 |
| `collectstatic --noinput` | 收集静态文件 |

## 目录说明

- `media/` — 上传文件（产品图片、聚水潭导出文件）
- `static/` — CSS、JS、图片
- `templates/` — Django HTML 模板
- `db.sqlite3` — SQLite 数据库（开发）

## 待扩展功能（二期）

- 聚水潭 API 直连上传订单
- 客户专属价格 / 阶梯价
- 库存实时同步
- 发票、对账单、合同附件
- 多角色权限管理
