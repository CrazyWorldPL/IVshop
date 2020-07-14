from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('login/', views.login, name='login'),
    path('oauth_callback/', views.callback, name='callback'),
    path('logout/', views.logout, name='logout'),
    path('add_server/', views.add_server, name='add_server'),
    path('panel/<int:server_id>/', views.panel, name='panel'),
    path('add_product/', views.add_product, name='add_product'),
    path('save_settings/', views.save_settings, name='save_settings'),
    path('shop/<int:server_id>/', views.shop, name='shop'),
    path('buy_sms/', views.buy_sms, name='buy_sms'),
    path('buy_other/', views.buy_other, name='buy_other')
]
