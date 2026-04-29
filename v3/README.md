# payment-core v3

Stripe Checkout を使った自由金額決済の Django app。
Stripe SDK を gateway 層に密閉し、service 層は SDK 非依存。`USE_MOCK_STRIPE=true` で Stripe を叩かずローカル開発が可能。

---

## セットアップ

### 1. 仮想環境

```bash
cd v3
python -m venv venv
source venv/Scripts/activate    # Windows Git Bash
pip install -r requirements.txt
```

### 2. 環境変数

`.env.example` をコピーして `.env` を作成:

```bash
cp .env.example .env
```

`.env` の中身:

| key | 用途 | local 推奨値 |
|---|---|---|
| `USE_MOCK_STRIPE` | true なら Stripe API を叩かず in-memory mock で動作 | `true` |
| `STRIPE_SECRET_KEY` | Stripe API key (mock 時は使われない) | `sk_test_...` |
| `STRIPE_WEBHOOK_SECRET` | webhook 署名検証用 (mock 時は使われない) | `whsec_...` |
| `STRIPE_API_VERSION` | Stripe API version pin. Dashboard の webhook 設定と揃える | `2025-03-31.basil` (default) |
| `DJANGO_SECRET_KEY` | Django secret | 任意 |

> **注:** 本番 (`DEBUG=False`) で `USE_MOCK_STRIPE=true` は `apps.py` で `ImproperlyConfigured` を投げて起動失敗します。

### 3. マイグレーション

```bash
python manage.py migrate
```

---

## 起動

### Mock モード (推奨 / 既定)

`.env` に `USE_MOCK_STRIPE=true` を設定したうえで:

```bash
python manage.py runserver
```

Stripe API も stripe-cli も不要で end-to-end 動作する。決済起票 → ブラウザが mock 中継 URL に飛ぶ → 自動的に webhook handler を発火 → success_url にリダイレクト → polling で SUCCEEDED が見える。

**フロー確認 (curl):**

```bash
# 1. 決済起票
curl -X POST http://localhost:8000/payment/checkout/ \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ord-test-1",
    "company_id": "cmp-1",
    "company_name": "テスト株式会社",
    "amount": 1000,
    "description": "テスト決済"
  }'
# → {"url": "http://localhost:8000/payment/mock/checkout/cs_mock_xxx/"}

# 2. 返ってきた URL をブラウザで開くと、自動完了 → /payment/checkout/success/?order_id=ord-test-1 に redirect

# 3. status 確認
curl "http://localhost:8000/payment/status/?order_id=ord-test-1"
# → {"status": "succeeded", "amount": 1000, "description": "テスト決済"}
```

### 本物 Stripe モード

`.env` で `USE_MOCK_STRIPE=false` にして 2 ターミナル起動:

```bash
# ターミナル 1: Django
python manage.py runserver

# ターミナル 2: Stripe CLI (webhook 転送)
stripe login
stripe listen --forward-to localhost:8000/payment/webhook/
```

stripe-cli が出した `whsec_...` を `.env` の `STRIPE_WEBHOOK_SECRET` に設定。

**テスト用カード:**

```
カード番号: 4242 4242 4242 4242
有効期限: 12/30
CVC: 123
```

---

## 開発コマンド

### Lint / 型チェック

```bash
# ruff (lint + import 順)
ruff check .
ruff check --fix .   # auto-fix 可能なものだけ修正

# mypy (型チェック)
mypy .
```

### テスト

```bash
# 全 test 実行
pytest

# 特定ファイルだけ
pytest payment/tests/services/test_webhook_handlers.py

# 特定 test だけ
pytest payment/tests/services/test_webhook_handlers.py::test_completed_already_refunded_not_overwritten

# verbose / 失敗時 traceback 詳細
pytest -v --tb=long
```

### マイグレーション

```bash
# モデル変更後 → migration 生成
python manage.py makemigrations payment

# DB 適用
python manage.py migrate

# 適用状況確認
python manage.py showmigrations
```

---

## エンドポイント

| Method | Path | 用途 |
|---|---|---|
| `POST` | `/payment/checkout/` | 決済起票 (JSON 入力 → Stripe Checkout URL を JSON で返す) |
| `GET` | `/payment/checkout/success/?order_id=X` | Stripe success_url 戻り先 (polling 画面) |
| `GET` | `/payment/checkout/cancel/?order_id=X` | Stripe cancel_url 戻り先 (`pending → canceled` 更新) |
| `GET` | `/payment/status/?order_id=X` | 決済状態 + 表示用データ (内部 API. success.html の JS が polling) |
| `POST` | `/payment/webhook/` | Stripe からの webhook 受信 (署名検証 + 冪等性 + dispatch) |
| `GET` | `/payment/mock/checkout/<session_id>/` | **mock 専用**. `USE_MOCK_STRIPE=true` 時だけ機能 (False なら 404) |

---

## ディレクトリ構成

```
v3/
├── config/
│   ├── settings.py
│   └── urls.py
├── payment/
│   ├── apps.py                     # AppConfig (DI: mock vs real Stripe client)
│   ├── models.py                   # Payment / StripeCustomer / StripeWebhookEventLog
│   ├── views.py                    # 全 view が 1 ファイルに集約
│   ├── urls.py                     # /payment/ 配下のルーティング
│   ├── stripe/                     # ★ Stripe SDK boundary (ここだけ stripe.* を import)
│   │   ├── client.py               #   StripeClient (本物)
│   │   ├── client_mock.py          #   StripeClientMock (in-memory)
│   │   ├── dtos.py                 #   Input/Output DTO (gateway ↔ service の契約)
│   │   └── exceptions.py           #   PaymentSystemError / PaymentConfigError / WebhookSignatureError
│   ├── services/                   # ★ business logic (mock 非依存)
│   │   ├── checkout.py             #   create_checkout_url / get_payment_status
│   │   ├── webhook_handlers.py     #   3 つの event handler (DB 更新のみ)
│   │   ├── dtos.py                 #   CheckoutInput (公開 DTO)
│   │   └── exceptions.py           #   DuplicateOrderError / InvalidInputError
│   ├── templates/payment/
│   │   ├── success.html            #   polling 画面
│   │   └── cancel.html
│   ├── tests/
│   │   ├── conftest.py             #   mock_stripe_client fixture
│   │   ├── factories.py            #   factory_boy
│   │   ├── services/               #   service 層 test (39 件)
│   │   └── views/                  #   view 層 test (30 件)
│   └── migrations/
├── manage.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `ImproperlyConfigured: USE_MOCK_STRIPE=True is not allowed when DEBUG=False` | 本番設定で mock を有効にしている。`.env` の `USE_MOCK_STRIPE` を `false` に |
| webhook で 400 (`signature verification failed`) | `STRIPE_WEBHOOK_SECRET` が stripe-cli 起動時に出る `whsec_...` と不一致 |
| webhook で 502 | Stripe API 一時障害 (rate limit / network)。Stripe 側のリトライで自動回復 |
| webhook で 500 | DB エラー or 設定不整合。サーバログで stacktrace 確認 |
| `Payment row vanished after status check` | status_view 直前に Payment が削除された極低確率 race。実運用ではほぼ起きない |
