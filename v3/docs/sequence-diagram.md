# Stripe 決済フロー

## 1. 自由金額決済 (本番モード `USE_MOCK_STRIPE=false`)

```mermaid
sequenceDiagram
    participant U as ユーザー (ブラウザ)
    participant C as 呼び出し側システム
    participant V as payment view
    participant SVC as services.checkout
    participant GW as stripe.StripeClient
    participant DB as DB
    participant S as Stripe API

    C->>V: POST /payment/checkout/<br/>{order_id, company_id, company_name, amount, description}

    V->>V: JSON parse + URL 組み立て<br/>(reverse + urlencode + build_absolute_uri)
    V->>V: CheckoutInput 構築 (__post_init__ で validation)
    V->>SVC: create_checkout_url(CheckoutInput)

    SVC->>DB: Payment.exists(order_id) 確認
    alt 既存
        DB-->>SVC: True
        SVC-->>V: raise DuplicateOrderError
        V-->>C: 409 {"error": "duplicate_order", "order_id"}
    else 新規
        DB-->>SVC: False
        SVC->>DB: StripeCustomer 検索 (company_id)

        opt 初回 (StripeCustomer 不在)
            SVC->>GW: create_customer(name, idempotency_key=customer-{company_id})
            GW->>S: stripe.Customer.create(...)
            S-->>GW: cus_xxx
            GW-->>SVC: stripe_customer_id
            SVC->>DB: StripeCustomer INSERT
            Note over SVC,DB: race: IntegrityError → 既存 get で fallback
        end

        SVC->>GW: create_checkout_session(amount, success_url, cancel_url,<br/>idempotency_key=checkout-{order_id})
        GW->>S: stripe.checkout.Session.create(...)
        S-->>GW: session_id, url<br/>(payment_intent は Adaptive Pricing 等で null の可能性)
        GW-->>SVC: CreateCheckoutSessionOutput (session_id + url のみ)
        SVC->>DB: Payment INSERT (session=pending, payment=unpaid,<br/>stripe_payment_id=NULL)
        Note over SVC,DB: stripe_payment_id は webhook で確定 (lazy PI 対応).<br/>race: IntegrityError → DuplicateOrderError 変換
        SVC-->>V: checkout_url
        V-->>C: 200 {"url": "..."}
        C-->>U: Stripe Checkout 画面へリダイレクト
    end

    U->>S: カード入力・決済

    alt 決済成功
        S-->>U: /payment/checkout/success/?order_id=X へリダイレクト
        U->>V: GET /payment/checkout/success/?order_id=X
        V->>DB: Payment 存在確認
        V-->>U: success.html (polling 画面)

        S->>V: POST /payment/webhook/<br/>(checkout.session.completed)
        V->>GW: construct_webhook_event(payload, sig)
        GW->>GW: 署名検証
        GW-->>V: ConstructWebhookEventOutput
        V->>DB: StripeWebhookEventLog 既存チェック (冪等性)
        Note over V,DB: 既存なら 200 で即 return
        V->>GW: get_completed_session_details(session_id)
        GW->>S: Session.retrieve(expand=["line_items"])
        S-->>GW: line_items.data[0] + payment_intent (確定済 str ID)
        GW-->>V: GetCompletedSessionDetailsOutput<br/>(amount, description, payment_intent_id)

        V->>DB: BEGIN tx
        V->>SVC: handle_checkout_completed(event, details)
        SVC->>DB: Payment UPDATE (session=completed, payment=succeeded,<br/>amount, description, stripe_payment_id ← ここで確定)
        Note over SVC,DB: 既 SUCCEEDED / REFUNDED は上書きしない
        V->>DB: StripeWebhookEventLog INSERT
        V->>DB: COMMIT
        V-->>S: 200 OK

        loop ポーリング (2秒間隔・最大60秒)
            U->>V: GET /payment/status/?order_id=X
            V->>SVC: get_payment_status(order_id)
            SVC->>DB: Payment 取得 + status 集約
            alt status = succeeded
                V-->>U: {"status": "succeeded", "amount", "description"}
                U->>U: 完了画面表示
            else status = pending
                V-->>U: {"status": "pending", "amount", "description"}
            end
        end

    else 決済キャンセル
        S-->>U: /payment/checkout/cancel/?order_id=X へリダイレクト
        U->>V: GET /payment/checkout/cancel/?order_id=X
        V->>DB: Payment 取得
        V->>DB: pending のみ canceled に UPDATE
        V-->>U: cancel.html
    end

    Note over U,S: 以降、Stripe が自動送信 (payment view が webhook で受け取る)

    opt セッション期限切れ
        S->>V: POST /payment/webhook/<br/>(checkout.session.expired)
        V->>GW: construct_webhook_event → 検証
        V->>SVC: handle_checkout_expired(event)
        SVC->>DB: Payment UPDATE (session=expired, payment 不変)
        V->>DB: StripeWebhookEventLog INSERT (同 tx)
        V-->>S: 200 OK
    end

    opt 返金時
        S->>V: POST /payment/webhook/<br/>(charge.refunded)
        V->>GW: construct_webhook_event → 検証
        V->>SVC: handle_charge_refunded(event)
        SVC->>DB: Payment UPDATE (payment=refunded) where stripe_payment_id<br/>session_status は不変
        V->>DB: StripeWebhookEventLog INSERT (同 tx)
        V-->>S: 200 OK
    end
```

