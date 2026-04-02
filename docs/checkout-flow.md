# Stripe決済フロー

## サブスクリプション契約

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Django
    participant DB as DB
    participant S as Stripe

    U->>D: POST /payments/checkout/ (type=subscription, plan_id=1)
    D->>DB: StripeCustomer取得 (なければ作成)
    D->>S: stripe.checkout.Session.create(mode="subscription")
    S-->>D: session_id, url
    D->>DB: CheckoutSession保存 (type=subscription, status=pending)
    D-->>U: Stripeへリダイレクト

    U->>S: カード入力・決済
    S-->>U: success_url?session_id=xxx へリダイレクト

    U->>D: GET /payments/checkout/success/?session_id=xxx
    D-->>U: 処理中画面 + ポーリング開始

    loop 2秒ごと (最大60秒)
        U->>D: GET /payments/api/status/?session_id=xxx
        D->>DB: CheckoutSession.status確認
        D-->>U: {"status": "pending"}
    end

    S->>D: Webhook: checkout.session.completed
    D->>DB: CheckoutSession.status = completed
    D-->>S: 200 OK

    S->>D: Webhook: customer.subscription.created
    D->>DB: Subscription作成 (plan=SubscriptionPlan, status=active)
    D-->>S: 200 OK

    U->>D: GET /payments/api/status/?session_id=xxx
    D->>DB: CheckoutSession.status確認
    D-->>U: {"status": "completed"}
    U->>U: 完了画面表示
```

## クレジット購入

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Django
    participant DB as DB
    participant S as Stripe

    U->>D: POST /payments/checkout/ (type=credit, credit_plan_id=1)
    D->>DB: StripeCustomer取得
    D->>S: stripe.checkout.Session.create(mode="payment")
    S-->>D: session_id, url
    D->>DB: CheckoutSession保存 (type=credit, status=pending)
    D-->>U: Stripeへリダイレクト

    U->>S: カード入力・決済
    S-->>U: success_url?session_id=xxx へリダイレクト

    U->>D: GET /payments/checkout/success/?session_id=xxx
    D-->>U: 処理中画面 + ポーリング開始

    loop 2秒ごと (最大60秒)
        U->>D: GET /payments/api/status/?session_id=xxx
        D->>DB: CheckoutSession.status確認
        D-->>U: {"status": "pending"}
    end

    S->>D: Webhook: checkout.session.completed
    D->>DB: CheckoutSession.status = completed
    D-->>S: 200 OK

    S->>D: Webhook: payment_intent.succeeded
    D->>DB: Credit作成 (credit_plan=CreditPlan)
    D->>DB: Wallet.document_credits += CreditPlan.document_credits
    D->>DB: Wallet.ai_chat_credits += CreditPlan.ai_chat_credits
    D-->>S: 200 OK

    U->>D: GET /payments/api/status/?session_id=xxx
    D->>DB: CheckoutSession.status確認
    D-->>U: {"status": "completed"}
    U->>U: 完了画面表示
```

## フローの違い

| | サブスクリプション | クレジット購入 |
|---|---|---|
| Checkout mode | `subscription` | `payment` |
| CheckoutSession.type | `subscription` | `credit` |
| Webhook | `customer.subscription.created` | `payment_intent.succeeded` |
| DB処理 | Subscription作成 | Credit作成 + Wallet加算 |

## エンドポイント

| URL | メソッド | 説明 |
|-----|---------|------|
| /payments/checkout/ | POST | Checkout開始 |
| /payments/checkout/success/ | GET | 成功画面 |
| /payments/checkout/cancel/ | GET | キャンセル画面 |
| /payments/api/status/ | GET | 状態確認API |
| /payments/webhook/ | POST | Stripe Webhook |
| /payments/billing-portal/ | GET | 顧客ポータル |
