import re
import requests
import threading

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.conf import settings

from shop.utils.oauth2 import Oauth
from shop.utils.functions import send_commands, check_rcon_connection, login_required, generate_random_chars

from .models import Server, PaymentOperator, Product, Purchase, Voucher, ServerNavbarLink

from shop.forms import ProductDescriptionForm

from config import RECAPTCHA_SECRET_KEY

if not settings.DEBUG:
    from shop.utils.functions import actualize_servers_data, check_rcon

    t1 = threading.Thread(target=actualize_servers_data)
    t1.start()
    #t2 = threading.Thread(target=check_rcon)
    #t2.start()


def index(request):
    domain = request.META['HTTP_HOST']
    if not domain == 'ivshop.pl' and not settings.DEBUG:
        server = Server.objects.filter(domain=domain).values('id', 'domain')
        if server:
            return redirect(f"shop/{server[0]['id']}")
        else:
            return redirect('https://ivshop.pl')

    if 'username' and 'user_id' in request.session:
        data = []
        user_id = request.session['user_id']
        to_data = Server.objects.all()
        for server in to_data:
            try:
                admins = server.admins.split(',')
            except:
                admins = []
            if server.owner_id == int(user_id) or user_id in admins:
                data.append(server)
        context = {'data': data}
        return render(request, "index.html", context)
    return render(request, "index.html")


def handler404(request, exception):
    return render(request, '404.html', status=404)


def login(request):
    if 'username' not in request.session:
        return redirect(Oauth.discord_login_url)
    del request.session['username']
    del request.session['user_id']
    return redirect(Oauth.discord_login_url)


def logout(request):
    if 'username' in request.session:
        del request.session['username']
        del request.session['user_id']
        return redirect('/')
    messages.add_message(request, messages.ERROR, 'Nie jesteś zalogowany.')
    return redirect('/')


def callback(request):
    if 'username' not in request.session:
        try:
            code = request.GET.get("code")
            access_token = Oauth.get_access_token(code)
            user_json = Oauth.get_user_json(access_token)
            username = user_json.get("username")
            user_id = user_json.get("id")
            if not user_id or not username:
                raise Exception('Login canceled')
            request.session['username'] = username
            request.session['user_id'] = user_id
            Oauth.join_to_server(access_token, user_id)
            return redirect('/')
        except:
            return redirect('/')
    messages.add_message(request, messages.ERROR, 'Jesteś już zalogowany.')
    return redirect('/')


def add_server(request):
    if 'user_id' not in request.session:
        return JsonResponse({'message': 'Nie jesteś zalogowany.'}, status=401)

    server_name = request.POST.get("server_name")
    server_ip = request.POST.get("server_ip")
    rcon_password = request.POST.get("rcon_password")
    rcon_port = request.POST.get("rcon_port")

    if not server_name or not server_ip or not rcon_password or not rcon_port:
        return JsonResponse({'message': 'Uzupełnij informacje o serwerze.'}, status=411)

    get_server_data = requests.get('https://api.mcsrvstat.us/2/' + server_ip).json()
    status = get_server_data["online"]
    if not status:
        return JsonResponse({'message': 'Serwer jest wyłączony.'}, status=400)
    if not check_rcon_connection(server_ip, rcon_password, rcon_port):
        return JsonResponse({'message': 'Wystąpił błąd podczas łączenia się do rcon.'}, status=400)

    i = Server(
        server_name=server_name,
        server_ip=server_ip,
        rcon_password=rcon_password,
        rcon_port=rcon_port,
        owner_id=request.session['user_id'],
        server_version=get_server_data["version"],
        server_status=True,
        server_players=str(get_server_data["players"]["online"]) + '/' + str(
            get_server_data["players"]["max"])
    )
    i.save()
    return JsonResponse({'message': 'Dodano serwer, możesz teraz odświeżyć stronę.'})