---

## 2. Mock モード (`USE_MOCK_STRIPE=true`)

stripe-cli が使えない開発者向け。Stripe API を一切叩かず in-memory mock で同等動作する。
Service / view 層は mock 非依存 (mock 知識は `stripe/client_mock.py` と `mock_checkout_view` のみに閉じる)。

```mermaid
sequenceDiagram
    participant U as ユーザー (ブラウザ)
    participant C as 呼び出し側システム
    participant V as payment view
    participant SVC as services.checkout
    participant GW as StripeClientMock
    participant DB as DB

    C->>V: POST /payment/checkout/<br/>{order_id, ...}
    V->>SVC: create_checkout_url(CheckoutInput)

    SVC->>GW: create_customer(...)
    GW-->>SVC: cus_mock_xxx (偽 ID)
    SVC->>DB: StripeCustomer INSERT

    SVC->>GW: create_checkout_session(...)
    GW->>GW: in-memory _sessions に保存<br/>(amount, description, payment_intent_id, success_url, cancel_url)
    GW-->>SVC: cs_mock_xxx,<br/>url=http://localhost:8000/payment/mock/checkout/cs_mock_xxx/

    SVC->>DB: Payment INSERT (pending / unpaid, stripe_payment_id=NULL)
    SVC-->>V: mock checkout URL
    V-->>C: 200 {"url": "..."}
    C-->>U: mock URL へリダイレクト

    U->>V: GET /payment/mock/checkout/cs_mock_xxx/
    V->>V: settings.USE_MOCK_STRIPE 確認 (False なら 404)
    V->>GW: _sessions[session_id] 取得
    GW-->>V: amount, description, payment_intent_id, success_url

    Note over V,DB: 本物 Stripe からは webhook で来る completion を、<br/>mock では view 内で同じ handler を発火して再現
    V->>DB: BEGIN tx
    V->>SVC: handle_checkout_completed(event, details)
    SVC->>DB: Payment UPDATE (session=completed, payment=succeeded,<br/>stripe_payment_id ← ここで確定)
    V->>DB: StripeWebhookEventLog INSERT
    V->>DB: COMMIT

    V-->>U: 302 redirect to success_url
    U->>V: GET /payment/checkout/success/?order_id=X
    V-->>U: success.html (polling 画面)

    loop ポーリング
        U->>V: GET /payment/status/?order_id=X
        V-->>U: {"status": "succeeded", ...}
    end
```

---

## 3. 結果取得 (status_view)

```mermaid
sequenceDiagram
    participant C as Caller
    participant V as status_view
    participant SVC as services.checkout
    participant DB as DB

    C->>V: GET /payment/status/?order_id=X
    V->>V: order_id 必須チェック (空 → 400)
    V->>SVC: get_payment_status(order_id)
    SVC->>DB: Payment.session_status / payment_status 取得
    alt 未発見
        SVC-->>V: NOT_FOUND
        V-->>C: 404 {"error": "not_found"}
    else 発見
        SVC->>SVC: 2 カラムを 1 値に集約 (REFUNDED > SUCCEEDED 優先)
        SVC-->>V: PaymentStatus
        V->>DB: amount / description 取得
        V-->>C: 200 {"status", "amount", "description"}
    end
```
