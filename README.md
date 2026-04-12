# payment-core

Stripe連携の決済・サブスクリプション管理プロトタイプ｜Django / Stripe API / 管理画面Excel出力

## セットアップ

### 1. 仮想環境

```bash
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
```

### 2. 環境変数

`.env.example` をコピーして `.env` を作成し、Stripe のキーを設定

```bash
cp .env.example .env
```

```
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
DJANGO_SECRET_KEY=change-me
```

### 3. マイグレーション & 初期データ

```bash
python manage.py migrate
python manage.py setup_dev
```

以下が作成されます:

| 種別 | 内容 |
|------|------|
| Company | テスト株式会社 |
| 管理者 | admin / admin1234 |
| テストユーザー | testuser / test1234 |
| SubscriptionPlan | Free / Standard / Premium |
| CreditPlan | 10パック / 50パック / 100パック |

### 4. 起動

2つのターミナルが必要です:

```bash
# ターミナル1: Django
python manage.py runserver

# ターミナル2: Stripe CLI（Webhook転送）
stripe login
stripe listen --forward-to localhost:8000/webhook/
```

### 5. アクセス

| URL | 説明 |
|-----|------|
| http://127.0.0.1:8000/ | ログイン画面 |
| http://127.0.0.1:8000/dashboard/ | ダッシュボード |
| http://127.0.0.1:8000/admin/ | 管理画面 |

### テスト用カード

```
カード番号: 4242 4242 4242 4242
有効期限: 12/30
CVC: 123
```

## テスト・静的解析

```bash
pytest                # テスト実行
ruff check .          # リンター
mypy .                # 型チェック
```

### テスト戦略

| レイヤー | テスト対象 | Stripe モック | テストファイル |
|---------|-----------|:---:|------------|
| バリデーション | StripeCheckoutValidator | 不要 | test_stripe_checkout_validator.py |
| ドメインサービス | RemainingSubscriptionService | 不要 | test_remaining_subscription.py |
| ドメインサービス | RemainingCreditService | 不要 | test_remaining_credit.py |
| Stripe Checkout | StripeCheckoutService | 必要 | test_stripe_checkout.py |
| Stripe Webhook | StripeWebhookService | 必要 | test_stripe_webhook.py |

- **モック不要のテスト**: テスト用データを DB に作成 → サービス呼び出し → 結果を検証
- **モック必要のテスト**: Stripe API を `unittest.mock.patch` で差し替え → DB への書き込み結果を検証
- **テストデータ**: `conftest.py` に pytest fixture で定義。各テストは fixture を引数で受け取る
- **モックヘルパー**: `mock_stripe.py` に Stripe API レスポンスの組み立てを集約

## 設計ドキュメント

- [ER図](docs/er-diagram.md)
- [エンドポイント](docs/endpoints.md)
- [シーケンス図](docs/sequence-diagram.md)