@login_required
def panel(request, server_id):
    counted_sells = {}
    exclude = []
    counted_products = Product.objects.filter(server__id=server_id).count()
    purchases_count = Purchase.objects.filter(product__server__id=server_id, status=1).count()
    purchases = Purchase.objects.filter(product__server__id=server_id).order_by('-date')
    server = Server.objects.get(id=server_id)
    products = Product.objects.filter(server__id=server_id)
    vouchers = Voucher.objects.filter(product__server__id=server_id)
    payment_operators = PaymentOperator.objects.filter(server__id=server_id)
    server_navigations_links = ServerNavbarLink.objects.filter(server__id=server_id)

    for po in payment_operators:
        if po.operator_type == 'lvlup_sms' or po.operator_type == 'lvlup_other' or po.operator_type == 'microsms_sms':
            exclude.append(po.operator_type)

    for product in products:
        count = Purchase.objects.filter(product_id=product.id, status=1).count()
        counted_sells.update({str(product.id): count})

    context = {
        'server_id': server_id,  # Wiem, że rak, do zmiany xD
        'server_name': server.server_name,
        'server_ip': server.server_ip,
        'counted_products': counted_products,
        'purchases_count': purchases_count,
        'purchases': purchases,
        'products': products,
        'counted_sells': counted_sells,
        'vouchers': vouchers,
        'server_logo': server.logo,
        'own_css': server.own_css,
        'rcon_port': server.rcon_port,
        'payment_operators': payment_operators,
        'assigned_operators': exclude,
        'discord_webhook': server.discord_webhook,
        'ProductDescriptionForm': ProductDescriptionForm,
        'admins': server.admins,
        'domain': server.domain,
        'rcon_status': server.rcon_status,
        'server_navigation_links': server_navigations_links
    }

    return render(request, 'panel.html', context=context)


@login_required
def add_product(request):
    captcha = request.POST.get("captcha")

    if not captcha and not request.POST.get('edit_mode'):
        return JsonResponse({'message': 'Uzupełnij recaptche.'}, status=411)
    r = requests.post('https://www.google.com/recaptcha/api/siteverify', params={'secret': RECAPTCHA_SECRET_KEY, 'response': captcha}).json()
    if not r['success'] and not request.POST.get('edit_mode'):
        return JsonResponse({'message': 'Uzupełnij recaptche xd.'}, status=411)

    server_id = request.POST.get("server_id")
    product_name = request.POST.get("product_name")
    product_description = request.POST.get("product_description")
    lvlup_other_price = request.POST.get("lvlup_other_price")
    lvlup_sms_number = request.POST.get("lvlup_sms_price")
    microsms_sms_number = request.POST.get("microsms_sms_price")
    product_commands = request.POST.get("product_commands")
    product_image = request.POST.get("product_image")
    edit_mode = request.POST.get("edit_mode")

    if not product_name or not product_description or not product_commands or not server_id:
        return JsonResponse({'message': 'Uzupełnij informacje o produkcie.'}, status=411)

    if not edit_mode:
        check_payment_type = PaymentOperator.objects.filter(server__id=server_id)
    elif request.POST.get("product_id"):
        server_id = Product.objects.filter(id=request.POST.get("product_id")).values('server__id')
        server_id = server_id[0]['server__id']
        check_payment_type = PaymentOperator.objects.filter(server_id=server_id)
    else:
        return JsonResponse({'message': 'Wystąpił niespodziewany błąd.'}, status=404)

    if not check_payment_type.exists():
        return JsonResponse({'message': 'Aby dodać produkt wybierz operatora płatności.'}, status=411)

    for po in check_payment_type:
        if po.operator_type == 'lvlup_sms' and not lvlup_sms_number:
            return JsonResponse({'message': 'Uzupełnij informacje o produkcie.'}, status=411)
        elif po.operator_type == 'lvlup_other' and not lvlup_other_price:
            return JsonResponse({'message': 'Uzupełnij informacje o produkcie.'}, status=411)
        elif po.operator_type == 'microsms_sms' and not microsms_sms_number:
            return JsonResponse({'message': 'Uzupełnij informacje o produkcie.'}, status=411)

    if lvlup_other_price:
        lvlup_other_price = float(lvlup_other_price)
        lvlup_other_price = float(format(lvlup_other_price, '.2f'))
        if not lvlup_other_price > 0.99:
            return JsonResponse({'message': 'Minimalna cena wynosi 1 PLN.'}, status=401)
        elif lvlup_other_price > 999.99:
            return JsonResponse({'message': 'Maksymalna cena wynosi 999.99 PLN.'}, status=401)

    if edit_mode:
        Product.objects.select_for_update().filter(id=request.POST.get("product_id")).update(
            product_name=product_name,
            product_description=product_description,
            lvlup_other_price=lvlup_other_price,
            lvlup_sms_number=lvlup_sms_number,
            microsms_sms_number=microsms_sms_number,
            product_commands=product_commands,
            product_image=product_image)
        return JsonResponse({'message': 'Zapisano zmiany.'}, status=200)
    else:
        p = Product(
            product_name=product_name,
            product_description=product_description,
            server=Server.objects.get(id=server_id),
            lvlup_other_price=lvlup_other_price,
            lvlup_sms_number=lvlup_sms_number,
            microsms_sms_number=microsms_sms_number,
            product_commands=product_commands,
            product_image=product_image)
        p.save()
        return JsonResponse({'message': 'Dodano produkt.'}, status=200)


