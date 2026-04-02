# ビジネスロジック

## サブスクリプション

### プラン構成

| プラン | ドキュメント上限/月 | AIチャット上限/月 |
|--------|-------------------|------------------|
| Free | 10 | 5 |
| Standard | 100 | 50 |
| Premium | 無制限 | 無制限 |

※ 具体的な数値は営業と要相談

### サブスクのライフサイクル

```
契約開始 → active
  → 毎月自動更新（current_period_start/end が更新される）
  → 解約 → canceled
  → 支払い失敗 → past_due → リトライ → active or unpaid
```

### 月間枠リセット

- current_period_start 〜 current_period_end が1ヶ月の期間
- 期間が変わると使用量カウントがリセットされる（CompanyUsageHistoryのcreated_atで判定）

## クレジット（単発購入）

### 購入フロー

1. ユーザーが CreditPlan を選択
2. Stripe Checkout で決済
3. CreditHistory に INSERT（is_active=True）

### 残高計算

```
クレジット残 = is_active=True の CreditHistory → CreditPlan のクレジット合計
             - source=credit の CompanyUsageHistory COUNT
```

### 無効化

- 管理者またはバッチで CreditHistory.is_active = False に変更可能
- 将来的に期限管理が必要になった場合:
  - CreditHistory に expires_at を追加
  - バッチで期限切れを is_active=False に更新

## 使用量管理

### 使用時の処理

1. ユーザーが操作（ドキュメント作成 / AIチャット）
2. source（subscription / credit）を決定
3. CompanyUsageHistory に INSERT

### source の決定ルール（現在）

- ユーザーが選択する

### source の決定ルール（将来案）

- サブスク枠が残っていれば subscription から優先消費
- サブスク枠を超えたら credit から消費
- どちらも残っていなければ使用不可

## 残数計算

### サブスク残

```
サブスク残 = SubscriptionPlan.monthly_limit
           - 今期間内の CompanyUsageHistory(source=subscription) COUNT
```

- SubscriptionHistory.status が active または trialing であること
- current_period_start 〜 current_period_end の範囲で集計

### クレジット残

```
クレジット残 = is_active=True の CreditPlan.credits 合計
             - CompanyUsageHistory(source=credit) COUNT
```

### 使用可否判定

```
サブスク残 > 0 OR クレジット残 > 0 → 使用可能
```

## 拡張パス

| 段階 | 対応内容 | モデル変更 |
|------|---------|-----------|
| 現在 | ユーザーが source を選択 | なし |
| 拡張1 | サブスク優先で自動判定 | なし（ロジックのみ） |
| 拡張2 | クレジットに有効期限追加 | CreditHistory に expires_at 追加 |
| 拡張3 | 期限切れバッチ | バッチで is_active=False に更新 |
