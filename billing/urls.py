from django.urls import path
from . import views
app_name = 'billing'
urlpatterns = [
    path('signup/', views.SignUpView.as_view(), name='signup'),
    # Brand (FBV)
    path('brands/', views.brand_list, name='brand_list'),
    path('brands/create/', views.brand_create, name='brand_create'),
    path('brands/<int:pk>/edit/', views.brand_update, name='brand_update'),
    path('brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),
    path('groups/', views.productgroup_list, name='productgroup_list'),
    path('groups/create/', views.ProductGroupCreateView.as_view(), name='productgroup_create'),
    path('groups/<int:pk>/edit/', views.ProductGroupUpdateView.as_view(), name='productgroup_update'),
    path('groups/<int:pk>/delete/', views.ProductGroupDeleteView.as_view(), name='productgroup_delete'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_update'),
    path('suppliers/<int:pk>/delete/', views.SupplierDeleteView.as_view(), name='supplier_delete'),
    path('suppliers/<int:pk>/', views.SupplierDetailView.as_view(), name='supplier_detail'),
    path('products/', views.product_list, name='product_list'),
    path('products/create/', views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/', views.ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_update'),
    path('products/<int:pk>/delete/', views.ProductDeleteView.as_view(), name='product_delete'),
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='customer_update'),
    path('customers/<int:pk>/delete/', views.CustomerDeleteView.as_view(), name='customer_delete'),
    path('customers/<int:pk>/', views.CustomerDetailView.as_view(), name='customer_detail'),
    path('invoices/', views.invoice_list, name='invoice_list'),
    path('invoices/create/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),
    path('', views.home, name='home'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    
]