@login_required
def add_operator(request, operator_type):
    if operator_type not in ['lvlup_sms', 'lvlup_other', 'microsms_sms']:
        return JsonResponse({'message': 'Taki operator nie został znaleziony.'}, status=404)

    operator_name = request.POST.get("operator_name")
    if not operator_name:
        return JsonResponse({'message': 'Uzupełnij informacje o operatorze.'}, status=411)

    client_id = request.POST.get("client_id")
    server_id = request.POST.get("server_id")
    api_key = request.POST.get("api_key")
    service_id = request.POST.get("service_id")
    sms_content = request.POST.get("sms_content")
    operator = PaymentOperator.objects.filter(operator_type=operator_type, server__id=server_id)
    if operator.exists():
        return JsonResponse({'message': 'Dodałeś już takiego operatora.'}, status=409)
    if operator_type == 'lvlup_sms' and not client_id:
        return JsonResponse({'message': 'Uzupełnij informacje o operatorze.'}, status=411)
    elif operator_type == 'lvlup_other' and not api_key:
        return JsonResponse({'message': 'Uzupełnij informacje o operatorze.'}, status=411)
    elif operator_type == 'microsms_sms':
        if not client_id or not service_id or not sms_content:
            return JsonResponse({'message': 'Uzupełnij informacje o operatorze.'}, status=411)

    if operator_type == 'lvlup_sms':
        new_operator = PaymentOperator(
            operator_type=operator_type,
            operator_name=operator_name,
            client_id=client_id,
            server=Server.objects.get(id=server_id)
        )
        new_operator.save()

    elif operator_type == 'lvlup_other':
        new_operator = PaymentOperator(
            operator_type=operator_type,
            operator_name=operator_name,
            api_key=api_key,
            server=Server.objects.get(id=server_id)
        )
        new_operator.save()

    elif operator_type == 'microsms_sms':
        new_operator = PaymentOperator(
            operator_type=operator_type,
            operator_name=operator_name,
            client_id=client_id,
            service_id=service_id,
            sms_content=sms_content,
            server=Server.objects.get(id=server_id)
        )
        new_operator.save()

    messages.add_message(request, messages.SUCCESS, 'Dodano nowego operatora płatności.')
    return JsonResponse({'message': 'Zapisano ustawienia'}, status=200)


@login_required
def save_settings2(request):
    server_id = request.POST.get("server_id")
    server_name = request.POST.get("server_name")
    server_ip = request.POST.get("server_ip")
    server_rcon_password = request.POST.get("rcon_password")
    server_rcon_port = request.POST.get("rcon_port")

    if not server_id or not server_name or not server_ip or not server_rcon_password or not server_rcon_port:
        return JsonResponse({'message': 'Uzupełnij informacje o serwerze.'}, status=411)

    server = Server.objects.filter(id=server_id)

    if not check_rcon_connection(server_ip, server_rcon_password, server_rcon_port):
        return JsonResponse({'message': 'Wystąpił błąd podczas łączenia się do rcon.'}, status=400)

    server.update(
        server_name=server_name,
        server_ip=server_ip,
        rcon_password=server_rcon_password,
        rcon_port=server_rcon_port
    )

    return JsonResponse({'message': 'Zapisano ustawienia'}, status=200)


@login_required
def remove_product(request):
    product_id = request.POST.get('product_id')
    product_to_delete = Product.objects.filter(id=product_id)

    if not product_to_delete.exists():
        return JsonResponse({'message': 'Taki produkt nie istnieje'}, status=401)

    product_to_delete.delete()
    return JsonResponse({'message': 'Produkt został usunięty.'}, status=200)


@login_required
def generate_voucher(request):
    product_id = request.POST.get('product_id')
    server_id = request.POST.get('server_id')
    voucher_code = request.POST.get('voucher_code')
    if voucher_code:
        code = voucher_code
    else:
        code = generate_random_chars(6)

    product = Product.objects.filter(id=product_id, server_id=server_id)

    if not product.exists():
        return JsonResponse({'message': 'Taki produkt nie istnieje.'}, status=401)

    v = Voucher(
        product=Product.objects.get(id=product_id, server_id=server_id),
        code=code,
        status=0
    )
    v.save()

    return JsonResponse({'message': 'Voucher został wygenerowany. Znajdziesz go w liście voucherów.'}, status=200)


