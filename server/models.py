from django.db import models


class StudyCase(models.Model):
    fingerprint = models.CharField(max_length=64, unique=True)
    document_sha256 = models.CharField(max_length=64)
    title = models.CharField(max_length=250)
    source = models.TextField()
    document = models.TextField()
    situation = models.TextField()
    learning_goal = models.TextField()
    question = models.TextField()
    spec = models.JSONField()
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Clause(models.Model):
    case = models.ForeignKey(StudyCase, on_delete=models.CASCADE, related_name="clauses")
    key = models.CharField(max_length=32)
    location = models.TextField()
    quote = models.TextField()
    issue = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["case", "key"], name="unique_case_clause")]

    def __str__(self):
        return f"{self.case} · {self.key}"


class MockTurn(models.Model):
    clause = models.ForeignKey(Clause, on_delete=models.CASCADE, related_name="mock_turns")
    role = models.CharField(max_length=20)
    statement = models.TextField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["clause", "role"], name="unique_mock_role")]

    def __str__(self):
        return f"{self.clause} · {self.role}"


class MockRevision(models.Model):
    turn = models.OneToOneField(MockTurn, on_delete=models.CASCADE, related_name="revision")
    wording = models.TextField()
    reason = models.TextField()


class PolicySummary(models.Model):
    cache_key = models.CharField(max_length=64, unique=True)
    model = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=40)
    result = models.JSONField(default=dict)
    response_id = models.CharField(max_length=200, blank=True)
    usage = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ResearchAsset(models.Model):
    path = models.TextField(unique=True)
    title = models.TextField()
    category = models.CharField(max_length=40)
    source_url = models.TextField(blank=True)
    available = models.BooleanField(default=True)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict)


class Evidence(models.Model):
    key = models.CharField(max_length=64, unique=True)
    asset = models.ForeignKey(ResearchAsset, on_delete=models.CASCADE)
    role = models.CharField(max_length=20)
    kind = models.CharField(max_length=40)
    locator = models.TextField()
    text = models.TextField()
    context = models.TextField()
    active = models.BooleanField(default=True)
    managed = models.BooleanField(default=False)
    present = models.BooleanField(default=True)


class SyntheticProfile(models.Model):
    key = models.CharField(max_length=64, unique=True)
    asset = models.ForeignKey(ResearchAsset, on_delete=models.CASCADE)
    role = models.CharField(max_length=20)
    background = models.JSONField()
    locator = models.TextField()


class DebatePair(models.Model):
    import uuid
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64)
    document = models.JSONField()
    spec = models.JSONField()
    model = models.CharField(max_length=100)
    profiles = models.JSONField(default=dict)
    evidence = models.JSONField(default=dict)
    issues = models.JSONField(default=list)
    cursor = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, default="ready")
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "input_hash"], name="unique_owner_debate_input")]


class DebateCall(models.Model):
    pair = models.ForeignKey(DebatePair, on_delete=models.CASCADE, related_name="calls")
    step = models.PositiveIntegerField()
    condition = models.CharField(max_length=10)
    stage = models.CharField(max_length=20)
    role = models.CharField(max_length=20)
    request = models.JSONField(default=dict)
    response = models.JSONField(default=dict)
    usage = models.JSONField(default=dict)
    response_id = models.CharField(max_length=200, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["pair", "step"], name="unique_pair_step")]


class DebateAttempt(models.Model):
    request = models.JSONField(default=dict)
    call = models.ForeignKey(DebateCall, on_delete=models.CASCADE, related_name="attempt_log")
    number = models.PositiveIntegerField()
    output = models.JSONField(default=dict)
    response_id = models.CharField(max_length=200, blank=True)
    usage = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["call", "number"], name="unique_call_attempt")]


class BSourceCandidate(models.Model):
    workbook_sha256 = models.CharField(max_length=64)
    sheet = models.CharField(max_length=80)
    row_number = models.PositiveIntegerField()
    role = models.CharField(max_length=20)
    topic = models.TextField()
    source_type = models.CharField(max_length=120)
    question = models.TextField(blank=True)
    original_excerpt = models.TextField(blank=True)
    reported_view = models.TextField(blank=True)
    source_location = models.TextField(blank=True)
    source_url = models.TextField(blank=True)
    audit_status = models.CharField(max_length=100)
    decision = models.CharField(max_length=40, default='pending_review')
    review_note = models.TextField(blank=True)
    matched_source_ids = models.JSONField(default=list)
    collection_status = models.CharField(max_length=32, default='not_checked')
    local_source_path = models.TextField(blank=True)
    local_text_path = models.TextField(blank=True)
    quote_match = models.CharField(max_length=20, default='not_checked')
    attachment_paths = models.JSONField(default=list)
    matching_attachment_paths = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workbook_sha256', 'sheet', 'row_number'], name='unique_b_workbook_row')]
