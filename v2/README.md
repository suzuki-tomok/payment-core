# payment-core v2

自由金額決済を題材にした Django payment app。
他の Django app から Python 関数として呼ばれ、Stripe Checkout で決済を行う。

## 特徴

- **公開 API は 1 ファイル (`payment/api.py`) に集約**: 入口が物理的に明白
- **race condition 三段防御**: `exists()` 早期検知 + Stripe `idempotency_key` + DB `IntegrityError` ガード
- **状態を 2 カラムに分離**: UX フロー (`session_status`) と業務判定 (`payment_status`) を独立管理、外部公開時は `PaymentStatus` 1 値に集約
- **入力 validation**: `CheckoutInput.__post_init__` で構築時に検証
- **例外階層**: `PaymentError` を基底に既知ケースを 4 種類で分類
- **Webhook 冪等性**: `StripeWebhookEventLog` + atomic で handler と同 tx 化
- **Stripe API version pin**: `2025-03-31.basil` をコード + Dashboard で固定

## ディレクトリ構成

```
v2/
├── config/                              # Django プロジェクト設定
│   ├── settings.py
│   └── urls.py
├── payment/                             # 唯一の Django app
│   ├── api.py                           # ★ 公開 API の窓口
│   ├── dto.py                           # CheckoutInput
│   ├── enums.py                         # PaymentStatus
│   ├── exceptions.py                    # PaymentError 階層
│   ├── apps.py
│   ├── urls.py
│   ├── models/
│   │   ├── payment.py                   # Payment
│   │   ├── stripe_customer.py           # StripeCustomer
│   │   └── stripe_webhook_event_log.py  # StripeWebhookEventLog
│   ├── services/                        # 内部実装 (api.py から delegate)
│   │   ├── __init__.py                  # Stripe SDK 初期化
│   │   ├── stripe_checkout.py           # StripeCheckoutService
│   │   └── stripe_webhook_handlers.py   # StripeWebhookHandlers
│   ├── views/
│   │   ├── stripe_checkout.py           # success / cancel / status
│   │   └── stripe_webhook.py            # webhook 受信
│   ├── templates/payment/
│   │   ├── success.html
│   │   └── cancel.html
│   ├── tests/
│   └── migrations/
├── docs/
│   ├── er-diagram.md
│   └── sequence-diagram.md
├── manage.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

## セットアップ

### 1. 仮想環境

```bash
cd v2
python -m venv venv
source venv/Scripts/activate    # Windows Git Bash
pip install -r requirements.txt
```

### 2. 環境変数

`.env.example` をコピーして `.env` を作成し、Stripe のキーを設定:

```bash
cp .env.example .env
```

```
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
DJANGO_SECRET_KEY=change-me
PAYMENT_BASE_URL=http://localhost:8000   # 任意 (default: http://localhost:8000)
```

### 3. マイグレーション

```bash
python manage.py migrate
```

### 4. 起動

2 つのターミナルが必要:

```bash
# ターミナル 1: Django
python manage.py runserver

# ターミナル 2: Stripe CLI (Webhook 転送)
stripe login
stripe listen --forward-to localhost:8000/webhook/
```

### テスト用カード

```
カード番号: 4242 4242 4242 4242
有効期限: 12/30
CVC: 123
```

## 公開 API (consumer 視点)

### 起票 (決済開始)

```python
from django.shortcuts import redirect
from payment.api import create_checkout_url, CheckoutInput, DuplicateOrderError

def my_view(request):
    try:
        url = create_checkout_url(CheckoutInput(
            order_id="order-2026-001",
            company_id="comp-abc",
            company_name="Acme株式会社",
            amount=5000,
            description="2026年4月分コンサル料",
        ))
    except DuplicateOrderError:
        return error_page("既に決済中です")

    return redirect(url)
```

### 結果取得

```python
from payment.api import get_payment_status, PaymentStatus

status = get_payment_status("order-2026-001")
match status:
    case PaymentStatus.SUCCEEDED: grant_access()
    case PaymentStatus.REFUNDED:  revoke_access()
    case PaymentStatus.CANCELED | PaymentStatus.EXPIRED: prompt_retry()
    case PaymentStatus.PENDING:   wait()
    case PaymentStatus.NOT_FOUND: raise OrderNotFound()