@login_required
def customize_website(request):
    server_id = request.POST.get("server_id")
    domain = request.POST.get("own_domain")

    if domain:
        check_domain = Server.objects.filter(domain=domain).values('id', 'domain')
        if check_domain and not str(check_domain[0]['id']) == server_id:
            return JsonResponse({'message': 'Taka domena jest już w bazie.'}, status=409)

    Server.objects.select_for_update().filter(id=server_id).update(
        logo=request.POST.get("server_logo"),
        own_css=request.POST.get("own_css"),
        shop_style=request.POST.get("shop_style"),
        discord_webhook=request.POST.get("discord_webhook"),
        admins=request.POST.get("admins").replace(" ", ""),
        domain=domain)

    return JsonResponse({'message': 'Zapisano.'}, status=200)


@login_required
def remove_payment_operator(request):
    operator_id = request.POST.get("operator_id")

    operator = PaymentOperator.objects.filter(id=operator_id)

    if not operator.exists():
        return JsonResponse({'message': 'Nie znaleziono takiego operatora.'}, status=404)

    operator.delete()
    messages.add_message(request, messages.SUCCESS, 'Operator został usunięty.')
    return JsonResponse({'message': 'Operator został usunięty.'}, status=200)


@csrf_exempt
def shop(request, server_id):
    try:
        check_server_exists = Server.objects.get(id=server_id)
    except:
        return render(request, '404.html')

    products = Product.objects.filter(server__id=server_id)
    purchases = Purchase.objects.filter(product__server__id=server_id, status=1).order_by('-id')[0:5]
    payment_operators = PaymentOperator.objects.filter(server__id=server_id)
    navbar_links = ServerNavbarLink.objects.filter(server__id=server_id)

    context = {
        'server': check_server_exists,
        'products': products,
        'purchases': purchases,
        'payment_operators': payment_operators,
        'navbar_links': navbar_links
    }

    return render(request, 'shop.html', context=context)


@csrf_exempt
def use_voucher(request):
    player_nick = request.POST.get('player_nick')
    voucher_code = request.POST.get('voucher_code')
    server_id = request.POST.get('server_id')
    if not player_nick or not voucher_code or not server_id:
        return JsonResponse({'message': 'Uzupełnij dane.'}, status=411)

    pattern = re.compile('^\w{3,16}$')
    if not pattern.match(player_nick):
        return JsonResponse({'message': 'Niepoprawny format nicku.'}, status=406)

    voucher = Voucher.objects.filter(code=voucher_code, status=0, product__server_id=server_id).values(
        'product__server__server_ip',
        'product__server__rcon_password',
        'product__product_commands', 'product__server__rcon_port')
    if not voucher.exists():
        return JsonResponse({'message': 'Niepoprawny kod'}, status=401)

    server_ip = voucher[0]['product__server__server_ip']
    rcon_password = voucher[0]['product__server__rcon_password']
    commands = voucher[0]['product__product_commands'].split(';')
    rcon_port = voucher[0]['product__server__rcon_port']

    try:
        send_commands(server_ip, rcon_password, commands, player_nick, rcon_port)
    except:
        return JsonResponse({'message': 'Wystąpił błąd podczas łączenia się do rcon.'}, status=401)

    voucher.update(status=1, player=player_nick)
    return JsonResponse({'message': 'Voucher został wykorzystany.'}, status=200)


def success_page(request):
    return render(request, 'success.html')


def faq(request):
    return render(request, 'faq.html')


@login_required
def check_rcon_status(request):
    server_id = request.POST.get("server_id")

    server = Server.objects.filter(id=server_id).values('server_ip', 'rcon_password', 'rcon_port')

    if not check_rcon_connection(server[0]['server_ip'], server[0]['rcon_password'], server[0]['rcon_port']):
        return JsonResponse({'message': 'Wystąpił błąd podczas łączenia się do rcon.'}, status=400)

    server.update(
        rcon_status=True
    )

    return JsonResponse({'message': 'Sukces, połączenie rcon ponownie działa.'}, status=200)


@login_required
def add_link(request):
    server_id = request.POST.get("server_id")
    name = request.POST.get("link_name")
    url = request.POST.get("link_url")

    if not name or not url:
        return JsonResponse({'message': 'Uzupełnij dane.'}, status=411)

    link = ServerNavbarLink(
        server=Server.objects.get(id=server_id),
        name=name,
        url=url
    )
    link.save()

    return JsonResponse({'message': 'Dodano link.'}, status=200)


@login_required
def remove_link(request):
    link_id = request.POST.get('link_id')
    server_id = request.POST.get('server_id')

    if not link_id:
        return JsonResponse({'message': 'Uzupełnij dane.'}, status=411)

    link = ServerNavbarLink.objects.filter(id=link_id, server__id=server_id)
    if not link.exists():
        return JsonResponse({'message': 'Link o takim id nie istnieje.'}, status=404)

    link.delete()

    return JsonResponse({'message': 'Usunięto link.'}, status=200)