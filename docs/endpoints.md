# エンドポイント

| URL | メソッド | 説明 |
|-----|---------|------|
| /login/ | GET/POST | ログイン画面 |
| /logout/ | GET | ログアウト |
| /dashboard/ | GET | ダッシュボード（残量表示・プラン変更・クレジット購入・カスタム支払い） |
| /checkout/subscription/ | POST | サブスク Checkout 開始 |
| /checkout/credit/ | POST | クレジット Checkout 開始 |
| /checkout/custom/ | POST | カスタム金額 Checkout 開始 |
| /checkout/success/ | GET | 決済処理中画面（ポーリング） |
| /checkout/cancel/ | GET | 決済キャンセル画面 |
| /api/checkout-status/ | GET | CheckoutSessionStatus ステータス確認 API |
| /webhook/ | POST | Stripe Webhook 受信 |
| /admin/ | GET | 管理画面 |

## Webhook 対象イベント

| イベント | 処理 |
|---------|------|
| `checkout.session.completed` | CheckoutSessionStatus.status → completed。type=credit なら CreditStatus INSERT (succeeded)、type=custom なら InvoiceStatus INSERT (succeeded) |
| `checkout.session.expired` | CheckoutSessionStatus.status → expired |
| `customer.subscription.created` | SubscriptionStatus INSERT (status=active) |
| `customer.subscription.updated` | SubscriptionStatus UPDATE (status=active/past_due, plan, period) |
| `customer.subscription.deleted` | SubscriptionStatus UPDATE (status=canceled) |
| `charge.refunded` | CreditStatus / InvoiceStatus UPDATE (status=refunded) |
