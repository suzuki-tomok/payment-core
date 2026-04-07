# エンドポイント

| URL | メソッド | 説明 |
|-----|---------|------|
| /login/ | GET/POST | ログイン画面 |
| /logout/ | GET | ログアウト |
| /dashboard/ | GET | ダッシュボード（残量表示・プラン変更・クレジット購入） |
| /checkout/subscription/ | POST | サブスク Checkout 開始 |
| /checkout/credit/ | POST | クレジット Checkout 開始 |
| /checkout/success/ | GET | 決済処理中画面（ポーリング） |
| /checkout/cancel/ | GET | 決済キャンセル画面 |
| /api/checkout-status/ | GET | CheckoutSession ステータス確認 API |
| /webhook/ | POST | Stripe Webhook 受信 |
| /admin/ | GET | 管理画面 |

## Webhook 対象イベント

| イベント | 処理 |
|---------|------|
| `checkout.session.completed` | CheckoutSession.status → completed（type=credit なら CreditHistory も作成） |
| `customer.subscription.created` | SubscriptionHistory INSERT (active) |
| `customer.subscription.updated` | SubscriptionHistory INSERT (新しい status/period) |
| `customer.subscription.deleted` | SubscriptionHistory INSERT (canceled) |
