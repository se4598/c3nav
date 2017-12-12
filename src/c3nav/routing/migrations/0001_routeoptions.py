# -*- coding: utf-8 -*-
# Generated by Django 1.11.6 on 2017-12-12 22:03
from __future__ import unicode_literals

import c3nav.mapdata.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0008_alter_user_username_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='RouteOptions',
            fields=[
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name='routeoptions', serialize=False, to=settings.AUTH_USER_MODEL)),
                ('data', c3nav.mapdata.fields.JSONField(default={})),
            ],
            options={
                'verbose_name': 'Route options',
                'verbose_name_plural': 'Route options',
                'default_related_name': 'routeoptions',
            },
        ),
    ]
