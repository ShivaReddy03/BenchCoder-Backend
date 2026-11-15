from django.contrib import admin
from .models import ProblemKnowledge, HintRequest


@admin.register(ProblemKnowledge)
class ProblemKnowledgeAdmin(admin.ModelAdmin):
    list_display = ('problem', 'concepts', 'embedding_model', 'updated_at')
    search_fields = ('problem__title', 'approach_summary')
    readonly_fields = ('embedding_model', 'content_hash', 'updated_at')
    fields = ('problem', 'concepts', 'approach_summary', 'embedding_model', 'content_hash', 'updated_at')


@admin.register(HintRequest)
class HintRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'problem', 'level', 'status', 'created_at')
    readonly_fields = ('user', 'problem', 'level', 'code', 'language', 'status', 'hint', 'retrieved_sources', 'error_message', 'fingerprint', 'created_at', 'started_at', 'finished_at')
    def has_add_permission(self, request):
        return False
