from django.db import models
from django.utils.translation import gettext_noop

class ReviewRun(models.Model):
    owner = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    pages = models.JSONField()
    analysis = models.JSONField(default=dict)
    selected_role = models.IntegerField(null=True)
    steps = models.JSONField(default=list)
    baseline = models.TextField(blank=True)
    evaluation = models.JSONField(default=dict)
    as_of = models.DateField(null=True)
    calls = models.JSONField(default=list)
    prompts = models.JSONField()
    model = models.CharField(max_length=100)
    provider = models.CharField(max_length=500)
    error = models.TextField(blank=True)
    language = models.CharField(max_length=2, default='ko')
    created_at = models.DateTimeField(auto_now_add=True)


class Source(models.Model):
    """A reviewed public document kept on the server for agents to look up."""
    doc_id = models.CharField(max_length=64, unique=True)
    kind = models.CharField(max_length=20, choices=[('policy', gettext_noop('정책')), ('opinion', gettext_noop('의견'))])
    title = models.CharField(max_length=300)
    issuer = models.CharField(max_length=200)
    version = models.CharField(max_length=200)
    source_url = models.URLField(max_length=1000)
    published_on = models.DateField(null=True)
    pages = models.JSONField()