```

### 例外階層

```python
from payment.api import (
    PaymentError,           # 基底 (全例外を catch したい時)
    DuplicateOrderError,    # 二重起票
    InvalidInputError,      # CheckoutInput バリデーション失敗
    PaymentSystemError,     # Stripe 一時障害 (リトライ可能)
    PaymentConfigError,     # Stripe 恒久エラー (開発者対応必要)
)
```

### 公開してるもの一覧

`payment/api.py` の `__all__` を見れば全部。consumer は **必ずこのモジュールから import**:

| 種別 | 名前 |
|------|------|
| 関数 | `create_checkout_url`, `get_payment_status` |
| DTO | `CheckoutInput` |
| Enum | `PaymentStatus` |
| 例外 | `PaymentError`, `DuplicateOrderError`, `InvalidInputError`, `PaymentSystemError`, `PaymentConfigError` |

## 設計方針

### 公開 API は `payment.api` の 1 ファイルに集約

ファイル名で「ここが入口」と分かる慣習 (Django の `urls.py` / `models.py` と同じ感覚)。
内部実装 (`services/`, `models/`) は consumer から直接 import しない契約。

### 公開 API は薄いファサード、実装は `services/`

`api.py` は型 + 例外 + 関数シグネチャだけ並べた読みやすい窓口。
実装は `StripeCheckoutService` / `StripeWebhookHandlers` クラス (v1 と同じスタイル)。

### Stripe を「source of truth」に

webhook 受信時に Stripe から `line_items` を retrieve して amount/description を更新。
起票時にも保存するが、Stripe 側で割引等が乗った場合は webhook で正しい値に更新される。

### atomic 内に外部 API を入れない

webhook view は事前に Stripe API を叩いて結果を変数に持ち、atomic 内では DB UPDATE のみ実行。
`StripeWebhookEventLog.create` も同 atomic に含めて、handler と冪等性記録を 1 トランザクションに。

### race condition の三段防御

`create_checkout_url` で同じ `order_id` への同時呼び出しに対して:

1. `exists()` で通常パスを早期検知 → `DuplicateOrderError`
2. Stripe `idempotency_key` で API 側の重複作成を防止
3. DB `IntegrityError` を catch → `DuplicateOrderError` に変換

### 例外設計

`PaymentError` を基底に既知ケースを 4 種類:
- `DuplicateOrderError`: 二重起票
- `InvalidInputError`: 入力バリデーション失敗
- `PaymentSystemError`: 一時障害 (リトライ可)
- `PaymentConfigError`: 恒久エラー (開発者対応必要)

**プログラミングエラー (TypeError 等) は wrap せず propagate**。
caller が `except Exception` するか、Sentry 等の監視で拾う想定。

## Stripe API バージョン

`config/settings.py` で `STRIPE_API_VERSION = "2025-03-31.basil"` を pin。
SDK 初期化は `payment/services/__init__.py` で行う。

バージョンを上げる際:
1. コード側 (`STRIPE_API_VERSION`) を更新
2. **Stripe Dashboard 側の Webhook エンドポイント設定も同じバージョンに揃える**
3. [Stripe API changelog](https://docs.stripe.com/changelog) で破壊的変更を確認

## テスト・静的解析

```bash
pytest                # テスト実行
ruff check .          # リンター
mypy .                # 型チェック
python manage.py check # Django ヘルスチェック
```

## v1 との違い

| | v1 (payments) | v2 (payment) |
|---|---|---|
| Company / User マスタ | あり | なし (外部依存) |
| Subscription / Plan | あり | なし (将来追加予定) |
| Credit / Plan | あり | なし |
| Usage History | あり | なし |
| Checkout / Payment テーブル | 別々 | 1本に統合 (Payment) |
| 状態管理 | 1 カラム | 2 カラム + 公開時集約 |
| 外部公開 | HTTP view 経由 | Python 関数 (`payment.api`) |
| 例外設計 | なし | `PaymentError` 階層 (4 種) |
| 入力 validation | なし | `CheckoutInput.__post_init__` |
| Stripe SDK 例外 | view で素 catch | service で `PaymentError` に変換 |
| race condition 対策 | 部分的 | `exists()` + `idempotency_key` + `IntegrityError` 三段 |
| Webhook 冪等性 | あり | あり + atomic で handler と同 tx |
| テーブル数 | 11 | 3 |

## ドキュメント

- [ER 図](docs/er-diagram.md)
- [シーケンス図](docs/sequence-diagram.md)
