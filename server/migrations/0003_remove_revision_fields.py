from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('server', '0002_reviewrun_comparison_reviewrun_previous'),
    ]

    operations = [
        migrations.RemoveField(model_name='reviewrun', name='comparison'),
        migrations.RemoveField(model_name='reviewrun', name='previous'),
    ]
