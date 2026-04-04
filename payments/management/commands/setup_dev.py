"""開発環境の初期データセットアップコマンド.

Usage:
    python manage.py setup_dev
"""

from typing import Any

from django.core.management.base import BaseCommand

from payments.models import Company, CreditPlan, SubscriptionPlan, User


class Command(BaseCommand):
    help = "開発環境の初期データをセットアップします"

    def handle(self, *args: Any, **options: Any) -> None:
        # --- Company ---
        company, _ = Company.objects.get_or_create(name="テスト株式会社")
        self.stdout.write(f"Company: {company.name}")

        # --- Superuser ---
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(username="admin", password="admin1234", company=company)
            self.stdout.write(self.style.SUCCESS("Superuser: admin / admin1234"))
        else:
            self.stdout.write("Superuser: already exists")

        # --- テストユーザー ---
        if not User.objects.filter(username="testuser").exists():
            User.objects.create_user(username="testuser", password="test1234", company=company)
            self.stdout.write(self.style.SUCCESS("Test user: testuser / test1234"))
        else:
            self.stdout.write("Test user: already exists")

        # --- SubscriptionPlan ---
        plans = [
            {
                "name": "Free",
                "stripe_price_id": "price_free",
                "monthly_document_limit": 10,
                "monthly_ai_chat_limit": 5,
            },
            {
                "name": "Standard",
                "stripe_price_id": "price_standard",
                "monthly_document_limit": 100,
                "monthly_ai_chat_limit": 50,
            },
            {
                "name": "Premium",
                "stripe_price_id": "price_premium",
                "monthly_document_limit": 999999,
                "monthly_ai_chat_limit": 999999,
            },
        ]
        for plan_data in plans:
            plan, created = SubscriptionPlan.objects.get_or_create(
                stripe_price_id=plan_data["stripe_price_id"],
                defaults=plan_data,
            )
            status = "(created)" if created else "(exists)"
            self.stdout.write(f"SubscriptionPlan: {plan.name} {status}")

        # --- CreditPlan ---
        credit_plans = [
            {
                "name": "クレジット10パック",
                "stripe_price_id": "price_credit_10",
                "document_credits": 10,
                "ai_chat_credits": 10,
            },
            {
                "name": "クレジット50パック",
                "stripe_price_id": "price_credit_50",
                "document_credits": 50,
                "ai_chat_credits": 50,
            },
            {
                "name": "クレジット100パック",
                "stripe_price_id": "price_credit_100",
                "document_credits": 100,
                "ai_chat_credits": 100,
            },
        ]
        for cp_data in credit_plans:
            cp, created = CreditPlan.objects.get_or_create(
                stripe_price_id=cp_data["stripe_price_id"],
                defaults=cp_data,
            )
            status = "(created)" if created else "(exists)"
            self.stdout.write(f"CreditPlan: {cp.name} {status}")

        self.stdout.write(self.style.SUCCESS("\nSetup complete!"))
