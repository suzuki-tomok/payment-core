# 決済機能 ER図

```mermaid
erDiagram
    Company ||--o{ User : "1:N"
    Company ||--o| StripeCustomer : "1:1"
    Company ||--o{ CompanyUsageHistory : "1:N"
    User ||--o{ CompanyUsageHistory : "1:N"
    StripeCustomer ||--o{ CheckoutSession : "1:N"
    StripeCustomer ||--o{ SubscriptionHistory : "1:N"
    SubscriptionHistory }o--|| SubscriptionPlan : "N:1"
    StripeCustomer ||--o{ CreditHistory : "1:N"
    CreditHistory }o--|| CreditPlan : "N:1"
    StripeCustomer ||--o{ InvoiceHistory : "1:N"

    User {
        int id PK
        int company_id FK
        string username
        string password
        datetime created_at
        datetime updated_at
    }

    Company {
        int id PK
        string name
        datetime created_at
        datetime updated_at
    }

    StripeCustomer {
        int id PK
        int company_id FK
        string stripe_customer_id
        datetime created_at
        datetime updated_at
    }

    CompanyUsageHistory {
        int id PK
        int company_id FK
        int user_id FK
        string type
        string source
        datetime created_at
        datetime updated_at
    }

    CheckoutSession {
        int id PK
        int stripe_customer_id FK
        string stripe_session_id
        string type
        string status
        datetime created_at
        datetime updated_at
    }

    SubscriptionHistory {
        int id PK
        int stripe_customer_id FK
        int subscription_plan_id FK
        string stripe_subscription_id
        string status
        datetime current_period_start
        datetime current_period_end
        datetime created_at
        datetime updated_at
    }

    SubscriptionPlan {
        int id PK
        string name
        string stripe_price_id
        int monthly_document_limit
        int monthly_ai_chat_limit
        datetime created_at
        datetime updated_at
    }

    CreditHistory {
        int id PK
        int stripe_customer_id FK
        int credit_plan_id FK
        string stripe_payment_id
        string status
        datetime created_at
        datetime updated_at
    }

    CreditPlan {
        int id PK
        string name
        string stripe_price_id
        int document_credits
        int ai_chat_credits
        datetime created_at
        datetime updated_at
    }

    InvoiceHistory {
        int id PK
        int stripe_customer_id FK
        string description
        int amount
        string stripe_payment_id
        string status
        datetime created_at
        datetime updated_at
    }
```

## テーブル責務

| テーブル | 責務 | 状態管理 |
|---------|------|---------|
| User | ユーザー（Django AbstractUser拡張、Companyに所属） | - |
| Company | 会社情報 | - |
| StripeCustomer | Stripe顧客紐付け | - |
| CompanyUsageHistory | 使用履歴（type: document/ai_chat、source: subscription/credit） | - |
| CheckoutSession | 決済セッション追跡（ポーリング用） | pending → completed |
| SubscriptionHistory | サブスク契約（1 subscription_id = 1レコード、UPDATE） | created → updated → deleted |
| SubscriptionPlan | 月額プラン定義（静的マスタ） | - |
| CreditHistory | クレジット購入（1 payment_id = 1レコード、UPDATE） | completed → refunded |
| CreditPlan | クレジットパック定義（静的マスタ） | - |
| InvoiceHistory | カスタム支払い（1 payment_id = 1レコード、UPDATE） | completed → refunded |
