from django.contrib import admin
from .models import Clause, MockRevision, MockTurn, StudyCase


class SnapshotAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StudyCase)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("title", "source", "published")
    readonly_fields = tuple(field.name for field in StudyCase._meta.fields if field.name != "published")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (Clause, MockTurn, MockRevision):
    admin.site.register(model, SnapshotAdmin)


from .models import ResearchAsset, Evidence, SyntheticProfile, DebatePair, DebateCall, DebateAttempt

@admin.register(ResearchAsset)
class ResearchAssetAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'category', 'available']
    list_filter = ['category', 'available']
    search_fields = ['title', 'path', 'source_url']

@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    readonly_fields = ['key', 'managed', 'present']
    def save_model(self, request, obj, form, change):
        from .data.corpus import digest
        obj.key = digest(f"{obj.asset.path}:{obj.role}:{obj.kind}:{obj.locator}:{obj.text}")
        super().save_model(request, obj, form, change)
    list_display = ['key', 'role', 'kind', 'active', 'locator']
    list_filter = ['role', 'kind', 'active']
    search_fields = ['text', 'locator', 'context']
    raw_id_fields = ['asset']

@admin.register(SyntheticProfile)
class SyntheticProfileAdmin(admin.ModelAdmin):
    list_display = ['key', 'role', 'locator']
    list_filter = ['role']
    raw_id_fields = ['asset']

@admin.register(DebatePair, DebateCall, DebateAttempt)
class ExecutionAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


from .models import BSourceCandidate

@admin.register(BSourceCandidate)
class BSourceCandidateAdmin(admin.ModelAdmin):
    list_display = ['sheet', 'row_number', 'topic', 'source_type', 'collection_status', 'quote_match', 'decision']
    list_filter = ['role', 'source_type', 'collection_status', 'quote_match', 'decision']
    search_fields = ['topic', 'original_excerpt', 'source_location', 'source_url']
    readonly_fields = ['workbook_sha256', 'sheet', 'row_number', 'role', 'topic', 'source_type',
                       'question', 'original_excerpt', 'reported_view', 'source_location',
                       'source_url', 'audit_status', 'matched_source_ids', 'collection_status',
                       'local_source_path', 'local_text_path', 'quote_match',
                       'attachment_paths', 'matching_attachment_paths']
    def has_add_permission(self, request):
        return False
