# 決済機能 ER図

```mermaid
erDiagram
    StripeCustomer ||--o{ Payment : "1:N"

    StripeCustomer {
        int id PK
        string company_id
        string company_name
        string stripe_customer_id
        datetime created_at
    }

    Payment {
        int id PK
        int stripe_customer_id FK
        string order_id
        string stripe_session_id
        string stripe_payment_id
        int amount
        string description
        string session_status
        string payment_status
        datetime created_at
        datetime updated_at
    }

    StripeWebhookEventLog {
        int id PK
        string event_id
        string event_type
        datetime created_at
    }
```

## テーブル責務

| テーブル | 責務 | 状態管理 |
|---------|------|---------|
| StripeCustomer | 外部 company_id ↔ Stripe Customer 紐付け（1社1レコード） | - |
| Payment | Checkout Session の lifecycle と決済結果を1テーブルで表現 | session: pending → completed / canceled / expired<br>payment: unpaid → succeeded / refunded |
| StripeWebhookEventLog | Webhook 受信の冪等性管理（event_id unique） | INSERT only |
