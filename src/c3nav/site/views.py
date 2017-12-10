import json
from typing import Optional

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.contrib.auth.views import redirect_to_login
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import etag

from c3nav.mapdata.models import Location, Source
from c3nav.mapdata.models.access import AccessPermissionToken
from c3nav.mapdata.models.locations import LocationRedirect, SpecificLocation
from c3nav.mapdata.utils.locations import get_location_by_slug_for_request, levels_by_short_label_for_request
from c3nav.mapdata.utils.user import get_user_data
from c3nav.mapdata.views import set_tile_access_cookie


def check_location(location: Optional[str], request) -> Optional[SpecificLocation]:
    if location is None:
        return None

    location = get_location_by_slug_for_request(location, request)
    if location is None:
        return None

    if isinstance(location, LocationRedirect):
        location: Location = location.target
    if location is None:
        return None

    if not location.can_search:
        location = None

    return location


def map_index(request, mode=None, slug=None, slug2=None, details=None,
              level=None, x=None, y=None, zoom=None, embed=None):
    origin = None
    destination = None
    routing = False
    if slug2 is not None:
        routing = True
        origin = check_location(slug, request)
        destination = check_location(slug2, request)
    else:
        routing = (mode and mode != 'l')
        if mode == 'o':
            origin = check_location(slug, request)
        else:
            destination = check_location(slug, request)

    state = {
        'routing': routing,
        'origin': (origin.serialize(detailed=False, simple_geometry=True, geometry=False)
                   if origin else None),
        'destination': (destination.serialize(detailed=False, simple_geometry=True, geometry=False)
                        if destination else None),
        'sidebar': routing or destination is not None,
        'details': True if details else False,
    }

    levels = levels_by_short_label_for_request(request)

    level = levels.get(level, None) if level else None
    if level is not None:
        state.update({
            'level': level.pk,
            'center': (float(x), float(y)),
            'zoom': float(zoom),
        })

    ctx = {
        'bounds': json.dumps(Source.max_bounds(), separators=(',', ':')),
        'levels': json.dumps(tuple((level.pk, level.short_label) for level in levels.values()), separators=(',', ':')),
        'state': json.dumps(state, separators=(',', ':'), cls=DjangoJSONEncoder),
        'tile_cache_server': settings.TILE_CACHE_SERVER,
        'embed': bool(embed),
    }
    response = render(request, 'site/map.html', ctx)
    set_tile_access_cookie(request, response)
    if embed:
        xframe_options_exempt(lambda: response)()
    return response


def qr_code_etag(request, path):
    return '1'


@etag(qr_code_etag)
@cache_control(max_age=3600)
def qr_code(request, path):
    data = (request.build_absolute_uri('/'+path) +
            ('?'+request.META['QUERY_STRING'] if request.META['QUERY_STRING'] else ''))
    if len(data) > 256:
        return HttpResponseBadRequest()

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    response = HttpResponse(content_type='image/png')
    qr.make_image().save(response, 'PNG')
    return response


def close_response(request):
    ajax = request.is_ajax() or 'ajax' in request.GET
    if ajax:
        return HttpResponse(json.dumps(get_user_data(request), cls=DjangoJSONEncoder).encode(),
                            content_type='text/plain')
    redirect_path = request.GET['next'] if request.GET.get('next', '').startswith('/') else reverse('site.index')
    return redirect(redirect_path)


@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return close_response(request)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.user_cache)
            return close_response(request)
    else:
        form = AuthenticationForm(request)

    return render(request, 'site/account_form.html', {
        'title': _('Log in'),
        'form': form,
        'bottom_link_url': reverse('site.register'),
        'bottom_link_text': _('Create new account')
    })


@never_cache
def logout_view(request):
    logout(request)
    return close_response(request)


@never_cache
def register_view(request):
    if request.user.is_authenticated:
        return close_response(request)

    if request.method == 'POST':
        form = UserCreationForm(data=request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return close_response(request)
    else:
        form = UserCreationForm()

    form.fields['username'].max_length = 20
    for field in form.fields.values():
        field.help_text = None

    return render(request, 'site/account_form.html', {
        'title': _('Create new account'),
        'back_url': reverse('site.login'),
        'form': form
    })


@never_cache
@login_required(login_url='site.login')
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            login(request, request.user)
            messages.success(request, _('Password successfully changed.'))
            return redirect('site.account')
    else:
        form = PasswordChangeForm(user=request.user)

    for field in form.fields.values():
        field.help_text = None

    return render(request, 'site/account_form.html', {
        'title': _('Change password'),
        'back_url': reverse('site.account'),
        'form': form
    })


@never_cache
@login_required(login_url='site.login')
def account_view(request):
    return render(request, 'site/account.html', {})


@never_cache
@login_required(login_url='site.login')
def access_redeem_view(request, token):
    with transaction.atomic():
        try:
            token = AccessPermissionToken.objects.select_for_update().get(id=token, redeemed=False,
                                                                          valid_until__gte=timezone.now())
        except AccessPermissionToken.DoesNotExist:
            messages.error(request, _('This token does not exist or was already redeemed.'))
            return redirect('site.index')

        num_restrictions = len(token.restrictions)

        if request.method == 'POST':
            token.redeemed = True
            token.save()

            if not request.user.is_authenticated:
                messages.info(request, _('You need to log in to unlock areas.'))
                request.session['redeem_token_on_login'] = token.id
                return redirect_to_login(request.get_full_path(), 'site.login')

            token.redeemed_by = request.user
            token.save()

            messages.success(request, ungettext_lazy('Area successfully unlocked.',
                                                     'Areas successfully unlocked.', num_restrictions))
            return redirect('site.index')

    return render(request, 'site/confirm.html', {
        'title': ungettext_lazy('Unlock area', 'Unlock areas', num_restrictions),
        'texts': (ungettext_lazy('You have been invited to unlock the following area:',
                                 'You have been invited to unlock the following areas:',
                                 num_restrictions),
                  ', '.join(str(restriction.title) for restriction in token.restrictions)),
    })
