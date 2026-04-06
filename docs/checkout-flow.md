# Stripe決済フロー

## サブスクリプション契約

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Django
    participant DB as DB
    participant S as Stripe

    U->>D: ダッシュボードでプラン選択
    U->>D: POST /checkout/subscription/ (plan_id)

    D->>DB: StripeCustomer 検索

    opt 初回（StripeCustomer が存在しない）
        D->>S: stripe.Customer.create()
        S-->>D: cus_xxx
        D->>DB: StripeCustomer レコード作成 (stripe_customer_id = cus_xxx)
    end

    D->>S: checkout.Session.create(mode="subscription", price=stripe_price_id)
    S-->>D: session_id, url
    D->>DB: CheckoutSession INSERT (type=subscription, status=pending)
    D-->>U: Stripe Checkout 画面へリダイレクト

    U->>S: カード入力・決済

    alt 決済成功
        S-->>U: /checkout/success/?session_id=xxx へリダイレクト
        U->>D: GET /checkout/success/?session_id=xxx
        D-->>U: 処理中画面（スピナー表示）

        loop 2秒ごとにポーリング（最大60秒）
            U->>D: GET /api/checkout-status/?session_id=xxx
            D->>DB: CheckoutSession.status 確認
            D-->>U: {"status": "pending"}
        end

        S->>D: Webhook: checkout.session.completed
        D->>DB: CheckoutSession.status = completed
        D-->>S: 200 OK

        U->>D: GET /api/checkout-status/?session_id=xxx
        D->>DB: CheckoutSession.status 確認
        D-->>U: {"status": "completed"}
        U->>U: 完了画面表示

    else 決済キャンセル
        S-->>U: /checkout/cancel/ へリダイレクト
        U->>D: GET /checkout/cancel/
        D-->>U: キャンセル画面表示
    end

    Note over U,S: 以降、Stripe が自動送信（Django は Webhook で受け取るだけ）

    opt 契約直後
        S->>D: Webhook: customer.subscription.created
        D->>DB: SubscriptionHistory INSERT (status=active)
        D-->>S: 200 OK
    end

    opt 毎月更新時
        S->>D: Webhook: customer.subscription.updated
        D->>DB: SubscriptionHistory INSERT (status=active, 新しい period)
        D-->>S: 200 OK
    end

    opt 解約時
        S->>D: Webhook: customer.subscription.deleted
        D->>DB: SubscriptionHistory INSERT (status=canceled)
        D-->>S: 200 OK
    end
```

## クレジット購入

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Django
    participant DB as DB
    participant S as Stripe

    U->>D: ダッシュボードでクレジットパック選択
    U->>D: POST /checkout/credit/ (credit_plan_id)

    D->>DB: StripeCustomer 検索

    opt 初回（StripeCustomer が存在しない）
        D->>S: stripe.Customer.create()
        S-->>D: cus_xxx
        D->>DB: StripeCustomer レコード作成 (stripe_customer_id = cus_xxx)
    end

    D->>S: checkout.Session.create(mode="payment", price=stripe_price_id)
    S-->>D: session_id, url
    D->>DB: CheckoutSession INSERT (type=credit, status=pending)
    D-->>U: Stripe Checkout 画面へリダイレクト

    U->>S: カード入力・決済

    alt 決済成功
        S-->>U: /checkout/success/?session_id=xxx へリダイレクト
        U->>D: GET /checkout/success/?session_id=xxx
        D-->>U: 処理中画面（スピナー表示）

        loop 2秒ごとにポーリング（最大60秒）
            U->>D: GET /api/checkout-status/?session_id=xxx
            D->>DB: CheckoutSession.status 確認
            D-->>U: {"status": "pending"}
        end

        S->>D: Webhook: checkout.session.completed
        D->>DB: CheckoutSession.status = completed
        D-->>S: 200 OK

        U->>D: GET /api/checkout-status/?session_id=xxx
        D->>DB: CheckoutSession.status 確認
        D-->>U: {"status": "completed"}
        U->>U: 完了画面表示

    else 決済キャンセル
        S-->>U: /checkout/cancel/ へリダイレクト
        U->>D: GET /checkout/cancel/
        D-->>U: キャンセル画面表示
    end

    Note over U,S: 以降、Stripe が自動送信（Django は Webhook で受け取るだけ）

    opt 決済成功時
        S->>D: Webhook: payment_intent.succeeded
        D->>DB: CheckoutSession から stripe_session_id 取得
        D->>S: Session.retrieve（line_items から price_id 特定）
        S-->>D: price_id
        D->>DB: CreditHistory INSERT (credit_plan, is_active=True)
        D-->>S: 200 OK
    end
```

## 残量計算

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant D as Django
    participant DB as DB

    U->>D: GET /dashboard/

    Note over D,DB: サブスク残量計算

    D->>DB: SubscriptionHistory を created_at DESC で取得（最新1件）
    alt 最新レコードが active/trialing
        D->>DB: CompanyUsageHistory COUNT (source=subscription, type=document, サブスク期間内)
        D->>D: ドキュメント残 = monthly_document_limit - 使用数
        D->>DB: CompanyUsageHistory COUNT (source=subscription, type=ai_chat, サブスク期間内)
        D->>D: AIチャット残 = monthly_ai_chat_limit - 使用数
    else 最新レコードが canceled/未契約
        D->>D: ドキュメント残 = 0, AIチャット残 = 0
    end

    Note over D,DB: クレジット残量計算

    D->>DB: CreditHistory (is_active=True) → CreditPlan のドキュメント/AIチャット合計
    D->>DB: CompanyUsageHistory COUNT (source=credit, type=document)
    D->>D: ドキュメント残 = 購入合計 - 消費数
    D->>DB: CompanyUsageHistory COUNT (source=credit, type=ai_chat)
    D->>D: AIチャット残 = 購入合計 - 消費数

    D-->>U: ダッシュボード表示
```

## エンドポイント

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
| /webhook/ | POST | Stripe Webhook 受信（対象イベント: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `payment_intent.succeeded`） |
