# Stripe 決済フロー

## 設計の核心思想
```
「Stripe が状態の真実、DB は成功記録のキャッシュ」
```

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

    Note over C,SVC: ── 起票フェーズ (Payment はまだ作らない) ──

    C->>V: POST /payment/checkout/<br/>{order_id, company_id, company_name, amount, description}

    V->>V: JSON parse + URL 組み立て<br/>(reverse + urlencode + build_absolute_uri)
    V->>V: CheckoutInput 構築 (__post_init__ で validation)
    V->>SVC: create_checkout_url(CheckoutInput)

    SVC->>DB: StripeCustomer 検索 (company_id)
    opt 初回 (StripeCustomer 不在)
        SVC->>GW: create_customer(name, idempotency_key=customer-{company_id})
        GW->>S: stripe.Customer.create(...)
        S-->>GW: cus_xxx
        GW-->>SVC: stripe_customer_id
        SVC->>DB: StripeCustomer INSERT
        Note over SVC,DB: race: IntegrityError → 既存 get で fallback
    end

    SVC->>GW: create_checkout_session(<br/>idempotency_key=checkout-{order_id}-{amount},<br/>metadata={"order_id": ...})
    GW->>S: stripe.checkout.Session.create(...)
    S-->>GW: session_id, url
    GW-->>SVC: CreateCheckoutSessionOutput
    Note over SVC,DB: ★ Payment は作らない (起票時は DB に書かない)
    SVC-->>V: checkout_url
    V-->>C: 200 {"url": "..."}
    C-->>U: Stripe Checkout 画面へリダイレクト

    Note over U,S: ── 決済フェーズ ──

    U->>S: カード入力・決済

    alt 決済成功
        S-->>U: success_url へリダイレクト
        U->>V: GET /payment/checkout/success/?order_id=X
        V-->>U: success.html「決済を受け付けました」<br/>(DB チェックなし、polling なし)

        Note over S,V: ── webhook フェーズ ──
        S->>V: POST /payment/webhook/<br/>(checkout.session.completed)
        V->>GW: construct_webhook_event(payload, sig) → 署名検証
        GW-->>V: ConstructWebhookEventOutput
        V->>DB: StripeWebhookEventLog 既存チェック (冪等性)
        V->>GW: get_completed_session_details(session_id)
        GW->>S: Session.retrieve(expand=["line_items"])
        S-->>GW: line_items.data[0] + payment_intent (str ID)
        GW-->>V: GetCompletedSessionDetailsOutput<br/>(amount, description, payment_intent_id)

        V->>DB: BEGIN tx
        V->>SVC: handle_checkout_completed(event, details)
        SVC->>DB: Payment.objects.get_or_create(order_id=...) <br/>★ ここで初めて INSERT
        Note over SVC,DB: 既存なら skip + warning (冪等性)
        V->>DB: StripeWebhookEventLog INSERT
        V->>DB: COMMIT
        V-->>S: 200 OK

    else 決済キャンセル
        S-->>U: cancel_url へリダイレクト
        U->>V: GET /payment/checkout/cancel/?order_id=X
        V-->>U: cancel.html「キャンセルしました」<br/>(DB 操作なし — Payment 元々無い)
    end

    Note over C,DB: ── 結果取得フェーズ (consumer 側、任意のタイミング) ──

    C->>SVC: get_payment_status(order_id)
    SVC->>DB: Payment 取得 (is_refunded のみ select)
    alt Payment 不在
        SVC-->>C: PaymentStatus.NOT_PAID<br/>(未決済 / キャンセル / 期限切れ全て含む)
    else Payment 存在 (is_refunded=False)
        SVC-->>C: PaymentStatus.PAID
    else Payment 存在 (is_refunded=True)
        SVC-->>C: PaymentStatus.REFUNDED
    end

    Note over U,S: ── 後続イベント ──

    opt セッション期限切れ (24h)
        S->>V: POST /payment/webhook/<br/>(checkout.session.expired)
        V->>SVC: handle_checkout_expired(event)
        SVC->>SVC: no-op (DB 操作なし)
        V->>DB: StripeWebhookEventLog INSERT (冪等性キー)
        V-->>S: 200 OK
    end

    opt 返金時
        S->>V: POST /payment/webhook/<br/>(charge.refunded)
        V->>SVC: handle_charge_refunded(event)
        SVC->>DB: Payment UPDATE (is_refunded=True, refunded_at=now)<br/>WHERE stripe_payment_id=...
        V->>DB: StripeWebhookEventLog INSERT (同 tx)
        V-->>S: 200 OK
    end
```

---

## 2. Mock モード (`USE_MOCK_STRIPE=true`)

stripe-cli が使えない開発者向け。Stripe API を一切叩かず in-memory mock で同等動作。
Service / view 層は mock 非依存 (mock 知識は `stripe/client_mock.py` と `mock_checkout_view` のみに閉じる)。

```mermaid
sequenceDiagram
    participant U as ユーザー (ブラウザ)
    participant C as 呼び出し側システム
    participant V as payment view
    participant SVC as services.checkout
    participant GW as StripeClientMock
    participant DB as DB

    C->>V: POST /payment/checkout/
    V->>SVC: create_checkout_url(CheckoutInput)

    SVC->>GW: create_customer(...)
    GW-->>SVC: cus_mock_xxx (偽 ID)
    SVC->>DB: StripeCustomer INSERT

    SVC->>GW: create_checkout_session(<br/>idempotency_key=checkout-{order_id}-{amount},<br/>metadata={"order_id": ...})
    GW->>GW: in-memory _sessions に保存<br/>(amount, description, payment_intent_id, success_url, metadata, customer_id)
    GW-->>SVC: cs_mock_xxx,<br/>url=http://localhost:8000/payment/mock/checkout/cs_mock_xxx/

    Note over SVC,DB: ★ Payment はまだ作らない
    SVC-->>V: mock checkout URL
    V-->>C: 200 {"url": "..."}
    C-->>U: mock URL へリダイレクト

    U->>V: GET /payment/mock/checkout/cs_mock_xxx/
    V->>V: settings.USE_MOCK_STRIPE 確認 (False なら 404)
    V->>GW: _sessions[session_id] 取得
    GW-->>V: amount, description, payment_intent_id, metadata, customer_id, success_url

    Note over V,DB: 本物 Stripe の webhook を mock で再現
    V->>DB: BEGIN tx
    V->>SVC: handle_checkout_completed(event, details)
    SVC->>DB: Payment INSERT (ここで初めて作成)
    V->>DB: StripeWebhookEventLog INSERT
    V->>DB: COMMIT

    V-->>U: 302 redirect to success_url
    U->>V: GET /payment/checkout/success/?order_id=X
    V-->>U: success.html「決済を受け付けました」

    Note over C,DB: ── 結果取得 (consumer 側、任意のタイミング) ──

    C->>SVC: get_payment_status(order_id)
    SVC->>DB: Payment 取得
    SVC-->>C: PaymentStatus.PAID
```
