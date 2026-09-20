from django.contrib import admin
from .models import UserProfile, TravelRequest, ExpenseClaim, ExpenseItem, Approval

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'department']

@admin.register(TravelRequest)
class TravelRequestAdmin(admin.ModelAdmin):
    list_display = ['employee', 'destination', 'from_date', 'to_date', 'status']

@admin.register(ExpenseClaim)
class ExpenseClaimAdmin(admin.ModelAdmin):
    list_display = ['employee', 'travel_request', 'status', 'created_at']

@admin.register(ExpenseItem)
class ExpenseItemAdmin(admin.ModelAdmin):
    list_display = ['claim', 'category', 'amount', 'is_disallowed']

@admin.register(Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = ['claim', 'level', 'approver', 'decision', 'decided_at']
