import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('clusters', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PatchTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
                ('patch_content', models.TextField(help_text='JSON patch content (array of patch operations)')),
                ('target_role', models.CharField(
                    choices=[('all', 'All Nodes'), ('controlplane', 'Control Plane'), ('worker', 'Worker')],
                    default='all', max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='patch_templates', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='PatchJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('patch_content', models.TextField(help_text='Snapshot of patch content at time of application')),
                ('target_role', models.CharField(max_length=20)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending'), ('running', 'Running'), ('success', 'Success'),
                        ('failed', 'Failed'), ('partial', 'Partial Success'),
                    ],
                    default='pending', max_length=20,
                )),
                ('celery_task_id', models.CharField(blank=True, max_length=200)),
                ('logs', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('cluster', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='patch_jobs', to='clusters.cluster',
                )),
                ('initiated_by', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
                ('patch_template', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='jobs', to='patches.patchtemplate',
                )),
                ('target_nodes', models.ManyToManyField(
                    blank=True, related_name='patch_jobs', to='clusters.node',
                )),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
