# -*- coding: utf-8 -*-
# Generated by Django 1.11.2 on 2017-07-04 14:31
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('editor', '0009_auto_20170701_1218'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='changedobject',
            name='last_update',
        ),
        migrations.RemoveField(
            model_name='changedobject',
            name='stale',
        ),
        migrations.AddField(
            model_name='changeset',
            name='last_change',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='last change'),
            preserve_default=False,
        ),
    ]
