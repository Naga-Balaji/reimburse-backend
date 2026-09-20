from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserProfileViewSet, TravelRequestViewSet, ExpenseClaimViewSet,
    ExpenseItemViewSet, import_emails, create_items_from_import,
    admin_overview, admin_policy, admin_organization,
)

router = DefaultRouter()
router.register(r'user-profiles', UserProfileViewSet, basename='userprofile')
router.register(r'travel-requests', TravelRequestViewSet, basename='travelrequest')
router.register(r'expense-claims', ExpenseClaimViewSet, basename='expenseclaim')
router.register(r'expense-items', ExpenseItemViewSet, basename='expenseitem')

urlpatterns = [
    path('', include(router.urls)),
    path('import/emails/', import_emails, name='import_emails'),
    path('import/create-items/', create_items_from_import, name='create_items_from_import'),
    path('admin/overview/', admin_overview, name='admin_overview'),
    path('admin/policy/', admin_policy, name='admin_policy'),
    path('admin/organization/', admin_organization, name='admin_organization'),
]
