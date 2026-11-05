from django.contrib import admin
from django.urls import path
from .features import research as views, policies, uploads, summaries, debates, demo, health

urlpatterns = [path("health/", health.ready, name="health"), path("", policies.home, name="home"), path("demo/", demo.snapshot, name="demo_snapshot"), path("policies/", policies.catalogue, name="catalogue"), path("policies/<int:pk>/", policies.detail, name="policy"), path("research/", views.intake, name="intake"), path("admin/", admin.site.urls),
               path("api/admin/cases", views.register_api),
               path("sources/", debates.sources, name="sources"),
               path("api/debates/start/", debates.start, name="debate_start"),
               path("api/debates/<uuid:pk>/step/", debates.step, name="debate_step"),
               path("api/debates/<uuid:pk>/", debates.status, name="debate_status"),
               path("api/summary/", summaries.summarize, name="summary"),
               path("upload/", uploads.upload, name="upload"),
               path("review/", uploads.review, name="review"),
               path("perspectives/", uploads.perspectives, name="perspectives")]
