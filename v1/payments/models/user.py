from django.contrib.auth.models import AbstractUser
from django.db import models

from .company import Company


class User(AbstractUser):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="users")
