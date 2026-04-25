# ステータス状態遷移図

## CheckoutSessionStatus

```mermaid
stateDiagram-v2
    [*] --> pending: アプリが Checkout Session 作成時に設定
    pending --> completed: Webhook: checkout.session.completed
    pending --> canceled: ユーザーがキャンセル
    pending --> expired: Webhook: checkout.session.expired
```

## SubscriptionStatus

```mermaid
stateDiagram-v2
    [*] --> active: Webhook: customer.subscription.created
    active --> active: Webhook: customer.subscription.updated（月次更新/プラン変更）
    active --> past_due: Webhook: customer.subscription.updated（支払い失敗）
    active --> canceled: Webhook: customer.subscription.deleted（解約）
    past_due --> active: Webhook: customer.subscription.updated（支払いリトライ成功）
    past_due --> canceled: Webhook: customer.subscription.deleted（解約）
```

## CreditStatus

```mermaid
stateDiagram-v2
    [*] --> succeeded: Webhook: checkout.session.completed (type=credit)
    succeeded --> refunded: Webhook: charge.refunded（返金）
```

## InvoiceStatus

```mermaid
stateDiagram-v2
    [*] --> succeeded: Webhook: checkout.session.completed (type=custom)
    succeeded --> refunded: Webhook: charge.refunded（返金）
```

## WebhookEventLog

```mermaid
stateDiagram-v2
    [*] --> recorded: Webhook 処理成功時に INSERT
    note right of recorded: event_id (unique) で冪等性を担保
```

## ステータスと Webhook の対応表

| テーブル | status | 対応する Webhook |
|---------|--------|-----------------|
| SubscriptionStatus | active | customer.subscription.created / customer.subscription.updated |
| SubscriptionStatus | past_due | customer.subscription.updated（支払い失敗） |
| SubscriptionStatus | canceled | customer.subscription.deleted |
| CreditStatus | succeeded | checkout.session.completed (type=credit) |
| CreditStatus | refunded | charge.refunded |
| InvoiceStatus | succeeded | checkout.session.completed (type=custom) |
| InvoiceStatus | refunded | charge.refunded |
| CheckoutSessionStatus | pending | アプリが設定 |
| CheckoutSessionStatus | completed | checkout.session.completed |
| CheckoutSessionStatus | canceled | ユーザーがキャンセル |
| CheckoutSessionStatus | expired | checkout.session.expired |
