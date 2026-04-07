import json
import yaml
from django import forms
from apps.clusters.models import Cluster, Node
from .models import PatchTemplate


class PatchTemplateForm(forms.ModelForm):
    class Meta:
        model = PatchTemplate
        fields = ['name', 'description', 'patch_content', 'target_role']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'patch_content': forms.Textarea(attrs={'rows': 20, 'class': 'font-monospace'}),
        }
        help_texts = {
            'patch_content': (
                'JSON patch (RFC 6902 array) or YAML merge patch. '
                'YAML example: machine:\\n  features:\\n    hostDNS:\\n      enabled: true'
            ),
        }

    def clean_patch_content(self):
        content = self.cleaned_data['patch_content'].strip()
        # Try JSON first
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
        # Try YAML
        try:
            yaml.safe_load(content)
            return content
        except yaml.YAMLError as e:
            raise forms.ValidationError(f'Invalid JSON or YAML: {e}')
        return content


class PatchApplyForm(forms.Form):
    cluster = forms.ModelChoiceField(
        queryset=Cluster.objects.filter(is_active=True),
        empty_label='Select cluster…',
    )
    target_role = forms.ChoiceField(
        choices=[
            ('all', 'All Nodes'),
            ('controlplane', 'Control Plane Only'),
            ('worker', 'Worker Only'),
        ],
    )
    target_nodes = forms.ModelMultipleChoiceField(
        queryset=Node.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Leave empty to apply to all nodes matching the selected role.',
    )

    def __init__(self, *args, patch_template=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.patch_template = patch_template
        if patch_template:
            self.fields['target_role'].initial = patch_template.target_role
        if args and args[0] and args[0].get('cluster'):
            try:
                cluster_id = int(args[0]['cluster'])
                self.fields['target_nodes'].queryset = Node.objects.filter(cluster_id=cluster_id)
            except (ValueError, TypeError):
                pass
