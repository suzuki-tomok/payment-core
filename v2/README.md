# payment-core v2

自由金額決済を題材に、ユースケース層 + Input DTO + 例外翻訳 Middleware で再設計した Django 実装。

## ディレクトリ構成

```
v2/
├── config/               # Django プロジェクト設定
│   ├── settings.py       # payment app, Stripe API version pin, 例外翻訳 Middleware
│   └── urls.py
├── payment/              # 単一 Django app
│   ├── apps.py
│   ├── middleware.py     # ExceptionTranslationMiddleware (EXCEPTION_MAP)
│   ├── urls.py
│   ├── models/
│   ├── services/
│   │   ├── stripe_client.py  # Stripe SDK の api_key / api_version 設定
│   │   ├── dto.py            # service 関数の Input DTO
│   │   └── exceptions.py     # PaymentError 基底
│   ├── views/                # 薄い view 層
│   ├── tests/
│   └── migrations/
├── manage.py
├── pyproject.toml
├── requirements.txt
└── README.md
```

## セットアップ

```bash
cd v2
python -m venv venv
source venv/Scripts/activate          # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                  # 必要に応じて編集
python manage.py migrate
```

## 設計方針

- **View は薄く**: HTTP/フォームの parse → DTO 構築 → service 関数呼び出し → レスポンス
- **service 関数 = 1ユースケース**: `payment/services/<usecase>.py` に関数1つ
- **Input DTO**: `payment/services/dto.py` に dataclass で集約
- **例外**: `payment/services/exceptions.py` に集約。Middleware が HTTP に翻訳
- **クラス化はしない**: 必要になった時だけ（明確な信号が出るまで関数で十分）

## Stripe API バージョン

`config/settings.py` で `STRIPE_API_VERSION = "2025-03-31.basil"` を pin。
バージョンを上げる際は **Stripe Dashboard 側の Webhook エンドポイント設定も同じバージョンに揃える** こと。

## テスト・静的解析

```bash
pytest                # テスト実行
ruff check .          # リンター
mypy .                # 型チェック
```

## v1 との違い

- 単一 app (`payment`) に集約
- Excel エクスポート等の Admin 強化機能は含まない
- ユースケース＝関数で実装
- 例外翻訳を Middleware で一元化
