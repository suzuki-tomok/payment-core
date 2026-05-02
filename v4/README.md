# payment-core

Stripe Checkout を使った自由金額決済の Django app。
Stripe SDK を gateway 層に密閉し、service 層は SDK 非依存。`USE_MOCK_STRIPE=true` で Stripe を叩かずローカル開発が可能。

## セットアップ

### 1. 仮想環境

```bash
cd v4
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
| `STRIPE_API_VERSION` | Stripe API version pin | `2025-03-31.basil` (default) |
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

Stripe API も stripe-cli も不要で end-to-end 動作する。決済起票 → ブラウザが mock 中継 URL に飛ぶ → 自動的に webhook handler を発火 → success_url にリダイレクト。

**ブラウザで確認 (推奨):**

`http://localhost:8000/demo/` を開いて起票フォーム submit → 自動成功 → demo トップから order_id で状態確認できる。

### 本物 Stripe モード

`.env` で `USE_MOCK_STRIPE=false` に変更してから、2 ターミナル必要。

#### 1. Stripe CLI の準備 (初回のみ)

[公式ガイド](https://stripe.com/docs/stripe-cli) を参考にインストール:

- macOS: `brew install stripe/stripe-cli/stripe`
- Windows: scoop / 公式バイナリ DL
- Linux: 公式 apt repo / バイナリ DL

インストール後、Stripe アカウントに紐付け (ブラウザで認可):

```bash
stripe login
```

#### 2. Webhook 転送を起動

```bash
# ターミナル 2:
stripe listen --forward-to localhost:8000/payment/webhook/
```

実行すると次のような出力:

```
> Ready! You are using Stripe API Version [2025-03-31.basil].
  Your webhook signing secret is whsec_xxxxxxxxxxxxxxxxxxxxxx (^C to quit)
```

この `whsec_xxx...` を `.env` の `STRIPE_WEBHOOK_SECRET` に設定して Django を再起動。
**毎回新しい値が発行される**ので、`stripe listen` を再起動するたびに `.env` を更新する必要あり。

#### 3. Django を起動

```bash
# ターミナル 1:
python manage.py runserver
```

> **ポート変更時の注意:** `runserver 8001` 等でポートを変えた場合は、
> `stripe listen --forward-to localhost:8001/payment/webhook/` も同じポートに合わせる。

#### 4. 動作確認

ブラウザで `http://localhost:8000/demo/` を開いてフォーム submit → Stripe Checkout 画面でテストカード入力。

**テスト用カード:**

```
カード番号: 4242 4242 4242 4242
有効期限: 12/30
CVC: 123
```

---

## 開発コマンド

### マイグレーション

```bash
python manage.py makemigrations payment
python manage.py migrate
python manage.py showmigrations
```


### Lint / 型チェック

```bash
# ruff (lint + import 順)
ruff check .
ruff check --fix .

# mypy (型チェック)
mypy .
```

### テスト

```bash
# 全 test
pytest

# 特定ファイル
pytest payment/tests/services/test_webhook_handlers.py

# 特定 test
pytest payment/tests/services/test_webhook_handlers.py::test_completed_creates_new_payment

# verbose
pytest -v --tb=long
```

## 状態対応表 (Stripe / DB / PaymentStatus / ログ)

```
[Stripe 側のイベント / 状態]              [DB Payment]                  [PaymentStatus]   [アプリログ]
────────────────────────────────────────────────────────────────────────────────────────────────
起票直後 (Session open)                   None                          NOT_PAID         あり (起票時 1 行)
ユーザが「戻る」(cancel_url)              None                          NOT_PAID         なし (Django access log のみ)
24h 放置 (checkout.session.expired)       None                          NOT_PAID         あり (webhook 受信 + handler no-op)
決済成功 (checkout.session.completed)     Create(is_refunded=False)     PAID             あり (webhook 受信 + Payment created)
返金 (charge.refunded)                    Update(is_refunded=True)      REFUNDED         あり (webhook 受信 + Payment refunded)
```
