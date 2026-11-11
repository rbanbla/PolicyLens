from django.db import models
from django.utils.translation import gettext_noop

class ReviewRun(models.Model):
    owner = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    pages = models.JSONField()
    analysis = models.JSONField(default=dict)
    personas = models.JSONField(default=list)  # One Persona snapshot (or None) per role, in role order.
    selected_role = models.IntegerField(null=True)
    steps = models.JSONField(default=list)
    baseline = models.TextField(blank=True)
    baseline_items = models.JSONField(default=list)  # The stored answer moved into the PolicyLens fields, for display only.
    evaluation = models.JSONField(default=dict)
    as_of = models.DateField(null=True)
    structured_facts = models.BooleanField(default=False)
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


class Persona(models.Model):
    """A synthetic person from NVIDIA Nemotron-Personas-Korea (CC BY 4.0), given to a role so it speaks as someone."""
    uuid = models.CharField(max_length=32, unique=True)
    persona = models.TextField()
    professional_persona = models.TextField()
    family_persona = models.TextField()
    sex = models.CharField(max_length=10)
    age = models.PositiveSmallIntegerField()
    marital_status = models.CharField(max_length=50)
    family_type = models.CharField(max_length=100)
    housing_type = models.CharField(max_length=100)
    education_level = models.CharField(max_length=50)
    occupation = models.CharField(max_length=200)
    district = models.CharField(max_length=100)
    province = models.CharField(max_length=50)


class Policy(models.Model):
    policy_id = models.SlugField(max_length=96, primary_key=True)
    title = models.CharField(max_length=300)
    region_code = models.CharField(max_length=20)
    issuer = models.CharField(max_length=200)


class PolicyVersion(models.Model):
    version_id = models.SlugField(max_length=96, primary_key=True)
    policy = models.ForeignKey(Policy, on_delete=models.CASCADE, related_name='versions')
    label = models.CharField(max_length=200)
    supersedes = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)
    application_from = models.DateField(null=True, blank=True)
    application_until = models.DateField(null=True, blank=True)


class PolicyFact(models.Model):
    fact_id = models.SlugField(max_length=96, primary_key=True)
    version = models.ForeignKey(PolicyVersion, on_delete=models.CASCADE, related_name='facts')
    predicate = models.CharField(max_length=20, choices=[(v, v) for v in ('eligibility', 'benefit', 'application', 'exclusion', 'interaction')])
    value = models.JSONField()
    status = models.CharField(max_length=10, default='pending', choices=[(v, v) for v in ('pending', 'verified', 'rejected')])
    reviewed_by = models.CharField(max_length=200, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    extracted_by = models.CharField(max_length=200)


class FactEvidence(models.Model):
    fact = models.ForeignKey(PolicyFact, on_delete=models.CASCADE, related_name='evidence')
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True)
    source_hash = models.CharField(max_length=64)
    page = models.PositiveIntegerField()
    quote = models.TextField()
