"""Searchable catalogue of collected research assets."""
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import render
from django.views.decorators.http import require_safe

from ..models import Evidence, ResearchAsset, SyntheticProfile


@require_safe
def sources(request):
    assets = ResearchAsset.objects.order_by("path")
    query = request.GET.get("q", "")[:200]
    if query: assets = assets.filter(path__icontains=query)
    return render(request, "sources.html", {"page": Paginator(assets, 30).get_page(request.GET.get("page")),
        "query": query, "counts": ResearchAsset.objects.values("category").annotate(count=Count("id")),
        "evidence_counts": Evidence.objects.filter(active=True, present=True).values("role", "kind").annotate(count=Count("id")),
        "profiles": SyntheticProfile.objects.count()})
