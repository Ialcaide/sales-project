from django.urls import path
from . import views

# app_name activa el "namespace": en templates/vistas se referencia como
# {% url 'security:login' %}, 'security:register', etc. — así no chocan
# nombres de URL entre esta app y billing/purchasing.
app_name = 'security'

urlpatterns = [
    path('', views.security_dashboard, name='dashboard'),

    # Autenticación (login personalizado; también existe /accounts/login/,
    # que es la ruta que trae Django por defecto vía config/urls.py)
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.SecurityLoginView.as_view(), name='login'),
    path('recover/', views.RecoverCredentialsView.as_view(), name='recover_credentials'),
    path('logout/', views.SecurityLogoutView.as_view(), name='logout'),

    # Mi Perfil (autoedición + cambio de contraseña con código por correo)
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/password/request/', views.password_change_request, name='password_change_request'),
    path('profile/password/confirm/', views.password_change_confirm, name='password_change_confirm'),

    # Usuarios (CRUD, solo administradores)
    path('users/', views.user_list, name='user_list'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),

    # Roles = Group de Django (CRUD)
    path('roles/', views.group_list, name='group_list'),
    path('roles/create/', views.GroupCreateView.as_view(), name='group_create'),
    path('roles/<int:pk>/', views.GroupDetailView.as_view(), name='group_detail'),
    path('roles/<int:pk>/edit/', views.GroupUpdateView.as_view(), name='group_update'),
    path('roles/<int:pk>/delete/', views.GroupDeleteView.as_view(), name='group_delete'),

    # Permisos: permission_list es la pantalla de asignación (roles/usuarios
    # a la izquierda, cuadros por modelo a la derecha). Las de abajo son CRUD
    # de la DEFINICIÓN del permiso (raro de usar, ya vienen creados por Django).
    path('permissions/', views.permission_list, name='permission_list'),
    path('permissions/create/', views.PermissionCreateView.as_view(), name='permission_create'),
    path('permissions/<int:pk>/', views.PermissionDetailView.as_view(), name='permission_detail'),
    path('permissions/<int:pk>/edit/', views.PermissionUpdateView.as_view(), name='permission_update'),
    path('permissions/<int:pk>/delete/', views.PermissionDeleteView.as_view(), name='permission_delete'),
]